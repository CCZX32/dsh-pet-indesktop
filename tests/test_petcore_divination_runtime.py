from datetime import datetime
import importlib
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from petcore.mods.feature import import_entrypoint
from tests.petcore_reminder_support import Harness
from tests.test_petcore_reminder_ports import wait_for


def module(name='runtime', owner='fun.divination'):
    factory = import_entrypoint(Path('examples/petcore-mods') / owner, 'host/__init__.py:create_host', owner)
    return importlib.import_module(factory.__module__.rsplit('.', 1)[0] + '.' + name)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    m = module()
    assert m.READING_GAP_MS == 2800 and m.WAITING_MAX_WAIT_MS == 6000
    monkeypatch.setattr(m, 'READING_GAP_MS', 20)
    monkeypatch.setattr(m, 'WAITING_MAX_WAIT_MS', 10000)
    h = Harness(tmp_path)
    now = [datetime(2032, 1, 2, 9)]
    r = m.DivinationRuntime(h.context, now=lambda: now[0])
    r.start()
    yield h, r, now, m
    r.stop()
    if r._prewarm_thread:
        r._prewarm_thread.join(10)
        assert not r._prewarm_thread.is_alive()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    h.close()


def test_shared_today_target_binding_duplicate_click_and_cards(setup):
    h, r, _, _ = setup
    r.draw(1)
    state = r.store().state.copy()
    r.draw(0)
    assert h.presentation.messages == [(1, '抽签中...')]
    wait_for(lambda: r._job is None)
    assert list(r.cards) == [1]
    assert r.store().state == state and not h.speech.calls and not h.speech.precached
    first = h.presentation.messages[-1][1]
    r.draw(0)
    wait_for(lambda: r._job is None)
    assert h.presentation.messages[-1] == (0, first)
    assert r.store().state == state
    for _ in range(30):
        r.show_card(0, state)
        r.cards[0].close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert 0 not in r.cards


def test_real_finish_not_synthesis_reveals_and_failure_completes(setup):
    h, r, _, _ = setup
    h.handles[0].config.set('divination_speak', True)
    r.draw(0)
    call = h.speech.calls[-1]
    assert call[2]['owner'] == 'fun.divination' and call[2]['slot'] == 0
    done = call[2].get('on_done')
    if done:
        done(None)
    h.app.processEvents()
    assert r._job is not None and not r.cards
    call[2]['on_finished'](None)
    call[2]['on_finished'](None)
    wait_for(lambda: r._job is None)
    assert len(h.speech.calls) == 2 and r.cards
    r.draw(0)
    h.speech.calls[-1][2]['on_error'](RuntimeError('synthetic'))
    wait_for(lambda: r._job is None)
    assert len(h.presentation.messages) == 4


def test_timeout_cancels_and_late_finish_cannot_double_reveal(setup, monkeypatch):
    h, r, _, m = setup
    monkeypatch.setattr(m, 'WAITING_MAX_WAIT_MS', 20)
    h.handles[0].config.set('divination_speak', True)
    r.draw(0)
    call = h.speech.calls[-1]
    wait_for(lambda: r._job is None)
    assert call[0] in h.speech.canceled
    count = len(h.presentation.messages)
    call[2]['on_finished'](None)
    h.app.processEvents()
    assert len(h.presentation.messages) == count


def test_hidden_quiet_and_closed_pet_do_not_late_show_or_speak(setup):
    h, r, _, _ = setup
    h.quiet.set_quiet(60)
    h.handles[0].config.set('divination_speak', True)
    r.draw(0)
    wait_for(lambda: r._job is None)
    assert not h.presentation.messages and not h.speech.calls and not r.cards
    h.quiet.set_quiet(0)
    assert len(h.presentation.messages) == 1 and not h.speech.calls
    h.presentation.hidden.add(1)
    r.draw(1)
    wait_for(lambda: r._job is None)
    assert h.presentation.notifications[-1][0] == 1 and not r.cards
    click = h.presentation.notifications[-1][3]
    closed = h.handles.pop()
    r.on_pet_removed(closed)
    click()
    assert not r.cards
    r.draw(0)
    call = h.speech.calls[-1]
    r.stop()
    call[2]['on_finished'](None)
    h.app.processEvents()
    assert r._job is None and not r.cards and not h.clicks
    assert call[0] in h.speech.canceled


def test_hint_only_once_when_shown_and_save_cancel_preserves_draw(setup):
    h, r, _, _ = setup
    callback = h.clicks['fun.divination']
    h.presentation.hidden.add(1)
    callback(SimpleNamespace(slot=1))
    assert not r.store().state['hint_date']
    callback(SimpleNamespace(slot=0))
    assert r.store().state['hint_date'] == '2032-01-02'
    count = len(h.presentation.messages)
    callback(SimpleNamespace(slot=0))
    assert len(h.presentation.messages) == count
    page = module('settings_page').DivinationPage(SimpleNamespace(config=h.handles[0].config, window=SimpleNamespace(slot=0)), runtime=r)
    page.enabled.setChecked(False)
    assert h.handles[0].config.get('divination_enabled') is False
    page.discard_changes()
    r.draw(0)
    wait_for(lambda: r._job is None)
    state = r.store().state.copy()
    page.hint.setChecked(False)
    page.discard_changes()
    assert r.store().state == state and h.handles[1].config.get('divination_speak') is False
    page.deleteLater()


