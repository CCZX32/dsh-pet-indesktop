from copy import deepcopy
from datetime import date, timedelta
import importlib
import json
from pathlib import Path

import pytest

from petcore.config import Config
from petcore.mods.feature import import_entrypoint


def modules():
    factory = import_entrypoint(Path('examples/petcore-mods/fun.divination'), 'host/__init__.py:create_host', 'fun.divination')
    package = factory.__module__.rsplit('.', 1)[0]
    return (importlib.import_module(package + '.divination'), importlib.import_module(package + '.store'))


def test_48_pool_weights_stability_and_complete_text():
    d, _ = modules()
    assert [q.id for q in d.QUOTES] == list(range(1, 49))
    assert d.TIER_WEIGHTS == {'上上': 4, '上': 18, '中平': 56, '下': 22}
    assert [sum(q.tier == tier for q in d.QUOTES) for tier in d.TIERS] == [4, 10, 24, 10]
    seen = []
    for n in range(48):
        day = date(2031, 12, 20) + timedelta(days=n)
        quote = d.draw_for_day(day, seen)
        assert quote == d.draw_for_day(day, tuple(seen))
        assert quote.id not in seen
        assert len(quote.verses) == 4 and len(d.card_lines(quote)) == 6
        assert quote.reading in d.speech_text(quote) and d.WAITING_TEXT not in d.speech_text(quote)
        seen.append(quote.id)
    assert sorted(seen) == list(range(1, 49))


def test_store_restart_rollover_rollback_and_no_unchanged_write(tmp_path, monkeypatch):
    d, s = modules()
    day = date(2031, 12, 20)
    ids = []
    for n in range(49):
        store = s.DivinationStore(tmp_path)
        result = store.resolve(day + timedelta(days=n))
        if n < 48:
            assert result['quote_id'] not in ids
            ids.append(result['quote_id'])
        else:
            assert store.state['drawn'] == [result['quote_id']]
    previous = deepcopy(store.state)
    def fail(*args):
        raise AssertionError('same day/rollback must not write')
    monkeypatch.setattr(s, 'write_json', fail)
    assert store.resolve(day + timedelta(days=48)) == previous
    assert store.resolve(day) == previous
    assert store.peek(day + timedelta(days=49))['quote_id'] == d.draw_for_day(day + timedelta(days=49), previous['drawn']).id


def test_legacy_today_preserved_next_day_new_pool_and_backup(tmp_path):
    _, s = modules()
    original = {'date': '2032-01-02', 'quote': '原签保留，不能升级当天变签。'}
    old = tmp_path / 'daily.json'
    old.write_text(json.dumps(original, ensure_ascii=False), encoding='utf-8')
    raw = old.read_bytes()
    store = s.DivinationStore(tmp_path)
    today = store.resolve(date(2032, 1, 2))
    assert today['legacy_quote'] == original['quote'] and today['quote_id'] is None
    assert old.read_bytes() == raw
    assert json.loads((tmp_path / 'daily-legacy-v1.json').read_text(encoding='utf-8')) == original
    assert store.resolve(date(2032, 1, 3))['quote_id'] in range(1, 49)
    assert old.read_bytes() == raw


@pytest.mark.parametrize('raw', [{'date': 'bad', 'quote': '旧签'}, {'date': '2032-01-02', 'quote': []}])
def test_bad_legacy_fail_closed(tmp_path, raw):
    _, s = modules()
    path = tmp_path / 'daily.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError):
        s.DivinationStore(tmp_path)
    assert json.loads(path.read_text()) == raw
    assert not (tmp_path / 'daily-v2.json').exists()


def test_failed_write_preserves_both_memory_and_original(tmp_path, monkeypatch):
    _, s = modules()
    store = s.DivinationStore(tmp_path)
    store.resolve(date(2032, 1, 2))
    old, raw = deepcopy(store.state), store.path.read_bytes()
    def fail(*args):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(s, 'write_json', fail)
    with pytest.raises(OSError):
        store.resolve(date(2032, 1, 3))
    assert store.state == old and store.path.read_bytes() == raw


def test_per_pet_preferences_keep_existing_default(tmp_path):
    config = Config(tmp_path)
    assert config.get('divination_enabled') is True
    assert config.get('divination_speak') is False
    assert config.get('divination_hint') is True


def test_draw_deterministic_across_process_hash_seeds():
    import os
    import subprocess
    import sys

    script = """
from datetime import date
from tests.test_petcore_divination import modules
d, _ = modules()
print(d.draw_for_day(date(2032, 2, 29), [1, 4, 9]).id)
"""
    results = []
    for seed in ('1', '42137'):
        result = subprocess.run(
            [sys.executable, '-c', script], capture_output=True, text=True,
            env={**os.environ, 'PYTHONHASHSEED': seed}, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        results.append(result.stdout.strip())
    assert results[0] == results[1] and int(results[0]) in range(1, 49)


def test_reminder_preferences_roundtrip_and_missing_key_defaults(tmp_path):
    defaults = Config(tmp_path).data
    values = {'todo_reminder_lead_minutes': 17, 'todo_reminder_speak': True,
              'festival_reminder_enabled': True, 'festival_birthday': '02-29',
              'festival_reminder_times': '08:15, 19:00', 'divination_speak': True,
              'divination_hint': False}
    cfg = Config(tmp_path)
    for key, value in values.items():
        cfg.set(key, value)
    expected = {key: cfg.get(key) for key in values}
    cfg.save()
    loaded = Config.load(tmp_path)
    assert {key: loaded.get(key) for key in values} == expected
    for key in values:
        loaded.data.pop(key)
    loaded.save()
    restored = Config.load(tmp_path)
    assert {key: restored.get(key) for key in values} == {key: defaults[key] for key in values}
