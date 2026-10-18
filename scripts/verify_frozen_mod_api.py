# -*- coding: utf-8 -*-
"""构建门：冻结产物必须能真正预检随包的官方功能包。

`--feature-package-probe` 是冻结构建里唯一会在**干净子进程**里 import 包 host 的
路径。PyInstaller 的静态分析看不到包代码（它们在 `<app>/features/` 运行时才导入），
所以 `pet.mod_api` 这类只在包里出现的公开接口很容易漏收；漏收的表现不是启动报错，
而是装前预检统一 `import_failed`，MOD 中心与 Setup 回执的安装全部被拒。

本脚本用源码侧的信任策略生成一份真实 probe 作业，交给**构建产物 exe** 跑一遍，
逐包要求 `ok=true`。构建脚本在复制 features 后调用；也可单独跑::

    python scripts/verify_frozen_mod_api.py \
        --exe dist-onedir/<name>/<name>.exe --features dist-onedir/<name>/features
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet.feature_package_preflight import PROBE_SCHEMA, probe_policy  # noqa: E402
from pet.feature_policy import official_package_verifier  # noqa: E402
from pet.official_features import ACCOUNT_USAGE_FEATURE_ID, AI_FEATURE_ID, SCREEN_FEATURE_ID  # noqa: E402

_PACKAGES = {
    "ai-chat": AI_FEATURE_ID,
    "screen-understanding": SCREEN_FEATURE_ID,
    "account-usage": ACCOUNT_USAGE_FEATURE_ID,
}


def _probe_one(exe: Path, package_root: Path, owner: str, timeout: float) -> tuple[bool, str]:
    verifier = official_package_verifier(owner)
    descriptor = verifier.verify(package_root.resolve())
    with tempfile.TemporaryDirectory(prefix="dsh-pet-frozen-probe-") as scratch:
        job_path = Path(scratch) / "job.json"
        verdict_path = Path(scratch) / "verdict.json"
        job = {
            "schema": PROBE_SCHEMA,
            "package_root": str(descriptor.root),
            "verdict_path": str(verdict_path),
            "policy": probe_policy(verifier),
        }
        job_path.write_text(json.dumps(job, ensure_ascii=True), encoding="utf-8")
        environment = dict(os.environ)
        environment.pop("DSH_PET_PROBE_DEBUG", None)
        try:
            proc = subprocess.run(
                [str(exe), "--feature-package-probe", str(job_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=environment,
                cwd=str(exe.parent),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"probe could not run: {type(exc).__name__}: {exc}"
        if not verdict_path.is_file():
            return False, f"no verdict (exit {proc.returncode}): {(proc.stderr or '')[:400]}"
        try:
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return False, f"unreadable verdict: {exc}"
        if not isinstance(verdict, dict) or not verdict.get("ok"):
            reason = verdict.get("reason") if isinstance(verdict, dict) else "invalid_verdict"
            return False, f"probe rejected: {reason}"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    exe = args.exe.resolve()
    if not exe.is_file():
        print(f"frozen exe missing: {exe}", file=sys.stderr)
        return 2
    checked = 0
    failed = 0
    for directory, owner in _PACKAGES.items():
        package_root = args.features / directory
        if not (package_root / "manifest.json").is_file():
            continue
        checked += 1
        ok, detail = _probe_one(exe, package_root, owner, args.timeout)
        status = "ok" if ok else "FAILED"
        print(f"[frozen-probe] {directory} ({owner}): {status} — {detail}")
        if not ok:
            failed += 1
    if checked == 0:
        print("[frozen-probe] no bundled official packages to check")
        return 0
    if failed:
        print(f"[frozen-probe] {failed}/{checked} package(s) failed", file=sys.stderr)
        return 1
    print(f"[frozen-probe] {checked} package(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
