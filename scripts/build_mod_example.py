# -*- coding: utf-8 -*-
"""把作者源码打成标准功能包：``mod.json`` + ``host/`` → 目录 + 同名 ZIP。

这是**作者侧唯一一条打包入口**（`python scripts/build_mod_example.py …`，作者教程里的
那条命令），产出的两份东西都能直接交给 MOD 中心导入：目录与 ZIP 在安装链里是同一份
东西（``feature_package_files.stage`` 把两条路归一成同一个已解包目录）。

与上游 DLC 版的三处差异（都是本仓库拓扑决定的，不是顺手改的）：

* **能力上限 / API 版本从 ``pet.feature_policy`` 取**——那里是唯一真相源（宿主侧、
  打包脚本、构建门共用一份）；上游那份取自 ``pet.feature_build_policy``（本仓库没有
  那个模块）。曾在这里抄过一份字面量，``tests/test_feature_packaging_wiring.py``
  的"不许有第二份定义"守卫现在钉住这件事；
* **``--check`` 是发布前的真自检**：清单 + 验签 + **装前子进程预检**，判据与构建脚本
  用的那道门是同一个（``scripts/verify_feature_package.py``）——自检不该是另一套结论；
* **打包期不静默**：源码树不合格、``host/`` 里有打不进包的文件、输出已存在，都在写任何
  字节之前报一句作者能照做的错（不给 traceback），而不是产出一个"看着装上了、缺东西"的包。

**未验证项**：``--worker-bundle`` 那条 host-worker 路径需要冻结的 worker 可执行，本机
没有，也未验证；host-only 示例（``examples/mods/hello-local``）已真跑通。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

# 作者教程里写的是直接给路径跑（``python scripts/build_mod_example.py``）——那时
# ``sys.path[0]`` 是 ``scripts/``，产品包不在路径上，所以自己把仓库根放上去。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import __version__  # noqa: E402
from pet.feature_policy import API_VERSION, FEATURE_CAPABILITIES, local_package_verifier  # noqa: E402
from pet.feature_state_io import safe_path  # noqa: E402
from pet.plugins.package_trust import PackageVerificationError  # noqa: E402

#: ``mod.json`` 必须给的字段（``name``/``description`` 之类的展示字段原样进清单）。
_REQUIRED_FIELDS = ("id", "name", "version", "factory", "execution_kind")

#: Core 版本下限取自**打包这一份的 Core 自己**（写死一个版本会让示例包在自家 Core 上
#: 就装不上）；上限沿用上游的 ``<6.0.0``。
CORE_REQUIRES = f">={__version__},<6.0.0"


class BuildError(ValueError):
    """作者能照做的那种错：由 :func:`main` 印成一句话，不给 traceback。"""


def _manifest_values(source: Path) -> dict:
    """读并校验 ``mod.json``（缺件/坏 JSON/缺字段都在写任何字节之前说清楚）。"""
    manifest = source / "mod.json"
    if not manifest.is_file():
        raise BuildError(f"{manifest} 不存在：作者源码树是「mod.json + host/」两件")
    try:
        values = json.loads(manifest.read_text("utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise BuildError(f"{manifest} 读不出来（要 UTF-8 的 JSON）：{error}") from error
    if not isinstance(values, dict):
        raise BuildError(f"{manifest} 的最外层必须是一个对象")
    missing = [field for field in _REQUIRED_FIELDS if not values.get(field)]
    if missing:
        raise BuildError(f"{manifest} 缺少必填字段：{', '.join(missing)}")
    if values["execution_kind"] not in {"host-only", "host-worker"}:
        raise BuildError(f"{manifest} 的 execution_kind 只能是 host-only 或 host-worker")
    return values


def _check_host_tree(source: Path) -> None:
    """``host/`` 只有 ``.py`` 进包，且这不是偏好。

    宿主装载链只从**捕获并验过摘要的 ``host/**.py`` 字节**导入（``package_trust`` 的
    ``capture_sources``），别的文件既不会被捕获、也没有读取入口。所以遇到非 ``.py``
    要**报错**而不是默默丢掉——默默丢掉的下场是作者拿到一个"看着装上了、缺东西"的包。
    """
    host = source / "host"
    if not host.is_dir():
        raise BuildError(f"{host} 不存在：包必须有 host/factory.py")
    foreign = [
        path for path in sorted(host.rglob("*"))
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
    ]
    if foreign:
        names = ", ".join(path.relative_to(source).as_posix() for path in foreign[:5])
        raise BuildError(
            f"host/ 下只有 .py 会进包（装载链只从捕获的 host/*.py 字节导入）：{names}"
            f"{' 等' if len(foreign) > 5 else ''}；数据请走 mod API 的 documents / 配置，不要随包放文件"
        )
    if not (host / "factory.py").is_file():
        raise BuildError(f"{host / 'factory.py'} 不存在：包必须用它交出 create_host()")


def build_example(source: Path, output: Path, *, worker_bundle: Path | None = None, worker_name: str = 'mod-echo.exe') -> Path:
    """把作者源码树打成包（目录 + 同名 ZIP），返回那个目录。

    写完立刻在**进程内**过一遍路由与验签（快、零子进程）；更完整的自检（含子进程预检）
    在 :func:`main` 的 ``--check`` 与 ``scripts/verify_feature_package.py`` 那一道门里。
    """
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    safe_path(output)
    if output.exists() or output.with_suffix('.zip').exists():
        raise BuildError('output already exists; choose a new candidate directory')
    values = _manifest_values(source)
    kind = values['execution_kind']
    if kind == 'host-worker' and worker_bundle is None:
        raise BuildError('host-worker requires a separately frozen --worker-bundle')
    _check_host_tree(source)
    files = {}

    def copy_tree(root, prefix, *, python_only=False):
        root = Path(root).resolve(strict=True)
        for path in sorted(root.rglob('*')):
            safe_path(path)
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            if python_only and path.suffix != '.py':
                continue
            relative = prefix + '/' + path.relative_to(root).as_posix()
            data = path.read_bytes()
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files[relative] = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}

    copy_tree(source / 'host', 'host', python_only=True)
    if worker_bundle is not None:
        copy_tree(worker_bundle, 'worker')
    manifest = {**values, 'format_version': 2, 'key_id': 'local-user', 'api_version': API_VERSION,
                'core_requires': CORE_REQUIRES, 'platforms': [sys.platform],
                'capabilities': sorted(FEATURE_CAPABILITIES),
                'worker': {'path': 'worker/' + worker_name, 'args': []} if kind == 'host-worker' else None, 'files': files}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n', 'utf-8')
    check(output)
    with zipfile.ZipFile(output.with_suffix('.zip'), 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(output).as_posix())
    return output


def check(package):
    """进程内自检：路由 + 完整验签（不起子进程，也不执行包代码）。"""
    from pet.local_package_intents import route_local_package

    package = Path(package).expanduser().absolute()
    route = route_local_package(package)
    return local_package_verifier(route.feature_id).verify(package)


def check_report(source: Path | str) -> dict:
    """发布前自检 = 构建脚本用的那道门（同一份判据、同一套原因码）。"""
    from scripts.verify_feature_package import inspect

    return inspect(source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把作者源码树（mod.json + host/）打成标准功能包：目录 + 同名 ZIP",
        epilog="包打好后交给 MOD 中心导入；发布前请用 --check 自检一遍",
    )
    parser.add_argument('source', type=Path, help="作者源码树；--check 时是要检查的包（目录/ZIP）")
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--worker-bundle', type=Path, help="host-worker 包要随包携带的冻结 worker 目录")
    parser.add_argument('--worker-name', default='mod-echo.exe')
    parser.add_argument('--check', action='store_true', help="只自检：清单 + 验签 + 装前子进程预检")
    args = parser.parse_args(argv)
    if args.check:
        from scripts.verify_feature_package import format_human

        report = check_report(args.source)
        if report["feature_id"]:
            # CLI 契约行：作者教程与 tests/test_mod_center_contracts.py 认它
            # （机器可读的一行摘要）；门的人读报告跟在它后面，不替代它。
            print(f"valid: {report['feature_id']} {report['version']} ({report['execution_kind']})")
        print(format_human(report))
        if report["ok"]:
            return 0
        print(f"自检没过（{report['reason']}）：这份包装上一样会失败，别发出去。", file=sys.stderr)
        return 1
    if args.output is None:
        parser.error('output is required unless --check is selected')
    try:
        result = build_example(args.source, args.output, worker_bundle=args.worker_bundle, worker_name=args.worker_name)
    except (BuildError, PackageVerificationError, OSError) as error:
        print(f"打不了包：{error}", file=sys.stderr)
        return 2
    print(f'created: {result}\nZIP: {result.with_suffix(".zip")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
