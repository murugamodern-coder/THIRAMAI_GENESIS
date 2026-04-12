import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  createPersonalExpense,
  fetchLifeDashboard,
  fetchPendingDecisions,
  fetchPersonalMorningBrief,
  postLifeHabit,
  postLifeHabitCheckIn,
  postLifeHealth,
  postLifeMission,
} from "../../api/commandCenterApi.js";
import { safeAsync } from "../../lib/safeAsync.js";

const FINANCE_QUICK_CATEGORIES = [
  { value: "loans", label: "Loans" },
  { value: "vehicle", label: "Vehicle" },
  { value: "digital_bills", label: "Digital bills" },
  { value: "personal", label: "Personal" },
  { value: "worker_payment", label: "Worker payment" },
];

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    }).format(new Date(iso + "T12:00:00"));
  } catch {
    return iso;
  }
}

function deadlineFromDateInput(dateStr) {
  if (!dateStr || !String(dateStr).trim()) return null;
  const d = new Date(`${dateStr}T12:00:00`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

const EMPTY_LIFE_DASH = { habits: [], habits_pending_today: 0, health_today: [], missions_open: [], legacy_health_log: null };

export default function PersonalHomePage() {
  const [vaultPass, setVaultPass] = useState("");
  const vaultRef = useRef("");
  const [brief, setBrief] = useState(null);
  const [dashboard, setDashboard] = useState(EMPTY_LIFE_DASH);
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [formMsg, setFormMsg] = useState(null);

  const [habitName, setHabitName] = useState("");
  const [habitFreq, setHabitFreq] = useState("daily");
  const [habitCat, setHabitCat] = useState("health");
  const [habitBusy, setHabitBusy] = useState(false);

  const [hSleep, setHSleep] = useState("");
  const [hWater, setHWater] = useState("");
  const [hStress, setHStress] = useState("5");
  const [hWeight, setHWeight] = useState("");
  const [hSys, setHSys] = useState("");
  const [hDia, setHDia] = useState("");
  const [healthBusy, setHealthBusy] = useState(false);

  const [mTitle, setMTitle] = useState("");
  const [mPri, setMPri] = useState("P2");
  const [mDue, setMDue] = useState("");
  const [missionBusy, setMissionBusy] = useState(false);

  const [feAmount, setFeAmount] = useState("");
  const [feCat, setFeCat] = useState("personal");
  const [feNote, setFeNote] = useState("");
  const [feBusy, setFeBusy] = useState(false);

  useEffect(() => {
    vaultRef.current = vaultPass;
  }, [vaultPass]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const v = vaultRef.current?.trim() || undefined;
    try {
      const [b, d, dash] = await Promise.all([
        fetchPersonalMorningBrief(v),
        fetchPendingDecisions(12).catch(() => ({ items: [] })),
        fetchLifeDashboard().catch(() => ({ ...EMPTY_LIFE_DASH })),
      ]);
      setBrief(b);
      setDecisions(Array.isArray(d?.items) ? d.items : []);
      setDashboard(dash && typeof dash === "object" ? dash : { ...EMPTY_LIFE_DASH });
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Could not load morning brief.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    safeAsync(load, { toast: false })();
  }, [load]);

  const habits = dashboard?.habits ?? [];
  const missionsOpen = dashboard?.missions_open ?? [];
  const legacy = dashboard?.legacy_health_log;
  const metricsToday = dashboard?.health_today ?? [];
  const hasHealthToday =
    (legacy &&
      (legacy.sleep_hours != null ||
        legacy.water_glasses != null ||
        legacy.stress_1_10 != null ||
        legacy.weight_kg != null ||
        legacy.bp_systolic != null)) ||
    metricsToday.length > 0;

  const onSaveHabit = async (e) => {
    e.preventDefault();
    setFormMsg(null);
    const name = habitName.trim();
    if (!name) {
      setFormMsg("Enter a habit name.");
      return;
    }
    setHabitBusy(true);
    try {
      const out = await postLifeHabit({
        title: name,
        goal_frequency: habitFreq,
        category: habitCat || null,
      });
      const hid = out?.habit_id;
      if (hid) {
        await postLifeHabitCheckIn({ habit_id: hid, status: "completed" }).catch(() => null);
      }
      setHabitName("");
      setFormMsg("Habit saved and marked done for today.");
      await load();
    } catch (err) {
      setFormMsg(err?.response?.data?.detail || err?.message || "Could not save habit.");
    } finally {
      setHabitBusy(false);
    }
  };

  const onSaveHealth = async (e) => {
    e.preventDefault();
    setFormMsg(null);
    setHealthBusy(true);
    const v = vaultRef.current?.trim() || undefined;
    try {
      const payload = {
        sleep_hours: hSleep === "" ? null : Number(hSleep),
        water_glasses: hWater === "" ? null : Number(hWater),
        stress_1_10: hStress === "" ? null : Number(hStress),
        weight_kg: hWeight === "" ? null : Number(hWeight),
        bp_systolic: hSys === "" ? null : Number(hSys),
        bp_diastolic: hDia === "" ? null : Number(hDia),
      };
      await postLifeHealth(payload, v);
      setFormMsg("Today’s health log saved.");
      setHSleep("");
      setHWater("");
      setHStress("5");
      setHWeight("");
      setHSys("");
      setHDia("");
      await load();
    } catch (err) {
      setFormMsg(err?.response?.data?.detail || err?.message || "Could not save health.");
    } finally {
      setHealthBusy(false);
    }
  };

  const onSaveMission = async (e) => {
    e.preventDefault();
    setFormMsg(null);
    const title = mTitle.trim();
    if (!title) {
      setFormMsg("Enter a task name.");
      return;
    }
    setMissionBusy(true);
    try {
      await postLifeMission({
        title,
        priority: mPri,
        deadline: deadlineFromDateInput(mDue),
        status: "open",
      });
      setMTitle("");
      setMDue("");
      setFormMsg("Task saved.");
      await load();
    } catch (err) {
      setFormMsg(err?.response?.data?.detail || err?.message || "Could not save task.");
    } finally {
      setMissionBusy(false);
    }
  };

  const onSaveQuickExpense = async (e) => {
    e.preventDefault();
    setFormMsg(null);
    const amount = Number(feAmount);
    if (!amount || amount <= 0) {
      setFormMsg("Enter a valid expense amount.");
      return;
    }
    setFeBusy(true);
    const v = vaultRef.current?.trim() || undefined;
    try {
      await createPersonalExpense(
        {
          amount,
          currency: "INR",
          category: feCat,
          subcategory: "",
          title: feNote || "Quick entry",
        },
        v,
      );
      setFeAmount("");
      setFeNote("");
      setFormMsg("Expense saved.");
      await load();
    } catch (err) {
      setFormMsg(err?.response?.data?.detail || err?.message || "Could not save expense.");
    } finally {
      setFeBusy(false);
    }
  };

  const onHabitDone = async (habitId) => {
    setFormMsg(null);
    try {
      await postLifeHabitCheckIn({ habit_id: habitId, status: "completed" });
      setFormMsg("Habit checked in.");
      await load();
    } catch (err) {
      setFormMsg(err?.response?.data?.detail || err?.message || "Check-in failed.");
    }
  };

  const weather = brief?.weather;
  const fin = brief?.financial_snapshot || {};
  const health = brief?.health_score || {};
  const headerDate = brief?.date || todayIsoDate();

  return (
    <div className="personal-os-page">
      <div className="personal-os-hero">
        <div>
          <h1 className="personal-os-title">Daily command center</h1>
          <p className="personal-os-sub">{formatDate(headerDate)}</p>
        </div>
        <div className="personal-os-vault">
          <label className="personal-os-label">
            Vault passphrase (optional — encrypts synced notes when saving health/finance)
            <input
              type="password"
              className="cc-input personal-os-input"
              value={vaultPass}
              onChange={(e) => setVaultPass(e.target.value)}
              placeholder="Leave empty if not using encrypted fields"
              autoComplete="off"
            />
          </label>
          <button type="button" className="cc-btn cc-btn-primary personal-os-btn-touch" onClick={() => load()} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <div className="personal-os-banner personal-os-banner--error">{String(error)}</div>}
      {formMsg && <div className="personal-os-banner">{formMsg}</div>}
      {loading && !brief && <p className="cc-muted">Loading your brief…</p>}

      <p className="personal-os-section-lead cc-muted">Quick add — habit, health, task, expense (scroll for snapshot and brief).</p>

      <div className="personal-os-quick-forms personal-os-touch">
        <form className="personal-os-card personal-os-quick-form" onSubmit={onSaveHabit}>
          <h2 className="personal-os-card-title">Add Habit</h2>
          <p className="personal-os-form-help">Creates the habit and marks it completed for today.</p>
          <label className="personal-os-label">
            Habit name
            <input className="cc-input" value={habitName} onChange={(e) => setHabitName(e.target.value)} placeholder="e.g. Morning walk" />
          </label>
          <label className="personal-os-label">
            Frequency
            <select className="cc-select" value={habitFreq} onChange={(e) => setHabitFreq(e.target.value)}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </label>
          <label className="personal-os-label">
            Category
            <select className="cc-select" value={habitCat} onChange={(e) => setHabitCat(e.target.value)}>
              <option value="health">Health</option>
              <option value="work">Work</option>
              <option value="personal">Personal</option>
            </select>
          </label>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" disabled={habitBusy}>
            {habitBusy ? "Saving…" : "Save habit"}
          </button>
        </form>

        <form className="personal-os-card personal-os-quick-form" onSubmit={onSaveHealth} id="health-log">
          <h2 className="personal-os-card-title">Health log</h2>
          <p className="personal-os-form-help">Sleep, water, stress, weight, BP → POST /life/health.</p>
          <div className="personal-os-form-grid personal-os-form-grid--dense">
            <label className="personal-os-label">
              Sleep hours
              <input className="cc-input" type="number" step="0.25" min="0" max="24" value={hSleep} onChange={(e) => setHSleep(e.target.value)} />
            </label>
            <label className="personal-os-label">
              Water (glasses)
              <input className="cc-input" type="number" min="0" max="40" value={hWater} onChange={(e) => setHWater(e.target.value)} />
            </label>
            <label className="personal-os-label personal-os-label--full">
              Stress 1–10: {hStress}
              <input
                type="range"
                min="1"
                max="10"
                value={hStress}
                onChange={(e) => setHStress(e.target.value)}
                className="personal-os-range"
              />
            </label>
            <label className="personal-os-label">
              Weight kg (optional)
              <input className="cc-input" type="number" step="0.1" min="0" value={hWeight} onChange={(e) => setHWeight(e.target.value)} />
            </label>
            <label className="personal-os-label">
              BP systolic
              <input className="cc-input" type="number" min="0" value={hSys} onChange={(e) => setHSys(e.target.value)} />
            </label>
            <label className="personal-os-label">
              BP diastolic
              <input className="cc-input" type="number" min="0" value={hDia} onChange={(e) => setHDia(e.target.value)} />
            </label>
          </div>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" disabled={healthBusy}>
            {healthBusy ? "Saving…" : "Save health"}
          </button>
        </form>

        <form className="personal-os-card personal-os-quick-form" onSubmit={onSaveMission}>
          <h2 className="personal-os-card-title">Add Task</h2>
          <p className="personal-os-form-help">Personal mission → POST /life/mission.</p>
          <label className="personal-os-label">
            Task name
            <input className="cc-input" value={mTitle} onChange={(e) => setMTitle(e.target.value)} placeholder="What needs to ship?" />
          </label>
          <label className="personal-os-label">
            Priority
            <select className="cc-select" value={mPri} onChange={(e) => setMPri(e.target.value)}>
              <option value="P1">P1 — Urgent</option>
              <option value="P2">P2 — Normal</option>
              <option value="P3">P3 — Later</option>
            </select>
          </label>
          <label className="personal-os-label">
            Due date
            <input className="cc-input" type="date" value={mDue} onChange={(e) => setMDue(e.target.value)} />
          </label>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" disabled={missionBusy}>
            {missionBusy ? "Saving…" : "Save task"}
          </button>
        </form>

        <form className="personal-os-card personal-os-quick-form" onSubmit={onSaveQuickExpense}>
          <h2 className="personal-os-card-title">Add expense</h2>
          <p className="personal-os-form-help">Quick personal expense → POST /personal/os/expenses.</p>
          <div className="personal-os-form-grid">
            <label className="personal-os-label">
              Amount (INR)
              <input className="cc-input" type="number" step="0.01" min="0" value={feAmount} onChange={(e) => setFeAmount(e.target.value)} />
            </label>
            <label className="personal-os-label">
              Category
              <select className="cc-select" value={feCat} onChange={(e) => setFeCat(e.target.value)}>
                {FINANCE_QUICK_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="personal-os-label personal-os-label--full">
              Note
              <input className="cc-input" value={feNote} onChange={(e) => setFeNote(e.target.value)} placeholder="What was this for?" />
            </label>
          </div>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" disabled={feBusy}>
            {feBusy ? "Saving…" : "Save expense"}
          </button>
          <Link to="/personal/finance" className="personal-os-finance-link">
            Full finance and loans →
          </Link>
        </form>
      </div>

      <section className="personal-os-life-summary personal-os-touch" aria-label="Life OS snapshot">
        <div className="personal-os-life-card">
          <h3 className="personal-os-life-card-title">Habits</h3>
          {habits.length === 0 ? (
            <p className="personal-os-empty-cta">No habits yet → use Add Habit above.</p>
          ) : (
            <>
              <p className="personal-os-life-stat">
                <strong>{habits.length}</strong> active · <strong>{dashboard.habits_pending_today ?? 0}</strong> pending today
              </p>
              <ul className="personal-os-mini-list">
                {habits.slice(0, 6).map((h) => (
                  <li key={h.id} className="personal-os-mini-row">
                    <span>{h.title}</span>
                    {!h.completed_today ? (
                      <button type="button" className="cc-btn cc-btn-primary personal-os-btn-compact" onClick={() => onHabitDone(h.id)}>
                        Done today
                      </button>
                    ) : (
                      <span className="cc-muted">Done</span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div className="personal-os-life-card">
          <h3 className="personal-os-life-card-title">Health</h3>
          {!hasHealthToday ? (
            <p className="personal-os-empty-cta">No health data yet → use Health log above.</p>
          ) : (
            <p className="personal-os-life-stat">
              {legacy?.sleep_hours != null && <>Sleep {legacy.sleep_hours}h · </>}
              {legacy?.water_glasses != null && <>Water {legacy.water_glasses} · </>}
              {legacy?.stress_1_10 != null && <>Stress {legacy.stress_1_10}/10</>}
              {metricsToday.length > 0 && (
                <span className="cc-muted"> · {metricsToday.length} metric reading(s) today</span>
              )}
            </p>
          )}
        </div>
        <div className="personal-os-life-card">
          <h3 className="personal-os-life-card-title">Tasks</h3>
          {missionsOpen.length === 0 ? (
            <p className="personal-os-empty-cta">No tasks yet → use Add Task above.</p>
          ) : (
            <p className="personal-os-life-stat">
              <strong>{missionsOpen.length}</strong> open (showing top {Math.min(8, missionsOpen.length)})
            </p>
          )}
        </div>
      </section>

      {brief && (
        <div className="personal-os-grid">
          <section className="personal-os-card personal-os-card--wide">
            <h2 className="personal-os-card-title">Today at a glance</h2>
            <div className="personal-os-row">
              {weather?.temperature_c != null ? (
                <div>
                  <span className="personal-os-stat-label">Weather</span>
                  <span className="personal-os-stat-value">{Number(weather.temperature_c).toFixed(0)}°C</span>
                  <span className="cc-muted" style={{ display: "block", fontSize: 12 }}>
                    Code {weather.weather_code ?? "—"}
                  </span>
                </div>
              ) : (
                <div>
                  <span className="personal-os-stat-label">Weather</span>
                  <span className="cc-muted">Set PERSONAL_OS_WEATHER_LAT / LON on the server for live weather.</span>
                </div>
              )}
              <div>
                <span className="personal-os-stat-label">Cash out (today)</span>
                <span className="personal-os-stat-value">
                  {fin.currency || "INR"} {fin.spent_today ?? "0"}
                </span>
              </div>
              <div>
                <span className="personal-os-stat-label">Month spend</span>
                <span className="personal-os-stat-value">
                  {fin.currency || "INR"} {fin.spent_month ?? "0"}
                </span>
              </div>
              <div>
                <span className="personal-os-stat-label">Health score</span>
                <span className="personal-os-stat-value">{health.score != null ? `${health.score}/100` : "—"}</span>
                {health.hint && (
                  <span className="cc-muted" style={{ display: "block", fontSize: 12 }}>
                    {health.hint}
                  </span>
                )}
              </div>
            </div>
          </section>

          <section className="personal-os-card">
            <h2 className="personal-os-card-title">Top 3 priorities</h2>
            <p className="cc-muted personal-os-hint">From open personal missions (P1 first).</p>
            <ol className="personal-os-list">
              {(brief.priorities || []).length === 0 && (
                <li className="personal-os-empty-cta">No tasks yet for the brief → add a task above.</li>
              )}
              {(brief.priorities || []).map((p) => (
                <li key={p.id}>
                  <span className={`personal-os-pill personal-os-pill--${(p.priority || "P2").toLowerCase()}`}>
                    {p.priority || "P2"}
                  </span>
                  {p.title}
                  {p.deadline && (
                    <span className="cc-muted" style={{ display: "block", fontSize: 12 }}>
                      Due {p.deadline}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </section>

          <section className="personal-os-card">
            <h2 className="personal-os-card-title">Upcoming EMIs</h2>
            <ul className="personal-os-list personal-os-list--plain">
              {(fin.upcoming_emis || []).length === 0 && (
                <li className="personal-os-empty-cta">No loans on file → add one under Finance.</li>
              )}
              {(fin.upcoming_emis || []).map((e) => (
                <li key={e.id}>
                  <strong>{e.name}</strong>
                  <span className="cc-muted" style={{ marginLeft: 8 }}>
                    {e.due} {e.emi ? `· EMI ${e.emi}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <section className="personal-os-card">
            <h2 className="personal-os-card-title">Meetings</h2>
            <p className="cc-muted">
              {(brief.meetings || []).length === 0
                ? "Planner sync for today arrives in a later phase — use your calendar for now."
                : JSON.stringify(brief.meetings)}
            </p>
          </section>

          <section className="personal-os-card personal-os-card--wide">
            <h2 className="personal-os-card-title">Pending decisions</h2>
            {decisions.length === 0 ? (
              <p className="cc-muted">No pending decisions in Command Center.</p>
            ) : (
              <ul className="personal-os-list personal-os-list--plain">
                {decisions.slice(0, 8).map((d) => (
                  <li key={d.id}>
                    <strong>{d.action || "Decision"}</strong>
                    {d.entity ? <span className="cc-muted"> · {d.entity}</span> : null}
                    {d.created_at && (
                      <span className="cc-muted" style={{ display: "block", fontSize: 12 }}>
                        {d.created_at}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="personal-os-card personal-os-card--wide personal-os-card--insight">
            <h2 className="personal-os-card-title">Strategic insight</h2>
            <p className="personal-os-insight">{brief.ai_insight || "—"}</p>
          </section>
        </div>
      )}
    </div>
  );
}