def test_prewarm_bounded_cancel_blocked_worker_not_replaced(setup):
    h, r, _, _ = setup
    entered, release = threading.Event(), threading.Event()
    calls = []
    def synthesize(request):
        calls.append(request)
        entered.set()
        assert release.wait(10)
        return None
    h.speech.synthesize = synthesize
    r.prewarm()
    assert not calls
    h.handles[0].config.set('divination_speak', True)
    try:
        r.preferences_changed(0)
        assert entered.wait(10)
        old = r._prewarm_thread
        r.stop(); r.start(); r.prewarm()
        assert r._prewarm_thread is old and len(calls) == 1
    finally:
        release.set()
        if r._prewarm_thread:
            r._prewarm_thread.join(10)
    assert len(calls) == 1
    r.prewarm()
    if r._prewarm_thread:
        r._prewarm_thread.join(10)
    assert len(calls) <= 3
    r.prewarm()
    assert len(calls) <= 3


def test_failed_persistence_no_waiting_voice_or_card(setup, monkeypatch):
    h, r, _, _ = setup
    store = r.store()
    def fail(*args):
        raise OSError('synthetic full disk')
    monkeypatch.setattr(store, 'save', fail)
    r.draw(0)
    assert not h.speech.calls and not r.cards and r._job is None
    assert not any(text == '抽签中...' for _, text in h.presentation.messages)

@pytest.mark.parametrize('festival_first', [False, True])
def test_chime_yields_to_festival_in_both_timer_orders(tmp_path, festival_first):
    from tests.test_petcore_chime_mod import _context, ENABLED_HOURLY
    from tests.test_petcore_festival import birthday
    h = Harness(tmp_path)
    festival = module(owner='fun.festival').FestivalRuntime(h.context, now=lambda: datetime(2032, 2, 29, 9))
    birthday(h.handles[0].config)
    h.handles[0].config.set('festival_reminder_speak', True)
    festival.start()
    h.speech.calls.clear()
    chime, _, _ = _context(ENABLED_HOURLY, speech=h.speech)
    try:
        if festival_first:
            festival.tick()
        chime.tick(datetime(2032, 2, 29, 9))
        if not festival_first:
            festival.tick()
        assert not any(kw.get('owner') == 'voice.chime' or not kw.get('owner') for _, _, kw in h.speech.calls)
        festival.stop()
        chime.tick(datetime(2032, 2, 29, 10))
        assert h.speech.calls[-1][2]['owner'] == 'voice.chime'
        call = h.speech.calls[-1]
        chime.stop()
        assert call[0] in h.speech.canceled
    finally:
        chime.stop(); festival.stop(); h.close()


def test_chime_stopped_generation_suppresses_late_error(tmp_path):
    from tests.test_petcore_chime_mod import _context, ENABLED_HOURLY
    h = Harness(tmp_path)
    chime, presentation, _ = _context(ENABLED_HOURLY, speech=h.speech)
    try:
        chime.tick(datetime(2032, 1, 2, 9))
        callback = h.speech.calls[-1][2]['on_error']
        chime.stop(); chime.start()
        before = len(presentation.said)
        callback(RuntimeError('late'))
        assert len(presentation.said) == before
    finally:
        chime.stop(); h.close()


def test_invalidated_wait_releases_job_even_without_settings_callback(setup):
    h, r, _, _ = setup
    r.draw(0)
    h.handles[0].config.set('divination_enabled', False)
    wait_for(lambda: r._job is None)
    assert not r.cards
    h.handles[0].config.set('divination_enabled', True)
    r.draw(0)
    wait_for(lambda: r._job is None)
    assert r.cards


def test_quiet_cancels_remaining_prewarm_requests(setup):
    h, r, _, _ = setup
    entered, release = threading.Event(), threading.Event()
    calls = []
    def synthesize(request):
        calls.append(request)
        entered.set()
        assert release.wait(10)
    h.speech.synthesize = synthesize
    h.handles[0].config.set('divination_speak', True)
    try:
        r.preferences_changed(0)
        assert entered.wait(10)
        h.quiet.set_quiet(60)
    finally:
        release.set()
        if r._prewarm_thread:
            r._prewarm_thread.join(10)
    assert len(calls) == 1


def test_blocked_prewarm_is_not_replaced_across_feature_reload(tmp_path):
    from petcore.mods.feature import FeatureManager

    h = Harness(tmp_path)
    h.handles[0].config.set('divination_speak', True)
    entered, release = threading.Event(), threading.Event()
    calls, workers = [], []
    def synthesize(request):
        calls.append(request)
        entered.set()
        assert release.wait(15)
        return None
    h.speech.synthesize = synthesize
    manager = FeatureManager(h.ports)
    args = dict(pack=Path('examples/petcore-mods/fun.divination'),
                owner='fun.divination', entrypoint='host/__init__.py:create_host')
    try:
        assert not manager.load(**args)
        assert entered.wait(10)
        workers.append(manager.features['fun.divination'].runtime._prewarm_thread)
        for _ in range(3):
            manager.stop_owner('fun.divination')
            assert not manager.load(**args)
            worker = manager.features['fun.divination'].runtime._prewarm_thread
            if worker and worker not in workers:
                workers.append(worker)
            assert len([t for t in threading.enumerate() if t.name == 'divination-prewarm']) == 1
        assert len(calls) == 1
        release.set()
        workers[0].join(10)
        assert not workers[0].is_alive()
        latest = manager.features['fun.divination'].runtime
        latest.prewarm()
        workers.append(latest._prewarm_thread)
        latest._prewarm_thread.join(10)
        assert len(calls) == 3
    finally:
        manager.stop()
        release.set()
        for worker in workers:
            worker.join(10)
            assert not worker.is_alive()
        h.close()
