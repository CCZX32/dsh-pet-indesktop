from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidgetAction

from petcore.config import Config
from petcore.contracts.content import CharacterSpec
from petcore.ui.easter_egg_entry import build_easter_egg_entry
from petcore.ui.menu_model import MenuItem, MenuModel
from petcore.ui.pet_window import PetWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _model() -> MenuModel:
    model = MenuModel()
    model.register(MenuItem("a", "A", order=20))
    model.register(MenuItem("b", "B", order=10, checked=lambda: True))
    model.register(MenuItem("c", "C", owner="mod.x", order=30))
    return model


class FakeHost:
    def __init__(self, characters):
        self._characters = characters
        self.pets = None
        self.tray = None

    def characters(self):
        return list(self._characters)

    def build_menu(self, parent=None):
        return None

    def open_settings(self, initial_page=None):
        return None

    def reload_mods(self):
        return None

    def open_data_dir(self):
        return None

    def quit_app(self):
        return None


def fallback() -> CharacterSpec:
    return CharacterSpec(id="fallback", name="Fallback", root=Path("."), media_kind="none", animations=())


class EggWindow:
    """只提供彩蛋行需要的最小窗口接口。"""

    def __init__(self, root: Path) -> None:
        self.config = Config(root)
        self.easter = self
        self.clicked = 0

    def images(self):
        return []

    def show_easter_egg(self) -> bool:
        self.clicked += 1
        return True


def _pet_window(tmp_path: Path, slot: int) -> PetWindow:
    config = Config(tmp_path, filename=f"config-slot-{slot}.json")
    return PetWindow(config, tmp_path, FakeHost([fallback()]), slot=slot)


def test_order_and_visibility_preferences() -> None:
    model = _model()
    assert [item.id for item in model.visible_items()] == ["b", "a", "c"]
    model.apply_preferences(hidden=["a"], order=["c", "a", "b"])
    assert [item.id for item in model.visible_items()] == ["c", "b"]
    assert model.is_hidden("a")
    model.set_hidden("a", False)
    assert [item.id for item in model.visible_items()] == ["c", "a", "b"]


def test_owner_unregister_removes_only_its_items() -> None:
    model = _model()
    model.unregister_owner("mod.x")
    assert model.snapshot() == ["b", "a"]


def test_build_creates_checkable_actions(qapp) -> None:
    model = _model()
    menu = model.build()
    assert isinstance(menu, QMenu)
    labels = [action.text() for action in menu.actions()]
    assert labels == ["B", "A", "C"]
    checkable = {action.text(): action.isCheckable() for action in menu.actions()}
    assert checkable["B"] is True
    assert checkable["A"] is False


def test_callback_is_wired(qapp) -> None:
    fired: list[int] = []
    model = MenuModel()
    model.register(MenuItem("x", "X", callback=lambda: fired.append(1)))
    menu = model.build()
    menu.actions()[0].trigger()
    assert fired == [1]


def test_layout_drives_order_separators_and_submenus(qapp) -> None:
    model = MenuModel()
    model.register(MenuItem("a", "A", icon="character"))
    model.register(MenuItem("b", "B"))
    model.apply_layout(
        (
            {"type": "action", "id": "b"},
            {"type": "separator", "id": "s"},
            {"type": "submenu", "id": "sub", "label": "子", "children": ({"type": "action", "id": "a"},)},
        )
    )
    menu = model.build()
    labels = [action.text() for action in menu.actions()]
    assert labels == ["B", "", "子"]
    assert menu.actions()[2].menu().actions()[0].text() == "A"
    assert model.snapshot() == ["b", "a"]


def test_menu_style_and_icons_are_applied(qapp) -> None:
    from petcore.ui.icons import icon
    from petcore.ui.menu_style import menu_stylesheet

    stylesheet = menu_stylesheet()
    assert "QMenu::item" in stylesheet
    assert "min-height: 26px" in stylesheet
    assert "font-size: 13px" in stylesheet
    assert "min-height: 31px" in menu_stylesheet(font_size=18)
    assert "font-size: 18px" in menu_stylesheet(font_size=18)
    assert "font-size: 13px" in menu_stylesheet(dark=True)
    assert not icon("character").isNull()
    assert not icon("quit").isNull()


