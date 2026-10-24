from __future__ import annotations
from datetime import datetime
import logging

from petcore.contracts.speech import SpeechRequest
from . import domain
from .festival import reminder_times, NO_FESTIVAL_TEXT
from .store import FestivalStore

OWNER = "fun.festival"
log = logging.getLogger(OWNER)


class FestivalRuntime:
    def __init__(self, context, *, now=datetime.now):
        self.context, self.ports, self.now = context, context.ports, now
        self.commands = {"today": self.today}
        self._active, self._generation, self._timer, self._yield_off = False, 0, None, None
        self.stores, self._epochs, self._tokens, self._seen = {}, {}, {}, {}

    def pets(self):
        return self.ports.pets.pets() if self.ports.pets else ()

    def pet(self, slot):
        return next((p for p in self.pets() if p.slot == slot), None)

    def store(self, slot):
        if slot not in self.stores:
            if not self.ports.storage:
                raise ValueError("local storage unavailable")
            self.stores[slot] = FestivalStore(self.ports.storage.data_dir(OWNER), slot)
        return self.stores[slot]

    def start(self):
        if self._active:
            return
        self._active = True
        self._generation += 1
        self._seen.clear()
        if self.ports.speech:
            self._yield_off = self.ports.speech.register_yield(OWNER, self.should_yield)
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
        if self._yield_off:
            self._yield_off()
            self._yield_off = None
        if self.ports.speech:
            self.ports.speech.cancel_owner(OWNER)
        if self.ports.reminders:
            self.ports.reminders.cancel_owner(OWNER)
        self._tokens.clear()

    close = stop

    def preferences_changed(self, slot):
        self._epochs[slot] = self._epochs.get(slot, 0) + 1
        for token in self._tokens.pop(slot, set()):
            if self.ports.speech:
                self.ports.speech.stop(token)
        self._seen.pop(slot, None)

    def on_pet_added(self, window):
        self.preferences_changed(window.slot)
        self.tick()

    def on_pet_removed(self, window):
        self.preferences_changed(window.slot)
        self.stores.pop(window.slot, None)

    def should_yield(self, moment):
        if not self._active:
            return False
        if isinstance(moment, str):
            try:
                moment = datetime.fromisoformat(moment[:16])
            except ValueError:
                return False
        if not isinstance(moment, datetime):
            return False
        for pet in self.pets():
            cfg = domain.config(pet.config)
            if cfg["enabled"] and cfg["speak"] and moment.strftime("%H:%M") in reminder_times(cfg) and domain.has_event(moment.date(), cfg):
                return True  # Deliberately independent of tick/fired order.
        return False

    def tick(self):
        if not self._active:
            return
        now = self.now()
        for pet in self.pets():
            cfg = domain.config(pet.config)
            startup = self._seen.get(pet.slot) != cfg
            if not cfg["enabled"]:
                self._seen[pet.slot] = cfg
                continue
            try:
                if not domain.has_event(now.date(), cfg):
                    self._seen[pet.slot] = cfg
                    continue
                store = self.store(pet.slot)
                day, clock = now.date().isoformat(), now.strftime("%H:%M")
                if day < store.state["day"]:
                    continue
                fired = list(store.state["fired"]) if day == store.state["day"] else []
                times = reminder_times(cfg)
                due = day + "T" + clock
                selected = None
                if startup and not fired and clock >= times[0]:
                    selected = day + "#startup"
                    fired.append(selected)
                    if clock in times:
                        fired.append(due)
                elif clock in times and due not in fired:
                    selected = due
                    fired.append(due)
                if selected:
                    store.save({"schema_version": 2, "day": day, "fired": fired})
                    self._deliver(pet, cfg, selected, domain.text(now.date(), cfg, max(0, len(fired) - 1)))
                self._seen[pet.slot] = cfg
            except (OSError, ValueError, TypeError):
                log.warning("节日状态读写失败：slot=%s；保留原文件，未交付", pet.slot, exc_info=True)

    def _deliver(self, pet, cfg, key, text, *, manual=False):
        if not self.ports.presentation or not self.ports.reminders:
            log.warning("节日提醒出口不可用：slot=%s", pet.slot)
            return
        generation, epoch = self._generation, self._epochs.get(pet.slot, 0)
        def guard():
            live = self.pet(pet.slot)
            return bool(self._active and generation == self._generation and epoch == self._epochs.get(pet.slot, 0)
                        and live and live.config is pet.config and live.config.get("festival_enabled" if manual else "festival_reminder_enabled", manual))
        status = self.ports.reminders.deliver(OWNER, pet.slot, key, self.ports.presentation.for_slot(pet.slot), "节日与生日提醒", text, guard=guard)
        if status in {"bubble", "notification"} and cfg["speak"] and self.ports.speech:
            tokens = self._tokens.setdefault(pet.slot, set())
            job = {"token": None, "done": False}
            def ended(_):
                job["done"] = True
                tokens.discard(job["token"])
            token = self.ports.speech.speak(SpeechRequest(text), owner=OWNER, slot=pet.slot, guard=guard, on_finished=ended, on_error=ended)
            job["token"] = token
            if not job["done"]:
                tokens.add(token)

    def today(self, slot=None):
        if not self._active:
            return
        if slot is None:
            active = self.ports.pets.active() if self.ports.pets else None
            slot = active.slot if active else None
        pet = self.pet(slot)
        if not pet or not pet.config.get("festival_enabled", True):
            return
        cfg = domain.config(pet.config)
        if not cfg["enabled"]:
            cfg["birthday"] = ""
        now = self.now()
        self._deliver(pet, cfg, "manual:" + now.isoformat(), domain.text(now.date(), cfg) or NO_FESTIVAL_TEXT, manual=True)
