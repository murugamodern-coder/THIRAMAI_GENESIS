"""Hardware Abstraction Layer — base contract + global device registry."""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class HardwareDevice(Protocol):
    """Minimum behaviour expected from any HAL device."""

    device_id: str
    device_type: str
    location: str

    def read_state(self) -> dict[str, Any]:
        ...

    def apply_action(self, action: dict[str, Any]) -> bool:
        ...

    def health_check(self) -> bool:
        ...


class DeviceRegistry:
    """Process-wide registry of connected hardware devices."""

    _devices: dict[str, Any] = {}

    @classmethod
    def register(cls, device_id: str, device: Any) -> None:
        cls._devices[device_id] = device
        logger.info("device_registered id=%s type=%s", device_id, type(device).__name__)

    @classmethod
    def unregister(cls, device_id: str) -> None:
        cls._devices.pop(device_id, None)

    @classmethod
    def get(cls, device_id: str) -> Any:
        return cls._devices.get(device_id)

    @classmethod
    def list_all(cls) -> list[dict[str, Any]]:
        return [
            {
                "device_id": did,
                "type": type(dev).__name__,
                "status": "connected" if getattr(dev, "_connected", False) else "registered",
            }
            for did, dev in cls._devices.items()
        ]

    @classmethod
    def read_all_states(cls) -> dict[str, Any]:
        states: dict[str, Any] = {}
        for did, dev in cls._devices.items():
            try:
                states[did] = dev.read_state()
            except Exception as exc:
                states[did] = {"error": str(exc)}
        return states

    @classmethod
    def connected_count(cls) -> int:
        return sum(1 for dev in cls._devices.values() if getattr(dev, "_connected", False))

    @classmethod
    def total(cls) -> int:
        return len(cls._devices)