def test_file_icon_spec_is_used_by_the_menu(qapp, tmp_path) -> None:
    from petcore.ui.icons import file_icon, image_error

    path = tmp_path / "icon.png"
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFF3366)
    assert image.save(str(path))
    assert image_error(path) == ""
    assert not file_icon(path).isNull()

    model = MenuModel()
    model.register(MenuItem("a", "A"))
    model.apply_layout(
        (
            {
                "type": "action",
                "id": "a",
                "icon": {"kind": "file", "path": str(path), "display": "contain"},
            },
        )
    )
    menu = model.build()
    assert not menu.actions()[0].icon().isNull()


def test_builder_replaces_the_plain_action(qapp, tmp_path: Path) -> None:
    window = EggWindow(tmp_path)
    built: list[QMenu] = []

    def builder(menu: QMenu) -> None:
        built.append(menu)
        build_easter_egg_entry(menu, window)

    model = MenuModel()
    model.register(MenuItem("a", "A", order=10))
    model.register(MenuItem("egg", "彩蛋图片", builder=builder, order=20))
    menu = model.build()

    assert built == [menu]
    labels = [action.text() for action in menu.actions()]
    assert labels[0] == "A"
    action = menu.actions()[-1]
    assert isinstance(action, QWidgetAction)
    assert action.defaultWidget() is not None


def test_builder_runs_inside_a_layout_node(qapp, tmp_path: Path) -> None:
    window = EggWindow(tmp_path)
    model = MenuModel()
    model.register(MenuItem("a", "A"))
    model.register(
        MenuItem("egg", "彩蛋图片", builder=lambda menu: build_easter_egg_entry(menu, window))
    )
    model.apply_layout(
        (
            {"type": "action", "id": "egg", "visible": True},
            {"type": "action", "id": "a", "visible": True},
        )
    )
    menu = model.build()
    assert isinstance(menu.actions()[0], QWidgetAction)
    assert menu.actions()[1].text() == "A"


def test_easter_egg_row_shows_title_and_triggers_after_menu_closes(
    qapp, tmp_path: Path
) -> None:
    window = EggWindow(tmp_path)
    window.config.set("easter_egg_title", "秘密彩蛋")
    menu = QMenu()
    action = build_easter_egg_entry(menu, window)
    row = action.defaultWidget()

    assert row.height() == 39
    assert "秘密彩蛋" in row.title_label.text()
    assert row.hint_label.text() == "请点击"

    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    assert window.clicked == 0, "彩蛋必须在菜单关闭后才执行"
    qapp.processEvents()
    assert window.clicked == 1


def test_easter_egg_row_falls_back_to_bundled_avatar(qapp, tmp_path: Path) -> None:
    window = EggWindow(tmp_path)
    menu = QMenu()
    action = build_easter_egg_entry(menu, window)
    row = action.defaultWidget()
    # 图片目录为空时必须回退到随包素材（存在时才有头像）。
    assert row.avatar_label is None or row.avatar_label.pixmap().isNull() is False
    assert action.text() == "彩蛋图片"


def test_easter_egg_row_uses_a_directory_image(qapp, tmp_path: Path) -> None:
    folder = tmp_path / "eggs"
    folder.mkdir()
    image = QImage(64, 64, QImage.Format.Format_ARGB32)
    image.fill(QColor("#30a0ff"))
    path = folder / "a.png"
    assert image.save(str(path))
    window = EggWindow(tmp_path)
    window.images = lambda: [path]
    menu = QMenu()
    action = build_easter_egg_entry(menu, window)
    row = action.defaultWidget()
    assert row.avatar_label is not None
    assert not row.avatar_label.pixmap().isNull()


def test_core_items_quit_label_follows_the_slot(qapp, tmp_path: Path) -> None:
    from petcore.ui.menu_actions import core_items

    primary = _pet_window(tmp_path, 0)
    child = _pet_window(tmp_path, 1)
    try:
        assert core_items(primary)["quit"].label == "退出"
        assert core_items(child)["quit"].label == "退出这只"
        assert core_items(primary)["quit"].id == "quit"
    finally:
        primary.shutdown()
        child.shutdown()


def test_core_items_easter_egg_uses_a_builder(qapp, tmp_path: Path) -> None:
    from petcore.ui.menu_actions import core_items

    window = _pet_window(tmp_path, 0)
    try:
        item = core_items(window)["easter_egg"]
        assert item.label == "彩蛋图片"
        assert item.builder is not None
        model = MenuModel()
        model.register(item)
        menu = model.build()
        assert isinstance(menu.actions()[-1], QWidgetAction)
    finally:
        window.shutdown()


