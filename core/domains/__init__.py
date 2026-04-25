"""
Self-Evolution Phase 2 — domain plugin system.

The :mod:`core.domains.domain_registry` module exposes :class:`Domain` and
:class:`DomainRegistry` and pre-registers six built-in domains covering the
founder's current businesses and personal verticals.

A *domain* is a reusable bundle of:
- ``models``    : ML model names that own predictions for this domain
- ``features``  : feature_store feature names this domain consumes
- ``tables``    : DB tables this domain reads/writes
- ``prompts``   : LLM prompt templates keyed by intent
- ``policies``  : governance / risk rules (declarative)

The registry is the in-process source of truth; rows are mirrored into
``domain_definitions`` for introspection from the UI.
"""

from core.domains.domain_registry import (  # noqa: F401
    Domain,
    DomainRegistry,
    register_default_domains,
)
