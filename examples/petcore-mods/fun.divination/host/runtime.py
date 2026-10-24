"""Lifecycle-bound daily draw. Timers and presentation stay on the host thread."""
from __future__ import annotations
from datetime import datetime
import logging
import threading

from petcore.contracts.speech import SpeechRequest
from petcore.mods.workers import try_start_worker
from . import divination as engine
from .store import DivinationStore

OWNER = 'fun.divination'
READING_GAP_MS = 2800
WAITING_MAX_WAIT_MS = 6000
log = logging.getLogger(OWNER)


def texts(state):
    quote = engine.quote_by_id(state['quote_id']) if state['quote_id'] else None
    if quote:
        return '\n'.join(engine.bubble_lines(quote)), engine.card_lines(quote), engine.speech_text(quote)
    text = state['legacy_quote']
    return text, [text], text


class DivinationRuntime:
    def __init__(self, context, *, now=datetime.now):
        self.context, self.ports, self.now = context, context.ports, now
        self.commands = {'draw': self.draw}
        self._active, self._generation, self._store, self._job = False, 0, None, None
        self.cards, self._epochs, self._tokens = {}, {}, {}
        self._click_off, self._warm_timer, self._quiet_off = None, None, None
        self._prewarm_thread, self._warm_key, self._warm_slot = None, None, None
        self._warm_cancel = threading.Event()

    def pets(self):
        return self.ports.pets.pets() if self.ports.pets else ()

    def pet(self, slot):
        return next((p for p in self.pets() if p.slot == slot), None)

    def quiet(self):
        return bool(self.ports.quiet and self.ports.quiet.quiet_active())

    def store(self):
        if self._store is None:
            if not self.ports.storage:
                raise ValueError('storage unavailable')
            self._store = DivinationStore(self.ports.storage.data_dir(OWNER))
        return self._store

    def guard(self, pet):
        generation, epoch = self._generation, self._epochs.get(pet.slot, 0)
        def valid():
            live = self.pet(pet.slot)
            return (self._active and self._generation == generation
                    and self._epochs.get(pet.slot, 0) == epoch and live is not None
                    and live.config is pet.config and engine.normalize_divination_config(live.config)['enabled'])
        return valid

    def target(self, slot):
        return self.ports.presentation.for_slot(slot) if self.ports.presentation else None

    def _speak(self, slot, text, guard, *, finished=None, failed=None):
        speech = self.ports.speech
        if speech is None or self.quiet() or not guard():
            if failed:
                failed(None)
            return ''
        pending = {'token': '', 'done': False}
        def completed(result, callback):
            pending['done'] = True
            self._tokens.get(slot, set()).discard(pending['token'])
            if guard() and callback:
                callback(result)
        try:
            token = speech.speak(SpeechRequest(text=text), owner=OWNER, slot=slot,
                                 guard=lambda: guard() and not self.quiet(),
                                 on_finished=lambda result: completed(result, finished),
                                 on_error=lambda error: completed(error, failed))
        except Exception as error:  # a failing provider must not strand the text flow
            completed(error, failed)
            return ''
        pending['token'] = token
        if token and not pending['done']:
            self._tokens.setdefault(slot, set()).add(token)
        return token

    def _later(self, job, delay, callback):
        scheduler = self.ports.scheduler
        if not scheduler:
            callback()
            return None
        handle = None
        def invoke():
            job['timers'].discard(handle)
            if self._job is job:
                if job['guard']():
                    callback()
                else:
                    self._cancel_job()
        handle = scheduler.call_later(delay, invoke)
        job['timers'].add(handle)
        return handle

    def _cancel_job(self):
        job, self._job = self._job, None
        if job:
            for handle in job['timers']:
                self.ports.scheduler.cancel(handle)
            if job['waiting_token'] and self.ports.speech:
                self.ports.speech.stop(job['waiting_token'])
                self._tokens.get(job['slot'], set()).discard(job['waiting_token'])

    def draw(self, slot=None):
        if not self._active or self._job is not None:
            return
        active = self.ports.pets.active() if slot is None and self.ports.pets else self.pet(slot)
        if active is None or not engine.normalize_divination_config(active.config)['enabled']:
            return
        slot = active.slot
        try:
            state = self.store().resolve(self.now().date())
        except (OSError, ValueError, TypeError) as error:
            log.warning('draw persistence failed: %s', type(error).__name__)
            target = self.target(slot)
            if target and not self.quiet():
                target.say('抽签未保存，请检查扩展数据目录后重试。', duration_ms=6000)
            return
        self._cancel_tokens(slot)
        guard = self.guard(active)
        job = dict(slot=slot, state=state, guard=guard, timers=set(), waiting=True, waiting_token='', deadline=None)
        self._job = job
        target = self.target(slot)
        if target and not self.quiet():
            target.say(engine.WAITING_TEXT, duration_ms=WAITING_MAX_WAIT_MS + READING_GAP_MS)
        if engine.normalize_divination_config(active.config)['speak'] and not self.quiet() and self.ports.speech:
            job['deadline'] = self._later(job, WAITING_MAX_WAIT_MS, lambda: self._waiting_done(job, timeout=True))
            job['waiting_token'] = self._speak(slot, engine.WAITING_TEXT, guard,
                finished=lambda _: self._waiting_done(job), failed=lambda _: self._waiting_done(job))
        else:
            self._waiting_done(job)

    def _waiting_done(self, job, *, timeout=False):
        if self._job is not job or not job['waiting'] or not job['guard']():
            return
        job['waiting'] = False
        if job['deadline']:
            self.ports.scheduler.cancel(job['deadline'])
            job['timers'].discard(job['deadline'])
        if timeout and job['waiting_token']:
            self.ports.speech.stop(job['waiting_token'])
            self._tokens.get(job['slot'], set()).discard(job['waiting_token'])
        self._later(job, READING_GAP_MS, lambda: self._reveal(job))

    def _reveal(self, job):
        if self._job is not job or not job['guard']():
            return
        self._job = None
        slot, state, guard = job['slot'], job['state'], job['guard']
        target = self.target(slot)
        bubble, _card, voice = texts(state)
        if not target or not self.ports.reminders:
            return
        status = self.ports.reminders.deliver(OWNER, slot, state['date'], target, '每日一签', bubble,
            guard=guard, on_click=lambda: self.show_card(slot, state) if guard() else None)
        if status == 'bubble':
            self.show_card(slot, state)
        pet = self.pet(slot)
        if status in ('bubble', 'notification') and pet and engine.normalize_divination_config(pet.config)['speak']:
            self._speak(slot, voice, guard)

    def show_card(self, slot, state):
        if not self._active or self.quiet() or not self.pet(slot):
            return
        if not engine.normalize_divination_config(self.pet(slot).config)['enabled']:
            return
        if slot in self.cards:
            card = self.cards[slot]
            card.set_state(state)
        else:
            from .panel import DivinationCard
            card = DivinationCard(state, slot)
            self.cards[slot] = card
            card.finished.connect(lambda _: self.cards.pop(slot, None) if self.cards.get(slot) is card else None)
        card.show()
        card.raise_()
        card.activateWindow()

    def on_interaction(self, window):
        pet = self.pet(getattr(window, 'slot', None))
        if not self._active or not pet or self.quiet() or self._job:
            return
        cfg = engine.normalize_divination_config(pet.config)
        if not cfg['enabled'] or not cfg['hint']:
            return
        try:
            store, day = self.store(), self.now().date()
            if day.isoformat() <= max(store.state['date'], store.state['hint_date']):
                return
            target = self.target(pet.slot)
            if target and target.say('今天还没抽签，右键「抽支签」看看今日一签。', duration_ms=5000):
                store.mark_hint(day)
        except (OSError, ValueError, TypeError) as error:
            log.warning('draw hint persistence failed: %s', type(error).__name__)

    def prewarm(self):
        if not self._active or self.quiet() or not self.ports.speech:
            return
        if self._prewarm_thread and self._prewarm_thread.is_alive():
            return
        pet = next((p for p in self.pets() if all(engine.normalize_divination_config(p.config)[k] for k in ('enabled', 'speak'))), None)
        if pet is None:
            return
        try:
            state = self.store().peek(self.now().date())
        except (OSError, ValueError, TypeError) as error:
            log.warning('draw prewarm state failed: %s', type(error).__name__)
            return
        key = (state['date'], state['quote_id'], state['legacy_quote'])
        if key == self._warm_key:
            return
        # All business/config reads above are on the host thread. The worker only
        # receives immutable requests and its own never-reused cancellation event.
        requests = (SpeechRequest(engine.WAITING_TEXT), SpeechRequest(texts(state)[2]))
        speech, cancel = self.ports.speech, threading.Event()
        def work():
            for request in requests:
                if cancel.is_set():
                    return
                try:
                    speech.synthesize(request)
                except Exception as error:
                    log.debug('draw prewarm unavailable: %s', type(error).__name__)
                    return
        worker = try_start_worker(OWNER, work, name='divination-prewarm')
        if worker is not None:
            self._warm_cancel, self._warm_key, self._warm_slot = cancel, key, pet.slot
            self._prewarm_thread = worker

    def _warm_schedule(self):
        wanted = self._active and any(all(engine.normalize_divination_config(p.config)[k] for k in ('enabled', 'speak')) for p in self.pets())
        if self._warm_timer and not wanted:
            self.ports.scheduler.cancel(self._warm_timer)
            self._warm_timer = None
        if wanted and not self._warm_timer and self.ports.scheduler:
            generation = self._generation
            self._warm_timer = self.ports.scheduler.call_every(600_000, lambda: self.prewarm() if self._generation == generation else None)
        self.prewarm()

    def _cancel_tokens(self, slot):
        for token in self._tokens.pop(slot, set()):
            if self.ports.speech:
                self.ports.speech.stop(token)

    def preferences_changed(self, slot):
        self._epochs[slot] = self._epochs.get(slot, 0) + 1
        if self._job and self._job['slot'] == slot:
            self._cancel_job()
        self._cancel_tokens(slot)
        if self._warm_slot == slot:
            self._warm_cancel.set()
            self._warm_key = None
        if slot in self.cards and (not self.pet(slot) or not engine.normalize_divination_config(self.pet(slot).config)['enabled']):
            self.cards[slot].close()
        self._warm_schedule()

    def on_pet_added(self, pet):
        self.preferences_changed(pet.slot)

    def on_pet_removed(self, pet):
        self.preferences_changed(pet.slot)
        if pet.slot in self.cards:
            self.cards[pet.slot].close()

    def _quiet_changed(self, active):
        if active:
            self._warm_cancel.set()
            self._warm_key = None
        # Leaving quiet mode only flushes text. Do not start deferred TTS here.

    def start(self):
        if self._active:
            return
        self._active = True
        self._generation += 1
        if self.ports.quiet:
            self._quiet_off = self.ports.quiet.subscribe(self._quiet_changed)
        if self.ports.interaction:
            self._click_off = self.ports.interaction.on_click(OWNER, self.on_interaction)
        self._warm_schedule()

    def stop(self):
        self._active = False
        self._generation += 1
        self._cancel_job()
        if self._quiet_off:
            self._quiet_off()
            self._quiet_off = None
        if self._click_off:
            self._click_off()
            self._click_off = None
        if self._warm_timer:
            self.ports.scheduler.cancel(self._warm_timer)
            self._warm_timer = None
        self._warm_cancel.set()
        self._warm_key = None
        for slot in tuple(self._tokens):
            self._cancel_tokens(slot)
        if self.ports.speech:
            self.ports.speech.cancel_owner(OWNER)
        if self.ports.reminders:
            self.ports.reminders.cancel_owner(OWNER)
        for card in tuple(self.cards.values()):
            card.close()
        self.cards.clear()

    close = stop
