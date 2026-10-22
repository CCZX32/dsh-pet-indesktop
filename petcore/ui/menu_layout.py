from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from importlib import resources
from typing import Collection, Mapping

DEFAULT_LAYOUT_ID = "petcore-default-v1"

logger = logging.getLogger("petcore.ui.menu_layout")

#: In-code copy of ``petcore/menu_templates/petcore-default-v1.json``.
#: The packaged build can lose data files (PyInstaller only collects modules
#: unless ``--add-data`` is passed); without this fallback a missing template
#: degrades the whole right-click menu to the settings/quit fallback.
#: ``tests/test_petcore_menu_layout.py`` keeps both copies identical.
BUILTIN_DEFAULT_LAYOUT: dict = {
    "schema_version": 1,
    "layout_id": DEFAULT_LAYOUT_ID,
    "nodes": [
        {"type": "action", "id": "easter_egg", "visible": True, "section": "tools"},
        {"type": "action", "id": "character", "visible": True, "section": "profile"},
        {"type": "action", "id": "animations_hub", "visible": True, "section": "playback"},
        {"type": "action", "id": "ai_chat", "visible": True, "section": "playback"},
        {"type": "action", "id": "look_screen", "visible": True, "section": "playback"},
        {"type": "action", "id": "screen_capture", "visible": True, "section": "playback"},
        {"type": "action", "id": "playback_speed", "visible": False, "section": "playback"},
        {"type": "action", "id": "size", "visible": False, "section": "playback"},
        {"type": "separator", "id": "default.separator-playback", "visible": True},
        {
            "type": "submenu",
            "id": "pet_controls",
            "label": "桌宠控制",
            "visible": True,
            "section": "pet",
            "children": [
                {"type": "action", "id": "drag_physics", "visible": True},
                {"type": "action", "id": "no_move", "visible": True},
                {"type": "action", "id": "on_top", "visible": True},
                {"type": "action", "id": "edge_probe", "visible": True},
                {"type": "action", "id": "autostart", "visible": True},
                {"type": "action", "id": "return_corner", "visible": True},
                {"type": "action", "id": "hide_pet", "visible": True},
                {"type": "action", "id": "spawn_pet", "visible": True},
                {"type": "action", "id": "clear_spawned_pets", "visible": True},
                {"type": "action", "id": "golden_spin", "visible": True},
                {"type": "separator", "id": "default.separator-pet-tools", "visible": True},
                {"type": "action", "id": "move_to_primary", "visible": True},
                {"type": "action", "id": "reload_mods", "visible": True},
                {"type": "action", "id": "open_data", "visible": True},
            ],
        },
        {"type": "separator", "id": "default.separator-pet", "visible": True},
        {
            "type": "submenu",
            "id": "tools_help",
            "label": "工具与帮助",
            "visible": True,
            "section": "tools",
            "children": [
                {"type": "action", "id": "tool.quick-launch:open_menu", "visible": True},
                {"type": "action", "id": "api_settings", "visible": True},
                {"type": "action", "id": "tool.links:deepseek_web", "visible": True},
                {"type": "action", "id": "tool.links:github_project", "visible": True},
                {"type": "action", "id": "tool.links:quark_download", "visible": True},
                {"type": "action", "id": "tool.network-info:show", "visible": True},
                {"type": "action", "id": "tool.memory-trim:trim", "visible": True},
            ],
        },
        {"type": "action", "id": "tool.quiet-mode:quiet_30", "visible": True, "section": "tools"},
        {
            "type": "submenu",
            "id": "extensions_hub",
            "label": "扩展",
            "visible": True,
            "section": "extensions",
            "children": [],
        },
        {"type": "separator", "id": "default.separator-extensions", "visible": True},
        {"type": "action", "id": "modern_settings", "visible": True, "section": "system"},
        {"type": "separator", "id": "default.separator-system", "visible": True},
        {"type": "action", "id": "quit", "visible": True, "section": "system"},
    ],
}

_warned_builtin_fallback = False

#: Old flat preferences (pre-layout) use the previous menu ids.
LEGACY_ID_MAP = {
    "scale": "size",
    "always_on_top": "on_top",
    "hide": "hide_pet",
    "settings": "modern_settings",
    "reload": "reload_mods",
    "data": "open_data",
    "primary": "move_to_primary",
    "reset": "return_corner",
}


@dataclass(frozen=True)
class ResolvedLayout:
    nodes: tuple[dict, ...]
    source: str
    diagnostics: tuple[str, ...]


