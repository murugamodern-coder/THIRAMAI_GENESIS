import { useCallback, useEffect, useState } from "react";

import {
  createPersonalMedicine,
  createPersonalVital,
  fetchPersonalMedicines,
  fetchPersonalVitals,
} from "../../api/commandCenterApi.js";
import { safeAsync } from "../../lib/safeAsync.js";

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function formatMedSchedule(sj) {
  if (!sj || typeof sj !== "object") return "—";
  const t = sj.times;
  if (Array.isArray(t) && t.length) return t.map((x) => String(x)).join(", ");
  if (sj.morning || sj.afternoon || sj.night) {
    const parts = [];
    if (sj.morning) parts.push("morning");
    if (sj.afternoon) parts.push("afternoon");
    if (sj.night) parts.push("night");
    return parts.join(", ");
  }
  return "—";
}

export default function PersonalHealthPage() {
  const [vaultPass, setVaultPass] = useState("");
  const [vitals, setVitals] = useState([]);
  const [medicines, setMedicines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState(null);

  const [weight, setWeight] = useState("");
  const [sys, setSys] = useState("");
  const [dia, setDia] = useState("");
  const [glucose, setGlucose] = useState("");
  const [sleep, setSleep] = useState("");
  const [stress, setStress] = useState("5");
  const [water, setWater] = useState("");
  const [notes, setNotes] = useState("");

  const [medName, setMedName] = useState("");
  const [medDose, setMedDose] = useState("");
  const [medStarted, setMedStarted] = useState(todayISO());
  const [medMorning, setMedMorning] = useState(true);
  const [medAfternoon, setMedAfternoon] = useState(false);
  const [medNight, setMedNight] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [v, m] = await Promise.all([fetchPersonalVitals(40), fetchPersonalMedicines()]);
      setVitals(v?.items || []);
      setMedicines(m?.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    safeAsync(load, { toast: false })();
  }, [load]);

  const onSaveVital = async (e) => {
    e.preventDefault();
    setMessage(null);
    try {
      await createPersonalVital(
        {
          weight_kg: weight ? Number(weight) : null,
          bp_systolic: sys ? Number(sys) : null,
          bp_diastolic: dia ? Number(dia) : null,
          blood_glucose_mg_dl: glucose ? Number(glucose) : null,
          sleep_hours: sleep ? Number(sleep) : null,
          stress_1_10: stress ? Number(stress) : null,
          water_glasses: water ? Number(water) : null,
          notes: notes || null,
        },
        vaultPass || undefined,
      );
      setWeight("");
      setSys("");
      setDia("");
      setGlucose("");
      setSleep("");
      setStress("5");
      setWater("");
      setNotes("");
      await load();
      setMessage("Vitals saved.");
    } catch (err) {
      setMessage(err?.response?.data?.detail || err?.message || "Failed.");
    }
  };

  const onSaveMed = async (e) => {
    e.preventDefault();
    setMessage(null);
    if (!medName.trim()) {
      setMessage("Medicine name required.");
      return;
    }
    const times = [];
    if (medMorning) times.push("morning");
    if (medAfternoon) times.push("afternoon");
    if (medNight) times.push("night");
    const schedule_json = {
      times,
      morning: medMorning,
      afternoon: medAfternoon,
      night: medNight,
    };
    try {
      await createPersonalMedicine(
        {
          name: medName.trim(),
          dosage_text: medDose,
          schedule_json,
          started_on: medStarted,
        },
        vaultPass || undefined,
      );
      setMedName("");
      setMedDose("");
      setMedMorning(true);
      setMedAfternoon(false);
      setMedNight(false);
      await load();
      setMessage("Medicine tracker added.");
    } catch (err) {
      setMessage(err?.response?.data?.detail || err?.message || "Failed.");
    }
  };

  return (
    <div className="personal-os-page personal-os-touch">
      <header className="personal-os-section-head">
        <h1 className="personal-os-title">Health command center</h1>
        <p className="personal-os-sub">Daily vitals and medicines (POST /personal/os/vitals and /personal/os/medicines).</p>
      </header>

      <label className="personal-os-label personal-os-inline-vault">
        Vault passphrase (optional)
        <input
          type="password"
          className="cc-input personal-os-input personal-os-input--narrow"
          value={vaultPass}
          onChange={(e) => setVaultPass(e.target.value)}
          autoComplete="off"
        />
      </label>

      {message && <div className="personal-os-banner">{message}</div>}

      <div className="personal-os-finance-grid">
        <form className="personal-os-card" onSubmit={onSaveVital}>
          <h2 className="personal-os-card-title">Daily vitals</h2>
          <div className="personal-os-form-grid personal-os-form-grid--dense">
            <label className="personal-os-label">
              Weight (kg)
              <input className="cc-input" type="number" step="0.1" min="0" value={weight} onChange={(e) => setWeight(e.target.value)} />
            </label>
            <label className="personal-os-label">
              BP systolic
              <input className="cc-input" type="number" min="0" value={sys} onChange={(e) => setSys(e.target.value)} />
            </label>
            <label className="personal-os-label">
              BP diastolic
              <input className="cc-input" type="number" min="0" value={dia} onChange={(e) => setDia(e.target.value)} />
            </label>
            <label className="personal-os-label">
              Blood sugar (mg/dL)
              <input className="cc-input" type="number" step="0.1" min="0" value={glucose} onChange={(e) => setGlucose(e.target.value)} />
            </label>
            <label className="personal-os-label">
              Sleep (h)
              <input className="cc-input" type="number" step="0.25" min="0" value={sleep} onChange={(e) => setSleep(e.target.value)} />
            </label>
            <label className="personal-os-label">
              Water (glasses)
              <input className="cc-input" type="number" min="0" max="40" value={water} onChange={(e) => setWater(e.target.value)} />
            </label>
            <label className="personal-os-label personal-os-label--full">
              Stress 1–10: {stress}
              <input type="range" min="1" max="10" value={stress} onChange={(e) => setStress(e.target.value)} className="personal-os-range" />
            </label>
            <label className="personal-os-label personal-os-label--full">
              Notes
              <input className="cc-input" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </label>
          </div>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" style={{ marginTop: 12 }}>
            Save vitals
          </button>
        </form>

        <form className="personal-os-card" onSubmit={onSaveMed}>
          <h2 className="personal-os-card-title">Medicine tracker</h2>
          <div className="personal-os-form-grid">
            <label className="personal-os-label personal-os-label--full">
              Medicine name
              <input className="cc-input" value={medName} onChange={(e) => setMedName(e.target.value)} required />
            </label>
            <label className="personal-os-label personal-os-label--full">
              Dosage
              <input className="cc-input" value={medDose} onChange={(e) => setMedDose(e.target.value)} placeholder="e.g. 500mg after food" />
            </label>
            <label className="personal-os-label">
              Started on
              <input className="cc-input" type="date" value={medStarted} onChange={(e) => setMedStarted(e.target.value)} required />
            </label>
            <div className="personal-os-label personal-os-label--full">
              <span>Timing</span>
              <div className="personal-os-chips">
                <label className="personal-os-chip">
                  <input type="checkbox" checked={medMorning} onChange={(e) => setMedMorning(e.target.checked)} />
                  Morning
                </label>
                <label className="personal-os-chip">
                  <input type="checkbox" checked={medAfternoon} onChange={(e) => setMedAfternoon(e.target.checked)} />
                  Afternoon
                </label>
                <label className="personal-os-chip">
                  <input type="checkbox" checked={medNight} onChange={(e) => setMedNight(e.target.checked)} />
                  Night
                </label>
              </div>
            </div>
          </div>
          <button type="submit" className="cc-btn cc-btn-primary personal-os-btn-touch" style={{ marginTop: 12 }}>
            Save medicine
          </button>
        </form>
      </div>

      <div className="personal-os-two-col">
        <section className="personal-os-card personal-os-table-card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <h2 className="personal-os-card-title" style={{ margin: 0 }}>
              Recent vitals
            </h2>
            <button type="button" className="cc-btn personal-os-btn-touch" onClick={() => load()} disabled={loading}>
              Refresh
            </button>
          </div>
          <div className="personal-os-table-wrap">
            <table className="personal-os-table personal-os-table--compact">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>WT</th>
                  <th>BP</th>
                  <th>Sugar</th>
                  <th>Sleep</th>
                  <th>Stress</th>
                </tr>
              </thead>
              <tbody>
                {vitals.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="personal-os-empty-cta">
                      No vitals yet → log your first reading above.
                    </td>
                  </tr>
                ) : (
                  vitals.map((r) => (
                    <tr key={r.id}>
                      <td>{r.recorded_at?.slice(0, 16)}</td>
                      <td>{r.weight_kg ?? "—"}</td>
                      <td>{r.bp_systolic != null && r.bp_diastolic != null ? `${r.bp_systolic}/${r.bp_diastolic}` : "—"}</td>
                      <td>{r.blood_glucose_mg_dl ?? "—"}</td>
                      <td>{r.sleep_hours ?? "—"}</td>
                      <td>{r.stress_1_10 ?? "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="personal-os-card">
          <h2 className="personal-os-card-title">Medicines</h2>
          <ul className="personal-os-list personal-os-list--plain">
            {medicines.length === 0 && <li className="personal-os-empty-cta">No medicines yet → add one above.</li>}
            {medicines.map((r) => (
              <li key={r.id}>
                <strong>{r.name}</strong>
                <div className="cc-muted" style={{ fontSize: 12 }}>
                  {r.dosage_text || "—"} · {formatMedSchedule(r.schedule_json)} · since {r.started_on}
                  {r.is_active === false ? " · inactive" : ""}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
