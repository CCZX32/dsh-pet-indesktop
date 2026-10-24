"""Real Qt scheduling/quiet delivery with synthetic OS/voice boundaries."""
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication
from petcore.config import Config
from petcore.contracts.host import HostPorts
from petcore.ui.ports import QtScheduler, QuietMode
from petcore.ui.reminders import ReminderDelivery


class Presentation:
    def __init__(self, root=None, slot=0):
        self.root = root or self
        if root is None:
            self.messages, self.notifications, self.hidden = [], [], set()
        self.slot = slot
    def for_slot(self, slot):
        return Presentation(self.root, slot)
    def say(self, text, **kwargs):
        if self.slot in self.root.hidden:
            return False
        self.root.messages.append((self.slot, text))
        return True
    def notify(self, title, message, **kwargs):
        self.root.notifications.append((self.slot, title, message, kwargs.get('on_click')))
        return True


class Speech:
    def __init__(self):
        self.calls, self.canceled, self.rules, self.precached = [], [], {}, []
    def speak(self, request, **kwargs):
        token = str(len(self.calls) + 1)
        self.calls.append((token, request, kwargs))
        return token
    def stop(self, token=''):
        self.canceled.append(token)
    def cancel_owner(self, owner):
        self.canceled.extend(t for t, _, kw in self.calls if kw.get('owner') == owner)
    def synthesize(self, request):
        self.precached.append(request)
        return None
    def precache(self, request):
        self.precached.append(request)
    def register_yield(self, owner, callback):
        self.rules[owner] = callback
        return lambda: self.rules.pop(owner, None)
    def should_yield(self, moment, *, requester=''):
        return any(fn(moment) for owner, fn in self.rules.items() if owner != requester)


class Harness:
    def __init__(self, root):
        self.app = QApplication.instance() or QApplication([])
        self.root = Path(root)
        self.handles = [SimpleNamespace(slot=i, config=Config(self.root / str(i))) for i in range(2)]
        self.scheduler, self.quiet, self.presentation, self.speech = QtScheduler(), QuietMode(), Presentation(), Speech()
        self.clicks = {}
        self.ports = HostPorts(
            pets=SimpleNamespace(pets=lambda: tuple(self.handles), active=lambda: self.handles[0] if self.handles else None),
            storage=SimpleNamespace(data_dir=lambda owner: self.root / owner),
            presentation=self.presentation, scheduler=self.scheduler, quiet=self.quiet, speech=self.speech,
            interaction=SimpleNamespace(on_click=self.on_click),
        )
        self.ports.reminders = ReminderDelivery(self.quiet, self.scheduler)
        self.context = SimpleNamespace(ports=self.ports, host=SimpleNamespace(config=self.handles[0].config), log=lambda *a, **kw: None)
    def on_click(self, owner, callback):
        self.clicks[owner] = callback
        return lambda: self.clicks.pop(owner, None)
    def close(self):
        self.ports.reminders.close()
        self.app.processEvents()
