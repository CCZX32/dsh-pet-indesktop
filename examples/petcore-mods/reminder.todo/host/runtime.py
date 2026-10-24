"""One process timer, slot-owned durable schedules and lifecycle-bound delivery."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import logging

from petcore.contracts.speech import SpeechRequest
from . import model
from .store import TodoStore

OWNER = "reminder.todo"
log = logging.getLogger(OWNER)


class TodoRuntime:
    def __init__(self, context, *, now=datetime.now):
        self.context, self.ports, self.now = context, context.ports, now
        self.commands = {"open": self.open_panel}
        self.panels, self.stores, self._epochs, self._tokens = {}, {}, {}, {}
        self._active, self._timer, self._generation = False, None, 0

    def pets(self):
        return self.ports.pets.pets() if self.ports.pets else ()

    def pet(self, slot):
        return next((p for p in self.pets() if p.slot == slot), None)

    def store(self, slot):
        pet = self.pet(slot)
        if pet is None or not self.ports.storage:
            raise ValueError("宠物已关闭或本地存储不可用")
        if slot not in self.stores:
            self.stores[slot] = TodoStore(self.ports.storage.data_dir(OWNER), slot, pet.config.get("todo_items", []))
        return self.stores[slot]

    def add(self, slot, **fields):
        if not str(fields.get("title", "")).strip():
            raise ValueError("请输入待办内容")
        entry = model.new_item(**fields)
        store = self.store(slot)
        state = deepcopy(store.state)
        state["items"].append(entry)
        store.save(state)
        self.refresh(slot)
        return entry["id"]

    def update(self, slot, identity, **fields):
        if set(fields) - {"title", "kind", "date", "time"}:
            raise ValueError("unsupported todo field")
        store = self.store(slot)
        state = deepcopy(store.state)
        entry = next((x for x in state["items"] if x["id"] == identity), None)
        if entry is None:
            raise ValueError("条目已删除，请重新打开")
        if "title" in fields and not str(fields["title"]).strip():
            raise ValueError("请输入待办内容")
        if any(key in fields and fields[key] != entry[key] for key in ("kind", "date", "time")):
            entry.update(marks={}, archived=False)
        entry.update(fields)
        store.save(state)
        self.refresh(slot)

    def delete(self, slot, identity):
        store = self.store(slot)
        state = deepcopy(store.state)
        state["items"] = [x for x in state["items"] if x["id"] != identity]
        store.save(state)
        self.refresh(slot)

    def toggle(self, slot, identity):
        store = self.store(slot)
        state = deepcopy(store.state)
        entry = next(x for x in state["items"] if x["id"] == identity)
        entry["enabled"] = not entry["enabled"]
        store.save(state)
        self.refresh(slot)

    def start(self):
        if self._active:
            return
        self._active = True
        self._generation += 1
        if self.ports.scheduler and self.ports.pets and self.ports.storage:
            generation = self._generation
            self._timer = self.ports.scheduler.call_every(15000, lambda: self.tick() if self._active and generation == self._generation else None)
            self.tick()

    def stop(self):
        self._active = False
        self._generation += 1
        if self._timer:
            self.ports.scheduler.cancel(self._timer)
            self._timer = None
        if self.ports.speech:
            self.ports.speech.cancel_owner(OWNER)
        if self.ports.reminders:
            self.ports.reminders.cancel_owner(OWNER)
        self._tokens.clear()
        for panel in tuple(self.panels.values()):
            panel.close()
        self.panels.clear()

    close = stop

    def on_pet_added(self, window):
        self._epochs[window.slot] = self._epochs.get(window.slot, 0) + 1
        self.tick()

    def on_pet_removed(self, window):
        self.preferences_changed(window.slot)
        panel = self.panels.get(window.slot)
        if panel:
            panel.close()
        self.stores.pop(window.slot, None)

    def preferences_changed(self, slot):
        self._epochs[slot] = self._epochs.get(slot, 0) + 1
        for token in self._tokens.pop(slot, set()):
            if self.ports.speech:
                self.ports.speech.stop(token)
        self.refresh(slot)

    def tick(self):
        if not self._active:
            return
        for pet in self.pets():
            if not pet.config.get("todo_reminder_enabled", True):
                continue
            try:
                store = self.store(pet.slot)
                state, fires = model.advance(store.state, self.now(), lead_minutes=pet.config.get("todo_reminder_lead_minutes", 5))
                if state != store.state:
                    store.save(state)  # Persist before delivery; never announce a failed write.
                if fires:
                    self._deliver(pet, fires)
                self.refresh(pet.slot)
            except (OSError, ValueError, TypeError):
                log.warning("待办状态不可读写：slot=%s；未交付提醒，保留原文件", pet.slot, exc_info=True)

    def _deliver(self, pet, fires):
        if not self.ports.presentation or not self.ports.reminders:
            log.warning("待办提醒出口不可用：slot=%s", pet.slot)
            return
        # A late poll can see both phases: the due message supersedes its lead.
        selected = {fire["id"]: fire for fire in fires}
        text = "；".join(("到期提醒：" if f["phase"] == "due" else "提前提醒：") + f["title"] for f in selected.values())
        generation, epoch = self._generation, self._epochs.get(pet.slot, 0)
        signatures = {x["id"]: (x["kind"], x["date"], x["time"]) for x in self.store(pet.slot).state["items"] if x["id"] in selected}
        def guard():
            live = self.pet(pet.slot)
            if not (self._active and generation == self._generation and epoch == self._epochs.get(pet.slot, 0)
                    and live and live.config is pet.config and live.config.get("todo_reminder_enabled", True)):
                return False
            return all(any(x["id"] == identity and x["enabled"] and (x["kind"], x["date"], x["time"]) == signature
                           for x in self.store(pet.slot).state["items"]) for identity, signature in signatures.items())
        key = "|".join(f'{f["id"]}:{f["occurrence"]}:{f["phase"]}' for f in selected.values())
        status = self.ports.reminders.deliver(OWNER, pet.slot, key, self.ports.presentation.for_slot(pet.slot), "待办提醒", text,
                                             guard=guard, on_click=lambda: self.open_panel(pet.slot))
        if status in {"bubble", "notification"} and pet.config.get("todo_reminder_speak", False) and self.ports.speech:
            tokens = self._tokens.setdefault(pet.slot, set())
            job = {"token": None, "done": False}
            def ended(_):
                job["done"] = True
                tokens.discard(job["token"])
            token = self.ports.speech.speak(SpeechRequest(text), owner=OWNER, slot=pet.slot, guard=guard,
                                          on_finished=ended, on_error=ended)
            job["token"] = token
            if not job["done"]:
                tokens.add(token)

    def refresh(self, slot):
        panel = self.panels.get(slot)
        if panel:
            panel.refresh()

    def open_panel(self, slot=None):
        if not self._active:
            return
        if slot is None:
            active = self.ports.pets.active() if self.ports.pets else None
            slot = active.slot if active else None
        if self.pet(slot) is None:
            return
        if slot in self.panels:
            self.panels[slot].show()
            self.panels[slot].raise_()
            self.panels[slot].activateWindow()
            return
        from .panel import TodoPanel
        panel = TodoPanel(self, slot)
        self.panels[slot] = panel
        panel.finished.connect(lambda _: self.panels.pop(slot, None) if self.panels.get(slot) is panel else None)
        panel.show()
