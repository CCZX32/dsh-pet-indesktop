from __future__ import annotations

import json
import logging
from pathlib import Path

from .. import paths
from ..contracts.content import AnimationSpec, CharacterSpec
from ..engine.enums import AnimatType, GraphType, ModeType
from ..engine.geometry import HEAD_FALLBACK_RATIO

logger = logging.getLogger("petcore.content.legacy")

MEDIA_SUFFIXES = (".webm", ".gif")

_FOLDER_MAP: dict[str, tuple[GraphType, AnimatType, str, bool]] = {
    "idle": (GraphType.IDEL, AnimatType.B_LOOP, "ground", True),
    "idle_turn": (GraphType.IDEL, AnimatType.B_LOOP, "ground", True),
    "turn": (GraphType.MOVE, AnimatType.B_LOOP, "in_place", False),
    "move": (GraphType.MOVE, AnimatType.B_LOOP, "ground", False),
    "click": (GraphType.TOUCH_BODY, AnimatType.SINGLE, "ground", False),
    "drag": (GraphType.RAISED_STATIC, AnimatType.SINGLE, "ground", False),
    "raised_static": (GraphType.RAISED_STATIC, AnimatType.SINGLE, "ground", False),
    "raised_dynamic": (GraphType.RAISED_DYNAMIC, AnimatType.B_LOOP, "ground", False),
    "touch_head": (GraphType.TOUCH_HEAD, AnimatType.SINGLE, "ground", False),
    "say": (GraphType.SAY, AnimatType.SINGLE, "ground", False),
    "sleep": (GraphType.SLEEP, AnimatType.B_LOOP, "ground", True),
    "startup": (GraphType.STARTUP, AnimatType.SINGLE, "ground", False),
    "start_up": (GraphType.STARTUP, AnimatType.SINGLE, "ground", False),
    "work": (GraphType.WORK, AnimatType.B_LOOP, "ground", True),
    # events/<group>/<name>.webm：语义事件动画（如 events/balance/余额-*.webm），
    # 不进随机动作池，只能由 play_event() 显式触发。
    "events": (GraphType.EVENT, AnimatType.SINGLE, "ground", False),
}


