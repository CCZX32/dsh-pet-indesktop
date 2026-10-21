from __future__ import annotations

from petcore.ui.menu_actions import core_items
from petcore.ui.settings.coverage import (
    CORE_MENU_SETTINGS_COVERAGE,
    SETTINGS_EXEMPT,
    missing_settings_entries,
)
from petcore.ui.settings.dialog import _PAGE_KEYS


class StubWindow:
    state = type("State", (), {"scale": 0.72})()

    def toggle_hidden(self):
        return None

    def toggle_always_on_top(self):
        return None

    def toggle_click_through(self):
        return None

    def toggle_edge_probe(self):
        return None

    def return_corner(self):
        return None

    def move_to_primary(self):
        return None

    def reload_mods(self):
        return None

    def open_data_dir(self):
        return None

    def open_settings(self):
        return None

    def quit_from_menu(self):
        return None

    def show_about(self):
        return None

    def quit_app(self):
        return None


def test_every_core_menu_item_has_a_settings_home():
    items = core_items(StubWindow())
    assert missing_settings_entries(items) == []
    assert set(CORE_MENU_SETTINGS_COVERAGE) | SETTINGS_EXEMPT == set(items)


def test_coverage_points_at_real_pages_and_rows():
    pages = set(_PAGE_KEYS.values())
    for menu_id, (page, row) in CORE_MENU_SETTINGS_COVERAGE.items():
        assert page in pages, menu_id
        assert row.strip(), menu_id
