# -*- coding: utf-8 -*-
"""官方音乐启动器包测试的共享装配：真打包 + 真验签装载。"""

from __future__ import annotations

from pathlib import Path

from pet.feature_policy import official_package_verifier
from pet.official_features import MUSIC_FEATURE_ID
from pet.plugins.feature_packages import FeaturePackageLoader

OWNER = MUSIC_FEATURE_ID
ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE = ROOT / "features" / "music"


class MemoryVault:
    priority = 1

    def __init__(self):
        self.items = {}

    def set_password(self, service, ref, value):
        self.items[service, ref] = value

    def get_password(self, service, ref):
        return self.items.get((service, ref))

    def delete_password(self, service, ref):
        self.items.pop((service, ref), None)


def build_package(target_dir: Path) -> Path:
    from scripts.build_music_package import build_package as build

    return build(PACKAGE_SOURCE, target_dir)


def load_host(built: Path):
    verifier = official_package_verifier(OWNER)
    descriptor = verifier.verify(built)
    loader = FeaturePackageLoader(verifier)
    handle = loader.load_host(descriptor)
    return loader, descriptor, handle


def import_pkg(handle, dotted: str):
    import importlib

    return importlib.import_module(handle.namespace + "." + dotted)
