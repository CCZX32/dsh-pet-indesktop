# -*- coding: utf-8 -*-
"""主套件分片执行器（本地并行 / CI 串行）。

用法::

    python scripts/ci_shards.py --include-isolated   # 本地全量（默认 min(8, CPU 核数) 路并发）
    python scripts/ci_shards.py --jobs 1             # CI 口径（Windows 主套件）

为什么分片：Windows CI（hosted runner，Python 3.11.9 toolcache + PySide6 6.12.0）上
整套件单进程跑到 ~2/3 处会偶发 access violation（崩点漂移、堆腐蚀签名，mac/Linux
不复现；取证见 .scratch/ci243/WIN-AV-HUNT-2026-10-13.md）。按分片起独立 pytest
进程后崩溃不再发生（每个进程的堆状态从头开始，跨族腐蚀没有积累窗口）。这不是
掩盖失败：任何分片里的测试失败照常红，只是崩溃归因更准。

分片按**收集到的用例数**做 LPT 均衡（历史四分片按文件数等分时实测 266s vs 516s，
近 2 倍差）；并行跑完会从 JUnit 记录每个文件的实测耗时，下一次自动改按耗时均衡。
文件在片内仍按收集序排列，新测试文件自动入片。`--jobs` 默认 ``min(8, CPU 核数)``：
本机 16 核实测 9175 条用例 **约 6 分钟**跑完（单进程串行约 30-60 分钟）；CI runner
只有 4 vCPU，workflow 显式传 `--jobs 1` 保持原来的串行口径。

`--include-isolated` 把 CI 里单列步骤的 4 个 webm/低优先级文件也纳入：每个文件
单独一片（崩溃只丢自己那一片，不牵连主套件）；本机并行时另外把 2 个对 CPU 负载
敏感的灵动岛像素文件单独成片（CI 串行主套件照常包含它们）。不给这个开关时与 CI
主套件范围一致。
"""
from __future__ import annotations

import argparse
import json
import locale
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import TextIO

#: CI 的主套件步骤显式设置它；本地分片运行必须用同一平台插件，否则像素/字体
#: 度量与 CI 不同（灵动岛 8px 状态点在真实 Windows 插件下会量成 13x12）。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: 主套件忽略清单：与 .github/workflows/pr-test.yml 的主套件步骤同源同内容
#: （tests/test_ci_workflows.py 会逐条比对，改名/改内容都会红）。
IGNORES = [
    "tests/test_webm_reader_lifecycle.py",
    "tests/test_webm_clip_lifecycle.py",
    "tests/test_webm_first_frame_lock.py",
    "tests/test_low_priority_warm_interaction_yield.py",
]
#: 本机并行全量时对 CPU 负载敏感的像素/渲染用例（不在 CI 忽略清单里）：
#: 与重负载分片争核时会把 8px 状态点渲染成 13x12 之类的假红，隔离复跑稳定绿。
#: 只在 ``--include-isolated`` 下单独成片，CI 的串行主套件仍照常包含它们。
LOCAL_LOAD_SENSITIVE = [
    "tests/test_island_status_dot.py",
    "tests/test_island_alert_colors.py",
    "tests/test_animation_menu_close_and_group.py",
    "tests/test_settings_page_guide.py",
    "tests/test_workers_lifecycle.py",
    "tests/test_settings_overlay_copy.py",
    "tests/test_library_shared_media.py",
    "tests/test_proactive_worker.py",
    "tests/test_proactive_worker_adapter.py",
    "tests/test_screen_package_worker.py",
]
DEFAULT_SHARDS = 4
#: 本地默认并发：16 核 8 路约 6 分钟跑完；4 核机器自动降到 4 路。CI 显式传 --jobs 1。
DEFAULT_JOBS = min(8, os.cpu_count() or 4)
#: 失败时回读的日志尾部行数（并行模式下分片输出落在 .scratch/test-shards/）。
FAILURE_TAIL_LINES = 60
#: 上一次运行按文件实测的耗时权重（JUnit XML 汇总）。存在即用它做均衡。
WEIGHTS_PATH = Path(".scratch") / "test-shards" / "weights.json"
#: 没有历史耗时时，按「用例数 × 这个秒数」估算文件权重。
FALLBACK_SECONDS_PER_TEST = 0.4
#: 子进程重定向输出按解释器默认的 locale 编码写；回读必须用同一编码。
LOG_ENCODING = locale.getpreferredencoding(False) or "utf-8"


