"""MQTT-backed HAL device.

Generic controller for any device that
* publishes state to ``thiramai/{location}/{device_id}/state``
* listens for commands on ``thiramai/{location}/{device_id}/command``

When ``MQTT_BROKER_HOST`` is unset or ``paho-mqtt`` is missing the device stays
in a "disabled" state so app startup never crashes on missing hardware.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

MQTT_ENABLED = bool((os.getenv("MQTT_BROKER_HOST") or "").strip())


class MQTTDevice:
    """Generic MQTT command/state HAL device."""

    def __init__(
        self,
        device_id: str,
        device_type: str,
        location: str,
        broker_host: str | None = None,
    ) -> None:
        self.device_id = device_id
        self.device_type = device_type
        self.location = location
        self.broker_host = broker_host or (os.getenv("MQTT_BROKER_HOST") or "localhost").strip()
        try:
            self.broker_port = int((os.getenv("MQTT_BROKER_PORT") or "1883").strip() or 1883)
        except ValueError:
            self.broker_port = 1883
        self._client: Any = None
        self._last_state: dict[str, Any] = {}
        self._connected: bool = False

    def connect(self) -> bool:
        if not MQTT_ENABLED:
            logger.info("mqtt_disabled device=%s", self.device_id)
            return False
        try:
            import paho.mqtt.client as mqtt  # type: ignore[import-not-found]

            self._client = mqtt.Client(client_id=f"thiramai_{self.device_id}")

            def on_connect(client: Any, userdata: Any, flags: Any, rc: int) -> None:
                if rc == 0:
                    self._connected = True
                    state_topic = f"thiramai/{self.location}/{self.device_id}/state"
                    client.subscribe(state_topic)
                    logger.info("mqtt_connected device=%s", self.device_id)
                else:
                    logger.error("mqtt_connect_failed rc=%s device=%s", rc, self.device_id)

            def on_disconnect(client: Any, userdata: Any, rc: int) -> None:
                self._connected = False

            def on_message(client: Any, userdata: Any, msg: Any) -> None:
                try:
                    self._last_state = json.loads(msg.payload.decode())
                except Exception:
                    pass

            self._client.on_connect = on_connect
            self._client.on_disconnect = on_disconnect
            self._client.on_message = on_message

            self._client.connect(self.broker_host, self.broker_port, 60)
            self._client.loop_start()
            return True
        except ImportError:
            logger.warning("paho-mqtt not installed — device=%s offline", self.device_id)
            return False
        except Exception as exc:
            logger.error("mqtt_connect_error device=%s error=%s", self.device_id, exc)
            return False

    def read_state(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "location": self.location,
            "connected": bool(self._connected),
            "last_state": dict(self._last_state),
            "mqtt_enabled": bool(MQTT_ENABLED),
        }

    def apply_action(self, action: dict[str, Any]) -> bool:
        if not self._connected or self._client is None:
            logger.warning("mqtt_not_connected device=%s", self.device_id)
            return False
        try:
            command_topic = f"thiramai/{self.location}/{self.device_id}/command"
            payload = json.dumps(action)
            self._client.publish(command_topic, payload, qos=1)
            logger.info("mqtt_command_sent device=%s action=%s", self.device_id, action)
            return True
        except Exception as exc:
            logger.error("mqtt_publish_error device=%s error=%s", self.device_id, exc)
            return False

    def health_check(self) -> bool:
        return bool(self._connected)

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._connected = False