class AnimWindow:
    """只提供「播放动画」子树需要的窗口接口。"""

    def __init__(self, root: Path, catalog, config=None) -> None:
        self.catalog = catalog
        self.config = Config(root) if config is None else config
        self.played: list[str] = []

    def play_animation(self, name: str) -> None:
        self.played.append(name)


def _animation_spec(name: str, graph, *, locate: str = "ground", **extra):
    from petcore.contracts.content import AnimationSpec
    from petcore.engine.enums import AnimatType

    return AnimationSpec(
        name=name,
        graph=graph,
        animat=AnimatType.SINGLE,
        locate=locate,
        **extra,
    )


def _catalog(specs):
    from petcore.engine.catalog import GraphCatalog

    return GraphCatalog(specs)


def _animated_window(root: Path, specs, config=None) -> AnimWindow:
    return AnimWindow(root, _catalog(specs), config=config)


def test_animation_menu_builds_only_category_submenus(qapp, tmp_path: Path) -> None:
    from petcore.engine.enums import GraphType
    from petcore.ui.menu_actions import _populate_animations

    window = _animated_window(
        tmp_path,
        [
            _animation_spec("idle_a", GraphType.IDEL),
            _animation_spec("turn_a", GraphType.MOVE, locate="in_place"),
            _animation_spec("walk_a", GraphType.MOVE, locate="ground"),
            _animation_spec("touch_a", GraphType.TOUCH_BODY),
            _animation_spec("act_a", GraphType.DEFAULT),
        ],
    )
    menu = QMenu()
    _populate_animations(window, menu)

    labels = [action.text() for action in menu.actions()]
    assert labels == ["待机", "转向", "移动", "点击回应", "随机动作"]
    for action in menu.actions():
        assert action.menu().actions() == [], f"{action.text()} 不应在构建时展开"


def test_animation_group_populates_on_about_to_show(qapp, tmp_path: Path) -> None:
    from petcore.engine.enums import GraphType
    from petcore.ui.menu_actions import _populate_animations

    window = _animated_window(
        tmp_path,
        [
            _animation_spec("idle_a", GraphType.IDEL),
            _animation_spec("idle_b", GraphType.IDEL),
        ],
    )
    menu = QMenu()
    _populate_animations(window, menu)
    idle = menu.actions()[0].menu()

    idle.aboutToShow.emit()
    assert [action.text() for action in idle.actions()] == ["idle_a", "idle_b"]

    idle.aboutToShow.emit()  # 同一个子菜单只填一次
    assert [action.text() for action in idle.actions()] == ["idle_a", "idle_b"]

    idle.actions()[0].trigger()
    assert window.played == ["idle_a"]


def test_random_actions_group_by_name_prefix_when_numerous(qapp, tmp_path: Path) -> None:
    from petcore.engine.enums import GraphType
    from petcore.ui.menu_actions import _populate_animations

    names = (
        [f"wave_{index}" for index in range(5)]
        + [f"sleep_{index}" for index in range(4)]
        + [f"misc{index}" for index in range(12)]
    )
    window = _animated_window(tmp_path, [_animation_spec(name, GraphType.DEFAULT) for name in names])
    menu = QMenu()
    _populate_animations(window, menu)
    random_menu = next(action.menu() for action in menu.actions() if action.text() == "随机动作")

    random_menu.aboutToShow.emit()
    labels = [action.text() for action in random_menu.actions()]
    assert "wave" in labels
    assert "sleep" in labels
    assert "misc0" in labels
    groups = {
        action.text(): action.menu()
        for action in random_menu.actions()
        if action.menu() is not None
    }
    assert [action.text() for action in groups["wave"].actions()] == [
        f"wave_{index}" for index in range(5)
    ]
    assert [action.text() for action in groups["sleep"].actions()] == [
        f"sleep_{index}" for index in range(4)
    ]


def test_random_actions_stay_flat_below_the_grouping_threshold(qapp, tmp_path: Path) -> None:
    from petcore.engine.enums import GraphType
    from petcore.ui.menu_actions import _populate_animations

    names = [f"wave_{index}" for index in range(6)] + ["solo"]
    window = _animated_window(tmp_path, [_animation_spec(name, GraphType.DEFAULT) for name in names])
    menu = QMenu()
    _populate_animations(window, menu)
    random_menu = next(action.menu() for action in menu.actions() if action.text() == "随机动作")

    random_menu.aboutToShow.emit()
    assert [action.text() for action in random_menu.actions()] == names
    assert all(action.menu() is None for action in random_menu.actions())


