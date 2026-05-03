"""
Register domain HTTP routers on the FastAPI app.

Called from app.py after core setup; main.py may call again safely (idempotent via app.state).

**Phase 8 (scale):** horizontal rate limits and request tracing are **not** configured here — they live in
``app.py`` middleware: ``CorrelationIdMiddleware`` (``X-Correlation-ID`` + structured log context),
``RateLimitMiddleware`` (path buckets + optional Redis global limit via ``core.distributed_rate_limit``).
"""

from __future__ import annotations

from fastapi import FastAPI

_STATE_FLAG = "_thiramai_domain_routers_attached"


def attach_domain_routers(app: FastAPI) -> None:
    """Mount inventory, factory, billing, empire, analytics, and AI chat routers (no duplicate registration)."""
    if getattr(app.state, _STATE_FLAG, False):
        return
    setattr(app.state, _STATE_FLAG, True)

    from core.dangerous_routes import production_blocks_dangerous_routes

    _prod_danger_off = production_blocks_dangerous_routes()

    from api.routes.health import router as health_router
    from api.routes.monitoring import router as monitoring_router
    from api.routes.jarvis_bridge import router as jarvis_bridge_router
    from api.routes.execute import router as execute_router
    from api.routes.brain_execute import router as brain_execute_router

    app.include_router(health_router)
    app.include_router(monitoring_router)
    if not _prod_danger_off:
        app.include_router(jarvis_bridge_router)
    app.include_router(execute_router)
    app.include_router(brain_execute_router)

    from api.routes.kernel_microkernel import router as kernel_microkernel_router

    if not _prod_danger_off:
        app.include_router(kernel_microkernel_router)

    from api.routes.sovereign import router as sovereign_router

    app.include_router(sovereign_router)

    from api.routes.ai_goal import router as ai_goal_router
    from api.routes.ai_goal import router_v1_ai as ai_goal_v1_router
    from api.routes.ai_ltm import router as ai_ltm_router
    from api.routes.ai_local import router as ai_local_router
    from api.routes.metrics_autonomy import router as metrics_autonomy_router

    app.include_router(ai_goal_router)
    app.include_router(ai_goal_v1_router)
    app.include_router(metrics_autonomy_router)
    app.include_router(ai_ltm_router)
    app.include_router(ai_local_router)

    from api.routes.tenancy import router as tenancy_router
    from api.routes.security_status import router as security_status_router

    app.include_router(tenancy_router)
    app.include_router(security_status_router)

    from api.routes.org import router as org_router
    from api.routes.product_growth import router as product_growth_router

    app.include_router(org_router)
    app.include_router(product_growth_router)

    from api.routes.ai_chat import router as ai_chat_router
    from api.routes.business_module import router as business_module_router
    from api.routes.analytics import router as analytics_router
    from api.routes.audit import router as audit_router
    from api.routes.billing import router as billing_router
    from api.routes.control_plane import router as control_plane_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.dashboard_ws import router as dashboard_ws_router
    from api.routes.stock_ws import router as stock_ws_router
    from api.routes.empire import router as empire_router
    from api.routes.factory import router as factory_router
    from api.routes.inventory import router as inventory_router
    from api.routes.production import router as production_phase2_router
    from api.routes.business_depth import router as business_depth_router
    from api.routes.compliance_hub import router as compliance_hub_router
    from api.routes.life_os import router as life_os_router
    from api.routes.executive_os import router_executive, router_research
    from api.routes.personal import router as personal_router
    from api.routes.personal_command_center import router as personal_command_center_router
    from api.routes.stock_assistant import router as stock_assistant_router
    from api.routes.website_builder import router as website_builder_router
    from api.routes.ai_erp import router as ai_erp_router
    from api.routes.saas_admin import router as saas_admin_router
    from api.routes.autonomy import router as autonomy_router
    from api.routes.integrations import router as integrations_router
    from api.routes.push_notifications import router as push_notifications_router
    from api.routes.automation import router as automation_router
    from api.routes.opportunities import router as opportunities_router
    from api.routes.learning import router as learning_router
    from api.routes.governance import router as governance_router
    from api.routes.money_loop import router as money_loop_router
    from api.routes.system_overview import router as system_overview_router
    from api.routes.predict import router as predict_router
    from api.routes.feedback import router as feedback_router
    from api.routes.experimentation import router as experimentation_router
    from api.routes.market_timing import router as market_timing_router
    from api.routes.autonomy_control import router as autonomy_control_router
    from api.routes.goal_engine import router as goal_engine_router
    from api.routes.research_loop import router as research_loop_router
    from api.routes.invention_loop import router as invention_loop_router
    from api.routes.scientific_validation import router as scientific_validation_router
    from api.routes.proactive_autonomy import router as proactive_autonomy_router
    from api.routes.real_world_autonomy import router as real_world_autonomy_router
    from api.routes.full_autonomous_operator import router as full_autonomous_operator_router
    from api.routes.tool_builder import router as tool_builder_router
    from api.routes.long_term_memory import router as long_term_memory_router
    from api.routes.goal_prioritization import router as goal_prioritization_router
    from api.routes.self_expansion import router as self_expansion_router
    from api.routes.continuous_thinking import router as continuous_thinking_router
    from api.routes.continuity import router as continuity_router
    from api.routes.world_model import router as world_model_router
    from api.routes.simulation import router as simulation_router
    from api.routes.strategy_generator import router as strategy_generator_router
    from api.routes.multi_org_control import router as multi_org_control_router
    from api.routes.revenue_engine import router as revenue_engine_router
    from api.routes.autonomous_operations import router as autonomous_operations_router
    from api.routes.system_bootstrap import router as system_bootstrap_router
    from api.routes.research_projects import router as research_projects_router
    from api.routes.action_execution import router as action_execution_router
    from api.routes.autonomy_safety import router as autonomy_safety_router
    from api.routes.domain_dominion import router as domain_dominion_router
    from api.routes.decision_intelligence import router as decision_intelligence_router
    from api.routes.negotiation_intelligence import router as negotiation_intelligence_router

    app.include_router(personal_router)
    app.include_router(personal_command_center_router)
    app.include_router(stock_assistant_router)
    if not _prod_danger_off:
        app.include_router(website_builder_router)
    app.include_router(ai_erp_router)
    app.include_router(router_executive)
    app.include_router(router_research)
    app.include_router(compliance_hub_router)
    app.include_router(business_depth_router)
    app.include_router(business_module_router)
    app.include_router(inventory_router)
    app.include_router(production_phase2_router)
    app.include_router(factory_router)
    app.include_router(billing_router)
    app.include_router(empire_router)
    app.include_router(analytics_router)
    app.include_router(audit_router)
    app.include_router(control_plane_router)
    app.include_router(saas_admin_router)
    app.include_router(autonomy_router)
    app.include_router(dashboard_router)
    app.include_router(dashboard_ws_router, prefix="/ws")
    app.include_router(stock_ws_router, prefix="/ws")
    app.include_router(integrations_router)
    app.include_router(push_notifications_router)
    app.include_router(automation_router)
    app.include_router(opportunities_router)
    app.include_router(learning_router)
    app.include_router(governance_router)
    app.include_router(money_loop_router)
    app.include_router(system_overview_router)
    app.include_router(predict_router)
    app.include_router(feedback_router)
    app.include_router(experimentation_router)
    app.include_router(market_timing_router)
    app.include_router(autonomy_control_router)
    app.include_router(goal_engine_router)
    app.include_router(research_loop_router)
    app.include_router(invention_loop_router)
    app.include_router(scientific_validation_router)
    app.include_router(proactive_autonomy_router)
    app.include_router(real_world_autonomy_router)
    app.include_router(full_autonomous_operator_router)
    if not _prod_danger_off:
        app.include_router(tool_builder_router)
    app.include_router(long_term_memory_router)
    app.include_router(goal_prioritization_router)
    app.include_router(self_expansion_router)
    app.include_router(continuous_thinking_router)
    app.include_router(continuity_router)
    app.include_router(world_model_router)
    app.include_router(simulation_router)
    app.include_router(strategy_generator_router)
    app.include_router(multi_org_control_router)
    app.include_router(revenue_engine_router)
    app.include_router(autonomous_operations_router)
    app.include_router(system_bootstrap_router)
    app.include_router(research_projects_router)
    app.include_router(action_execution_router)
    app.include_router(autonomy_safety_router)
    app.include_router(domain_dominion_router)
    app.include_router(decision_intelligence_router)
    app.include_router(negotiation_intelligence_router)
    app.include_router(ai_chat_router)
    app.include_router(life_os_router)

    from api.routes.os_central_brain import router as os_central_brain_router
    from api.routes.code_agent import router as code_agent_router
    from api.routes.code_agent import websites_router as code_agent_websites_router

    if not _prod_danger_off:
        app.include_router(code_agent_router, prefix="/api/agent")
        app.include_router(code_agent_websites_router, prefix="/api")
    app.include_router(os_central_brain_router)
