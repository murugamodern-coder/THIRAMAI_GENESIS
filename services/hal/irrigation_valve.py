"""Irrigation solenoid valve controller — first real HAL integration.

Controls drip-irrigation valves at the Thiramai factory over MQTT.
"""

from __future__ import annotations

import logging
from typing import Any

from services.hal.hal_base import DeviceRegistry
from services.hal.mqtt_device import MQTTDevice

logger = logging.getLogger(__name__)


class IrrigationValve(MQTTDevice):
    """Solenoid valve for drip irrigation control.

    Actions:
      * ``open``   — open valve (start irrigation)
      * ``close``  — close valve (stop irrigation)
      * ``status`` — get current state

    Reported state fields:
      * ``is_open`` (bool)
      * ``flow_rate`` (litres/min)
      * ``pressure`` (bar)
      * ``runtime_minutes`` (int)
    """

    def __init__(
        self,
        valve_id: str,
        zone: str,
        location: str = "irrigation_farm",
    ) -> None:
        super().__init__(
            device_id=f"valve_{valve_id}",
            device_type="irrigation_solenoid_valve",
            location=location,
        )
        self.valve_id = valve_id
        self.zone = zone

    def open_valve(self, duration_minutes: int = 30) -> dict[str, Any]:
        action = {
            "command": "open",
            "duration_minutes": int(duration_minutes),
            "zone": self.zone,
        }
        success = self.apply_action(action)
        return {
            "ok": bool(success),
            "valve_id": self.valve_id,
            "zone": self.zone,
            "action": "open",
            "duration_minutes": int(duration_minutes),
        }

    def close_valve(self) -> dict[str, Any]:
        action = {"command": "close", "zone": self.zone}
        success = self.apply_action(action)
        return {
            "ok": bool(success),
            "valve_id": self.valve_id,
            "zone": self.zone,
            "action": "close",
        }

    def get_status(self) -> dict[str, Any]:
        state = self.read_state()
        last = state.get("last_state") or {}
        return {
            "valve_id": self.valve_id,
            "zone": self.zone,
            "is_open": bool(last.get("is_open", False)),
            "flow_rate_lpm": float(last.get("flow_rate", 0) or 0),
            "pressure_bar": float(last.get("pressure", 0) or 0),
            "runtime_minutes": int(last.get("runtime_minutes", 0) or 0),
            "mqtt_connected": bool(state.get("connected")),
            "mqtt_enabled": bool(state.get("mqtt_enabled")),
        }


def setup_irrigation_devices() -> dict[str, Any]:
    """Register the factory irrigation valves on app startup.

    Idempotent: re-registering an existing valve just refreshes the entry.
    """
    zones = [
        ("01", "zone_a_north"),
        ("02", "zone_b_south"),
        ("03", "zone_c_east"),
    ]

    registered = 0
    for valve_id, zone in zones:
        valve = IrrigationValve(valve_id=valve_id, zone=zone)
        try:
            valve.connect()
        except Exception as exc:
            logger.warning("irrigation_connect_skipped valve=%s error=%s", valve_id, exc)
        DeviceRegistry.register(f"valve_{valve_id}", valve)
        registered += 1

    logger.info("irrigation_setup complete valves=%d", registered)
    return {"ok": True, "valves_registered": registered}
