from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from thiramai.core.telemetry import SessionTelemetry


DEFAULT_AUDIT_FILE = Path(__file__).resolve().parent.parent.parent / "logs" / "audit_trail.jsonl"
DEFAULT_HITL_DIR = Path(__file__).resolve().parent.parent.parent / "runtime" / "hitl"
DEFAULT_REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "reports"
APPROVE_FLAG_NAME = "approve.flag"
REJECT_FLAG_NAME = "reject.flag"


class RuntimeDashboard:
    def __init__(self, telemetry: SessionTelemetry, audit_file: Path | None = None) -> None:
        self.telemetry = telemetry
        self.audit_file = audit_file or DEFAULT_AUDIT_FILE

    def render(self) -> Layout:
        root = Layout()
        root.split_column(
            Layout(name="top", size=7),
            Layout(name="middle", size=7),
            Layout(name="bottom"),
        )
        root["top"].split_row(Layout(name="status"), Layout(name="security"))
        root["middle"].split_row(Layout(name="metrics"), Layout(name="live_log"))

        root["status"].update(self._status_panel())
        root["security"].update(self._security_panel())
        root["metrics"].update(self._metrics_panel())
        root["live_log"].update(self._live_log_panel())
        root["bottom"].update(Panel(Text("THIRAMAI Dashboard (metadata only; sensitive output redacted)", style="cyan")))
        return root

    def _status_panel(self) -> Panel:
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="right", style="bold")
        table.add_column()
        table.add_row("Goal", self._safe_text(self.telemetry.current_goal))
        table.add_row("Cycle ID", str(self.telemetry.current_cycle_id or "-"))
        table.add_row("Current Task", self._safe_text(self.telemetry.current_task))
        return Panel(table, title="Status Panel", border_style="green")

    def _security_panel(self) -> Panel:
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="right", style="bold")
        table.add_column()
        table.add_row("Total Blocks", str(self.telemetry.total_policy_blocks))
        table.add_row("Human Interventions", str(self.telemetry.total_human_interventions))
        table.add_row("Last Blocked Reason", self._safe_text(self.telemetry.last_blocked_reason))
        return Panel(table, title="Security Panel", border_style="red")

    def _metrics_panel(self) -> Panel:
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="right", style="bold")
        table.add_column()
        table.add_row("Success Rate", f"{self.telemetry.success_rate():.2f}%")
        table.add_row("Safety Score", f"{self.telemetry.safety_score():.2f}%")
        table.add_row("Avg Confidence", f"{self.telemetry.avg_llm_confidence:.3f}")
        table.add_row("Last Cycle Time", f"{self.telemetry.last_cycle_time_sec:.2f}s")
        table.add_row("Avg Cycle Time", f"{self.telemetry.avg_cycle_time_sec:.2f}s")
        return Panel(table, title="Metrics Panel", border_style="blue")

    def _live_log_panel(self) -> Panel:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Timestamp", overflow="fold")
        table.add_column("Task")
        table.add_column("Status")
        table.add_column("Policy")
        table.add_column("Reason", overflow="fold")
        for row in self._tail_audit_entries(limit=5):
            ts = str(row.get("timestamp", ""))[-19:]
            task_id = str(row.get("task_id", ""))
            status = str(row.get("execution_status", ""))
            decision = row.get("policy_decision", {})
            if not isinstance(decision, dict):
                decision = {}
            policy_id = str(decision.get("policy_id", ""))
            reason = str(decision.get("reason", ""))
            table.add_row(
                self._safe_text(ts),
                self._safe_text(task_id),
                self._safe_text(status),
                self._safe_text(policy_id),
                self._safe_text(reason),
            )
        return Panel(table, title="Live Log (Latest 5)", border_style="yellow")

    def _tail_audit_entries(self, *, limit: int) -> list[dict[str, Any]]:
        if not self.audit_file.exists():
            return []
        try:
            lines = self.audit_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for raw in lines[-max(1, int(limit)) :]:
            t = raw.strip()
            if not t:
                continue
            try:
                parsed = json.loads(t)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def _safe_text(self, value: str) -> str:
        txt = str(value or "")
        lower = txt.lower()
        sensitive_keys = ("password", "passwd", "secret", "token", "api_key", "apikey", "private_key", "bearer")
        if any(k in lower for k in sensitive_keys):
            return "[REDACTED]"
        return txt[:220]