def _media_files(videos_dir: Path) -> list[Path]:
    files = [
        path
        for path in videos_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
    ]
    return sorted(files, key=lambda item: (item.parent.as_posix(), item.name))


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid_box(value) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (int(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not (0 <= x1 < x2 <= 640 and 0 <= y1 < y2 <= 360):
        return None
    return x1, y1, x2, y2


def _read_manifest(character_dir: Path) -> dict:
    for candidate in (character_dir / "videos" / "manifest.json", character_dir / "manifest.json"):
        if candidate.exists():
            return _read_json(candidate)
    return {}


def _move_data(videos_dir: Path) -> tuple[dict[str, int], dict[str, tuple[float, ...]]]:
    raw = _read_json(videos_dir / "move_strides.json")
    strides: dict[str, int] = {}
    curves: dict[str, tuple[float, ...]] = {}
    for name, value in raw.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            stride = value
            curve = None
        elif isinstance(value, dict):
            stride = value.get("stride")
            curve = value.get("curve")
        else:
            continue
        if not isinstance(stride, bool) and isinstance(stride, int) and stride > 0:
            strides[str(name)] = stride
        cleaned = _clean_curve(curve)
        if cleaned is not None:
            curves[str(name)] = cleaned
    return strides, curves


def _clean_curve(value) -> tuple[float, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    cleaned: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if number != number:
            return None
        cleaned.append(max(0.0, min(1.0, number)))
    if cleaned[-1] < 1.0 - 1e-6:
        logger.debug("move curve does not end at 1.0; keeping raw values")
    return tuple(cleaned)


def _read_move_strides(videos_dir: Path) -> dict[str, int]:
    return _move_data(videos_dir)[0]


def _read_move_curves(videos_dir: Path) -> dict[str, tuple[float, ...]]:
    return _move_data(videos_dir)[1]


def _read_text_clips(videos_dir: Path) -> frozenset[str]:
    raw = _read_json(videos_dir / "text_clips.json")
    names = raw.get("no_mirror")
    if not isinstance(names, list):
        return frozenset()
    return frozenset(str(name) for name in names if isinstance(name, str))


def _frameseq_for(
    webm: Path, videos_dir: Path, frameseq_root: Path, mode: str
) -> Path | None:
    if mode == "off" or not frameseq_root.is_dir():
        return None
    try:
        from pet import frameseq_provision
    except Exception:
        return None
    try:
        generation = frameseq_provision.current_generation(webm, videos_dir, frameseq_root)
    except Exception:
        logger.debug("frameseq adoption failed for %s", webm, exc_info=True)
        return None
    return Path(generation) if generation is not None else None


def list_characters(root: Path | None = None) -> list[str]:
    base = Path(root) if root is not None else paths.legacy_characters_root()
    if not base.is_dir():
        return []
    names = []
    for child in base.iterdir():
        videos = child / "videos"
        if not child.is_dir() or not videos.is_dir():
            continue
        if any(path.suffix.lower() in MEDIA_SUFFIXES for path in videos.rglob("*")):
            names.append(child.name)
    return sorted(names)


def build_animations(
    videos_dir: Path, frameseq_root: Path, frameseq_mode: str = "auto"
) -> tuple[AnimationSpec, ...]:
    files = _media_files(videos_dir)
    animations: list[AnimationSpec] = []
    used_names: set[str] = set()
    for path in files:
        relative = path.relative_to(videos_dir)
        folder = relative.parts[0] if len(relative.parts) > 1 else ""
        graph, animat, locate, loop = _FOLDER_MAP.get(
            folder, (GraphType.DEFAULT, AnimatType.SINGLE, "ground", False)
        )
        event_group = ""
        if graph is GraphType.EVENT and len(relative.parts) > 2:
            event_group = str(relative.parts[1])
        name = path.stem
        if name in used_names:
            name = f"{folder}/{path.stem}" if folder else f"{path.parent.name}/{path.stem}"
        used_names.add(name)
        frameseq_dir = (
            _frameseq_for(path, videos_dir, frameseq_root, frameseq_mode)
            if path.suffix.lower() == ".webm"
            else None
        )
        animations.append(
            AnimationSpec(
                name=name,
                graph=graph,
                animat=animat,
                mode=ModeType.NOMAL,
                path=path,
                frameseq_dir=frameseq_dir,
                locate=locate,
                loop=loop,
                event_group=event_group,
            )
        )
    return tuple(animations)


def load_character(
    character_id: str,
    *,
    root: Path | None = None,
    frameseq_mode: str = "auto",
) -> CharacterSpec | None:
    base = Path(root) if root is not None else paths.legacy_characters_root()
    character_dir = base / character_id
    videos_dir = character_dir / "videos"
    if not videos_dir.is_dir():
        return None
    files = _media_files(videos_dir)
    if not files:
        return None

    manifest = _read_manifest(character_dir)
    body_box = _valid_box(manifest.get("body_box"))
    head_box = _valid_box(manifest.get("head_box"))
    if head_box is None and body_box is not None:
        x1, y1, x2, y2 = body_box
        head_box = (x1, y1, x2, y1 + round((y2 - y1) * HEAD_FALLBACK_RATIO))

    frameseq_root = character_dir / "frameseq"
    animations = build_animations(videos_dir, frameseq_root, frameseq_mode)
    suffixes = {path.suffix.lower() for path in files}
    media_kind = "mixed" if len(suffixes) > 1 else suffixes.pop().lstrip(".")
    display_name = str(manifest.get("name") or character_id)
    return CharacterSpec(
        id=character_id,
        name=display_name,
        root=character_dir,
        media_kind=media_kind,
        animations=animations,
        body_box=body_box,
        head_box=head_box,
        move_strides=_read_move_strides(videos_dir),
        move_curves=_read_move_curves(videos_dir),
        text_clips=_read_text_clips(videos_dir),
        phrases_path=(videos_dir / "phrases.json") if (videos_dir / "phrases.json").exists() else None,
        owner="legacy",
    )


def load_all(
    *, root: Path | None = None, frameseq_mode: str = "auto"
) -> list[CharacterSpec]:
    specs = []
    for character_id in list_characters(root):
        spec = load_character(character_id, root=root, frameseq_mode=frameseq_mode)
        if spec is not None:
            specs.append(spec)
    return specs
