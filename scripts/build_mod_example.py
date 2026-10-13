# -*- coding: utf-8 -*-
"""Build a user-trusted local MOD folder and ZIP (no publisher signing).

Ported from the DLC branch ``scripts/build_mod_example.py``；最小可用版（DLC 融合
D2 待拍板项 ⑥）。与 DLC 的两处差异：

* DLC 从 ``pet.feature_build_policy`` 取 ``FEATURE_CAPABILITIES`` 作为兼容上限声明；
  本仓库没有该模块（那份策略随官方功能包线一起做），这里改用下面这一份显式常量，
  与 ``examples/mods/`` 示例清单声明的能力集合一致；
* ``--check`` 走本仓库的路由 + 验签（``route_local_package`` + ``FeaturePackageVerifier``）。

**未验证项**：只在本机跑过 host-only 示例（``examples/mods/hello-local``）。
``--worker-bundle`` 那条 host-worker 路径需要冻结的 worker 可执行，本机不可验证。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

from pet import __version__
from pet.feature_state_io import safe_path
from pet.plugins.package_trust import FeaturePackageVerifier

#: 本地示例包声明的能力上限（兼容上限声明，不是运行期权限）。
FEATURE_CAPABILITIES = frozenset({"menu.contribute", "settings.contribute"})
API_VERSION = "1"
#: Core 版本下限取自**打包这一份的 Core 自己**（DLC 硬编码 ``>=4.2.5``，本仓库基线是
#: 4.2.1，硬编码会让示例包在自家 Core 上就装不上）；上限沿用 DLC 的 ``<6.0.0``。
CORE_REQUIRES = f">={__version__},<6.0.0"


def build_example(source: Path, output: Path, *, worker_bundle: Path | None = None, worker_name: str = 'mod-echo.exe') -> Path:
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    safe_path(output)
    if output.exists() or output.with_suffix('.zip').exists():
        raise ValueError('output already exists; choose a new candidate directory')
    values = json.loads((source / 'mod.json').read_text('utf-8-sig'))
    kind = values['execution_kind']
    if kind == 'host-worker' and worker_bundle is None:
        raise ValueError('host-worker requires a separately frozen --worker-bundle')
    if kind not in {'host-only', 'host-worker'}:
        raise ValueError('unsupported execution kind')
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
    from pet.local_package_intents import route_local_package

    package = Path(package).expanduser().absolute()
    route = route_local_package(package)
    verifier = FeaturePackageVerifier(core_version=__version__, api_version=API_VERSION, feature_id=route.feature_id,
                                      allowed_capabilities=FEATURE_CAPABILITIES, allow_local_packages=True)
    return verifier.verify(package)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--worker-bundle', type=Path)
    parser.add_argument('--worker-name', default='mod-echo.exe')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        descriptor = check(args.source)
        print(f'valid: {descriptor.id} {descriptor.version} ({descriptor.execution_kind})')
    else:
        if args.output is None:
            parser.error('output is required unless --check is selected')
        result = build_example(args.source, args.output, worker_bundle=args.worker_bundle, worker_name=args.worker_name)
        print(f'created: {result}\nZIP: {result.with_suffix(".zip")}')


if __name__ == '__main__':
    main()