def run_streamlit_dashboard(
    *,
    audit_file: Path | None = None,
    hitl_dir: Path | None = None,
    report_dir: Path | None = None,
) -> None:
    """
    Streamlit dashboard with:
    - Current agent chain and task metadata
    - Live audit log rows
    - Risk meter
    - HITL approve/reject controls
    - DPR export (Markdown + optional PDF)
    """
    try:
        import streamlit as st
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Streamlit is required for web dashboard. Install with: pip install streamlit"
        ) from exc

    audit_path = audit_file or DEFAULT_AUDIT_FILE
    hitl_path = hitl_dir or DEFAULT_HITL_DIR
    reports_path = report_dir or DEFAULT_REPORT_DIR
    hitl_path.mkdir(parents=True, exist_ok=True)
    reports_path.mkdir(parents=True, exist_ok=True)

    st.set_page_config(page_title="THIRAMAI HITL Dashboard", layout="wide")
    st.title("THIRAMAI Dynamic Telemetry + HITL")

    rows = _tail_jsonl(audit_path, limit=50)
    latest = rows[-1] if rows else {}
    risk_level = str(latest.get("risk_level", "low")).lower()

    col1, col2, col3 = st.columns([2, 2, 1.5])
    with col1:
        st.subheader("Agent Chain")
        st.markdown("`Researcher -> Coder -> Reviewer`")
        st.caption("Chain is monitored by central security controls.")
    with col2:
        st.subheader("Current Task")
        st.write(f"Task ID: `{latest.get('task_id', '-')}`")
        st.write(f"Status: `{latest.get('execution_status', '-')}`")
        policy = latest.get("policy_decision", {})
        if isinstance(policy, dict):
            st.write(f"Policy: `{policy.get('policy_id', '-')}`")
    with col3:
        st.subheader("Risk Meter")
        risk_map = {"low": 0.2, "medium": 0.6, "high": 1.0}
        meter = risk_map.get(risk_level, 0.2)
        st.progress(meter, text=f"Risk: {risk_level.upper()}")
        if risk_level == "high":
            st.error("High-risk command requires human approval.")
        elif risk_level == "medium":
            st.warning("Medium risk. Monitor execution.")
        else:
            st.success("Low risk.")

    st.subheader("Live Logs (audit_trail.jsonl)")
    st.dataframe(rows[-20:] if rows else [], use_container_width=True)

    st.subheader("HITL Controls")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Approve High-Risk Command", type="primary", use_container_width=True):
            _write_flag(hitl_path / APPROVE_FLAG_NAME, "approved_from_dashboard")
            _clear_file(hitl_path / REJECT_FLAG_NAME)
            st.success("Approval flag written.")
    with c2:
        if st.button("Reject High-Risk Command", use_container_width=True):
            _write_flag(hitl_path / REJECT_FLAG_NAME, "rejected_from_dashboard")
            _clear_file(hitl_path / APPROVE_FLAG_NAME)
            st.warning("Rejection flag written.")
    with c3:
        if st.button("Clear HITL Flags", use_container_width=True):
            _clear_file(hitl_path / REJECT_FLAG_NAME)
            _clear_file(hitl_path / APPROVE_FLAG_NAME)
            st.info("HITL flags cleared.")

    st.subheader("Auto-Report Generation")
    default_report = _build_project_report(rows)
    report_text = st.text_area("Project Report (DPR) Content", value=default_report, height=260)
    as_pdf = st.checkbox("Also export PDF (requires reportlab)", value=False)
    if st.button("Export Project Report", use_container_width=True):
        outputs = export_project_report(report_text, report_dir=reports_path, export_pdf=as_pdf)
        st.success(f"Exported: {', '.join(str(x) for x in outputs)}")

    st.caption("Tip: run with `streamlit run thiramai/ui/dashboard.py`")


def export_project_report(report_markdown: str, *, report_dir: Path, export_pdf: bool = False) -> list[Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _now_compact()
    md_path = report_dir / f"project_report_{timestamp}.md"
    md_path.write_text(report_markdown, encoding="utf-8")
    outputs = [md_path]
    if export_pdf:
        pdf_path = report_dir / f"project_report_{timestamp}.pdf"
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            c = canvas.Canvas(str(pdf_path), pagesize=A4)
            width, height = A4
            y = height - 40
            for line in report_markdown.splitlines():
                c.drawString(40, y, line[:120])
                y -= 14
                if y <= 40:
                    c.showPage()
                    y = height - 40
            c.save()
            outputs.append(pdf_path)
        except Exception:
            # Keep markdown export successful even if PDF dependency is absent.
            pass
    return outputs


def _tail_jsonl(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for raw in lines[-max(1, int(limit)) :]:
        t = raw.strip()
        if not t:
            continue
        try:
            parsed = json.loads(t)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _build_project_report(rows: list[dict[str, Any]]) -> str:
    total = len(rows)
    blocked = 0
    high_risk = 0
    for r in rows:
        if str(r.get("execution_status", "")).lower() == "blocked":
            blocked += 1
        if str(r.get("risk_level", "")).lower() == "high":
            high_risk += 1
    return (
        "# THIRAMAI Project Report (DPR)\n\n"
        "## Agent Chain\n"
        "- Researcher -> Coder -> Reviewer\n\n"
        "## Security Summary\n"
        f"- Total Logged Tasks: {total}\n"
        f"- Blocked Tasks: {blocked}\n"
        f"- High Risk Tasks: {high_risk}\n\n"
        "## Notes\n"
        "- Generated from latest audit trail telemetry.\n"
        "- Review blocked commands and HITL approvals before production release.\n"
    )


def _write_flag(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _clear_file(path: Path) -> None:
    if path.exists():
        path.unlink()


def _now_compact() -> str:
    from datetime import datetime

    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


if __name__ == "__main__":
    run_streamlit_dashboard()
