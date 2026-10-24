"""P4-c3 public lifecycle contracts; audio/network are the only fake boundaries."""
import threading
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from petcore.contracts.speech import SpeechRequest, SpeechResult
from petcore.ui.ports import CoreSpeechPort, QtScheduler


def wait_for(predicate):
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop()
    poll, timeout = QTimer(), QTimer()
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    poll.start(5)
    timeout.start(10000)
    if not predicate():
        loop.exec()
    poll.stop()
    timeout.stop()
    app.processEvents()
    assert predicate()


class Audio:
    def __init__(self):
        self.calls = []
        self.ended = None
        self.stops = 0

    def play_tracked(self, path, *, volume, on_finished, on_error):
        self.calls.append(path)
        self.ended = on_finished
        return True

    def stop(self):
        self.stops += 1


class Service:
    def synthesize(self, request):
        return SpeechResult(Path('synthetic.wav'), 'test', '', text=request.text)


def test_playback_end_is_distinct_and_single_channel():
    app = QApplication.instance() or QApplication([])
    audio = Audio()
    port = CoreSpeechPort(Service(), audio, scheduler=QtScheduler())
    events = []
    try:
        port.speak(SpeechRequest('one'), on_done=lambda _: events.append('started'),
                   on_finished=lambda _: events.append('ended'))
        port.speak(SpeechRequest('two'))
        wait_for(lambda: events == ['started'])
        assert port.playing() and len(audio.calls) == 1
        finish = audio.ended
        finish()
        finish()  # duplicate native event cannot finish the next token
        wait_for(lambda: len(audio.calls) == 2)
        assert events == ['started', 'ended']
        audio.ended()
        wait_for(lambda: not port.playing())
    finally:
        port.stop()
        app.processEvents()


def test_cancel_owner_blocks_late_synthesis_and_playback():
    app = QApplication.instance() or QApplication([])
    gate, started = threading.Event(), threading.Event()
    class Blocking(Service):
        def synthesize(self, request):
            started.set()
            assert gate.wait(10)
            return super().synthesize(request)
    audio = Audio()
    port = CoreSpeechPort(Blocking(), audio, scheduler=QtScheduler())
    events = []
    try:
        port.speak(SpeechRequest('one'), owner='mod', slot=2,
                   on_finished=lambda _: events.append(1))
        assert started.wait(10)
        worker = port._worker
        port.cancel_owner('mod')
        port.speak(SpeechRequest('two'), owner='other')
        assert port._worker is worker
        gate.set()
        wait_for(lambda: len(audio.calls) == 1)
        port.cancel_owner('other')
        audio.ended()
        assert not events
        wait_for(lambda: not port.playing())
    finally:
        gate.set()
        port.stop()
        app.processEvents()


def test_queue_bound_quiet_and_revocable_yield():
    from petcore.ui.ports import QuietMode
    app = QApplication.instance() or QApplication([])
    quiet, audio = QuietMode(), Audio()
    port = CoreSpeechPort(Service(), audio, scheduler=QtScheduler(), quiet=quiet, queue_limit=2)
    errors = []
    try:
        cancel = port.register_yield('festival', lambda moment: moment == 'due')
        assert port.should_yield('due', requester='chime')
        cancel()
        assert not port.should_yield('due', requester='chime')
        port.speak(SpeechRequest('a'))
        port.speak(SpeechRequest('b'))
        port.speak(SpeechRequest('c'), on_error=errors.append)
        wait_for(lambda: bool(errors))
        assert errors[0].reason == 'rate_limit'
        quiet.set_quiet(60)
        wait_for(lambda: not port.playing())
        port.speak(SpeechRequest('silent'), on_error=errors.append)
        wait_for(lambda: len(errors) == 2)
        assert len(audio.calls) <= 1
    finally:
        port.stop()
        app.processEvents()


def test_bound_presentation_does_not_retarget_closed_slot():
    from petcore.ui.app import _PresentationAdapter
    calls = []
    win = SimpleNamespace(slot=2, isVisible=lambda: True, say=lambda *a, **k: calls.append(a) or True)
    other = SimpleNamespace(slot=0, isVisible=lambda: True)
    windows = [win, other]
    host = SimpleNamespace(pets=SimpleNamespace(each=lambda: tuple(windows)), window=other, quiet=None)
    bound = _PresentationAdapter(host).for_slot(2)
    assert bound.say('first') is True
    windows.remove(win)
    assert bound.say('late') is False
    assert len(calls) == 1

