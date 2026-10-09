# -*- coding: utf-8 -*-
"""打包前帧序列完整性硬门（scripts/check_frameseq_bundle.py）测试。

素材树全部用 ``tmp_path`` 造（不碰真实 106 段 / 53MB 素材），每个用例只注入
一种缺陷，断言**退出码 + 报错关键词**——门是构建管线的一环，它的契约就是
「非零退出 + 说清怎么补」。

三类断言：

1. 判定行为：完整树 0 退出；缺子树 / 缺单段产物 / 世代档陈旧 / meta 损坏
   逐类 1 退出，且报错能指出路径与补法；
2. 硬约束：零 Qt 零第三方依赖（AST 扫 import）、只读（跑完素材树字节级不变）；
3. 接线：``build_onedir.ps1`` 的非 GIF 分支在 PyInstaller 起跑前调用本门、
   非零即中止，GIF 分支跳过（源码文本断言——行为测试看不到「有没有接上」）。

世代常量与 ``pet/frameseq_provision.py`` 的同源性由 ``TestGenerationHomology``
从 provision 源码**文本提取**后逐条比对：provision 改档而门内常量没跟，即红。
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_frameseq_bundle.py"
BUILD_SCRIPT = ROOT / "scripts" / "build_onedir.ps1"
PROVISION_SOURCE = ROOT / "pet" / "frameseq_provision.py"

# 旧档串（改档前的产物）：用来构造「世代陈旧」的假素材。取自
# pet/frameseq_provision.py 的 LEGACY_ENCODER_DESCS，只作测试输入。
LEGACY_ENCODER = "libwebp lossy q70 (bgra straight, unblend-white)"
# 旧反解标记（v2）
LEGACY_UNBLEND = "white"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_frameseq_bundle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclass 装饰器依赖模块已在 sys.modules 里（按路径加载不会自动登记）
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load_gate()


# --------------------------------------------------------------------------- 造素材


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_clip(
    characters_dir: Path,
    character: str,
    stem: str,
    *,
    folder: str = "idle",
    generation: bool = True,
    encoder: str | None = None,
    unblend: str | None = None,
    meta: str = "ok",
    meta_frames: int = 1,
    frame_files: int = 1,
) -> tuple[Path, Path]:
    """造一段假 clip：webm +（可选）其世代目录与 meta.json。

    ``meta`` 取值：``"ok"`` 当前档 / ``"missing"`` 不写 meta.json /
    ``"corrupt"`` 写坏 JSON。``meta_frames`` / ``frame_files`` 用来造
    「meta 记 24 帧、磁盘只有 3 帧」这类半成品世代目录。
    """
    videos = characters_dir / character / "videos" / folder
    videos.mkdir(parents=True, exist_ok=True)
    webm = videos / f"{stem}.webm"
    webm.write_bytes(b"fake-webm:" + stem.encode("utf-8"))
    if not generation:
        return webm, Path()
    digest = _sha256(webm)
    gen = (characters_dir / character / "frameseq" / folder
           / f"{stem}{GATE.GEN_INFIX}{digest[:GATE.GEN_STAMP_HEX]}")
    gen.mkdir(parents=True, exist_ok=True)
    for index in range(frame_files):
        (gen / f"f_{index + 1:04d}.webp").write_bytes(b"frame")
    if meta == "missing":
        return webm, gen
    if meta == "corrupt":
        (gen / "meta.json").write_text("{ 这不是 JSON", encoding="utf-8")
        return webm, gen
    payload = {
        "fps": 24.0,
        "source": f"{stem}.webm",
        "frames": meta_frames,
        "encoder": GATE.ENCODER_DESC if encoder is None else encoder,
        "unblend": GATE.UNBLEND_MARK if unblend is None else unblend,
        "source_sha256": digest,
    }
    (gen / "meta.json").write_text(json.dumps(payload), encoding="utf-8")
    return webm, gen


def _run(characters_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--characters-dir", str(characters_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(ROOT), check=False,
    )


def _snapshot(root: Path) -> list[tuple[str, int, int]]:
    return sorted(
        (str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
    )


# --------------------------------------------------------------------------- 判定行为


class TestGateVerdicts:
    def test_complete_tree_passes(self, tmp_path):
        characters = tmp_path / "characters"
        for character in ("shenshen", "other"):
            for stem in ("待机呼吸休闲", "左转奔跑", "写代码"):
                _make_clip(characters, character, stem, meta_frames=3, frame_files=3)
        result = _run(characters)
        assert result.returncode == 0, result.stderr
        assert "shenshen: 3 个 clip" in result.stdout
        assert "other: 3 个 clip" in result.stdout
        # 摘要要交代世代档（构建日志里能看见以哪一档为基准放行）
        assert GATE.ENCODER_DESC in result.stdout
        assert GATE.UNBLEND_MARK in result.stdout

    def test_nested_clip_folder_passes(self, tmp_path):
        # events/balance 这类二级目录也在门内（rglob 口径）
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "余额播报", folder="events/balance")
        result = _run(characters)
        assert result.returncode == 0, result.stderr

    def test_missing_frameseq_subtree_fails(self, tmp_path):
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "待机呼吸休闲", generation=False)
        result = _run(characters)
        assert result.returncode == 1
        assert "frameseq" in result.stderr
        assert "待机呼吸休闲" in result.stderr
        # 报错必须说清怎么补（同步素材源 / 先跑离线供给）
        assert "同步" in result.stderr

    def test_missing_single_clip_fails(self, tmp_path):
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "待机呼吸休闲")
        _, stale_gen = _make_clip(characters, "shenshen", "左转奔跑")
        # 只剩旧戳目录（模拟源已换版 / 产物没跟上）：当前戳目录不存在
        for item in stale_gen.iterdir():
            item.unlink()
        stale_gen.rmdir()
        result = _run(characters)
        assert result.returncode == 1
        assert "左转奔跑" in result.stderr
        assert "缺" in result.stderr
        assert "待机呼吸休闲" not in result.stderr  # 完好 clip 不误报

    def test_stale_encoder_fails(self, tmp_path):
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "写代码", encoder=LEGACY_ENCODER)
        result = _run(characters)
        assert result.returncode == 1
        assert "世代" in result.stderr
        assert LEGACY_ENCODER in result.stderr  # 报错要给出实际档串
        assert GATE.ENCODER_DESC in result.stderr  # 与当前档对照

    def test_stale_unblend_mark_fails(self, tmp_path):
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "写代码", unblend=LEGACY_UNBLEND)
        result = _run(characters)
        assert result.returncode == 1
        assert "世代" in result.stderr
        assert LEGACY_UNBLEND in result.stderr

    def test_corrupt_meta_fails(self, tmp_path):
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "写代码", meta="corrupt")
        result = _run(characters)
        assert result.returncode == 1
        assert "meta.json" in result.stderr

    def test_missing_meta_file_fails(self, tmp_path):
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "写代码", meta="missing")
        result = _run(characters)
        assert result.returncode == 1
        assert "meta.json" in result.stderr

    def test_partial_frame_set_fails(self, tmp_path):
        # 半成品世代目录（meta 记 24 帧、磁盘只有 3 帧）：运行时采纳闸门会拒收，
        # 用户看到的就是未转换素材——构建门必须拦住
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "写代码", meta_frames=24, frame_files=3)
        result = _run(characters)
        assert result.returncode == 1
        assert "帧数" in result.stderr
        assert "24" in result.stderr and "3" in result.stderr

    def test_zero_frame_generation_fails(self, tmp_path):
        characters = tmp_path / "characters"
        _make_clip(characters, "shenshen", "写代码", meta_frames=0, frame_files=0)
        result = _run(characters)
        assert result.returncode == 1
        assert "帧数" in result.stderr

    def test_absent_characters_dir_fails(self, tmp_path):
        result = _run(tmp_path / "nope")
        assert result.returncode == 1
        assert "assets" in result.stderr or "素材" in result.stderr

    def test_empty_material_tree_fails(self, tmp_path):
        # 素材树在但没有一个 clip：构建环境异常，不许静默放行
        characters = tmp_path / "characters"
        (characters / "shenshen" / "videos").mkdir(parents=True)
        result = _run(characters)
        assert result.returncode == 1
        assert "webm" in result.stderr

    def test_failure_list_capped_at_twenty(self, tmp_path):
        characters = tmp_path / "characters"
        # 先造一段完好的 clip，让 frameseq 子树存在 → 25 段缺产物落到「单段缺产物」类
        _make_clip(characters, "shenshen", "待机呼吸休闲")
        for index in range(25):
            _make_clip(characters, "shenshen", f"缺失段{index:02d}", generation=False)
        result = _run(characters)
        assert result.returncode == 1
        listed = [line for line in result.stderr.splitlines() if line.startswith("    - ")]
        assert len(listed) == 20, result.stderr
        assert "其余 5 条省略" in result.stderr

    def test_multiline_reporting_covers_each_class(self, tmp_path):
        # 四类缺陷同场：每一类都要出现在报错里（不因先出现的类别吞掉后面的）
        characters = tmp_path / "characters"
        _make_clip(characters, "完整的", "待机呼吸休闲")
        _make_clip(characters, "缺产物的", "写代码", generation=False)
        _make_clip(characters, "档陈旧的", "左转奔跑", encoder=LEGACY_ENCODER)
        _make_clip(characters, "meta坏的", "漂浮踏步", meta="corrupt")
        result = _run(characters)
        assert result.returncode == 1
        for needle in ("frameseq", "缺", "世代", "meta.json"):
            assert needle in result.stderr
        for character in ("缺产物的", "档陈旧的", "meta坏的"):
            assert character in result.stderr


# --------------------------------------------------------------------------- 硬约束


class TestGateConstraints:
    def test_script_imports_stdlib_only(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    imported.add("." * node.level + (node.module or ""))
                elif node.module:
                    imported.add(node.module.split(".")[0])
        assert imported, "脚本必须至少导入 argparse/sys"
        assert imported <= set(sys.stdlib_module_names), f"非标准库依赖: {imported}"
        assert "pet" not in imported, "构建门不许 import pet 包（会连带 PySide6）"
        assert not any(name.lower().startswith("pyside") for name in imported)

    def test_gate_is_read_only(self, tmp_path):
        characters = tmp_path / "characters"
        _make_clip(characters, "完整的", "待机呼吸休闲")
        _make_clip(characters, "缺产物的", "写代码", generation=False)
        before = _snapshot(characters)
        result = _run(characters)
        assert result.returncode == 1
        assert _snapshot(characters) == before, "门只许读：素材树一个字节都不许动"


# --------------------------------------------------------------------------- 常量同源


def _source_constant(name: str) -> str:
    text = PROVISION_SOURCE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\s*=\s*(.+)$", text, flags=re.MULTILINE)
    assert match, f"pet/frameseq_provision.py 里找不到 {name}（改名/删除了？）"
    raw = match.group(1).split("#", 1)[0].strip()
    return raw


class TestGenerationHomology:
    """门内世代常量必须与 pet/frameseq_provision.py 的运行时口径逐字一致。"""

    def test_encoder_desc_matches_provision(self):
        assert GATE.ENCODER_DESC == ast.literal_eval(_source_constant("ENCODER_DESC"))

    def test_unblend_mark_matches_provision(self):
        assert GATE.UNBLEND_MARK == ast.literal_eval(_source_constant("UNBLEND_MARK"))

    def test_generation_dir_naming_matches_provision(self):
        assert GATE.GEN_INFIX == ast.literal_eval(_source_constant("GEN_INFIX"))
        assert GATE.GEN_STAMP_HEX == ast.literal_eval(_source_constant("GEN_STAMP_HEX"))

    def test_stamp_is_sha256_prefix(self, tmp_path):
        characters = tmp_path / "characters"
        webm, gen = _make_clip(characters, "shenshen", "待机呼吸休闲")
        assert gen.name.endswith(_sha256(webm)[:GATE.GEN_STAMP_HEX])

    def test_provision_constants_are_not_legacy(self):
        # 防线自证：门认的档串必须不在 provision 的 LEGACY_ENCODER_DESCS 里
        # （否则门会把旧世代当当前档放行）
        text = PROVISION_SOURCE.read_text(encoding="utf-8")
        block = text.split("LEGACY_ENCODER_DESCS", 1)[1].split(")", 1)[0]
        assert GATE.ENCODER_DESC not in block


# --------------------------------------------------------------------------- 接线


def _build_text() -> str:
    return BUILD_SCRIPT.read_text(encoding="utf-8")


def _enclosing_gate_block(text: str) -> str:
    """取调用本门的那段 ``if (-not $isGif) { ... }`` 语句原文。"""
    call = text.index("check_frameseq_bundle")
    start = text.rindex("if (-not $isGif) {", 0, call)
    end = text.index("}", call)
    return text[start:end + 1]


class TestBuildScriptWiring:
    def test_gate_runs_before_pyinstaller(self):
        text = _build_text()
        assert text.index("check_frameseq_bundle") < text.index("python -m PyInstaller")

    def test_non_gif_branch_calls_gate_and_aborts_on_failure(self):
        block = _enclosing_gate_block(_build_text())
        assert "check_frameseq_bundle" in block
        assert "$LASTEXITCODE" in block, "门非零必须中止构建"
        assert "throw" in block

    def test_gif_branch_skips_gate(self):
        text = _build_text()
        # 脚本调用点只有一个，且它在 `if (-not $isGif)` 里 → GIF 变体天然跳过
        assert text.count("check_frameseq_bundle.py") == 1
        assert _enclosing_gate_block(text).startswith("if (-not $isGif) {")
        call = text.index("check_frameseq_bundle")
        assert text[call - 800:call].count("GIF") >= 1, "注释要说明 GIF 变体为何跳过"
