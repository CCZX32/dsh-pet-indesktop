"""Exercise the installed APK through adb and Android UI, and retain evidence.

Use a dedicated emulator or test handset: this changes this app's permissions.
All waits poll real state with deadlines; timed observation windows measure
that drawing has stopped, rather than guessing when a transition will finish.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "io.github.dshpet.mobile"
SERVICE = PACKAGE + "/.PetOverlayService"


class Device:
    def __init__(self, adb: str, serial: str, output: Path):
        self.adb, self.serial, self.output = adb, serial, output
        self.output.mkdir(parents=True, exist_ok=True)
        self.observations = []

    def run(self, *args: str) -> str:
        for attempt in range(3):
            result = subprocess.run([self.adb, "-s", self.serial, *map(str, args)],
                                    capture_output=True, encoding="utf-8", errors="replace", timeout=45)
            if result.returncode == 0 or "device offline" not in result.stderr or attempt == 2:
                break
            # An offline transport rejected the command before it reached Android.
            subprocess.run([self.adb, "-s", self.serial, "wait-for-device"],
                           capture_output=True, timeout=30, check=True)
        if result.returncode:
            raise RuntimeError(f"adb {args}: exit={result.returncode}: {result.stderr or result.stdout}")
        return result.stdout.strip()

    def shell(self, *args: str) -> str:
        return self.run("shell", *args)

    def record(self, name: str, value):
        self.observations.append({"name": name, "value": value, "at": time.time()})
        (self.output / "acceptance.json").write_text(json.dumps(
            {"serial": self.serial, "is_emulator": self.serial.startswith("emulator-"),
             "observations": self.observations}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{name}: {value}", flush=True)

    def wait(self, predicate, description: str, timeout: float = 30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            threading.Event().wait(.15)
        raise AssertionError(f"Timed out: {description}")

    def runtime(self) -> dict:
        text = self.shell("dumpsys", "activity", "service", SERVICE)
        values = dict(re.findall(r"(running|paused|interactive|windows|draws|decoded|mode)=([\w.]+)", text))
        return values

    def screenshot(self, name: str):
        for _ in range(3):
            result = subprocess.run([self.adb, "-s", self.serial, "exec-out", "screencap", "-p"],
                                    capture_output=True, timeout=30)
            if result.returncode == 0 and result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
                (self.output / f"{name}.png").write_bytes(result.stdout)
                return
        raise RuntimeError(f"screenshot capture failed: {result.returncode}: {result.stderr!r}")

    def ui(self):
        self.shell("uiautomator", "dump", "/sdcard/pet-ui.xml")
        return ET.fromstring(self.shell("cat", "/sdcard/pet-ui.xml"))

    def tap_text(self, *labels: str):
        def find():
            for node in self.ui().iter("node"):
                if node.get("text", "").casefold() in {label.casefold() for label in labels} and node.get("enabled") == "true":
                    return node
            return None
        # Element's truthiness depends on its children, so return a list wrapper.
        found = self.wait(lambda: [n] if (n := find()) is not None else None, str(labels))[0]
        left, top, right, bottom = map(int, re.findall(r"\d+", found.get("bounds", "")))
        self.shell("input", "tap", str((left + right) // 2), str((top + bottom) // 2))

    def overlays(self):
        windows = self.shell("dumpsys", "window", "windows")
        return [block for block in re.split(r"\n  Window #", windows)
                if f"package={PACKAGE}" in block and "appop=SYSTEM_ALERT_WINDOW" in block]

    def pet_center(self):
        for block in self.overlays():
            legacy_flags = re.search(r"\bfl=#([0-9a-fA-F]+)", block)
            flags = int(legacy_flags[1], 16) if legacy_flags else None
            if "NOT_TOUCHABLE" in block or (flags is not None and flags & 0x10):
                continue
            if "mForceHideNonSystemOverlayWindow=true" in block:
                continue
            if "NOT_FOCUSABLE" not in block and (flags is None or not flags & 0x08):
                continue
            match = re.search(r"\b(?:mFrame|frame)=\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", block)
            if match:
                left, top, right, bottom = map(int, match.groups())
                return (left + right) // 2, (top + bottom) // 2
        raise AssertionError("Pet overlay window not found")

    def launch(self):
        return self.shell("am", "start", "-W", "-n", PACKAGE + "/.MainActivity")

    def go_home(self):
        home = self.shell("cmd", "package", "resolve-activity", "--brief", "-a",
                          "android.intent.action.MAIN", "-c", "android.intent.category.HOME").splitlines()[-1]
        self.shell("am", "start", "-W", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME")
        self.wait(lambda: any(n.get("package") == home.split("/")[0] for n in self.ui().iter("node")),
                  "launcher in foreground")

    def check(self):
        self.record("android", self.shell("getprop", "ro.build.version.release"))
        self.shell("am", "force-stop", PACKAGE)
        self.shell("appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "deny")
        self.launch()
        nodes = list(self.ui().iter("node"))
        assert any(n.get("text") in ("Allow overlay", "允许悬浮显示") for n in nodes)
        self.screenshot("permission-denied")
        self.record("permission_denied", "permission action visible; service absent")
        assert not self.runtime()
        self.shell("appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "allow")
        if int(self.shell("getprop", "ro.build.version.sdk")) >= 33:
            self.shell("pm", "grant", PACKAGE, "android.permission.POST_NOTIFICATIONS")
        self.shell("am", "force-stop", PACKAGE)
        launches = []
        for _ in range(3):
            self.shell("am", "force-stop", PACKAGE)
            launches.append(self.launch())
        self.record("cold_launches", launches)
        self.tap_text("Start", "启动")
        self.wait(lambda: int(self.runtime().get("draws", 0)) >= 3, "first pet frames")
        self.go_home()
        self.screenshot("home-overlay")
        self.shell("am", "start", "-W", "-a", "android.settings.SETTINGS")
        self.wait(lambda: any(n.get("package") == "com.android.settings" for n in self.ui().iter("node")),
                  "system settings in foreground")
        self.wait(lambda: self.runtime().get("windows") == "1", "overlay over Settings")
        self.screenshot("system-settings")
        self.record("system_overlay_policy", "mForceHideNonSystemOverlayWindow=true" in
                    self.shell("dumpsys", "window", "windows"))
        self.go_home()
        self.wait(lambda: "mForceHideNonSystemOverlayWindow=true" not in
                  self.shell("dumpsys", "window", "windows"), "leave protected system screen")
        clock = self.shell("cmd", "package", "resolve-activity", "--brief", "-a",
                           "android.intent.action.SHOW_ALARMS").splitlines()[-1]
        if "/" in clock and " " not in clock:
            clock = self.shell("cmd", "package", "resolve-activity", "--brief", "-a",
                               "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
                               clock.split("/")[0]).splitlines()[-1]
            self.shell("am", "start", "-W", "-a", "android.intent.action.MAIN", "-n", clock)
            self.wait(lambda: any(n.get("package") == clock.split("/")[0] for n in self.ui().iter("node")),
                      "clock activity in foreground")
            self.screenshot("other-app-overlay")
            self.record("other_app", clock)
            self.go_home()
        x, y = self.pet_center()
        _, height = map(int, re.findall(r"(\d+)x(\d+)", self.shell("wm", "size"))[-1])
        target_y = max(150, y - 500) if y > height / 2 else min(height - 150, y + 500)
        # Older adb input injects fewer MOVE samples; a 350ms fling remains fast
        # while supplying enough samples to the real platform VelocityTracker.
        self.shell("input", "swipe", x, y, x, target_y, "350")
        thrown = self.wait(lambda: s if (s := self.runtime()).get("mode") == "THROWN" else None,
                           "fling enters thrown mode", timeout=5)
        self.record("fling", thrown)
        self.wait(lambda: self.runtime().get("mode") != "THROWN", "fling settles")
        x, y = self.pet_center()
        self.shell("input", "swipe", x, y, x, y, "1500")
        self.tap_text("Pause", "暂停")
        self.wait(lambda: self.runtime().get("paused") == "true", "pause")
        baseline = self.runtime()
        threading.Event().wait(2)
        after = self.runtime()
        assert after["draws"] == baseline["draws"], (baseline, after)
        self.record("paused_observation_2s", after)
        self.shell("input", "keyevent", "KEYCODE_SLEEP")
        self.wait(lambda: self.runtime().get("windows") == "0", "screen-off removes window")
        assert not self.overlays()
        baseline = self.runtime()
        threading.Event().wait(2)
        after = self.runtime()
        assert after["draws"] == baseline["draws"] and after["decoded"] == baseline["decoded"]
        self.record("screen_off_observation_2s", after)
        self.shell("input", "keyevent", "KEYCODE_WAKEUP")
        self.shell("wm", "dismiss-keyguard")
        self.wait(lambda: self.runtime().get("windows") == "1", "unlock restores window")
        self.launch()
        self.tap_text("Resume", "继续")
        self.wait(lambda: self.runtime().get("paused") == "false", "resume")
        self.tap_text("Stop", "停止")
        self.wait(lambda: not self.runtime() and not self.overlays(), "stop removes service and OS windows")
        self.record("explicit_stop", "service and application overlay windows absent")
        self.tap_text("Start", "启动")
        self.wait(lambda: self.runtime().get("running") == "true", "restart before revocation")
        self.shell("appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "deny")
        self.wait(lambda: not self.runtime(), "revoked permission stops service")
        self.record("permission_revoked", "service removed")
        self.shell("appops", "set", PACKAGE, "SYSTEM_ALERT_WINDOW", "allow")
        self.shell("am", "force-stop", PACKAGE)
        self.launch()
        self.tap_text("Start", "启动")
        self.wait(lambda: self.runtime().get("running") == "true", "restart after permission restored")
        self.go_home()
        self.record("result", "PASS")

    def measure(self, minutes: float):
        path = self.output / "performance.jsonl"
        deadline = time.monotonic() + minutes * 60
        with path.open("w", encoding="utf-8") as output:
            while True:
                pid = self.shell("pidof", PACKAGE)
                if not pid.isdigit():
                    raise RuntimeError("Pet process stopped during measurement")
                record = {"timestamp": time.time(), "serial": self.serial, "pid": int(pid),
                          "runtime": self.runtime(),
                          "memory": self.shell("dumpsys", "meminfo", PACKAGE),
                          "cpu": self.shell("top", "-b", "-d", "1", "-n", "2", "-p", pid),
                          "threads": self.shell("ps", "-T", "-p", pid),
                          "battery": self.shell("dumpsys", "battery")}
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                if time.monotonic() >= deadline:
                    break
                threading.Event().wait(min(30, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes", type=float, default=0)
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()
    device = Device(args.adb, args.serial, args.output)
    if not args.measure_only:
        device.check()
    if args.minutes:
        device.measure(args.minutes)


if __name__ == "__main__":
    main()
