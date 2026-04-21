import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from thiramai.config import get_thiramai_mode, validate_openai_api_key
from thiramai.integrations.mock_llm import dry_run_llm_response, mock_llm


FALLBACK_MODELS = ["gpt-4o-mini", "gpt-3.5-turbo"]
logger = logging.getLogger("thiramai.llm")
_StructuredModel = TypeVar("_StructuredModel", bound=BaseModel)


def _client() -> OpenAI:
    api_key = validate_openai_api_key()
    return OpenAI(api_key=api_key)


def _observe_llm_call(start: float, ok: bool) -> None:
    latency_ms = max(0.0, (time.monotonic() - start) * 1000.0)
    try:
        from thiramai.runtime import ai_observability

        ai_observability.record_llm_call(latency_ms=latency_ms, ok=ok)
    except Exception:
        pass


def _degraded_llm_output(prompt: str, error: BaseException | None) -> str:
    """Deterministic JSON-shaped fallback when live LLMs fail (keeps autonomy loop alive)."""
    mem_hint: list[Any] = []
    try:
        from thiramai.core.memory import MemoryStore

        raw = MemoryStore().read_all()
        mem_hint = raw[-16:] if isinstance(raw, list) else []
    except Exception:
        pass
    payload = {
        "status": "degraded",
        "detail": "LLM unavailable — partial fallback using cached memory hints",
        "error_class": type(error).__name__ if error else None,
        "cached_memory_hints": [
            {"event_type": e.get("event_type"), "snippet": str(e.get("payload", ""))[:420]}
            for e in mem_hint[-10:]
            if isinstance(e, dict)
        ],
        "prompt_digest": prompt[:280],
    }
    logger.warning("[LLM] graceful degrade (%s)", payload.get("error_class"))
    try:
        from thiramai.runtime import ai_observability

        ai_observability.record_failure(
            "llm_graceful_degrade",
            extra={"error": str(error)[:800] if error else ""},
        )
    except Exception:
        pass
    return json.dumps(payload, ensure_ascii=False)


