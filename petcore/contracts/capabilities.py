from __future__ import annotations

CAPABILITIES = frozenset(
    {
        "character.read",
        "animation.request",
        "speech.present",
        "sound.play",
        "notification.present",
        "settings.read",
        "settings.write",
        "network.request",
        "filesystem.user_data",
        "screenshot.capture",
        "process.spawn",
    }
)


class CapabilityDenied(PermissionError):
    pass


class CapabilitySet:
    def __init__(self, declared: tuple[str, ...] = (), granted: tuple[str, ...] = ()):
        self.declared = frozenset(declared)
        self.granted = frozenset(granted)

    def allows(self, capability: str) -> bool:
        return capability in self.declared and capability in self.granted

    def require(self, capability: str) -> None:
        if capability not in CAPABILITIES:
            raise CapabilityDenied(f"unknown capability: {capability}")
        if capability not in self.declared:
            raise CapabilityDenied(f"capability not declared: {capability}")
        if capability not in self.granted:
            raise CapabilityDenied(f"capability not granted: {capability}")
