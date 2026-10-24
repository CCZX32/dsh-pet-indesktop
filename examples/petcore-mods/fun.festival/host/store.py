from copy import deepcopy
from datetime import date, datetime
from petcore.mods.json_store import read_json, write_json


def validate(value):
    if not isinstance(value, dict) or value.get("schema_version") != 2 or not isinstance(value.get("day"), str) or not isinstance(value.get("fired"), list):
        raise ValueError("invalid festival state; original preserved")
    day = value["day"]
    if day and date.fromisoformat(day).isoformat() != day:
        raise ValueError("invalid festival date")
    for stamp in value["fired"]:
        if not isinstance(stamp, str) or not day or not stamp.startswith(day):
            raise ValueError("invalid festival occurrence")
        if stamp != day + "#startup" and datetime.fromisoformat(stamp).strftime("%Y-%m-%dT%H:%M") != stamp:
            raise ValueError("invalid festival occurrence")
    if len(set(value["fired"])) != len(value["fired"]) or len(value["fired"]) > 1441:
        raise ValueError("invalid festival occurrences")
    return value


class FestivalStore:
    def __init__(self, root, slot):
        if not 0 <= int(slot) <= 128:
            raise ValueError("invalid pet slot")
        self.path = root / f"festival-slot-{int(slot)}-v2.json"
        self.state = validate(read_json(self.path)) if self.path.exists() else {"schema_version": 2, "day": "", "fired": []}

    def save(self, value):
        validate(value)
        if value != self.state:
            write_json(self.path, value)
            self.state = deepcopy(value)
