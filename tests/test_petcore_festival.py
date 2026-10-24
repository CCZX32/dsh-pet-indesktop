from copy import deepcopy
from datetime import datetime
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from petcore.config import Config, GLOBAL_CONFIG_KEYS
from petcore.mods.feature import import_entrypoint
from tests.petcore_reminder_support import Harness


@pytest.fixture
def setup(tmp_path):
    factory = import_entrypoint(Path('examples/petcore-mods/fun.festival'), 'host/__init__.py:create_host', 'fun.festival')
    module = importlib.import_module(factory.__module__.rsplit('.', 1)[0] + '.runtime')
    h = Harness(tmp_path)
    now = [datetime(2032, 2, 29, 9)]
    r = module.FestivalRuntime(h.context, now=lambda: now[0])
    r.start()
    yield h, r, now
    r.stop(); h.close()


def birthday(config, value='02-29'):
    config.set('festival_reminder_enabled', True)
    config.set('festival_birthday', value)
    for key in ('cn', 'solar_terms', 'west'):
        config.set('festival_reminder_' + key, False)


def test_defaults_are_per_pet_manual_is_not_automatic(tmp_path):
    config = Config(tmp_path)
    assert config.get('festival_enabled') is True
    assert config.get('festival_reminder_enabled') is False
    assert config.get('festival_reminder_speak') is False
    assert config.get('festival_birthday') == ''
    assert not {k for k in config.data if k.startswith('festival_')} & GLOBAL_CONFIG_KEYS
    for value, expected in [('02-29', '02-29'), ('02-30', ''), ('2032-02-29', ''), ('2-9', ''), ('', '')]:
        config.set('festival_birthday', value)
        assert config.get('festival_birthday') == expected
    for value, expected in [(0, 1), (9, 6), (3, 3)]:
        config.set('festival_reminder_count', value)
        assert config.get('festival_reminder_count') == expected


def test_birthday_categories_restart_rollback_and_unmodified_tick(setup, monkeypatch):
    h, r, now = setup
    assert not h.presentation.messages and not h.speech.calls
    birthday(h.handles[1].config)
    r.preferences_changed(1)
    r.tick()
    assert len(h.presentation.messages) == 1
    assert h.presentation.messages[0][0] == 1 and '生日快乐' in h.presentation.messages[0][1]
    store = r.store(1)
    raw = store.path.read_bytes()
    def fail(*a):
        raise AssertionError('unchanged tick must not write')
    monkeypatch.setattr(store, 'save', fail)
    r.tick(); r.tick()
    assert store.path.read_bytes() == raw
    monkeypatch.undo()
    r.stop(); r.start(); r.tick()
    assert len(h.presentation.messages) == 1
    now[0] = datetime(2032, 2, 29, 21)
    r.tick()
    assert len(h.presentation.messages) == 2
    now[0] = datetime(2032, 2, 29, 9)
    r.tick()
    assert len(h.presentation.messages) == 2
    now[0] = datetime(2033, 2, 28, 9)
    r.tick()
    now[0] = datetime(2033, 3, 1, 9)
    r.tick()
    assert len(h.presentation.messages) == 2


def test_startup_midday_custom_schedule_quiet_and_closed_pet(setup):
    h, r, now = setup
    birthday(h.handles[0].config)
    h.handles[0].config.set('festival_reminder_mode', 'custom')
    h.handles[0].config.set('festival_reminder_times', '09:00, 15:00')
    now[0] = datetime(2032, 2, 29, 12)
    h.quiet.set_quiet(3600)
    r.preferences_changed(0)
    r.tick()
    assert not h.presentation.messages and not h.speech.calls
    h.quiet.set_quiet(0)
    assert len(h.presentation.messages) == 1 and '汇总' not in h.presentation.messages[0][1]  # summary text begins 免打扰
    now[0] = datetime(2032, 2, 29, 15)
    r.tick()
    assert len(h.presentation.messages) == 2
    r.stop(); r.start()
    assert len(h.presentation.messages) == 2
    closed = h.handles.pop(0)
    r.on_pet_removed(closed)
    now[0] = datetime(2036, 2, 29, 15)
    r.tick()
    assert len(h.presentation.messages) == 2


def test_yield_is_independent_of_timer_order_and_revoked(setup):
    h, r, now = setup
    birthday(h.handles[0].config)
    h.handles[0].config.set('festival_reminder_speak', True)
    assert h.speech.should_yield(now[0], requester='voice.chime')
    r.tick()
    assert h.speech.should_yield(now[0], requester='voice.chime')
    assert len(h.speech.calls) == 1
    h.handles[0].config.set('festival_reminder_speak', False)
    assert not h.speech.should_yield(now[0], requester='voice.chime')
    r.stop()
    assert not h.speech.rules
    h.speech.calls[0][2]['on_error'](Exception('late'))
    assert len(h.presentation.messages) == 1


def test_save_failure_preserves_state_and_settings_cancel(setup, monkeypatch):
    h, r, now = setup
    birthday(h.handles[0].config)
    store = r.store(0)
    before = deepcopy(store.state)
    def fail(*args):
        raise OSError('synthetic')
    monkeypatch.setattr(store, 'save', fail)
    r.tick()
    assert store.state == before and not h.presentation.messages
    monkeypatch.undo()
    r.tick()
    state = deepcopy(store.state)
    Page = importlib.import_module(r.__class__.__module__.rsplit('.', 1)[0] + '.settings_page').FestivalPage
    page = Page(SimpleNamespace(config=h.handles[0].config, window=h.handles[0]), runtime=r)
    page.controls['festival_birthday'].setText('12-01')
    page.controls['festival_reminder_enabled'].setChecked(False)
    page.discard_changes()
    assert h.handles[0].config.get('festival_birthday') == '02-29'
    assert h.handles[0].config.get('festival_reminder_enabled') is True
    assert store.state == state
    page.deleteLater()
