"""One process-wide sign state; legacy data remains untouched for rollback."""
from __future__ import annotations
from copy import deepcopy
from datetime import date
from pathlib import Path

from petcore.mods.json_store import read_json, write_json
from .divination import draw_for_day


def _date(value):
    if not isinstance(value, str):
        raise ValueError('invalid divination date')
    if value and date.fromisoformat(value).isoformat() != value:
        raise ValueError('noncanonical divination date')
    return value


def validate(raw):
    if not isinstance(raw, dict) or raw.get('schema_version') != 2:
        raise ValueError('unsupported divination state')
    _date(raw.get('date'))
    _date(raw.get('hint_date'))
    drawn, quote_id, legacy = raw.get('drawn'), raw.get('quote_id'), raw.get('legacy_quote')
    if (not isinstance(drawn, list) or len(drawn) > 48
            or any(type(i) is not int or not 1 <= i <= 48 for i in drawn)
            or len(set(drawn)) != len(drawn) or not isinstance(legacy, str)):
        raise ValueError('invalid divination pool')
    if quote_id is not None and (type(quote_id) is not int or quote_id not in drawn):
        raise ValueError('invalid locked sign')
    if bool(raw['date']) != (quote_id is not None or bool(legacy)) or (quote_id is not None and legacy):
        raise ValueError('inconsistent locked sign')
    return deepcopy(raw)


def _legacy(raw):
    if not isinstance(raw, dict) or not _date(raw.get('date')) or not isinstance(raw.get('quote'), str) or not raw['quote']:
        raise ValueError('invalid legacy divination state')
    return raw


class DivinationStore:
    def __init__(self, root):
        root = Path(root)
        self.path = root / 'daily-v2.json'
        if self.path.exists():
            self.state = validate(read_json(self.path))
            return
        self.state = dict(schema_version=2, date='', quote_id=None, legacy_quote='', drawn=[], hint_date='')
        old, backup = root / 'daily.json', root / 'daily-legacy-v1.json'
        if old.exists() or backup.exists():
            raw = _legacy(read_json(backup if backup.exists() else old))
            if not backup.exists():
                write_json(backup, raw)
            state = dict(self.state, date=raw['date'], legacy_quote=raw['quote'])
            self.save(state)

    def save(self, state):
        state = validate(state)
        if state != self.state:
            write_json(self.path, state)
            self.state = state

    def peek(self, day: date):
        if self.state['date'] and day.isoformat() <= self.state['date']:
            return deepcopy(self.state)
        drawn = self.state['drawn'] if len(self.state['drawn']) < 48 else []
        quote = draw_for_day(day, drawn)
        return dict(self.state, date=day.isoformat(), quote_id=quote.id, legacy_quote='', drawn=[*drawn, quote.id])

    def resolve(self, day: date):
        self.save(self.peek(day))
        return deepcopy(self.state)

    def mark_hint(self, day: date):
        if day.isoformat() > self.state['hint_date']:
            self.save(dict(self.state, hint_date=day.isoformat()))
