from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import paths
from ..config import Config
from . import install as installer
from . import state
from .loader import load_mods
from .manifest import is_valid_id

PROG = "petcore mods"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description="manage petcore content and feature mods")
    parser.add_argument("--root", type=Path, default=None, help="data root (default: user data dir)")
    parser.add_argument(
        "--mods-dir",
        action="append",
        default=[],
        help="additional mod directory (repeatable)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list discovered mods")
    validate_parser = subparsers.add_parser("validate", help="validate a mod pack")
    validate_parser.add_argument("path", type=Path)
    enable_parser = subparsers.add_parser("enable", help="enable a mod")
    enable_parser.add_argument("id")
    disable_parser = subparsers.add_parser("disable", help="disable a mod")
    disable_parser.add_argument("id")
    install_parser = subparsers.add_parser("install", help="install a mod pack")
    install_parser.add_argument("path", type=Path)
    install_parser.add_argument("--force", action="store_true")
    remove_parser = subparsers.add_parser("remove", help="remove an installed mod")
    remove_parser.add_argument("id")
    subparsers.add_parser("doctor", help="print mod environment diagnostics")
    return parser


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root) if args.root is not None else paths.data_root()


def _extra(args: argparse.Namespace) -> tuple[Path, ...]:
    return tuple(Path(item) for item in args.mods_dir)


def _allow_feature_mods(root: Path) -> bool:
    try:
        return bool(Config.load(root).get("allow_feature_mods"))
    except Exception:
        return False


def _report_mods(args: argparse.Namespace, *, verbose: bool) -> int:
    root = _root(args)
    allow = _allow_feature_mods(root)
    result = load_mods(root, _extra(args), allow_feature_mods=allow)
    for mod in result.mods:
        status = "enabled " if mod.enabled else "disabled"
        manifest = mod.manifest
        line = f"{status} {manifest.kind:7} {manifest.id} {manifest.version} {mod.path}"
        if verbose:
            line += f" ({manifest.name})"
        print(line)
    if verbose:
        for entry in result.contents:
            print(f"  content {entry.kind:9} {entry.id} [{entry.owner}]")
    for diagnostic in result.diagnostics:
        print(f"  ! {diagnostic}")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    root = _root(args)
    allow = _allow_feature_mods(root)
    print(f"root: {root}")
    print(f"state: {paths.mods_state_path(root)}")
    print(f"allow_feature_mods: {allow}")
    for directory in paths.mods_dirs(root, _extra(args)):
        status = "present" if directory.is_dir() else "missing"
        print(f"mod dir: {directory} ({status})")
    disabled = sorted(state.load_disabled(root))
    print(f"disabled: {', '.join(disabled) if disabled else '(none)'}")
    result = load_mods(root, _extra(args), allow_feature_mods=allow)
    enabled_count = sum(1 for mod in result.mods if mod.enabled)
    print(f"mods: {len(result.mods)} discovered, {enabled_count} enabled")
    for mod in result.mods:
        print(f"  {'enabled ' if mod.enabled else 'disabled'} {mod.manifest.id} {mod.manifest.version}")
    for diagnostic in result.diagnostics:
        print(f"  ! {diagnostic}")
    return 1 if result.diagnostics else 0


def _toggle(args: argparse.Namespace, enabled: bool) -> int:
    if not is_valid_id(args.id):
        print(f"invalid mod id: {args.id!r}")
        return 1
    root = _root(args)
    result = load_mods(root, _extra(args), allow_feature_mods=_allow_feature_mods(root))
    if args.id not in {mod.manifest.id for mod in result.mods}:
        print(f"unknown mod: {args.id}")
        return 1
    state.set_enabled(root, args.id, enabled)
    print(f"{'enabled' if enabled else 'disabled'} {args.id}")
    return 0


def _namespace_argv(args: argparse.Namespace) -> list[str]:
    tokens: list[str] = []
    root = getattr(args, "root", None)
    if root is not None:
        tokens.extend(["--root", str(root)])
    for item in getattr(args, "mods_dir", None) or ():
        tokens.extend(["--mods-dir", str(item)])
    tokens.extend(str(item) for item in getattr(args, "mods_argv", None) or ())
    return tokens


def main(argv: list[str] | argparse.Namespace | None = None) -> int:
    if isinstance(argv, argparse.Namespace):
        tokens = _namespace_argv(argv)
    elif argv is None:
        tokens = list(sys.argv[1:])
    else:
        tokens = list(argv)
    if tokens and tokens[0] == "mods":
        tokens = tokens[1:]
    parser = _parser()
    try:
        args = parser.parse_args(tokens)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1

    if args.command == "list":
        return _report_mods(args, verbose=False)
    if args.command == "validate":
        problems = installer.validate(args.path)
        for problem in problems:
            print(problem)
        if not problems:
            print(f"ok: {args.path}")
            return 0
        return 1
    if args.command == "enable":
        return _toggle(args, True)
    if args.command == "disable":
        return _toggle(args, False)
    if args.command == "install":
        ok, message = installer.install(args.path, _root(args), force=args.force)
        print(message)
        return 0 if ok else 1
    if args.command == "remove":
        ok, message = installer.remove(_root(args), args.id)
        print(message)
        return 0 if ok else 1
    if args.command == "doctor":
        return _doctor(args)
    parser.print_usage()
    return 1
