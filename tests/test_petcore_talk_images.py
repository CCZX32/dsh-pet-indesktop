from __future__ import annotations

import random
from pathlib import Path

from petcore.media import talk_images


def _touch(path: Path) -> Path:
    path.write_bytes(b"x")
    return path


def test_image_files_filters_by_suffix(tmp_path: Path) -> None:
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "b.png")
    _touch(tmp_path / "c.txt")
    names = [path.name for path in talk_images.image_files(tmp_path)]
    assert names == ["a.jpg", "b.png"]


def test_pick_choice_obeys_the_percentage() -> None:
    rng = random.Random(1)
    texts = ["a", "b"]
    images = [Path("x.png"), Path("y.png")]
    for _ in range(20):
        assert talk_images.pick_choice(rng, texts, images, 100)[0] == "image"
        assert talk_images.pick_choice(rng, texts, images, 0)[0] == "text"
    assert talk_images.pick_choice(rng, [], images, 0) == ("image", rng.choice(images))
    assert talk_images.pick_choice(rng, texts, [], 100)[0] == "text"
    assert talk_images.pick_choice(rng, [], [], 50) is None


def test_configured_images_falls_back_to_builtin(tmp_path: Path, monkeypatch) -> None:
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    _touch(builtin / "a.png")
    monkeypatch.setattr(talk_images, "builtin_image_dir", lambda: builtin)
    monkeypatch.setattr(talk_images, "readable_images", talk_images.image_files)
    empty = tmp_path / "empty"
    empty.mkdir()
    config = {"self_talk_image_dir": str(empty)}
    directory, images = talk_images.configured_images(config)
    assert directory == builtin
    assert [path.name for path in images] == ["a.png"]