def _collect() -> list[tuple[str, int]]:
    """返回 ``(测试文件, 用例数)``，按 pytest 的收集序排列。"""
    command = [
        sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
        "-p", "no:cacheprovider",
    ]
    for path in IGNORES:
        command.append(f"--ignore={path}")
    out = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"收集失败（exit {out.returncode}）：\n{out.stdout[-2000:]}")
    counts: dict[str, int] = {}
    order: list[str] = []
    for line in out.stdout.splitlines():
        if "::" not in line:
            continue
        path = line.split("::")[0]
        if path not in counts:
            counts[path] = 0
            order.append(path)
        counts[path] += 1
    if not order:
        raise SystemExit("收集到 0 条用例——pytest 或目录结构出了问题")
    return [(path, counts[path]) for path in order]


def _load_weights() -> dict[str, float]:
    try:
        data = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(key): float(value) for key, value in data.items()
            if isinstance(value, (int, float))}


def _resolve_test_file(classname: str, cache: dict[str, str | None]) -> str | None:
    """JUnit 的 ``classname``（点分）→ 仓库内测试文件路径。"""
    if classname in cache:
        return cache[classname]
    parts = classname.split(".")
    resolved = None
    for length in range(len(parts), 0, -1):
        candidate = "/".join(parts[:length]) + ".py"
        if Path(candidate).is_file():
            resolved = candidate
            break
    cache[classname] = resolved
    return resolved


