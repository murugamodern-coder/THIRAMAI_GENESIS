"""
Optional **plug-in** handlers for the universal dashboard console.

Register actions with ``register_dashboard_command_handler`` from
``services.dashboard_command_registry`` (or the re-export on
``services.dashboard_command_executor``). This module is imported lazily by the executor so adding
handlers here does not require editing the core orchestrator.

Example::

    from services.dashboard_command_registry import register_dashboard_command_handler

    def _my_feature(*, organization_id: int, parsed: dict, sre_profile: str) -> dict:
        ...

    register_dashboard_command_handler("my_feature_action", _my_feature)

"""
