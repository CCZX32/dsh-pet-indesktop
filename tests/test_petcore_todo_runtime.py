from copy import deepcopy
from datetime import datetime, timedelta
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from petcore.mods.feature import import_entrypoint
from tests.petcore_reminder_support import Harness


@pytest.fixture
def setup(tmp_path):
    factory = import_entrypoint(Path('examples/petcore-mods/reminder.todo'), 'host/__init__.py:create_host', 'reminder.todo')
    package = factory.__module__.rsplit('.', 1)[0]
    runtime = importlib.import_module(package + '.runtime')
    h = Harness(tmp_path)
    now = [datetime(2032, 1, 2, 9)]
    r = runtime.TodoRuntime(h.context, now=lambda: now[0])
    r.start()
    yield h, r, now
    r.stop()
    h.close()


def test_slots_restart_grace_closed_pet_and_no_unchanged_writes(setup, monkeypatch):
    h, r, now = setup
    a = r.add(0, title='零', kind='once', date='2032-01-02', time='09:05')
    r.add(1, title='一', kind='once', date='2032-01-02', time='09:05')
    r.tick()
    assert h.presentation.messages == [(0, '提前提醒：零'), (1, '提前提醒：一')]
    assert not h.speech.calls
    store = r.store(0)
    raw = store.path.read_bytes()
    def fail(*a):
        raise AssertionError('unchanged tick must not write')
    monkeypatch.setattr(store, 'save', fail)
    r.tick()
    assert store.path.read_bytes() == raw
    monkeypatch.undo()
    closed = h.handles.pop()
    r.on_pet_removed(closed)
    now[0] += timedelta(minutes=5)
    r.tick()
    assert h.presentation.messages[-1] == (0, '到期提醒：零')
    h.handles.append(closed)
    r.on_pet_added(closed)
    r.tick()
    assert h.presentation.messages[-1] == (1, '到期提醒：一')
    count = len(h.presentation.messages)
    r.stop(); r.start(); r.tick()
    assert len(h.presentation.messages) == count
    assert r.store(0).state['items'][0]['id'] == a


def test_disk_failure_does_not_deliver_or_mutate(setup, monkeypatch):
    h, r, now = setup
    r.add(0, title='失败', kind='once', date='2032-01-02', time='09:00')
    old = deepcopy(r.store(0).state)
    def fail(*args):
        raise OSError('synthetic write failure')
    monkeypatch.setattr(r.store(0), 'save', fail)
    r.tick()
    assert r.store(0).state == old and not h.presentation.messages
    with pytest.raises(OSError):
        r.add(0, title='不保存', kind='none')
    assert r.store(0).state == old


def test_hidden_click_and_quiet_cancel_and_late_guard(setup):
    h, r, now = setup
    h.presentation.hidden.add(1)
    r.add(1, title='通知', kind='once', date='2032-01-02', time='09:00')
    r.tick()
    assert len(h.presentation.notifications) == 1
    h.presentation.notifications[0][3]()
    assert r.panels[1].isVisible()
    h.quiet.set_quiet(3600)
    r.add(0, title='静默', kind='once', date='2032-01-02', time='09:00')
    h.handles[0].config.set('todo_reminder_speak', True)
    r.tick()
    assert not h.speech.calls
    r.stop()
    h.quiet.set_quiet(0)
    assert not h.presentation.messages
    assert not r.panels


def test_panel_crud_settings_cancel_preserves_trigger_state_30_cycles(setup):
    h, r, now = setup
    package = r.__class__.__module__.rsplit('.', 1)[0]
    Page = importlib.import_module(package + '.settings_page').TodoPage
    host = SimpleNamespace(config=h.handles[0].config, window=h.handles[0])
    page = Page(host, runtime=r)
    page.enabled.setChecked(False)
    entry = r.add(0, title='保留', kind='once', date='2032-01-02', time='09:00')
    page.discard_changes()
    r.tick()
    state = deepcopy(r.store(0).state)
    page.voice.setChecked(True)
    page.discard_changes()
    assert r.store(0).state == state
    for _ in range(30):
        r.open_panel(0)
        panel = r.panels[0]
        panel.new_button.click()
        editor = panel.editor
        editor.title_edit.setPlainText('新条目')
        editor.save_button.click()
        assert len(r.store(0).state['items']) == 2
        r.delete(0, r.store(0).state['items'][-1]['id'])
        panel.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        h.app.processEvents()
        assert not r.panels
    r.update(0, entry, title='已修改')
    r.toggle(0, entry)
    assert not r.store(0).state['items'][0]['enabled']
    page.deleteLater()


def test_synchronous_speech_failure_does_not_leave_token_or_crash(setup):
    h, r, _ = setup
    def speak(request, **kwargs):
        kwargs['on_error'](RuntimeError('synthetic synchronous rejection'))
        return 'rejected'
    h.speech.speak = speak
    h.handles[0].config.set('todo_reminder_speak', True)
    r.add(0, title='同步拒绝', kind='once', date='2032-01-02', time='09:00')
    r.tick()
    assert not r._tokens.get(0)
