"""灵动岛（Dynamic Island）：段契约、布局与采样。

- :mod:`.segments`：段状态词表、盒宽自测量、字段盒、告警判定（零 Qt）。
- :mod:`.layout`：段落位与收缩流水线（零 Qt）。
- ``petcore/ui/island.py``：唯一 Qt 面（胶囊窗口、绘制、卡片、拖拽）。
- ``petcore/platform/netmon.py`` / ``sysmon.py``：采样线程（零 Qt）。
"""

from __future__ import annotations

__all__ = ["layout", "segments"]
