from __future__ import annotations

from pathlib import Path

from ..contracts.content import AnimationSpec
from .clip import PetClip, create_clip, create_frame_clip, create_fallback_clip
from . import backends as _backends  # noqa: F401  (registers built-in backends)


class ClipLibrary:
    def __init__(self, frameseq_mode: str = "auto"):
        self.frameseq_mode = frameseq_mode if frameseq_mode in {"auto", "off", "only"} else "auto"
        self._clips: dict[str, PetClip] = {}

    def clip_for(self, spec: AnimationSpec) -> PetClip | None:
        cached = self._clips.get(spec.name)
        if cached is not None:
            return cached
        clip = self._create(spec)
        if clip is None:
            return None
        self._clips[spec.name] = clip
        return clip

    def _create(self, spec: AnimationSpec) -> PetClip | None:
        if spec.frameseq_dir is not None and self.frameseq_mode != "off":
            clip = create_frame_clip(Path(spec.frameseq_dir), spec.name)
            if clip is not None:
                return clip
            if self.frameseq_mode == "only":
                return None
        if self.frameseq_mode == "only":
            return None
        if spec.path is not None:
            return create_clip(Path(spec.path), spec.name)
        return None

    def fallback(self, name: str = "fallback") -> PetClip:
        clip = self._clips.get(name)
        if clip is None:
            clip = create_fallback_clip(name)
            self._clips[name] = clip
        return clip

    def warm_first_frame(self, spec: AnimationSpec) -> None:
        clip = self.clip_for(spec)
        if clip is not None:
            clip.warm_first_frame()

    def stop_all(self) -> None:
        for clip in self._clips.values():
            clip.stop()

    def close_all(self) -> None:
        for clip in self._clips.values():
            clip.close()
        self._clips.clear()
