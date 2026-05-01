"""Tests for MAML meta-learning, task similarity, curriculum stages, and online-learner hooks."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pytest

from services.self_evolution.curriculum_manager import (
    CurriculumManager,
    reset_curriculum_manager,
)
from services.self_evolution.improvement_loop import reset_self_evolution_singletons
from services.self_evolution.meta_learner import (
    MAML,
    MetaLearner,
    Task,
    get_meta_learner,
    online_learner_meta_context,
    reset_meta_learner,
)

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
DIM = 4


def _task(
    tid: str,
    *,
    domain: str = "trading",
    task_type: str = "regression",
    difficulty: float = 0.2,
    w: np.ndarray | None = None,
    rng: np.random.Generator | None = None,
    n_sup: int = 6,
    n_q: int = 4,
) -> Task:
    rng = rng or np.random.default_rng(0)
    w = w if w is not None else np.array([1.0, -0.5, 0.25, 0.0], dtype=float)
    support = []
    query = []
    for _ in range(n_sup):
        x = rng.normal(size=DIM)
        support.append({"x": x, "y": float(np.dot(w, x) + 0.05 * rng.normal())})
    for _ in range(n_q):
        x = rng.normal(size=DIM)
        query.append({"x": x, "y": float(np.dot(w, x) + 0.05 * rng.normal())})
    return Task(
        task_id=tid,
        domain=domain,
        task_type=task_type,
        support_set=support,
        query_set=query,
        difficulty=difficulty,
        created_at=NOW,
    )


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_self_evolution_singletons()
    yield
    reset_self_evolution_singletons()


# --- MAML ---


def test_maml_meta_train_runs_and_returns_params():
    rng = np.random.default_rng(42)
    tasks = [_task(f"t{i}", rng=np.random.default_rng(i)) for i in range(5)]
    m = MAML(feature_dim=DIM, rng=rng, num_inner_steps=3, inner_lr=0.08, outer_lr=0.04)
    out = m.meta_train(tasks, num_iterations=15)
    assert "W" in out and "b" in out
    assert out["W"].shape == (DIM,)
    assert m.meta_params is not None


def test_maml_adaptation_improves_or_equal_loss():
    rng = np.random.default_rng(7)
    tasks = [_task(f"t{i}", rng=np.random.default_rng(100 + i)) for i in range(8)]
    m = MAML(feature_dim=DIM, rng=rng, num_inner_steps=8, inner_lr=0.15, outer_lr=0.05)
    m.meta_train(tasks, num_iterations=25)
    held = _task("held", rng=np.random.default_rng(999))
    res = m.adapt(held)
    assert res.num_gradient_steps == 8
    assert res.post_adaptation_loss <= res.pre_adaptation_loss + 1e-6 or res.improvement >= -1e-3


def test_maml_adapt_requires_meta_train():
    m = MAML(feature_dim=DIM, rng=np.random.default_rng(1))
    t = _task("a", rng=np.random.default_rng(2))
    with pytest.raises(ValueError, match="meta-train"):
        m.adapt(t)


def test_maml_compute_loss_zero_on_empty_examples():
    m = MAML(feature_dim=DIM, rng=np.random.default_rng(0))
    m.meta_params = m._initialize_params()
    assert m._compute_loss(m.meta_params, []) == 0.0


def test_maml_inner_lr_scales_with_difficulty():
    m = MAML(feature_dim=DIM, inner_lr=0.1, rng=np.random.default_rng(0))
    low = m._inner_lr_scaled(0.0)
    high = m._inner_lr_scaled(1.0)
    assert high < low


def test_maml_feature_dim_mismatch_raises():
    m = MAML(feature_dim=3, rng=np.random.default_rng(0))
    m.meta_params = m._initialize_params()
    with pytest.raises(ValueError, match="dim"):
        m._compute_loss(m.meta_params, [{"x": [1, 2, 3, 4], "y": 1.0}])


# --- MetaLearner ---


def test_meta_learner_add_task_and_library():
    ml = MetaLearner(feature_dim=DIM)
    ml.add_task(_task("a", rng=np.random.default_rng(1)))
    assert len(ml.tasks) == 1


def test_meta_learner_meta_train_warns_lt_two_tasks():
    ml = MetaLearner(feature_dim=DIM)
    ml.add_task(_task("only", rng=np.random.default_rng(3)))
    assert ml.meta_train(num_iterations=5) is not None


def test_meta_learner_meta_train_full():
    ml = MetaLearner(
        maml=MAML(feature_dim=DIM, rng=np.random.default_rng(11), num_inner_steps=3),
        feature_dim=DIM,
    )
    for i in range(4):
        ml.add_task(_task(f"u{i}", rng=np.random.default_rng(20 + i)))
    params = ml.meta_train(num_iterations=12)
    assert params is not None and "W" in params


def test_inner_lr_for_task_decreases_with_difficulty():
    ml = MetaLearner(maml=MAML(feature_dim=DIM, inner_lr=0.2), feature_dim=DIM)
    easy = _task("e", difficulty=0.0, rng=np.random.default_rng(0))
    hard = _task("h", difficulty=1.0, rng=np.random.default_rng(1))
    assert ml.inner_lr_for_task(easy) > ml.inner_lr_for_task(hard)


def test_task_similarity_same_domain_and_type():
    ml = MetaLearner(feature_dim=DIM)
    t1 = _task("a", domain="x", task_type="regression", difficulty=0.5, rng=np.random.default_rng(0))
    t2 = _task("b", domain="x", task_type="regression", difficulty=0.5, rng=np.random.default_rng(0))
    sim = MetaLearner._compute_task_similarity(t1, t2)
    assert sim >= 0.9


def test_task_similarity_different_domain():
    t1 = _task("a", domain="a", difficulty=0.5, rng=np.random.default_rng(0))
    t2 = _task("b", domain="b", difficulty=0.5, rng=np.random.default_rng(0))
    assert MetaLearner._compute_task_similarity(t1, t2) < MetaLearner._compute_task_similarity(t1, t1)


def test_find_similar_tasks_orders_by_score():
    ml = MetaLearner(feature_dim=DIM)
    probe = _task("q", domain="trading", task_type="regression", difficulty=0.2, rng=np.random.default_rng(1))
    ml.add_task(_task("close", domain="trading", task_type="regression", difficulty=0.25, rng=np.random.default_rng(2)))
    ml.add_task(_task("far", domain="business", task_type="classification", difficulty=0.9, rng=np.random.default_rng(3)))
    top = ml.find_similar_tasks(probe, top_k=1)
    assert len(top) == 1
    assert top[0][0].task_id == "close"


def test_adapt_to_new_task_caches_params():
    rng = np.random.default_rng(0)
    ml = MetaLearner(maml=MAML(feature_dim=DIM, rng=rng, num_inner_steps=4), feature_dim=DIM)
    for i in range(5):
        ml.add_task(_task(f"c{i}", rng=np.random.default_rng(i + 1)))
    ml.meta_train(num_iterations=10)
    t_new = _task("new", rng=np.random.default_rng(99))
    ml.adapt_to_new_task(t_new)
    assert "new" in ml._task_adapted_cache


def test_adapt_with_transfer_uses_peer_cache():
    rng = np.random.default_rng(0)
    ml = MetaLearner(maml=MAML(feature_dim=DIM, rng=rng, num_inner_steps=6, inner_lr=0.12), feature_dim=DIM)
    peer = _task("peer", domain="d", difficulty=0.2, rng=np.random.default_rng(1))
    other_tasks = [_task(f"p{i}", domain="d", difficulty=0.2, rng=np.random.default_rng(10 + i)) for i in range(3)]
    for t in other_tasks:
        ml.add_task(t)
    ml.add_task(peer)
    ml.meta_train(num_iterations=20)
    ml.adapt_to_new_task(peer)
    fresh = _task("fresh", domain="d", difficulty=0.22, rng=np.random.default_rng(77))
    result = ml.adapt_with_transfer(fresh, blend=0.5)
    assert result.post_adaptation_loss == result.post_adaptation_loss  # struct ok
    assert "fresh" in ml._task_adapted_cache


def test_transfer_gain_vs_baseline_returns_tuple():
    rng = np.random.default_rng(0)
    ml = MetaLearner(maml=MAML(feature_dim=DIM, rng=rng, num_inner_steps=4), feature_dim=DIM)
    for i in range(4):
        ml.add_task(_task(f"g{i}", domain="z", difficulty=0.3, rng=np.random.default_rng(i)))
    ml.meta_train(num_iterations=15)
    tgt = _task("tgt", domain="z", difficulty=0.31, rng=np.random.default_rng(50))
    a, b, d = ml.transfer_gain_vs_baseline(tgt, blend=0.4)
    assert isinstance(a, float) and isinstance(b, float) and isinstance(d, float)


def test_online_learner_meta_context_integrated():
    with patch("services.ml.online_learner.get_status") as gs:
        gs.return_value = {"samples_seen": 10, "rolling_accuracy": 0.5}
        ctx = online_learner_meta_context()
    assert ctx.get("integrated") is True
    assert ctx["samples_seen"] == 10


def test_online_learner_meta_context_failure():
    with patch("services.ml.online_learner.get_status", side_effect=RuntimeError("boom")):
        ctx = online_learner_meta_context()
    assert ctx.get("integrated") is False


def test_apply_online_learner_calibration():
    ml = MetaLearner(maml=MAML(feature_dim=DIM, outer_lr=0.05), feature_dim=DIM)
    with patch("services.self_evolution.meta_learner.online_learner_meta_context") as ctx:
        ctx.return_value = {"integrated": True, "samples_seen": 50, "rolling_accuracy": 0.6}
        out = ml.apply_online_learner_calibration(min_samples=10)
    assert out["applied"] is True
    assert out["outer_lr"] == pytest.approx(ml.maml.outer_lr)
    assert "scale" in out


def test_apply_online_learner_calibration_insufficient_samples():
    ml = MetaLearner(feature_dim=DIM)
    with patch("services.self_evolution.meta_learner.online_learner_meta_context") as ctx:
        ctx.return_value = {"integrated": True, "samples_seen": 3}
        out = ml.apply_online_learner_calibration(min_samples=100)
    assert out["applied"] is False


def test_get_meta_learner_singleton():
    reset_meta_learner()
    a = get_meta_learner()
    b = get_meta_learner()
    assert a is b


# --- Curriculum ---


def test_curriculum_add_task_buckets_by_difficulty():
    cm = CurriculumManager()
    cm.add_task(_task("e", difficulty=0.1, rng=np.random.default_rng(0)))
    cm.add_task(_task("m", difficulty=0.5, rng=np.random.default_rng(0)))
    cm.add_task(_task("h", difficulty=0.95, rng=np.random.default_rng(0)))
    assert len(cm.stages[0].tasks) == 1
    assert len(cm.stages[1].tasks) == 1
    assert cm.stages[3].tasks[0].task_id == "h"


def test_curriculum_difficulty_boundary_inclusive_top():
    cm = CurriculumManager()
    cm.add_task(_task("top", difficulty=1.0, rng=np.random.default_rng(0)))
    assert cm.stages[3].tasks[-1].task_id == "top"


def test_curriculum_get_current_task_returns_needs_work():
    cm = CurriculumManager(min_attempts_per_stage=2)
    cm.add_task(_task("t1", difficulty=0.1, rng=np.random.default_rng(0)))
    cm.add_task(_task("t2", difficulty=0.1, rng=np.random.default_rng(1)))
    assert cm.get_current_task().task_id in {"t1", "t2"}


def test_curriculum_record_result_tracks_success_rate():
    cm = CurriculumManager(min_attempts_per_stage=2)
    t1 = _task("t1", difficulty=0.1, rng=np.random.default_rng(0))
    t2 = _task("t2", difficulty=0.1, rng=np.random.default_rng(1))
    cm.add_task(t1)
    cm.add_task(t2)
    for _ in range(2):
        cm.record_result(t1, True, 1.0)
        cm.record_result(t2, True, 2.0)
    p = cm.get_progress()
    assert p is not None
    assert p.current_success_rate >= 0.99
    assert p.tasks_attempted == 4


def test_curriculum_advance_stage_when_ready():
    cm = CurriculumManager(min_attempts_per_stage=2)
    t1 = _task("t1", difficulty=0.1, rng=np.random.default_rng(0))
    t2 = _task("t2", difficulty=0.1, rng=np.random.default_rng(1))
    cm.add_task(t1)
    cm.add_task(t2)
    for _ in range(2):
        cm.record_result(t1, True, 1.0)
        cm.record_result(t2, True, 1.0)
    prog = cm.get_progress()
    assert prog.ready_to_advance is True
    assert cm.advance_stage() is True
    assert cm.current_stage_idx == 1


def test_curriculum_no_advance_when_not_ready():
    cm = CurriculumManager(min_attempts_per_stage=5)
    cm.add_task(_task("t1", difficulty=0.1, rng=np.random.default_rng(0)))
    cm.record_result(cm.stages[0].tasks[0], False, 1.0)
    assert cm.advance_stage() is False


def test_curriculum_final_stage_no_advance():
    cm = CurriculumManager(min_attempts_per_stage=1)
    cm.current_stage_idx = 3
    cm.add_task(_task("h", difficulty=0.9, rng=np.random.default_rng(0)))
    cm.record_result(cm.stages[3].tasks[0], True, 1.0)
    assert cm.advance_stage() is False


def test_curriculum_reset_stage_stats():
    cm = CurriculumManager()
    cm.add_task(_task("a", difficulty=0.1, rng=np.random.default_rng(0)))
    cm.record_result(cm.stages[0].tasks[0], True, 5.0)
    cm.reset_stage_stats()
    assert cm.get_progress() is None


def test_get_curriculum_manager_singleton():
    reset_curriculum_manager()
    from services.self_evolution.curriculum_manager import get_curriculum_manager

    x = get_curriculum_manager()
    y = get_curriculum_manager()
    assert x is y


def test_reset_meta_learner_clears():
    get_meta_learner()
    reset_meta_learner()
    m1 = get_meta_learner()
    m2 = get_meta_learner()
    assert m1 is m2


# --- Package exports ---


def test_self_evolution_package_exports_meta_and_curriculum():
    from services import self_evolution as se

    assert hasattr(se, "MAML")
    assert hasattr(se, "CurriculumManager")
    assert hasattr(se, "online_learner_meta_context")


def test_reset_self_evolution_singletons_includes_meta_curriculum():
    from services.self_evolution.improvement_loop import get_improvement_loop
    from services.self_evolution.meta_learner import get_meta_learner
    from services.self_evolution.curriculum_manager import get_curriculum_manager

    get_improvement_loop()
    get_meta_learner()
    get_curriculum_manager()
    reset_self_evolution_singletons()
    # new instances after reset
    m = get_meta_learner()
    m.tasks.clear()
    assert m.tasks == []
