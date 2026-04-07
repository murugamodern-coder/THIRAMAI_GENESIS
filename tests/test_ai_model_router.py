"""Unified local model routing (heuristics only)."""

from __future__ import annotations

from core.ai_model_router import PromptKind, classify_prompt_kind, ollama_model_for_kind


def test_short_default() -> None:
    assert classify_prompt_kind("add task buy milk") is PromptKind.SHORT


def test_reasoning_cues() -> None:
    assert classify_prompt_kind("Why did revenue drop? Explain your reasoning.") is PromptKind.REASONING


def test_long_by_length(monkeypatch) -> None:
    monkeypatch.setenv("THIRAMAI_ROUTER_LONG_CHARS", "50")
    assert classify_prompt_kind("x" * 60) is PromptKind.LONG_OUTPUT


def test_long_by_phrase() -> None:
    assert classify_prompt_kind("Write a detailed quarterly report") is PromptKind.LONG_OUTPUT


def test_models_resolve() -> None:
    assert ollama_model_for_kind(PromptKind.SHORT)
    assert ollama_model_for_kind(PromptKind.REASONING)
    assert ollama_model_for_kind(PromptKind.LONG_OUTPUT)
