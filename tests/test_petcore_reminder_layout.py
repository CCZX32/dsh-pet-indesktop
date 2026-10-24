from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from petcore.mods.feature import import_entrypoint
from tests.petcore_reminder_support import Harness
from tests.test_petcore_reminder_ports import wait_for


@pytest.mark.parametrize('owner,name', [
    ('reminder.todo', 'TodoPage'),
    ('fun.festival', 'FestivalPage'),
    ('fun.divination', 'DivinationPage'),
])
@pytest.mark.parametrize('width', [232, 600])
def test_embedded_reminder_page_controls_fit_compact_and_wide(tmp_path, owner, name, width):
    h = Harness(tmp_path)
    factory = import_entrypoint(Path('examples/petcore-mods') / owner, 'host/__init__.py:create_host', owner)
    module = import_module(factory.__module__.rsplit('.', 1)[0] + '.settings_page')
    shell = QWidget()
    shell.setFixedSize(width, 600)
    host = SimpleNamespace(config=h.handles[0].config, window=h.handles[0])
    page = getattr(module, name)(host, shell)
    page.prepare_embedded()
    layout = QVBoxLayout(shell)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(page)
    try:
        shell.show()
        wait_for(lambda: page.scroll.viewport().width() > 0)
        h.app.processEvents()
        assert page.scroll.widget().width() <= page.scroll.viewport().width(), (
            name, page.scroll.widget().width(), page.scroll.viewport().width()
        )
        if owner == 'reminder.todo':
            controls = (page.enabled, page.lead, page.voice)
        elif owner == 'fun.festival':
            controls = page.controls.values()
        else:
            controls = page.controls
        for control in controls:
            page.scroll.ensureWidgetVisible(control)
            h.app.processEvents()
            assert control.width() <= page.scroll.viewport().width()
    finally:
        shell.close()
        shell.deleteLater()
        h.close()
