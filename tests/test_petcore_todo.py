"""C acceptance tests staged while B's frozen full-suite gate runs."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
from pathlib import Path

import pytest

from petcore.mods.feature import import_entrypoint

PACK = Path(__file__).resolve().parents[1] / 'examples/petcore-mods/reminder.todo'

@pytest.fixture
def domain():
    factory = import_entrypoint(PACK, 'host/__init__.py:create_host', 'reminder.todo')
    package = factory.__module__.rsplit('.', 1)[0]
    return importlib.import_module(package + '.model')

@pytest.fixture
def repository(domain):
    return importlib.import_module(domain.__package__ + '.store')


def item(domain, kind='once', day='2032-01-02', clock='00:02'):
    return domain.new_item('合成待办', kind=kind, date=day, time=clock)


def test_legacy_migration_is_lossless_and_never_schedules(domain, repository, tmp_path):
    legacy = ['   ', '重复', '重复', '', '长' * 2000]
    store = repository.TodoStore(tmp_path, 2, legacy)
    assert [x['title'] for x in store.state['items']] == legacy
    assert all(x['kind'] == 'none' for x in store.state['items'])
    updated, fires = domain.advance(store.state, datetime(2032, 1, 2, 9))
    assert not fires and updated == store.state
    assert len({x['id'] for x in updated['items']}) == len(legacy)
    assert legacy == ['   ', '重复', '重复', '', '长' * 2000]
    assert (tmp_path / 'todo-slot-2-legacy-v1.json').exists()
    assert repository.TodoStore(tmp_path, 2, ['not a replacement']).state == store.state


@pytest.mark.parametrize('kind', ['once', 'daily'])
def test_lead_crosses_midnight_and_occurrence_is_persistent(domain, repository, tmp_path, kind):
    state = domain.new_state([])
    entry = item(domain, kind)
    state['items'].append(entry)
    before = deepcopy(state)
    state, fires = domain.advance(state, datetime(2032, 1, 1, 23, 57))
    assert before['items'][0]['marks'] == {}
    assert [f['phase'] for f in fires] == ['lead']
    assert fires[0]['occurrence'] == '2032-01-02T00:02'
    store = repository.TodoStore(tmp_path, 3, [])
    store.save(state)
    state = repository.TodoStore(tmp_path, 3, []).state
    state, fires = domain.advance(state, datetime(2032, 1, 2, 0, 2))
    assert [f['phase'] for f in fires] == ['due']
    assert not domain.advance(state, datetime(2032, 1, 2, 0, 2))[1]
    assert not domain.advance(state, datetime(2032, 1, 1, 23, 57))[1]


@pytest.mark.parametrize('minutes,count', [(0, 1), (10, 1), (11, 0), (180, 0)])
def test_grace_window_and_archival(domain, minutes, count):
    state = domain.new_state([])
    state['items'].append(item(domain))
    state, fires = domain.advance(state, datetime(2032, 1, 2, 0, 2) + timedelta(minutes=minutes), lead_minutes=0)
    assert len(fires) == count
    assert all(f['phase'] == 'due' for f in fires)
    assert state['items'][0]['archived'] == (minutes > 10)


def test_rewinding_more_than_a_day_never_replays_daily_occurrences(domain):
    state = domain.new_state([])
    state['items'].append(item(domain, 'daily'))
    state, fires = domain.advance(state, datetime(2032, 1, 5, 0, 2), lead_minutes=0)
    assert len(fires) == 1
    for day in [3, 4, 5]:
        state, fires = domain.advance(state, datetime(2032, 1, day, 0, 2), lead_minutes=0)
        assert not fires
    assert len(domain.advance(state, datetime(2032, 1, 6, 0, 2), lead_minutes=0)[1]) == 1


def test_unchanged_tick_and_next_preview(domain):
    state = domain.new_state([])
    state['items'].append(item(domain, 'daily'))
    now = datetime(2032, 1, 1, 23, 56)
    state, _ = domain.advance(state, now)
    assert domain.advance(state, now)[0] == state
    preview = domain.next_reminder(state, now)
    assert preview['at'] == '2032-01-01T23:57'
    assert preview['phase'] == 'lead'
    state['items'][0]['enabled'] = False
    assert domain.next_reminder(state, now) is None
    assert domain.advance(state, now)[0] == state


def test_atomic_failure_preserves_disk_memory_and_migration_source(repository, domain, tmp_path, monkeypatch):
    import petcore.mods.json_store as atomic
    store = repository.TodoStore(tmp_path, 0, ['原始'])
    old = deepcopy(store.state)
    raw = store.path.read_bytes()
    changed = deepcopy(old)
    changed['items'].append(item(domain))
    def fail(*args):
        raise OSError('synthetic disk failure')
    with monkeypatch.context() as patch:
        patch.setattr(atomic.os, 'replace', fail)
        with pytest.raises(OSError):
            store.save(changed)
    assert store.state == old and store.path.read_bytes() == raw
    assert not list(tmp_path.glob('*.tmp'))
    store.path.write_text('{broken', encoding='utf8')
    with pytest.raises(ValueError):
        repository.TodoStore(tmp_path, 0, ['must not overwrite'])
    assert store.path.read_text('utf8') == '{broken'


def test_preferences_are_per_pet_and_safe_by_default(tmp_path):
    from petcore.config import Config, GLOBAL_CONFIG_KEYS
    config = Config(tmp_path)
    assert config.get('todo_reminder_enabled') is True
    assert config.get('todo_reminder_lead_minutes') == 5
    assert config.get('todo_reminder_speak') is False
    for value, expected in [(-1, 0), (61, 60), (30, 30)]:
        config.set('todo_reminder_lead_minutes', value)
        assert config.get('todo_reminder_lead_minutes') == expected
    assert not {'todo_reminder_enabled', 'todo_reminder_lead_minutes', 'todo_reminder_speak'} & GLOBAL_CONFIG_KEYS