def test_animation_icon_toggle_reads_the_config_flag(qapp, tmp_path: Path) -> None:
    from petcore.engine.enums import GraphType
    from petcore.ui.menu_actions import _animation_icons_enabled, _populate_animations

    class DisabledConfig:
        def get(self, key, default=None):
            return False if key == "menu_animation_icons" else default

    window = _animated_window(
        tmp_path,
        [_animation_spec("idle_a", GraphType.IDEL)],
        config=DisabledConfig(),
    )
    assert _animation_icons_enabled(window) is False

    menu = QMenu()
    _populate_animations(window, menu)
    idle = menu.actions()[0].menu()
    idle.aboutToShow.emit()
    action = idle.actions()[0]
    assert [size.width() for size in action.icon().availableSizes()] == [36]


def test_animation_actions_get_a_decoded_thumbnail(qapp, tmp_path: Path) -> None:
    from PySide6.QtCore import QSize

    from petcore.engine.enums import GraphType
    from petcore.media.thumbnails import ThumbnailCache
    from petcore.ui.menu_actions import _populate_animations

    frames = tmp_path / "frames"
    frames.mkdir()
    for index in range(3):
        image = QImage(100, 80, QImage.Format.Format_ARGB32)
        image.fill(0xFF000000 | (index * 0x40 << 16))
        assert image.save(str(frames / f"frame_{index:03d}.png"))

    window = _animated_window(
        tmp_path,
        [
            _animation_spec(
                "idle_a",
                GraphType.IDEL,
                frameseq_dir=frames,
            )
        ],
    )
    menu = QMenu()
    _populate_animations(window, menu)
    idle = menu.actions()[0].menu()
    idle.aboutToShow.emit()
    action = idle.actions()[0]

    cache = ThumbnailCache.instance()
    assert cache.pool.waitForDone(5000)
    for _ in range(100):
        qapp.processEvents()
        if QSize(64, 51) in action.icon().availableSizes():
            break
        QTest.qWait(5)
    assert QSize(64, 51) in action.icon().availableSizes()



def test_extensions_hub_groups_actions_per_mod(qapp) -> None:
    model = MenuModel()
    model.set_owner_labels({"mod.music": "音乐", "mod.weather": "天气"})
    model.register(MenuItem("mod.music:next", "下一首", owner="mod.music", order=20))
    model.register(MenuItem("mod.music:pause", "播放 / 暂停", owner="mod.music", order=10))
    model.register(MenuItem("mod.weather:show", "看天气", owner="mod.weather", order=5))
    model.set_extension_skip_owners({"fun.self-talk"})
    model.register(MenuItem("fun.self-talk:say", "自言自语", owner="fun.self-talk", order=1))

    menu = model.build_layout(
        [
            {
                "type": "submenu",
                "id": "extensions_hub",
                "label": "扩展",
                "children": [],
            }
        ]
    )
    hub = menu.actions()[0].menu()
    assert [action.text() for action in hub.actions()] == ["天气", "音乐"]
    assert [action.text() for action in hub.actions()[1].menu().actions()] == [
        "播放 / 暂停",
        "下一首",
    ]


def test_extensions_hub_respects_layout_children_as_visibility(qapp) -> None:
    model = MenuModel()
    model.set_owner_labels({"mod.music": "音乐", "mod.weather": "天气"})
    model.register(MenuItem("mod.music:next", "下一首", owner="mod.music", order=20))
    model.register(MenuItem("mod.music:pause", "播放 / 暂停", owner="mod.music", order=10))
    model.register(MenuItem("mod.weather:show", "看天气", owner="mod.weather", order=5))

    menu = model.build_layout(
        [
            {
                "type": "submenu",
                "id": "extensions_hub",
                "label": "扩展",
                "children": [
                    {"type": "action", "id": "mod.music:pause", "visible": True}
                ],
            }
        ]
    )
    hub = menu.actions()[0].menu()
    assert [action.text() for action in hub.actions()] == ["音乐"]
    assert [action.text() for action in hub.actions()[0].menu().actions()] == [
        "播放 / 暂停"
    ]
