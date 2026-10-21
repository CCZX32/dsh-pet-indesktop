from __future__ import annotations

from petcore.contracts.host import HostPorts
from petcore.mods import feature as feature_mod

CORE_IDS = {
    "fun.self-talk",
    "fun.click-talk",
    "tool.quick-launch",
    "tool.quiet-mode",
    "tool.links",
    "tool.memory-trim",
    "tool.network-info",
}


def test_builtin_features_load_and_have_settings() -> None:
    manager = feature_mod.FeatureManager(HostPorts())
    diagnostics = manager.load_builtin_features()
    assert diagnostics == []
    assert CORE_IDS == set(manager.features)

    owners_with_menu = {feature.owner for feature, _ in manager.menu_contributions()}
    owners_with_settings = {
        feature.owner
        for feature in manager.features.values()
        for contribution in feature.definition.contributions
        if contribution.kind == "settings_page"
    }
    assert owners_with_menu <= owners_with_settings


def test_builtin_feature_menus_are_unique() -> None:
    manager = feature_mod.FeatureManager(HostPorts())
    assert manager.load_builtin_features() == []
    ids = [f"{feature.owner}:{contribution.id}" for feature, contribution in manager.menu_contributions()]
    assert len(ids) == len(set(ids))


def test_core_features_group_and_host_page() -> None:
    manager = feature_mod.FeatureManager(HostPorts())
    assert manager.load_builtin_features() == []
    specs = {spec.owner: spec for spec in manager.settings_pages()}
    assert set(specs) == CORE_IDS
    assert {spec.group for spec in specs.values()} == {"core"}
    assert specs["fun.click-talk"].host_page == "interaction"
    assert specs["tool.quick-launch"].host_page == "menu"
    assert specs["tool.links"].host_page == "about"


def test_embedded_pages_are_grouped_by_host_page() -> None:
    manager = feature_mod.FeatureManager(HostPorts())
    assert manager.load_builtin_features() == []

    interaction = manager.embedded_pages("interaction")
    assert [spec.owner for spec in interaction] == [
        "fun.click-talk",
        "fun.self-talk",
        "tool.quiet-mode",
    ]
    assert [spec.order for spec in interaction] == sorted(spec.order for spec in interaction)

    assert [spec.owner for spec in manager.embedded_pages("menu")] == ["tool.quick-launch"]
    assert [spec.owner for spec in manager.embedded_pages("about")] == [
        "tool.links",
        "tool.memory-trim",
        "tool.network-info",
    ]
    assert manager.embedded_pages("") == []
    assert manager.embedded_pages("mods") == []
