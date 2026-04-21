import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import api from "../../api/client.js";
import { fetchMyOrganizations } from "../../api/commandCenterApi.js";

const BUSINESS_TYPES = [
  "Manufacturing",
  "Retail / Shop",
  "Agriculture / Agro",
  "Service",
  "Trading",
];

const EMPTY_FORM = {
  company_name: "",
  business_type: "Manufacturing",
  gstin: "",
  phone: "",
  email: "",
  address: "",
  city: "",
  state: "",
  pincode: "",
};

export default function CompanyProfilePage() {
  const { orgId } = useParams();
  const resolvedOrgId = Number(orgId);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);

  const canSave = useMemo(() => Number.isFinite(resolvedOrgId) && resolvedOrgId > 0, [resolvedOrgId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSuccess("");

    (async () => {
      try {
        const rows = await fetchMyOrganizations();
        if (cancelled) return;
        const list = Array.isArray(rows) ? rows : [];
        const mine = list.find((r) => Number(r?.organization?.id) === resolvedOrgId)?.organization || null;
        if (!mine) {
          setError("Organization not found in your memberships.");
          setLoading(false);
          return;
        }
        setForm({
          company_name: mine?.name || "",
          business_type: mine?.business_type || mine?.company_type || "Manufacturing",
          gstin: mine?.gstin || "",
          phone: mine?.phone || "",
          email: mine?.email || "",
          address: mine?.address || "",
          city: mine?.city || "",
          state: mine?.state || "",
          pincode: mine?.pincode || "",
        });
      } catch (e) {
        if (!cancelled) setError(e?.response?.data?.detail || e?.message || "Could not load company profile.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [resolvedOrgId]);

  function onField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSave(e) {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    setSuccess("");

    const payload = {
      name: form.company_name.trim(),
      business_type: form.business_type,
      gstin: form.gstin.trim().toUpperCase().slice(0, 15),
      phone: form.phone.trim(),
      email: form.email.trim(),
      address: form.address.trim(),
      city: form.city.trim(),
      state: form.state.trim(),
      pincode: form.pincode.trim(),
    };

    try {
      await api.patch(`/me/organizations/${resolvedOrgId}`, payload);
      setSuccess("Company profile saved.");
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "24px 16px 40px" }}>
      <h1 className="cc-page-title">Company Profile</h1>
      <div className="cc-card">
        {loading ? (
          <div style={{ display: "grid", gap: 10 }}>
            <div className="cc-skeleton" style={{ height: 42 }} />
            <div className="cc-skeleton" style={{ height: 42 }} />
            <div className="cc-skeleton" style={{ height: 42 }} />
            <div className="cc-skeleton" style={{ height: 90 }} />
          </div>
        ) : (
          <form onSubmit={onSave} style={{ display: "grid", gap: 12 }}>
            {error && <p className="cc-error">{error}</p>}
            {success && <p className="cc-muted">{success}</p>}

            <label>
              <div className="cc-muted" style={{ marginBottom: 6 }}>
                Company name
              </div>
              <input
                className="cc-input"
                type="text"
                value={form.company_name}
                onChange={(e) => onField("company_name", e.target.value)}
                required
              />
            </label>

            <label>
              <div className="cc-muted" style={{ marginBottom: 6 }}>
                Business type
              </div>
              <select
                className="cc-input"
                value={form.business_type}
                onChange={(e) => onField("business_type", e.target.value)}
              >
                {BUSINESS_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <div className="cc-muted" style={{ marginBottom: 6 }}>
                GSTIN
              </div>
              <input
                className="cc-input"
                type="text"
                value={form.gstin}
                onChange={(e) => onField("gstin", e.target.value.toUpperCase().slice(0, 15))}
                maxLength={15}
              />
            </label>

            <label>
              <div className="cc-muted" style={{ marginBottom: 6 }}>
                Phone
              </div>
              <input className="cc-input" type="text" value={form.phone} onChange={(e) => onField("phone", e.target.value)} />
            </label>

            <label>
              <div className="cc-muted" style={{ marginBottom: 6 }}>
                Email
              </div>
              <input className="cc-input" type="text" value={form.email} onChange={(e) => onField("email", e.target.value)} />
            </label>

            <label>
              <div className="cc-muted" style={{ marginBottom: 6 }}>
                Address
              </div>
              <textarea
                className="cc-input"
                value={form.address}
                onChange={(e) => onField("address", e.target.value)}
                rows={3}
              />
            </label>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              <label>
                <div className="cc-muted" style={{ marginBottom: 6 }}>
                  City
                </div>
                <input className="cc-input" type="text" value={form.city} onChange={(e) => onField("city", e.target.value)} />
              </label>

              <label>
                <div className="cc-muted" style={{ marginBottom: 6 }}>
                  State
                </div>
                <input className="cc-input" type="text" value={form.state} onChange={(e) => onField("state", e.target.value)} />
              </label>

              <label>
                <div className="cc-muted" style={{ marginBottom: 6 }}>
                  Pincode
                </div>
                <input
                  className="cc-input"
                  type="text"
                  value={form.pincode}
                  onChange={(e) => onField("pincode", e.target.value)}
                />
              </label>
            </div>

            <div style={{ marginTop: 6 }}>
              <button className="cc-btn cc-btn-primary" type="submit" disabled={!canSave || saving}>
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
