# -*- coding: utf-8 -*-
"""D2 第一片的宿主运行时接缝：验签字节装载源、api 端口、owner 端口、子进程引导。

对应 spec 的六个既定口径：② ``package_trust.capture_sources``；⑤ ``api`` 端口抛
``unsupported_capability``；④ 两个子进程引导环境变量；以及"v1 门面 / 子进程传输
不拉 Qt"的机器守卫（无 GUI 探针会 import 它们）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pet.api_ports import UNSUPPORTED_CAPABILITY, CapabilityUnsupported
from pet.config import Config
from pet.feature_host_bindings import bind_local_context
from pet.feature_package_startup import _valid_execution_ports
from pet.feature_state_io import StateError
from pet.plugins.package_trust import FeaturePackageVerifier, PackageVerificationError
from tests.test_feature_package_transactions import _package

ROOT = Path(__file__).resolve().parents[1]
OWNER = "sample.offline"


def _context(tmp_path):
    return bind_local_context(Config(base=tmp_path), OWNER)


# --------------------------------------------------------- 已验签字节装载源

def test_capture_sources_returns_the_digest_checked_host_bytes(tmp_path):
    source, verifier, _manifest = _package(tmp_path / "pkg")
    descriptor = verifier.verify(source)
    sources = verifier.capture_sources(descriptor)
    assert set(sources) == {"host/__init__.py", "host/factory.py"}
    assert sources["host/factory.py"] == (source / "host/factory.py").read_bytes()
    # 只有 host/ 与 common/ 的 .py 被抓：worker / 资源不进内存
    assert "worker/screen-worker.exe" not in sources
    assert "resources/defaults.json" not in sources


def test_capture_sources_refuses_bytes_that_no_longer_match_the_descriptor(tmp_path):
    source, verifier, _manifest = _package(tmp_path / "pkg")
    descriptor = verifier.verify(source)
    (source / "host/factory.py").write_bytes(b"def create_host():\n    return 'swapped'\n")
    with pytest.raises(PackageVerificationError):
        verifier.capture_sources(descriptor)


# ----------------------------------------------------------------- api 端口

def test_the_api_port_refuses_with_a_fixed_code_instead_of_a_half_built_object(tmp_path):
    port = _context(tmp_path).api
    assert port is not None  # 不静默 None
    with pytest.raises(CapabilityUnsupported) as raised:
        port.resolve("chat.send")
    assert raised.value.code == UNSUPPORTED_CAPABILITY
    assert str(raised.value) == UNSUPPORTED_CAPABILITY  # 不带服务名/路径/凭据
    for call in (lambda: port.metadata("chat.send"), lambda: port.effective_version("chat.send"),
                 lambda: port.subscribe(lambda: None), lambda: port.open_settings()):
        with pytest.raises(CapabilityUnsupported):
            call()


# --------------------------------------------------------------- owner 端口

def test_the_context_grants_no_desktop_credentials_or_shared_configuration(tmp_path):
    context = _context(tmp_path)
    assert context.owner == OWNER
    assert context.desktop is None and context.worker_launch_factory is None
    assert context.allow_in_process is True
    assert _valid_execution_ports(context, "host-only") is True
    # 识屏包线起这四个字段在 ABI 上存在，但本地 MOD 路径一律不注入（恒 None）。
    for attribute in ("credentials", "legacy_secret_reader", "preferences", "window"):
        assert getattr(context, attribute) is None
    assert not hasattr(context, "user_data")


def test_author_configuration_lives_under_its_own_owner_directory(tmp_path):
    context = _context(tmp_path)
    root = Path(tmp_path) / "dsh-pet-standalone" / "feature-data" / OWNER
    assert root.is_dir()
    assert context.configuration.read_namespace() == {}
    first = context.configuration.revision()
    context.configuration.commit_namespace({"message": "你好"}, expected_revision=first)
    assert context.configuration.read_namespace() == {"message": "你好"}
    assert (root / "configuration.json").is_file()
    assert context.configuration.revision() != first
    with pytest.raises(StateError) as raised:
        context.configuration.commit_namespace({"message": "改"}, expected_revision=first)
    assert raised.value.code == "configuration_changed"
    assert context.configuration.read_namespace() == {"message": "你好"}


def test_two_owners_never_share_a_document_or_a_configuration(tmp_path):
    other = bind_local_context(Config(base=tmp_path), "sample.neighbour")
    mine = _context(tmp_path)
    mine.configuration.commit_namespace({"mine": 1}, expected_revision=mine.configuration.revision())
    assert other.configuration.read_namespace() == {}
    mine.documents["memory"].write({"greetings": 3})
    assert other.documents["memory"].read() == {}


def test_author_documents_are_written_atomically_and_can_be_cleared(tmp_path):
    context = _context(tmp_path)
    document = context.documents["memory"]
    document.write({"greetings": 1})
    assert document.read() == {"greetings": 1}
    document.clear()
    assert document.read() == {}
    state = context.state_documents["state"]
    with state.locked():
        state.write({"cursor": "abc"})
    assert state.read() == {"cursor": "abc"}


def test_an_invalid_owner_is_refused_before_any_directory_is_created(tmp_path):
    with pytest.raises(ValueError):
        bind_local_context(Config(base=tmp_path), "../escape")
    assert not (Path(tmp_path) / "dsh-pet-standalone" / "feature-data").exists()


# --------------------------------------------------------- 子进程引导与命令行

def test_source_mode_runs_the_package_script_with_the_current_interpreter(monkeypatch):
    from pet.plugins.worker_launch import worker_command

    script = Path("C:/pkg/worker/entry.py")
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert worker_command(script, ("--stdio",)) == (sys.executable, (str(script), "--stdio"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert worker_command(script, ("--stdio",)) == (str(script), ("--stdio",))


def test_core_issues_the_two_bootstrap_fields_and_only_in_source_mode(monkeypatch):
    from pet.plugins.worker_launch import CORE_ROOT_ENV, FEATURE_DATA_ROOT_ENV, child_bootstrap_environment

    monkeypatch.delattr(sys, "frozen", raising=False)
    values = child_bootstrap_environment(data_root=Path("C:/data/dsh-pet-standalone"))
    assert values[FEATURE_DATA_ROOT_ENV] == str(Path("C:/data/dsh-pet-standalone"))
    assert (Path(values[CORE_ROOT_ENV]) / "pet" / "mod_api").is_dir()
    frozen = child_bootstrap_environment(data_root=Path("C:/data/dsh-pet-standalone"), frozen=True)
    assert CORE_ROOT_ENV not in frozen  # 冻结态子进程自带依赖，不下发
    assert FEATURE_DATA_ROOT_ENV in frozen
    assert child_bootstrap_environment(data_root=None, frozen=True) == {}


def test_the_child_transport_and_the_lease_bootstrap_import_without_qt():
    probe = (
        "import sys;"
        "import pet.mod_api.v1, pet.mod_api.worker_v1, pet.workers.lease_bootstrap;"
        "assert 'PySide6' not in sys.modules, sorted(m for m in sys.modules if 'PySide6' in m)"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, timeout=60,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert result.returncode == 0, result.stderr


def test_importing_pet_mod_api_alone_does_not_pull_the_host_runtime_or_qt():
    probe = "import sys; import pet.mod_api; assert 'PySide6' not in sys.modules and 'pet.plugins.feature_host' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_the_v1_facade_exports_the_worker_client_lazily():
    import pet.mod_api.v1 as v1
    from pet.workers.worker_client import WorkerClient

    assert v1.WorkerClient is WorkerClient
    with pytest.raises(AttributeError):
        v1.NoSuchName


def test_the_worker_client_refuses_to_launch_without_an_authorized_context(tmp_path):
    from PySide6.QtWidgets import QApplication

    from pet.workers.worker_client import WorkerClient

    app = QApplication.instance() or QApplication([])
    context = _context(tmp_path)  # 未绑定授权 / 未给 launch 工厂的原始上下文
    assert context.execution_authorized is None and context.bind_execution is None
    client = WorkerClient(context)
    errors = []
    client.error.connect(errors.append)
    assert client.start() is False
    assert client.request("hello") is None
    assert errors == ["worker_not_authorized"]
    assert client.supervisor.process is None
    client.close()
    app.processEvents()


# ------------------------------------------------- 真包端到端（无 GUI 部分）

_AUTHOR_HOST = '''
from pet.mod_api.v1 import Contribution, FeatureDefinition

OWNER = "sample.offline"


def menu(menu, handle):
    action = menu.addAction("打个招呼")
    action.triggered.connect(lambda _checked=False: handle.invoke() if handle.active else None)


class Runtime:
    def __init__(self, context, **_kwargs):
        self.context = context
        self.commands = {"hello": self.hello}
        self.active = False

    def start(self):
        self.active = True

    def hello(self):
        if not self.active or not self.context.execution_authorized():
            return
        configuration = self.context.configuration
        values = configuration.read_namespace()
        values["greetings"] = int(values.get("greetings", 0)) + 1
        configuration.commit_namespace(values, expected_revision=configuration.revision())
        memory = self.context.documents["memory"]
        state = memory.read()
        state["last"] = "hello"
        memory.write(state)

    def stop(self):
        self.active = False

    def close(self):
        self.stop()


def create_host():
    return FeatureDefinition(
        OWNER,
        (Contribution("hello", "menu", command="hello", factory=menu),),
        lambda *_args, **_kwargs: None,
        runtime_factory=lambda context, **kwargs: Runtime(context, **kwargs),
    )
'''


def _built_local_package(tmp_path):
    from scripts.build_mod_example import build_example

    source = tmp_path / "src"
    (source / "host").mkdir(parents=True)
    (source / "host" / "__init__.py").write_text("", encoding="utf-8")
    (source / "host" / "factory.py").write_text(_AUTHOR_HOST, encoding="utf-8")
    (source / "mod.json").write_text(
        json.dumps({"id": OWNER, "name": "离线示例", "version": "1.0.0", "factory": "sample-offline/v1", "execution_kind": "host-only"}),
        encoding="utf-8",
    )
    return build_example(source, tmp_path / "built")


def test_a_locally_built_package_runs_from_captured_bytes_end_to_end(tmp_path):
    from pet import __version__
    from pet.mod_runtime import GenericModMounts
    from pet.plugins.feature_packages import FeaturePackageLoader
    from pet.plugins.feature_host import FeatureHost
    from pet.plugins.package_binding import bind_verified_feature
    from scripts.build_mod_example import FEATURE_CAPABILITIES

    package = _built_local_package(tmp_path)
    verifier = FeaturePackageVerifier(
        core_version=__version__, api_version="1", feature_id=OWNER,
        allowed_capabilities=FEATURE_CAPABILITIES, allow_local_packages=True,
    )
    descriptor = verifier.verify(package)
    host = FeatureHost()
    binding = bind_verified_feature(host, FeaturePackageLoader(verifier), descriptor, runtime_directory=tmp_path / "runtime", enabled=False)
    assert binding.handle.namespace in sys.modules  # 宿主代码是**从验签字节**导入的

    mounts = GenericModMounts(host, lambda _owner: bind_local_context(Config(base=tmp_path), OWNER))
    assert mounts.runtimes == {}  # 停用态：没有构造 Runtime
    host.enable(OWNER)
    runtime = mounts.runtimes[OWNER]
    assert runtime.active is True
    handle = host.menu(OWNER, mounts.scope, "hello")
    assert handle is not None and handle.active
    handle.invoke()

    data_root = Path(tmp_path) / "dsh-pet-standalone" / "feature-data" / OWNER
    assert json.loads((data_root / "configuration.json").read_text(encoding="utf-8"))["greetings"] == 1
    assert json.loads((data_root / "memory.json").read_text(encoding="utf-8")) == {"last": "hello"}

    host.disable(OWNER)
    assert runtime.active is False
    assert host.menu(OWNER, mounts.scope, "hello") is None  # 停用后旧句柄不再挂载
    mounts.close()
    assert mounts.runtimes == {}
    assert not binding.closed
    assert binding.close() is True