def load_default_with_source(layout_id: str = DEFAULT_LAYOUT_ID) -> tuple[dict, str]:
    """Load the default layout, returning ``(layout, "json"|"builtin")``.

    A packaged build may ship without ``petcore/menu_templates`` data; the
    in-code copy keeps the menu complete instead of falling back to a two-item
    menu. The warning is emitted once per process so a menu opened repeatedly
    does not flood the log.
    """
    global _warned_builtin_fallback
    if layout_id != DEFAULT_LAYOUT_ID:
        raise ValueError(f"unknown menu layout: {layout_id}")
    try:
        path = resources.files("petcore.menu_templates").joinpath(f"{layout_id}.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("layout_id") != layout_id or data.get("schema_version") != 1:
            raise ValueError("invalid menu layout")
    except (OSError, ValueError, ModuleNotFoundError):
        if not _warned_builtin_fallback:
            _warned_builtin_fallback = True
            logger.warning(
                "menu template %s is unavailable; falling back to the built-in layout",
                layout_id,
            )
        return deepcopy(BUILTIN_DEFAULT_LAYOUT), "builtin"
    return data, "json"


def load_default(layout_id: str = DEFAULT_LAYOUT_ID) -> dict:
    return load_default_with_source(layout_id)[0]


def normalize_separators(nodes) -> tuple[dict, ...]:
    kept: list[dict] = []
    for node in nodes:
        if node.get("type") == "separator":
            if not kept or kept[-1].get("type") == "separator":
                continue
        kept.append(node)
    while kept and kept[-1].get("type") == "separator":
        kept.pop()
    return tuple(kept)


def _action_ids(nodes) -> set[str]:
    found: set[str] = set()
    for node in nodes if isinstance(nodes, list) else ():
        if not isinstance(node, dict):
            continue
        if node.get("type") == "action":
            found.add(str(node.get("id") or ""))
        found.update(_action_ids(node.get("children", [])))
    return found


def _insert_at_template_anchor(target: list[dict], node: dict, template: list[dict], index: int) -> None:
    target_ids = [str(candidate.get("id") or "") for candidate in target]
    for sibling in reversed(template[:index]):
        sibling_id = str(sibling.get("id") or "")
        if sibling_id in target_ids:
            target.insert(target_ids.index(sibling_id) + 1, node)
            return
    for sibling in template[index + 1 :]:
        sibling_id = str(sibling.get("id") or "")
        if sibling_id in target_ids:
            target.insert(target_ids.index(sibling_id), node)
            return
    target.append(node)


def _merge_template_actions(
    target: list[dict],
    template: list[dict],
    *,
    present: set[str],
    registered: set[str],
    diagnostics: list[str],
) -> None:
    for index, default_node in enumerate(template):
        if not isinstance(default_node, dict):
            continue
        node_type = default_node.get("type")
        node_id = str(default_node.get("id") or "")
        if node_type == "action":
            if node_id in present or node_id not in registered:
                continue
            _insert_at_template_anchor(target, deepcopy(default_node), template, index)
            present.add(node_id)
            diagnostics.append(f"default-action-added:{node_id}")
            continue
        if node_type != "submenu":
            continue
        matching = next(
            (
                candidate
                for candidate in target
                if isinstance(candidate, dict)
                and candidate.get("type") == "submenu"
                and str(candidate.get("id") or "") == node_id
            ),
            None,
        )
        if matching is not None:
            children = matching.get("children")
            if not isinstance(children, list):
                children = []
                matching["children"] = children
            _merge_template_actions(
                children,
                default_node.get("children", []),
                present=present,
                registered=registered,
                diagnostics=diagnostics,
            )
            continue
        missing: list[dict] = []
        _merge_template_actions(
            missing,
            default_node.get("children", []),
            present=present,
            registered=registered,
            diagnostics=diagnostics,
        )
        if missing:
            submenu = deepcopy(default_node)
            submenu["children"] = missing
            _insert_at_template_anchor(target, submenu, template, index)


def _append_mod_actions(layout: dict, registered: set[str], diagnostics: list[str]) -> None:
    present = _action_ids(layout.get("nodes", []))
    extra = sorted(action_id for action_id in registered - present if ":" in action_id)
    if not extra:
        return
    nodes = layout.setdefault("nodes", [])
    hub = next(
        (
            node
            for node in nodes
            if isinstance(node, dict)
            and node.get("type") == "submenu"
            and node.get("id") == "extensions_hub"
        ),
        None,
    )
    if hub is None:
        hub = {"type": "submenu", "id": "extensions_hub", "label": "扩展", "visible": True, "children": []}
        nodes.append(hub)
    children = hub.setdefault("children", [])
    for action_id in extra:
        children.append({"type": "action", "id": action_id, "visible": True})
        diagnostics.append(f"mod-action-added:{action_id}")


def merge_user_layout(
    raw_layout: Mapping,
    *,
    registered: Collection[str],
    default: Mapping | None = None,
) -> tuple[dict, tuple[str, ...]]:
    """Return a copy of ``raw_layout`` with template and mod actions merged in.

    Unlike :func:`resolve` the result keeps hidden nodes and the user's order,
    so it can be written back to ``config.menu_layout`` without losing choices.
    """
    registered_set = set(registered)
    diagnostics: list[str] = []
    working = deepcopy(dict(raw_layout))
    try:
        template = (default or load_default()).get("nodes", [])
    except (OSError, ValueError, json.JSONDecodeError):
        template = []
    present = _action_ids(working.get("nodes", []))
    _merge_template_actions(
        working.setdefault("nodes", []),
        template,
        present=present,
        registered=registered_set,
        diagnostics=diagnostics,
    )
    _append_mod_actions(working, registered_set, diagnostics)
    return working, tuple(diagnostics)


def resolve(
    raw_layout: Mapping | None,
    *,
    registered: Collection[str],
    available: Collection[str],
    default: Mapping | None = None,
    include_hidden: bool = False,
) -> ResolvedLayout:
    registered_set = set(registered)
    available_set = set(available)

    def fallback(diagnostics: tuple[str, ...]) -> ResolvedLayout:
        nodes = tuple(
            {"type": "action", "id": action_id, "visible": True}
            for action_id in ("modern_settings", "quit")
            if action_id in registered_set and action_id in available_set
        )
        return ResolvedLayout(nodes, "fallback", diagnostics)

    source = "user"
    if raw_layout is None:
        try:
            raw_layout = default or load_default()
        except (OSError, ValueError, json.JSONDecodeError):
            return fallback(("default-layout-unavailable",))
        source = "default"

    if not isinstance(raw_layout, Mapping):
        return fallback(("layout-not-a-mapping",))
    if raw_layout.get("schema_version") != 1:
        return fallback((f"unsupported-schema:{raw_layout.get('schema_version')}",))

    seen: set[str] = set()
    diagnostics: list[str] = []

    def visit(nodes, depth: int = 0) -> None:
        for node in nodes if isinstance(nodes, list) else ():
            if not isinstance(node, dict):
                continue
            node_type = node.get("type")
            if node_type == "action":
                action_id = str(node.get("id") or "")
                if action_id in seen:
                    diagnostics.append(f"duplicate-action:{action_id}")
                seen.add(action_id)
            elif node_type == "submenu":
                if depth >= 1:
                    diagnostics.append(f"submenu-depth-exceeded:{node.get('id') or ''}")
                visit(node.get("children", []), depth + 1)

    visit(raw_layout.get("nodes", []))
    if any(item.startswith(("duplicate-action:", "submenu-depth-exceeded:")) for item in diagnostics):
        return fallback(tuple(diagnostics))

    working = deepcopy(dict(raw_layout))
    if source == "user":
        try:
            template = (default or load_default()).get("nodes", [])
        except (OSError, ValueError, json.JSONDecodeError):
            template = []
        present = _action_ids(working.get("nodes", []))
        _merge_template_actions(
            working.setdefault("nodes", []),
            template,
            present=present,
            registered=registered_set,
            diagnostics=diagnostics,
        )
    _append_mod_actions(working, registered_set, diagnostics)

    def resolve_nodes(nodes) -> list[dict]:
        resolved: list[dict] = []
        for node in nodes if isinstance(nodes, list) else ():
            if not isinstance(node, dict):
                continue
            visible = bool(node.get("visible", True))
            if not visible and not include_hidden:
                continue
            node_type = node.get("type")
            if node_type == "separator":
                resolved.append(
                    {"type": "separator", "id": str(node.get("id") or ""), "visible": visible}
                )
                continue
            if node_type == "action":
                action_id = str(node.get("id") or "")
                if action_id not in registered_set:
                    diagnostics.append(f"unknown-action:{action_id}")
                    continue
                is_available = action_id in available_set
                if not is_available and not include_hidden:
                    diagnostics.append(f"unavailable-action:{action_id}")
                    continue
                action = {"type": "action", "id": action_id, "visible": visible}
                if not is_available:
                    action["available"] = False
                for key in ("section", "alias", "icon"):
                    if key in node:
                        action[key] = node[key]
                resolved.append(action)
                continue
            if node_type == "submenu":
                children = resolve_nodes(node.get("children", []))
                if not include_hidden:
                    children = list(normalize_separators(children))
                if not children and not include_hidden:
                    continue
                submenu = {
                    "type": "submenu",
                    "id": str(node.get("id") or ""),
                    "label": str(node.get("label") or ""),
                    "visible": visible,
                    "children": children,
                }
                for key in ("section", "alias", "icon"):
                    if key in node:
                        submenu[key] = node[key]
                resolved.append(submenu)
        return resolved

    nodes = resolve_nodes(working.get("nodes", []))
    if not include_hidden:
        nodes = list(normalize_separators(nodes))
    return ResolvedLayout(tuple(nodes), source, tuple(diagnostics))


def _core_nodes(nodes) -> list[dict]:
    """去掉 mod 贡献与展示性字段，只留可比较的 Core 结构。"""
    core: list[dict] = []
    for node in nodes if isinstance(nodes, list) else ():
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        node_id = str(node.get("id") or "")
        if node_type == "action":
            if ":" in node_id:
                continue
            core.append(
                {
                    "type": "action",
                    "id": node_id,
                    "visible": bool(node.get("visible", True)),
                    "alias": node.get("alias"),
                    "icon": node.get("icon"),
                }
            )
        elif node_type == "separator":
            core.append(
                {
                    "type": "separator",
                    "id": node_id,
                    "visible": bool(node.get("visible", True)),
                }
            )
        elif node_type == "submenu":
            core.append(
                {
                    "type": "submenu",
                    "id": node_id,
                    "label": str(node.get("label") or ""),
                    "visible": bool(node.get("visible", True)),
                    "alias": node.get("alias"),
                    "icon": node.get("icon"),
                    "children": _core_nodes(node.get("children", [])),
                }
            )
    return core


def migrate_default_size_visibility(layout: dict) -> bool:
    """把「从未改过的旧默认布局」升级为默认隐藏大小。

    只处理同时满足以下条件的布局，避免覆盖真正的用户自定义：
    - `layout_id` 与当前默认模板一致；
    - 去掉 mod 动作后，Core 节点结构与旧默认（size 可见）完全一致；
    - `size` 节点当前可见。

    返回 True 表示已就地修改 layout。
    """
    if not isinstance(layout, dict) or layout.get("layout_id") != DEFAULT_LAYOUT_ID:
        return False
    nodes = layout.get("nodes")
    if not isinstance(nodes, list):
        return False
    size = next(
        (node for node in nodes if isinstance(node, dict) and node.get("id") == "size"),
        None,
    )
    if size is None or size.get("visible") is False:
        return False
    try:
        old_default = load_default()
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    old_size = next(
        (node for node in old_default["nodes"] if node.get("id") == "size"),
        None,
    )
    if old_size is None:
        return False
    old_size["visible"] = True
    if _core_nodes(nodes) != _core_nodes(old_default["nodes"]):
        return False
    size["visible"] = False
    return True


def _is_separator(node) -> bool:
    return isinstance(node, dict) and node.get("type") == "separator"


def _find_action(nodes, action_id: str) -> dict | None:
    for node in nodes if isinstance(nodes, list) else ():
        if not isinstance(node, dict):
            continue
        if node.get("type") == "action" and str(node.get("id") or "") == action_id:
            return node
        found = _find_action(node.get("children"), action_id)
        if found is not None:
            return found
    return None


def _take_action(nodes, action_id: str) -> dict | None:
    """摘掉任意层级上的所有同名 action，返回第一个（其余重复项丢弃）。"""
    found: dict | None = None
    if not isinstance(nodes, list):
        return None
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if not isinstance(node, dict):
            index += 1
            continue
        if node.get("type") == "action" and str(node.get("id") or "") == action_id:
            removed = nodes.pop(index)
            if found is None:
                found = removed
            continue
        nested = _take_action(node.get("children"), action_id)
        if nested is not None and found is None:
            found = nested
        index += 1
    return found


def migrate_p8_menu(layout: dict) -> bool:
    """把旧默认菜单升级成 P8 顺序（幂等，就地修改，返回是否发生变化）。

    只处理 `layout_id == "petcore-default-v1"`：

    1. 彩蛋从任意层级（含子菜单）挪到顶层第一项；
    2. 播放速率默认隐藏（用户之后可在菜单编辑器重新打开）；
    3. 顶层收尾固定为 `modern_settings / separator / quit`。

    `CoreHost.reload_menu()` 必须在 `migrate_default_size_visibility` / legacy
    迁移之前调用本函数，有变化才写盘。
    """
    if not isinstance(layout, dict) or layout.get("layout_id") != DEFAULT_LAYOUT_ID:
        return False
    nodes = layout.get("nodes")
    if not isinstance(nodes, list):
        return False
    before = deepcopy(nodes)

    egg = _take_action(nodes, "easter_egg")
    if egg is not None and (not nodes or str(nodes[0].get("id") or "") != "easter_egg"):
        nodes.insert(0, egg)

    playback = _find_action(nodes, "playback_speed")
    if playback is not None and playback.get("visible", True):
        playback["visible"] = False

    settings_index = next(
        (
            index
            for index, node in enumerate(nodes)
            if isinstance(node, dict)
            and node.get("type") == "action"
            and node.get("id") == "modern_settings"
        ),
        -1,
    )
    before_settings = (
        nodes[settings_index - 1]
        if settings_index > 0 and _is_separator(nodes[settings_index - 1])
        else None
    )

    while nodes and _is_separator(nodes[-1]):
        nodes.pop()

    settings = _take_action(nodes, "modern_settings")
    quit_node = _take_action(nodes, "quit")
    # 摘掉 modern_settings/quit 后可能留下并排的分割线：只留靠前那条。
    while len(nodes) >= 2 and _is_separator(nodes[-1]) and _is_separator(nodes[-2]):
        nodes.pop()

    if settings is None:
        settings = {"type": "action", "id": "modern_settings", "visible": True, "section": "system"}
    if quit_node is None:
        quit_node = {"type": "action", "id": "quit", "visible": True, "section": "system"}
    # modern_settings 前固定留一条分组线（有旧的就沿用），否则下一次迁移
    # 会把新加的那条当成前导分割线，越迁越多。
    if nodes and not _is_separator(nodes[-1]):
        nodes.append(
            dict(before_settings)
            if before_settings is not None
            else {"type": "separator", "id": "default.separator-settings", "visible": True}
        )
    nodes.extend(
        [
            settings,
            {"type": "separator", "id": "default.separator-system", "visible": True},
            quit_node,
        ]
    )
    return nodes != before


def _clean_submenu_children(nodes) -> None:
    for node in nodes if isinstance(nodes, list) else ():
        if not isinstance(node, dict) or node.get("type") != "submenu":
            continue
        children = node.get("children")
        if not isinstance(children, list):
            continue
        cleaned = list(normalize_separators(children))
        if cleaned != children:
            node["children"] = cleaned
        _clean_submenu_children(cleaned)


def migrate_p9_menu(layout: dict) -> bool:
    """把「鼠标穿透」从右键菜单里摘掉（P9 起只留在托盘菜单），幂等。

    旧布局可能把该项放在任意层级；这里全部移除并顺手清掉子菜单里因此变得
    重复/结尾的分割线。设置页的「点击穿透」勾选框与托盘菜单仍然可用。
    """
    if not isinstance(layout, dict) or layout.get("layout_id") != DEFAULT_LAYOUT_ID:
        return False
    nodes = layout.get("nodes")
    if not isinstance(nodes, list):
        return False
    if _take_action(nodes, "click_through") is None:
        return False
    _clean_submenu_children(nodes)
    return True


def _apply_legacy_hidden(nodes, hidden_ids: set[str]) -> None:
    for node in nodes if isinstance(nodes, list) else ():
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        if node_id in hidden_ids:
            node["visible"] = False
        _apply_legacy_hidden(node.get("children", []), hidden_ids)


def migrate_legacy(hidden: list[str] | None, order: list[str] | None) -> dict:
    layout = load_default()
    hidden_ids = {LEGACY_ID_MAP.get(str(item), str(item)) for item in (hidden or [])}
    order_ids = [LEGACY_ID_MAP.get(str(item), str(item)) for item in (order or [])]
    nodes = layout["nodes"]
    by_id = {str(node.get("id") or ""): node for node in nodes if isinstance(node, dict)}

    reordered = [by_id.pop(item_id) for item_id in order_ids if item_id in by_id]
    reordered.extend(node for node in nodes if str(node.get("id") or "") in by_id)
    _apply_legacy_hidden(reordered, hidden_ids)
    layout["nodes"] = reordered
    return layout
