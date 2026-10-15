"""Public build-export contract; no Android SDK or network required."""
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.export_android_assets import export_prepared


def prepared(tmp_path):
    video = tmp_path / "videos"
    video.mkdir()
    (video / "manifest.json").write_text(json.dumps({"body_box": [2, 1, 6, 7]}))
    clips = {}
    for group in ("idle", "move", "turn", "click", "drag"):
        source = video / group / "pet.webm"
        source.parent.mkdir()
        source.write_bytes(b"source")
        frames = tmp_path / "frames" / group
        frames.mkdir(parents=True)
        (frames / "meta.json").write_text(json.dumps({"fps": 24, "frames": 2}))
        for n in (1, 2):
            im = Image.new("RGBA", (8, 8))
            im.paste((25, 120, 180, 255), (2, 1, 6, 7))
            im.save(frames / f"f_{n:04d}.webp", lossless=True)
        clips[source] = frames
    return video, clips


def test_export_preserves_alpha_timing_geometry_and_source_identity(tmp_path):
    video, clips = prepared(tmp_path)
    output = tmp_path / "mobile"
    result = export_prepared(video, clips, output, ["Hello"])
    assert result["schema_version"] == 1
    assert result["body_box"] == [2, 1, 6, 7]
    assert result["phrases"] == ["Hello"]
    assert {c["group"] for c in result["clips"]} == {"idle", "move", "turn", "click", "drag"}
    for clip in result["clips"]:
        assert clip["fps"] == 24
        assert clip["frames"] == 2
        assert clip["source"].endswith("pet.webm")
        frame = Image.open(output / "pet" / clip["path"] / "f_0001.webp")
        assert frame.mode == "RGBA"
        assert frame.getpixel((0, 0))[3] == 0
    assert json.loads((output / "pet/manifest.json").read_text(encoding="utf8")) == result


def test_missing_required_action_fails_build(tmp_path):
    video, clips = prepared(tmp_path)
    clips = {s: f for s, f in clips.items() if s.parent.name != "drag"}
    with pytest.raises(ValueError, match="drag"):
        export_prepared(video, clips, tmp_path / "mobile", ["Hello"])


def test_missing_frame_fails_before_publishing_manifest(tmp_path):
    video, clips = prepared(tmp_path)
    next(iter(clips.values())).joinpath("f_0002.webp").unlink()
    output = tmp_path / "mobile"
    with pytest.raises(ValueError, match="frame"):
        export_prepared(video, clips, output, ["Hello"])
    assert not (output / "pet/manifest.json").exists()


def test_export_cannot_write_inside_source_package(tmp_path):
    video, clips = prepared(tmp_path)
    with pytest.raises(ValueError, match="source"):
        export_prepared(video, clips, video / "mobile", ["Hello"])