def _update_weights(xml_paths: list[Path]) -> int:
    """把本轮 JUnit 的逐用例耗时按文件汇总进权重缓存；返回覆盖到的文件数。"""
    weights = _load_weights()
    cache: dict[str, str | None] = {}
    updated = 0
    for xml_path in xml_paths:
        try:
            root = ElementTree.parse(xml_path).getroot()
        except (OSError, ElementTree.ParseError):
            continue
        for case in root.iter("testcase"):
            path = _resolve_test_file(case.attrib.get("classname", ""), cache)
            if path is None:
                continue
            try:
                seconds = float(case.attrib.get("time", "0"))
            except ValueError:
                continue
            weights[path] = weights.get(path, 0.0) + seconds
            updated += 1
    if updated:
        WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        WEIGHTS_PATH.write_text(
            json.dumps(weights, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return updated


def _balance(
    files: list[tuple[str, int]], shards: int, weights: dict[str, float] | None = None,
) -> list[list[str]]:
    """LPT 均衡：优先用上一轮的实测耗时，缺失时退回用例数。"""
    weights = weights or {}
    measured = [(path, weights[path]) for path, _count in files if path in weights]
    # 覆盖不足一半时，历史权重没有代表性，直接用用例数。
    use_seconds = len(measured) * 2 >= len(files)
    if use_seconds:
        measured_tests = sum(count for path, count in files if path in weights)
        measured_seconds = sum(seconds for _path, seconds in measured)
        per_test = measured_seconds / measured_tests if measured_tests else FALLBACK_SECONDS_PER_TEST
        load_of = {
            path: weights.get(path, count * per_test)
            for path, count in files
        }
    else:
        load_of = {path: float(count) for path, count in files}

    buckets: list[list[str]] = [[] for _ in range(shards)]
    loads = [0.0] * shards
    for path in sorted(load_of, key=load_of.__getitem__, reverse=True):
        index = loads.index(min(loads))
        buckets[index].append(path)
        loads[index] += load_of[path]
    order = {path: index for index, (path, _count) in enumerate(files)}
    for bucket in buckets:
        bucket.sort(key=order.__getitem__)
    return buckets


def _pytest_command(files: list[str], durations: int, junit_path: Path | None = None) -> list[str]:
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if durations > 0:
        command.append(f"--durations={durations}")
    if junit_path is not None:
        command.append(f"--junitxml={junit_path}")
    return [*command, *files]


def _tail(path: Path, lines: int = FAILURE_TAIL_LINES) -> str:
    try:
        text = path.read_text(encoding=LOG_ENCODING, errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _last_summary(path: Path) -> str:
    try:
        for line in reversed(path.read_text(encoding=LOG_ENCODING, errors="replace").splitlines()):
            if " passed" in line or " failed" in line or " error" in line:
                return line.strip()
    except OSError:
        return ""
    return ""


def _run_isolated(
    buckets: list[list[str]], durations: int, *, start_index: int, log_dir: Path | None = None,
) -> list[tuple[int, int, float]]:
    """Run load-sensitive files one at a time, after the main shards have finished.

    They are already isolated from each other; the point is to keep them away from
    the parallel CPU load, which changes font metrics / paint timing on this host.
    """
    results: list[tuple[int, int, float]] = []
    for offset, shard in enumerate(buckets, start=start_index):
        label = shard[0]
        print(f"\n===== isolated {offset - start_index + 1}/{len(buckets)}（{label}）=====", flush=True)
        started = time.monotonic()
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"shard-{offset:02d}.log"
            xml_path = log_dir / f"shard-{offset:02d}.xml"
            with log_path.open("w", encoding=LOG_ENCODING, errors="replace") as handle:
                rc = subprocess.call(
                    _pytest_command(shard, durations, xml_path),
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
        else:
            rc = subprocess.call(_pytest_command(shard, durations))
        elapsed = time.monotonic() - started
        results.append((offset, rc, elapsed))
        status = "通过" if rc == 0 else f"失败（exit {rc}）"
        print(f"[isolated {offset}] {status}  {elapsed:.1f}s", flush=True)
    return results


def _run_sequential(buckets: list[list[str]], durations: int) -> list[tuple[int, int, float]]:
    results: list[tuple[int, int, float]] = []
    for index, shard in enumerate(buckets, start=1):
        print(f"\n===== shard {index}/{len(buckets)}（{len(shard)} 个文件："
              f"{shard[0]} … {shard[-1]}）=====", flush=True)
        started = time.monotonic()
        rc = subprocess.call(_pytest_command(shard, durations))
        results.append((index, rc, time.monotonic() - started))
    return results


def _run_parallel(
    buckets: list[list[str]], jobs: int, durations: int, log_dir: Path,
) -> list[tuple[int, int, float]]:
    log_dir.mkdir(parents=True, exist_ok=True)
    for stale in log_dir.glob("shard-*.xml"):
        stale.unlink()
    running: list[tuple[int, subprocess.Popen, Path, float, TextIO]] = []
    pending = list(enumerate(buckets, start=1))
    results: list[tuple[int, int, float]] = []

    def launch(index: int, shard: list[str]) -> None:
        log_path = log_dir / f"shard-{index:02d}.log"
        xml_path = log_dir / f"shard-{index:02d}.xml"
        # 不覆盖子进程编码：测试会继承环境并自己解码子进程输出（本机 GBK 口径），
        # 硬钉 PYTHONIOENCODING 会让 test_module_level_validation 这类用例假红。
        handle = log_path.open("w", encoding=LOG_ENCODING, errors="replace")
        started = time.monotonic()
        process = subprocess.Popen(
            _pytest_command(shard, durations, xml_path),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        running.append((index, process, log_path, started, handle))
        print(f"[shard {index}/{len(buckets)}] 启动：{len(shard)} 个文件 → {log_path}", flush=True)

    def finish(index: int, process: subprocess.Popen, log_path: Path, started: float, handle) -> None:
        rc = process.wait()
        handle.close()
        elapsed = time.monotonic() - started
        results.append((index, rc, elapsed))
        status = "通过" if rc == 0 else f"失败（exit {rc}）"
        print(f"[shard {index}/{len(buckets)}] {status}  {elapsed:.1f}s  "
              f"{_last_summary(log_path)}", flush=True)
        if rc != 0:
            print(f"--- shard {index} 日志尾部（{log_path}）---\n{_tail(log_path)}", flush=True)

    while pending or running:
        while pending and len(running) < jobs:
            launch(*pending.pop(0))
        done = next((entry for entry in running if entry[1].poll() is not None), None)
        if done is None:
            time.sleep(0.2)  # 等任一分片结束，空出槽位就立刻补下一片
            continue
        running.remove(done)
        finish(*done)

    updated = _update_weights(sorted(log_dir.glob("shard-*.xml")))
    if updated:
        print(f"耗时权重已更新：{updated} 条用例 → {WEIGHTS_PATH}", flush=True)
    return results


def main(argv: list[str] | None = None) -> int:
    # 输出被重定向到日志时，Windows 默认按 GBK 写；统一钉 UTF-8，日志回读不乱码。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="按用例数均衡地并行/串行跑测试分片")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                        help=f"同时运行的分片数（默认 {DEFAULT_JOBS}；CI 传 1）")
    parser.add_argument("--shards", type=int, default=0,
                        help=f"主套件分片数（默认 max({DEFAULT_SHARDS}, --jobs)）")
    parser.add_argument("--include-isolated", action="store_true",
                        help="主套件跑完后串行跑 4 个 webm/低优先级文件 + 2 个负载敏感像素文件（每个单独一片）")
    parser.add_argument("--durations", type=int, default=25,
                        help="每个分片打印前 N 个慢用例（0 关闭，默认 25）")
    args = parser.parse_args(argv)

    if args.jobs < 1:
        raise SystemExit("--jobs 必须 >= 1")
    if args.shards < 0:
        raise SystemExit("--shards 必须 >= 0（0 = 跟随 --jobs）")
    args.shards = args.shards or max(DEFAULT_SHARDS, args.jobs)
    if args.jobs > args.shards:
        args.jobs = args.shards

    started = time.monotonic()
    files = _collect()
    isolated = list(IGNORES)
    isolated_buckets: list[list[str]] = []
    if args.include_isolated:
        isolated.extend(LOCAL_LOAD_SENSITIVE)
    isolated_keys = {str(Path(path)) for path in isolated}
    files = [item for item in files if str(Path(item[0])) not in isolated_keys]
    total_tests = sum(count for _path, count in files)
    weights = _load_weights()
    buckets = _balance(files, args.shards, weights)
    mode = "上次实测耗时" if weights else "用例数"
    print(f"主套件：{len(files)} 个文件 / {total_tests} 条用例 → {args.shards} 片，"
          f"并发 {args.jobs}（按{mode} LPT 均衡）", flush=True)

    if args.include_isolated:
        for path in isolated:
            if Path(path).is_file():
                isolated_buckets.append([path])
    else:
        isolated_buckets = []

    if args.jobs == 1:
        results = _run_sequential(buckets, args.durations)
    else:
        log_dir = Path(".scratch") / "test-shards"
        results = _run_parallel(buckets, args.jobs, args.durations, log_dir)
    if isolated_buckets:
        results.extend(
            _run_isolated(
                isolated_buckets,
                args.durations,
                start_index=len(results) + 1,
                log_dir=None if args.jobs == 1 else Path(".scratch") / "test-shards",
            )
        )

    elapsed = time.monotonic() - started
    print("\n===== 汇总 =====", flush=True)
    for index, rc, seconds in sorted(results):
        print(f"shard {index:02d}: {'ok' if rc == 0 else 'FAIL'}  {seconds:7.1f}s")
    print(f"总耗时 {elapsed:.1f}s（墙钟）", flush=True)

    failed = [index for index, rc, _seconds in results if rc != 0]
    if failed:
        print(f"\n分片失败：{failed}", flush=True)
        return 1
    print(f"\n全部 {len(results)} 个分片通过", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
