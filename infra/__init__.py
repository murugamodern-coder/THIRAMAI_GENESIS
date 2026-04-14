"""
Infrastructure adapters — persistence, Redis, external APIs, process boundaries.

Concrete implementations: ``core.database``, ``services.worker_heartbeat`` (Redis),
``services.cache_layer``, deployment probes in ``api.routes.health``.
"""