def test_reminders_quiet_summary_cancel_and_notification_fallback():
    from petcore.ui.reminders import ReminderDelivery
    from petcore.ui.ports import QuietMode
    quiet = QuietMode()
    delivered = []
    class Target:
        def say(self, text, **kwargs):
            return False
        def notify(self, title, message, **kwargs):
            delivered.append((title, message, kwargs))
            return True
    target = Target()
    hub = ReminderDelivery(quiet, QtScheduler())
    alive = [True]
    quiet.set_quiet(60)
    for i in range(3):
        assert hub.deliver('todo' if i < 2 else 'festival', 2, str(i), target, '待办', str(i),
                           guard=lambda: alive[0]) == 'queued'
    assert not delivered
    quiet.set_quiet(0)
    hub.flush()
    assert len(delivered) == 1 and '3' in delivered[0][1]
    hub.flush()
    assert len(delivered) == 1
    quiet.set_quiet(60)
    hub.deliver('todo', 2, 'later', target, '待办', 'late', guard=lambda: alive[0])
    hub.cancel_slot(2)
    quiet.set_quiet(0)
    hub.flush()
    assert len(delivered) == 1
    hub.close()


def test_audio_adapter_reports_real_media_end_and_cancellation(tmp_path):
    # A subprocess avoids the repository-wide intentional mute fixture; volume
    # remains zero and the source contains only synthetic PCM silence.
    import os
    import subprocess
    import sys
    code = r"""
import wave, sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from petcore.ui.ports import AudioAdapter
app = QApplication([])
path = Path(sys.argv[1]) / 'silence.wav'
with wave.open(str(path), 'wb') as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(44100)
    output.writeframes(b'\0\0' * 44100)
audio = AudioAdapter(None)
events = []
def ended():
    events.append('end')
    app.quit()
assert audio.play_tracked(path, volume=0, on_finished=ended,
                          on_error=lambda e: (events.append(e.reason), app.quit()))
QTimer.singleShot(15000, app.quit)
app.exec()
assert events == ['end'], events
assert audio.play_tracked(path, volume=0, on_finished=ended,
                          on_error=lambda e: (events.append(e.reason), app.quit()))
app.exec()
assert events == ['end', 'end'], events
assert audio.play_tracked(path, volume=0, on_finished=lambda: events.append('late'),
                          on_error=lambda e: events.append('error'))
audio.stop()
app.processEvents()
assert events == ['end', 'end'], events
audio.close()
app.processEvents()
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                            env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr

def test_rejected_speech_callback_is_revoked_with_owner():
    class Scheduler:
        def __init__(self):
            self.callbacks = []
        def call_later(self, delay, callback):
            self.callbacks.append(callback)
    scheduler = Scheduler()
    port = CoreSpeechPort(Service(), Audio(), scheduler=scheduler, queue_limit=1)
    errors = []
    try:
        port.speak(SpeechRequest('fills queue'), owner='other')
        port.speak(SpeechRequest('rejected'), owner='closing', on_error=errors.append)
        port.cancel_owner('closing')
        for callback in tuple(scheduler.callbacks):
            callback()
        assert errors == []
    finally:
        port.stop()


def test_repeated_audio_loading_does_not_start_decoding(tmp_path):
    import os
    import subprocess
    import sys
    code = r"""
import wave, sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from petcore.ui.ports import AudioAdapter
app = QApplication([])
path = Path(sys.argv[1]) / 'repeat.wav'
with wave.open(str(path), 'wb') as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(44100)
    output.writeframes(b'\0\0' * 44100)
audio = AudioAdapter(None)
events = []
audio.play_tracked(path, volume=0, on_finished=lambda: None, on_error=events.append)
assert audio._player.mediaStatus().name == 'LoadingMedia'
# Observe the public play boundary; do not alter Qt classes globally.
audio._player.play = lambda: events.append(audio._player.mediaStatus().name)
audio.play_tracked(path, volume=0, on_finished=lambda: None, on_error=events.append)
app.processEvents()
audio.close()
app.processEvents()
assert 'LoadingMedia' not in events, events
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                            env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_repeated_invalid_audio_reports_error_instead_of_stalling(tmp_path):
    import os
    import subprocess
    import sys
    code = r"""
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from petcore.ui.ports import AudioAdapter
app = QApplication([])
audio = AudioAdapter(None)
events = []
path = Path(sys.argv[1]) / 'missing.wav'
def failed(error):
    events.append(error.reason)
    app.quit()
audio.play_tracked(path, volume=0, on_finished=lambda: None, on_error=failed)
QTimer.singleShot(10000, app.quit)
app.exec()
assert events == ['unavailable'], events
audio.play_tracked(path, volume=0, on_finished=lambda: None, on_error=failed)
# Retry must finish too, rather than leaving the shared speech worker waiting
# for a status signal that will never recur for an unchanged invalid source.
app.exec()
assert events == ['unavailable', 'unavailable'], events
audio.close()
app.processEvents()
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                            env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
