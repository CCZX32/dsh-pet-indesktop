"""Todo schedule, occurrence high-water marks and previews; no IO or Qt."""
from __future__ import annotations

from copy import deepcopy
from datetime import date as Date, datetime, time as Time, timedelta
from uuid import uuid4

GRACE = timedelta(minutes=10)


def new_item(title, *, kind="none", date="", time=""):
    return {"id": uuid4().hex, "title": str(title), "kind": kind,
            "date": date, "time": time, "enabled": True, "archived": False, "marks": {}}


def new_state(legacy):
    return {"schema_version": 2, "items": [new_item(text) for text in legacy if isinstance(text, str)]}


def validate(state):
    if not isinstance(state, dict) or state.get("schema_version") != 2 or not isinstance(state.get("items"), list):
        raise ValueError("unsupported todo document")
    ids = set()
    for entry in state["items"]:
        if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                or not entry["id"] or entry["id"] in ids or not isinstance(entry.get("title"), str)
                or entry.get("kind") not in {"none", "once", "daily"}
                or not isinstance(entry.get("enabled"), bool)
                or not isinstance(entry.get("archived"), bool)
                or not isinstance(entry.get("marks"), dict)):
            raise ValueError("invalid todo entry; original file preserved")
        ids.add(entry["id"])
        if entry["kind"] == "once":
            Date.fromisoformat(entry.get("date", ""))
        if entry["kind"] != "none":
            value = entry.get("time", "")
            if not isinstance(value, str) or Time.fromisoformat(value).strftime("%H:%M") != value:
                raise ValueError("todo time must be HH:MM")
        for phase, stamp in entry["marks"].items():
            if phase not in {"lead", "due"} or not isinstance(stamp, str):
                raise ValueError("invalid todo occurrence")
            if datetime.fromisoformat(stamp).strftime("%Y-%m-%dT%H:%M") != stamp:
                raise ValueError("invalid todo occurrence")
    return state


def _occurrences(entry, now):
    if not entry["enabled"] or entry["archived"] or entry["kind"] == "none":
        return ()
    clock = Time.fromisoformat(entry["time"])
    days = ([now.date() + timedelta(days=n) for n in (-1, 0, 1)]
            if entry["kind"] == "daily" else [Date.fromisoformat(entry["date"])])
    return tuple(datetime.combine(day, clock) for day in days)


def _phases(due, lead):
    return (("lead", due - timedelta(minutes=lead)), ("due", due)) if lead else (("due", due),)


def advance(state, now, *, lead_minutes=5, enabled=True):
    updated = deepcopy(state)
    fires = []
    if not enabled:
        return updated, fires
    lead = max(0, min(60, int(lead_minutes)))
    for entry in updated["items"]:
        for due in _occurrences(entry, now):
            occurrence = due.strftime("%Y-%m-%dT%H:%M")
            for phase, at in _phases(due, lead):
                if at > now or occurrence <= entry["marks"].get(phase, ""):
                    continue
                entry["marks"][phase] = occurrence
                if now <= at + GRACE:
                    fires.append({"id": entry["id"], "title": entry["title"], "phase": phase,
                                  "occurrence": occurrence, "at": at.strftime("%Y-%m-%dT%H:%M")})
            if entry["kind"] == "once" and now > due + GRACE:
                entry["archived"] = True
    return updated, fires


def next_reminder(state, now, *, lead_minutes=5):
    candidates = []
    for entry in state["items"]:
        for due in _occurrences(entry, now):
            occurrence = due.strftime("%Y-%m-%dT%H:%M")
            for phase, at in _phases(due, max(0, min(60, int(lead_minutes)))):
                if at >= now and occurrence > entry["marks"].get(phase, ""):
                    candidates.append({"id": entry["id"], "title": entry["title"], "phase": phase,
                                       "at": at.strftime("%Y-%m-%dT%H:%M"), "occurrence": occurrence})
    return min(candidates, key=lambda x: (x["at"], x["id"])) if candidates else None