def warm_llm_stack() -> dict[str, Any]:
    """Startup warm: OpenAI client (live), embeddings probe, recent memory load."""
    detail: dict[str, Any] = {}
    mode = get_thiramai_mode()
    if mode == "live":
        try:
            _ = _client()
            detail["openai_client_ready"] = True
        except Exception as exc:
            detail["openai_client_ready"] = False
            detail["openai_client_error"] = f"{type(exc).__name__}: {exc}"
    else:
        detail["openai_client_ready"] = "skipped_non_live"
    try:
        from thiramai.integrations.embeddings import embed_text

        embed_text("THIRAMAI warm-up embedding probe")
        detail["embeddings_warmed"] = True
    except Exception as exc:
        detail["embeddings_warmed"] = False
        detail["embeddings_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from thiramai.core.memory import MemoryStore

        ev = MemoryStore().read_all()
        detail["memory_events_seen"] = len(ev) if isinstance(ev, list) else 0
    except Exception as exc:
        detail["memory_events_seen"] = -1
        detail["memory_error"] = f"{type(exc).__name__}: {exc}"
    return detail


def call_llm(prompt: str) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must be a non-empty string.")
    from thiramai.config import THIRAMAI_LLM_GRACEFUL_DEGRADE

    t0 = time.monotonic()
    try:
        return _call_llm_impl(prompt)
    except ValueError:
        raise
    except Exception as exc:
        _observe_llm_call(t0, False)
        if THIRAMAI_LLM_GRACEFUL_DEGRADE and isinstance(exc, RuntimeError) and "LLM call failed" in str(exc):
            return _degraded_llm_output(prompt, exc)
        raise
    else:
        _observe_llm_call(t0, True)


def _call_llm_impl(prompt: str) -> str:
    try:
        from thiramai.config import THIRAMAI_LLM_TOKEN_BUDGET_PER_MINUTE
        from thiramai.runtime.llm_quota import allow_or_raise

        est = max(32, len(prompt) // 4 + 48)
        allow_or_raise(est, limit_per_minute=THIRAMAI_LLM_TOKEN_BUDGET_PER_MINUTE)
        try:
            from thiramai.runtime.request_context import get_goal_tenant
            from thiramai.runtime import billing_quota

            oid, uid, _jid = get_goal_tenant()
            if oid is not None and uid is not None:
                billing_quota.assert_llm_allowed(int(oid), int(uid), est)
        except RuntimeError:
            raise
        except Exception:
            pass
    except RuntimeError:
        raise
    except Exception:
        pass
    mode = get_thiramai_mode()
    if mode == "dry-run":
        logger.info("[MODE] dry-run | LLM skipped (stub response)")
        return dry_run_llm_response(prompt)
    if mode == "simulation":
        logger.info("[MODE] simulation | mock_llm")
        return mock_llm(prompt)
    client = _client()
    logger.info("LLM call started")
    errors: list[str] = []
    for model in FALLBACK_MODELS:
        try:
            response = client.responses.create(
                model=model,
                input=prompt,
                temperature=0.2,
            )
            text = response.output_text.strip()
            if text:
                logger.info("LLM call finished with model=%s", model)
                try:
                    from thiramai.runtime import ai_observability

                    ntok = max(16, len(prompt) // 4 + len(text) // 4)
                    ai_observability.record_llm_tokens_est(ntok)
                    try:
                        from thiramai.runtime.request_context import get_goal_tenant
                        from thiramai.runtime import billing_quota

                        oid, uid, _j = get_goal_tenant()
                        if oid is not None and uid is not None:
                            billing_quota.record_tokens_estimated(int(oid), int(uid), ntok)
                    except Exception:
                        pass
                except Exception:
                    pass
                return text
            errors.append(f"{model}: empty response")
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    logger.error("LLM call failed for all models")
    raise RuntimeError("LLM call failed. " + " | ".join(errors))


def _collect_multi_responses(prompt: str) -> list[dict[str, str]]:
    try:
        from thiramai.config import THIRAMAI_LLM_TOKEN_BUDGET_PER_MINUTE
        from thiramai.runtime.llm_quota import allow_or_raise

        est = max(64, len(prompt) // 4 + 96)
        allow_or_raise(est, limit_per_minute=THIRAMAI_LLM_TOKEN_BUDGET_PER_MINUTE)
        try:
            from thiramai.runtime.request_context import get_goal_tenant
            from thiramai.runtime import billing_quota

            oid, uid, _jid = get_goal_tenant()
            if oid is not None and uid is not None:
                billing_quota.assert_llm_allowed(int(oid), int(uid), est)
        except RuntimeError:
            raise
        except Exception:
            pass
    except RuntimeError:
        raise
    except Exception:
        pass
    client = _client()
    responses: list[dict[str, str]] = []
    errors: list[str] = []

    for model in FALLBACK_MODELS:
        try:
            response = client.responses.create(
                model=model,
                input=prompt,
                temperature=0.2,
            )
            text = response.output_text.strip()
            if text:
                responses.append({"model": model, "response": text})
            else:
                errors.append(f"{model}: empty response")
        except Exception as exc:
            errors.append(f"{model}: {exc}")

    print("[MULTI-AI RESPONSES]")
    print(json.dumps(responses, ensure_ascii=True))

    if not responses:
        groq = _groq_chat_completion(prompt)
        if groq:
            responses.append({"model": "groq-llama", "response": groq})
    if not responses:
        raise RuntimeError("All multi-model calls failed. " + " | ".join(errors))
    try:
        from thiramai.runtime import ai_observability

        tot = max(
            64,
            len(prompt) // 4 + sum(len(str(r.get("response", ""))) // 4 for r in responses),
        )
        ai_observability.record_llm_tokens_est(tot)
        try:
            from thiramai.runtime.request_context import get_goal_tenant
            from thiramai.runtime import billing_quota

            oid, uid, _j = get_goal_tenant()
            if oid is not None and uid is not None:
                billing_quota.record_tokens_estimated(int(oid), int(uid), int(tot))
        except Exception:
            pass
    except Exception:
        pass
    return responses


def _groq_chat_completion(prompt: str) -> str | None:
    """Optional Groq fallback when OpenAI models all fail (same prompt)."""
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    model = (os.getenv("THIRAMAI_GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
    if not key:
        return None
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        choices = data.get("choices") or []
        if not choices:
            return None
        msg = choices[0].get("message") or {}
        content = str(msg.get("content") or "").strip()
        return content or None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("Groq fallback failed: %s", exc)
        return None


def cross_model_agreement_score(responses: list[dict[str, str]]) -> tuple[float, float]:
    """
    Returns (confidence 0..1, disagreement 0..1) using average pairwise Jaccard on word sets.
    """
    texts = [r.get("response", "").strip() for r in responses if r.get("response")]
    if len(texts) < 2:
        return 1.0, 0.0

    def _jaccard(a: str, b: str) -> float:
        sa, sb = set(a.split()), set(b.split())
        if not sa or not sb:
            return 0.0
        inter = len(sa & sb)
        union = len(sa | sb)
        return float(inter) / float(union) if union else 0.0

    pairs: list[float] = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            pairs.append(_jaccard(texts[i], texts[j]))
    avg = sum(pairs) / len(pairs) if pairs else 0.0
    return round(avg, 3), round(1.0 - avg, 3)


def multi_llm_with_meta(prompt: str) -> dict[str, Any]:
    """Same as multi_llm but includes consensus confidence metrics."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must be a non-empty string.")
    mode = get_thiramai_mode()
    if mode == "dry-run":
        return {"text": dry_run_llm_response(prompt), "confidence": 1.0, "disagreement": 0.0, "models": []}
    if mode == "simulation":
        return {"text": mock_llm(prompt), "confidence": 1.0, "disagreement": 0.0, "models": ["mock"]}
    responses = _collect_multi_responses(prompt)
    conf, disag = cross_model_agreement_score(responses)
    text = consensus(responses, original_prompt=prompt)
    models_used = responses
    low = float((os.getenv("THIRAMAI_LLM_LOW_CONF_THRESHOLD") or "0.35").strip() or "0.35")
    if conf < low and (os.getenv("THIRAMAI_LLM_RETRY_LOW_CONF") or "").strip().lower() in {"1", "true", "yes"}:
        responses2 = _collect_multi_responses(prompt + "\n\n[Second pass: tighten JSON/constraints.]")
        text2 = consensus(responses2, original_prompt=prompt)
        conf2, disag2 = cross_model_agreement_score(responses2)
        if conf2 >= conf:
            text, conf, disag = text2, conf2, disag2
            models_used = responses2
    return {"text": text, "confidence": conf, "disagreement": disag, "models": [r["model"] for r in models_used]}


def consensus(responses: list[dict[str, str]], original_prompt: str = "") -> str:
    if not responses:
        raise RuntimeError("Consensus requires at least one model response.")
    if len(responses) == 1:
        print("[CONSENSUS SELECTED]")
        print(json.dumps({"model": responses[0]["model"], "reason": "single available response"}, ensure_ascii=True))
        return responses[0]["response"]

    judge_prompt = (
        "You are a consensus evaluator for autonomous systems.\n"
        "Select the BEST response by correctness, completeness, and safety.\n"
        "Return strict JSON only:\n"
        '{"selected_model":"model-name","justification":"short reason"}\n'
        f"Original prompt:\n{original_prompt}\n"
        f"Candidate responses:\n{json.dumps(responses, ensure_ascii=True)}\n"
        "Prefer safer, more constrained answers when disagreement exists."
    )

    selected_model = ""
    try:
        judge_raw = call_llm(judge_prompt)
        parsed = json.loads(judge_raw)
        selected_model = str(parsed.get("selected_model", "")).strip()
    except Exception:
        selected_model = ""

    if selected_model:
        for item in responses:
            if item["model"] == selected_model:
                print("[CONSENSUS SELECTED]")
                print(json.dumps({"model": selected_model, "reason": "judge-selected"}, ensure_ascii=True))
                return item["response"]

    # Fail-safe: pick the safest-looking response (no dangerous shell tokens, shortest command density).
    unsafe_markers = {"rm ", "rmdir ", "del ", "shutdown", "reboot", "mkfs", "dd ", "chmod 777", ">", ">>", "|", "&"}
    safe_candidates: list[dict[str, str]] = []
    for item in responses:
        lower = item["response"].lower()
        if not any(marker in lower for marker in unsafe_markers):
            safe_candidates.append(item)

    chosen = min(safe_candidates or responses, key=lambda r: len(r["response"]))
    print("[CONSENSUS SELECTED]")
    print(json.dumps({"model": chosen["model"], "reason": "failsafe-safest-response"}, ensure_ascii=True))
    return chosen["response"]


def multi_llm(prompt: str) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must be a non-empty string.")
    mode = get_thiramai_mode()
    if mode == "dry-run":
        logger.info("[MODE] dry-run | multi_llm stub")
        return dry_run_llm_response(prompt)
    if mode == "simulation":
        logger.info("[MODE] simulation | multi_llm mock")
        return mock_llm(prompt)
    responses = _collect_multi_responses(prompt)
    text = consensus(responses, original_prompt=prompt)
    conf, _dis = cross_model_agreement_score(responses)
    logger.info("multi_llm consensus confidence=%s models=%s", conf, [r["model"] for r in responses])
    return text


def call_llm_structured(model_cls: type[_StructuredModel], prompt: str) -> _StructuredModel:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must be a non-empty string.")
    raw = multi_llm(prompt)
    try:
        return model_cls.model_validate_json(raw)
    except ValidationError as exc:
        repair_prompt = (
            "Your previous output failed strict schema validation.\n"
            f"Schema model: {model_cls.__name__}\n"
            "Return ONLY valid JSON that matches the schema exactly.\n"
            f"Validation errors: {exc}\n"
            f"Previous output:\n{raw}\n"
        )
        repaired = multi_llm(repair_prompt)
        try:
            return model_cls.model_validate_json(repaired)
        except ValidationError as repair_exc:
            raise RuntimeError(
                f"Structured LLM response validation failed for {model_cls.__name__} after repair attempt: {repair_exc}"
            ) from repair_exc


def call_llm_json(prompt: str) -> dict[str, Any]:
    raw = multi_llm(prompt)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = raw[start : end + 1]
            return json.loads(candidate)
    raise RuntimeError(f"LLM did not return valid JSON: {raw}")
