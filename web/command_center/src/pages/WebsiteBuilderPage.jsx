import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchMyOrganizations,
  fetchWebsiteMeta,
  fetchWebsitePreviewHtml,
  postWebsiteBuild,
  postWebsiteDeploy,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

const TEMPLATES = [
  { id: "shop", label: "Shop (retail / agro)" },
  { id: "manufacturing", label: "Manufacturing" },
  { id: "services", label: "Services" },
];

export default function WebsiteBuilderPage() {
  const [orgs, setOrgs] = useState([]);
  const [orgId, setOrgId] = useState("");
  const [template, setTemplate] = useState("shop");
  const [previewHtml, setPreviewHtml] = useState("");
  const [publicUrl, setPublicUrl] = useState("");
  const [slug, setSlug] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchMyOrganizations();
        if (cancelled) return;
        setOrgs(Array.isArray(list) ? list : []);
        const first = list?.[0]?.organization?.id;
        if (first) setOrgId(String(first));
      } catch {
        setOrgs([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const oidNum = useMemo(() => Number(orgId) || 0, [orgId]);

  const refreshMeta = useCallback(async () => {
    if (!oidNum) return;
    try {
      const m = await fetchWebsiteMeta(oidNum);
      if (m?.ok) {
        setPublicUrl(m.public_url || "");
        setSlug(m.slug || "");
      } else {
        setPublicUrl("");
        setSlug("");
      }
    } catch {
      setPublicUrl("");
      setSlug("");
    }
  }, [oidNum]);

  const refreshPreview = useCallback(async () => {
    if (!oidNum) return;
    setLoading(true);
    try {
      const p = await fetchWebsitePreviewHtml(oidNum);
      if (p?.ok && p.html) setPreviewHtml(p.html);
      else setPreviewHtml("");
    } catch {
      setPreviewHtml("");
    } finally {
      setLoading(false);
    }
  }, [oidNum]);

  useEffect(() => {
    refreshMeta();
  }, [refreshMeta]);

  const onBuild = useCallback(async () => {
    if (!oidNum) return;
    setLoading(true);
    try {
      const out = await postWebsiteBuild({
        organization_id: oidNum,
        template_type: template,
        deploy: false,
      });
      if (out?.ok) {
        setPublicUrl(out.public_url || "");
        setSlug(out.slug || "");
        showToastDedup({ type: "success", message: "Site generated" });
        await refreshPreview();
      } else {
        showToastDedup({ type: "error", message: out?.error || "Build failed" });
      }
    } catch (e) {
      showToastDedup({ type: "error", message: e?.message || "Build failed" });
    } finally {
      setLoading(false);
    }
  }, [oidNum, template, refreshPreview]);

  const onDeploy = useCallback(async () => {
    if (!oidNum) return;
    setLoading(true);
    try {
      const out = await postWebsiteDeploy({ organization_id: oidNum });
      if (out?.ok) {
        showToastDedup({
          type: "success",
          message: out.reloaded ? "Nginx reloaded" : "Nginx config written (reload may be manual)",
        });
      } else {
        showToastDedup({ type: "error", message: out?.error || "Deploy failed" });
      }
    } catch (e) {
      showToastDedup({ type: "error", message: e?.message || "Deploy failed" });
    } finally {
      setLoading(false);
    }
  }, [oidNum]);

  return (
    <div className="cc-dashboard" style={{ maxWidth: 1100, margin: "0 auto", padding: "16px 20px 40px" }}>
      <h1 style={{ marginBottom: 8 }}>Website builder</h1>
      <p className="cc-muted" style={{ marginBottom: 20 }}>
        Generate a static site from your org name + inventory, preview inline, then deploy nginx config when your
        server is ready. Wildcard DNS <code>*.thiramai.co.in</code> must point at the host.
      </p>

      <section className="cc-card" style={{ marginBottom: 20 }}>
        <h2 className="cc-today-card-title">Configure</h2>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
          <label className="cc-muted" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Business
            <select className="cc-select" value={orgId} onChange={(e) => setOrgId(e.target.value)} style={{ minWidth: 220 }}>
              {orgs.map((row) => (
                <option key={row.organization.id} value={String(row.organization.id)}>
                  {row.organization.name}
                </option>
              ))}
            </select>
          </label>
          <label className="cc-muted" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Template
            <select className="cc-select" value={template} onChange={(e) => setTemplate(e.target.value)} style={{ minWidth: 200 }}>
              {TEMPLATES.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="cc-btn cc-btn-primary" disabled={loading || !oidNum} onClick={onBuild}>
            Build site
          </button>
          <button type="button" className="cc-btn" disabled={loading || !oidNum} onClick={onDeploy}>
            Deploy (nginx)
          </button>
          <button type="button" className="cc-btn" disabled={loading || !oidNum} onClick={refreshPreview}>
            Refresh preview
          </button>
        </div>
        {(slug || publicUrl) && (
          <p style={{ marginTop: 16, fontSize: 14 }}>
            <strong>Slug:</strong> {slug || "—"} · <strong>Target URL:</strong>{" "}
            {publicUrl ? (
              <a href={publicUrl} target="_blank" rel="noreferrer">
                {publicUrl}
              </a>
            ) : (
              "—"
            )}
          </p>
        )}
      </section>

      <section className="cc-card">
        <h2 className="cc-today-card-title">Live preview</h2>
        {!previewHtml ? (
          <p className="cc-muted">{loading ? "Loading…" : "Build a site to see preview here."}</p>
        ) : (
          <iframe
            title="site-preview"
            sandbox="allow-scripts"
            style={{ width: "100%", minHeight: 520, border: "1px solid #334155", borderRadius: 8, background: "#fff" }}
            srcDoc={previewHtml}
          />
        )}
      </section>
    </div>
  );
}
