# -*- coding: utf-8 -*-
"""功能扩展包的门：清单 + 验签 + 装前子进程预检（作者自检 / 构建 / 发布共用）。

**为什么需要这道门**：一份功能包坏掉的方式，产品在运行期大多**看不见**——少一个文件、
摘要对不上、``create_host()`` 说的 owner 与清单不符，用户在 MOD 中心拿到的是"装不上"，
而作者在打包机上什么都看不到。所以门做三件事，一件都不省：

1. **清单**（有界路由）：读得出 id / version / platforms / execution_kind；
2. **验签**（完整验签链）：结构、Core/API/平台兼容、路径边界、逐文件摘要与指纹、
   祖先快照——目录与 ZIP 在这里归一成同一份已解包目录（``feature_package_files.stage``）；
3. **装前子进程预检**（``pet.feature_package_preflight``）：在**另一个进程**里把包按
   同一份字节导入一次，读回 ``create_host()`` 说了什么。

**边界（与产品口径一致，别读成沙箱）**：门的"通过"**不授权任何执行**，它只在"拒绝"
方向有权威——说不行的就是不行，说行的那一半仍由宿主按完整验签链自己重新回答。子进程
预检不声称任何隔离（同用户、同权限、同文件系统；超时只杀掉这一次直接起的进程）。

**约束**：只读输入（一个字节都不写；ZIP 只在私有临时目录里解包），只 import 零 Qt 的
产品模块（``pet/feature_policy`` / ``pet/local_package_intents`` /
``pet/feature_package_preflight``），因此能在最小构建机环境里跑，也不碰 PySide6。

用法：
    python scripts/verify_feature_package.py <包目录或 ZIP> [<包> ...]
    python scripts/verify_feature_package.py --bundle-root <包根>          # 根下每一份都验
    python scripts/verify_feature_package.py --bundle-root <包根> --target-platform linux
    python scripts/verify_feature_package.py --json

``--bundle-root`` 的候选是谁**不猜**：根下的**每个直接子目录**与**每个 ``*.zip``**
都算一份候选（点开头的条目除外）。于是"包目录少打了 manifest.json"会被如实报成
``route_rejected``，而不是被当成"看起来不像包"跳过——漏件的包正是要抓的那一种。

退出码：0 = 每一个候选都过；1 = 有任一份被拒（含"包根下什么都没找到"）。原因码是闭集
（``REASONS`` ∪ 探针的 ``probe_*``），构建脚本只看退出码。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
from pathlib import Path

# 直接给路径跑（``python scripts/verify_feature_package.py``）时 sys.path[0] 是
# scripts/，产品包不在路径上——自己把仓库根放上去，免得作者要先设 PYTHONPATH。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet import feature_package_files  # noqa: E402
from pet.feature_package_preflight import LocalPackageProbe  # noqa: E402
from pet.feature_policy import DEFAULT_LIMITS, local_package_verifier  # noqa: E402
from pet.local_package_intents import route_local_package  # noqa: E402
from pet.plugins.package_trust import PackageVerificationError  # noqa: E402

#: 门自己的原因码（**闭集**）。探针那一侧的原因码（``probe_*``）原样透传，
#: 因为它们是同一个安装链在宿主侧也会得到的码——门不发明第二套词汇。
REASONS = frozenset(
    {
        "source_missing",       # 路径不存在，或既不是目录也不是文件
        "route_rejected",       # 有界清单读不出来（缺 manifest.json / 形状不合路由契约）
        "official_reserved",    # 官方保留 owner：本地包占不了这个名字
        "platform_mismatch",    # 清单声明的 platforms 不含目标平台
        "verification_failed",  # 验签链拒：结构 / 兼容性 / 路径边界 / 摘要 / 指纹
    }
)

#: 包根下什么都没找到时的问题码（构建脚本要能一眼看出"根给错了"）。
BUNDLE_EMPTY = "bundle_empty"


# --------------------------------------------------------------------------- 单份包


def inspect(source: Path | str, *, target_platform: str = sys.platform) -> dict:
    """验一份包（目录或 ZIP），返回体检报告 dict——**不抛异常**，结论都在返回值里。

    预检那一环固定是生产那一份（``LocalPackageProbe``，30s 单次上限）：门与安装链要
    给出同一个结论，中间不该有第三份实现。
    """
    source = Path(source)
    report: dict = {
        "source": str(source),
        "kind": None,
        "target_platform": target_platform,
        "ok": False,
        "reason": None,
        "feature_id": None,
        "version": None,
        "execution_kind": None,
        "manifest_digest": None,
        "platforms": [],
        "probe": None,
        "problems": [],
    }
    if not source.is_dir() and not source.is_file():
        report["reason"] = "source_missing"
        report["problems"].append("包不存在：既不是目录也不是 ZIP")
        return report
    # 验签链要求**绝对路径**（relative root 会被它按"路径穿越"拒掉），而构建脚本与
    # 作者文档里给的都是相对路径；在这里归一，报告里也统一写绝对路径。
    try:
        source = source.resolve(strict=True)
    except OSError:
        report["reason"] = "source_missing"
        report["problems"].append("包打不开（路径解析失败）")
        return report
    report["source"] = str(source)

    try:
        route = route_local_package(source)
    except (PackageVerificationError, OSError, ValueError):
        report["reason"] = "route_rejected"
        report["problems"].append("清单读不出来（缺 manifest.json，或形状不合路由契约）")
        return report
    report.update(
        kind="directory" if source.is_dir() else "zip",
        feature_id=route.feature_id,
        version=route.version,
        execution_kind=route.execution_kind,
        manifest_digest=route.manifest_digest,
        platforms=list(route.platforms),
    )
    if route.is_official:
        report["reason"] = "official_reserved"
        report["problems"].append(f"{route.feature_id} 是官方保留 ID：那条链是 Core 自有的，本地包不能占用它")
        return report
    if target_platform not in route.platforms:
        report["reason"] = "platform_mismatch"
        report["problems"].append(
            f"清单声明 platforms={sorted(route.platforms)}，目标平台是 {target_platform}"
        )
        return report

    verifier = local_package_verifier(route.feature_id, platform=target_platform)
    try:
        # 解包目录要活到探针跑完（探针按 descriptor.root 重新验一遍）——所以整段
        # "验签 + 预检"都在这个上下文里，ZIP 的临时解包目录不能被提前回收。
        with _staged_root(source) as root:
            try:
                descriptor = verifier.verify(root)
            except (PackageVerificationError, OSError, ValueError) as error:
                report["reason"] = "verification_failed"
                report["problems"].append(f"验签链拒：{_bounded(error)}")
                return report
            try:
                verdict = LocalPackageProbe().run(descriptor, verifier)
            except (OSError, RuntimeError, ValueError):  # 探针实现本身出错，不是包的结论
                report["reason"] = "probe_unavailable"
                report["problems"].append("预检器起不来（这是环境问题，不是包的结论）")
                return report
    except (PackageVerificationError, OSError, ValueError) as error:
        report["reason"] = "verification_failed"
        report["problems"].append(f"压缩包结构/上限不合格：{_bounded(error)}")
        return report
    report["probe"] = {
        "ok": verdict.ok,
        "reason": verdict.reason,
        "child_pid": verdict.child_pid,
        "metadata": verdict.metadata.document() if verdict.metadata is not None else None,
    }
    if not verdict.ok:
        report["reason"] = verdict.reason or "probe_failed"
        report["problems"].append(f"装前子进程预检拒：{report['reason']}")
        return report
    report["ok"] = True
    return report


@contextlib.contextmanager
def _staged_root(source: Path):
    """目录**就地**验；ZIP 先在私有临时目录里按同一套边界解包再验（与安装链同一处归一）。

    生成器的生命周期就是调用方的 ``with`` 块——ZIP 的解包目录活到探针跑完为止
    （探针拿着 ``descriptor.root`` 在子进程里重新验一遍，提前删掉它会得到
    ``probe_verification_failed`` 这种看着像包的错）。
    """
    if source.is_dir():
        yield source
        return
    with tempfile.TemporaryDirectory(prefix="dsh-pet-feature-gate-") as scratch:
        staged = Path(scratch) / "package"
        try:
            feature_package_files.stage(source, "zip", staged, DEFAULT_LIMITS)
        except (PackageVerificationError, OSError, ValueError) as error:  # StateError 等
            raise PackageVerificationError(f"archive rejected: {_bounded(error)}") from error
        yield staged


def _bounded(error: BaseException, limit: int = 200) -> str:
    """异常文本进报告前先截断：门印出去的字要能被构建日志吞得下。"""
    text = str(error) or error.__class__.__name__
    return text[:limit]


# --------------------------------------------------------------------------- 包根


def bundle_candidates(root: Path | str) -> list[Path]:
    """包根的候选：每个直接子目录 + 每个 ``*.zip``（点开头的条目除外）。"""
    root = Path(root)
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return []
    return [
        entry
        for entry in entries
        if not entry.name.startswith(".") and (entry.is_dir() or (entry.is_file() and entry.suffix.lower() == ".zip"))
    ]


def inspect_bundle(root: Path | str, *, target_platform: str = sys.platform) -> dict:
    """验一个包根下的**每一份**候选包，返回 ``{root, ok, packages, problems}``。"""
    root = Path(root)
    candidates = bundle_candidates(root)
    packages = [inspect(candidate, target_platform=target_platform) for candidate in candidates]
    problems = [
        f"{Path(report['source']).name}: {problem}" for report in packages for problem in report["problems"]
    ]
    if not candidates:
        problems.append(f"{root} 下没有找到任何候选包（{BUNDLE_EMPTY}）：包根给错了，或包没打出来")
    return {
        "root": str(root),
        "target_platform": target_platform,
        "ok": bool(packages) and not problems,
        "packages": packages,
        "problems": problems,
    }


# --------------------------------------------------------------------------- 命令行


def format_human(report: dict) -> str:
    lines = [f"检查：{report['source']}（{report['kind'] or '未知'}）"]
    if report["feature_id"]:
        lines.append(
            f"  包：{report['feature_id']} {report['version']}（{report['execution_kind']}）"
            f" 声明平台 {','.join(sorted(report['platforms']))}"
        )
        lines.append(f"  清单摘要：sha256:{report['manifest_digest']}")
    probe = report["probe"]
    if probe is not None:
        if probe["ok"] and probe["metadata"] is not None:
            metadata = probe["metadata"]
            lines.append(
                f"  装前预检：通过（owner={metadata['owner']}，契约 {metadata['mount_contract'] or '—'}，"
                f"贡献 {len(metadata['contributions'])} 项）"
            )
        else:
            lines.append(f"  装前预检：拒（{probe['reason'] or 'probe_failed'}）")
    lines.append(f"  结论：{'通过' if report['ok'] else '拒（' + str(report['reason']) + '）'}")
    for problem in report["problems"]:
        lines.append(f"  问题：{problem}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # 三个平台的构建脚本都会调它，代码页不由门挑
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="校验功能扩展包（清单 + 验签 + 装前子进程预检）——作者自检与构建门共用",
        epilog=f"原因码闭集：{', '.join(sorted(REASONS))}，加上探针的 probe_*",
    )
    parser.add_argument("sources", nargs="*", type=Path, help="包目录或 ZIP（可多份）")
    parser.add_argument("--bundle-root", type=Path, default=None, help="包根：根下每一份候选包都验一遍")
    parser.add_argument("--target-platform", default=sys.platform, help="目标平台（构建脚本按产物平台传，默认本机）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    if not args.sources and args.bundle_root is None:
        parser.error("至少给一份包（位置参数），或用 --bundle-root 指定包根")
    try:  # 目标平台的合法性问产品自己的判据，不在本脚本里写第二份平台闭集
        local_package_verifier("gate.platform", platform=args.target_platform)
    except PackageVerificationError:
        parser.error(f"未知目标平台：{args.target_platform!r}")

    packages: list[dict] = []
    problems: list[str] = []
    if args.bundle_root is not None:
        bundle = inspect_bundle(args.bundle_root, target_platform=args.target_platform)
        packages.extend(bundle["packages"])
        problems.extend(bundle["problems"])
    for source in args.sources:
        report = inspect(source, target_platform=args.target_platform)
        packages.append(report)
        problems.extend(f"{Path(report['source']).name}: {problem}" for problem in report["problems"])

    ok = bool(packages) and not problems
    if args.json:
        print(json.dumps({"ok": ok, "target_platform": args.target_platform, "packages": packages, "problems": problems}, ensure_ascii=True, indent=2))
    else:
        for index, report in enumerate(packages):
            if index:
                print()
            print(format_human(report))
        if not ok:
            print("\nFAIL: 有包没通过门——构建/发布中止（坏包在界面上多半看不出来，"
                  "装到用户机器上才知道）。逐条见上面的「问题」。", file=sys.stderr)
        else:
            print(f"\nOK: {len(packages)} 份包全部通过（清单 + 验签 + 装前子进程预检）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
