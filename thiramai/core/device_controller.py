from typing import Any

from thiramai.config import THIRAMAI_MODE


class DeviceController:
    SAFE_ACTIONS = {"irrigation_on", "irrigation_off", "read_sensor"}

    def validate_action(self, device: str, action: str, payload: dict[str, Any] | None = None) -> tuple[bool, str]:
        payload = payload or {}
        action_key = action.strip().lower()
        if action_key not in self.SAFE_ACTIONS:
            return False, f"Action `{action_key}` not in safe device action list."
        if device.strip().lower() == "irrigation" and action_key == "irrigation_on":
            moisture = float(payload.get("soil_moisture", 0.0) or 0.0)
            if moisture > 0.6:
                return False, "Irrigation ON rejected: soil moisture already above safe threshold."
        return True, "safe"

    def send_command(self, device: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        allowed, reason = self.validate_action(device, action, payload)
        if not allowed:
            return {
                "status": "blocked",
                "device": device,
                "action": action,
                "mode": THIRAMAI_MODE,
                "result": "",
                "error": reason,
            }

        if THIRAMAI_MODE != "live":
            return {
                "status": "success",
                "device": device,
                "action": action,
                "mode": "simulation",
                "result": f"Simulated action executed: {device}:{action}",
                "error": "",
            }

        # Live mode hook point for real device drivers.
        return {
            "status": "success",
            "device": device,
            "action": action,
            "mode": "live",
            "result": f"Live action executed: {device}:{action}",
            "error": "",
        }
