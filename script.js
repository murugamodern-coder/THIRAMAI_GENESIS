/**
 * THIRAMAI Dashboard — minimal: /chat fetch + Markdown in #report.
 * Chart.js removed (strict reset). Errors use console.error + alert().
 */
document.addEventListener("DOMContentLoaded", function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function buildChatUrl(query) {
    return window.location.origin + "/chat?query=" + encodeURIComponent(query);
  }

  const queryEl = $("query");
  const executeBtn = $("executeBtn") || $("runBtn");
  const pdfBtn = $("pdfBtn");
  const statusEl = $("status");
  const reportMetaEl = $("reportMeta");
  const placeholderEl = $("placeholder");
  const loadingPanelEl = $("loadingPanel");
  const reportEl = $("report");

  const MAX_QUERY_CHARS = 5000;

  /** Match Command SPA / dashboard: JWT in localStorage or sessionStorage. */
  function getThiramaiJwt() {
    try {
      const a = (localStorage.getItem("thiramai_jwt") || "").trim();
      if (a) return a;
      return (sessionStorage.getItem("thiramai_jwt") || "").trim();
    } catch (e) {
      return "";
    }
  }

  function invoiceAuthHeaders() {
    const h = { Accept: "application/json", "Content-Type": "application/json" };
    const t = getThiramaiJwt();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }

  function escapeAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function setStatus(msg, isError, isWarn) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.toggle("text-red-400", !!isError);
    statusEl.classList.toggle("text-amber-400", !!isWarn && !isError);
    statusEl.classList.toggle("text-zinc-500", !isError && !isWarn);
  }

  function showLoading() {
    if (placeholderEl) placeholderEl.classList.add("hidden");
    if (reportEl) {
      reportEl.classList.add("hidden");
      reportEl.innerHTML = "";
    }
    if (loadingPanelEl) {
      loadingPanelEl.classList.remove("hidden");
      loadingPanelEl.classList.add("flex");
    }
  }

  function hideLoading() {
    if (loadingPanelEl) {
      loadingPanelEl.classList.add("hidden");
      loadingPanelEl.classList.remove("flex");
    }
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  /** Turn bare /static/factory/... and /media/vault/... paths into Markdown links (skip already-linked). */
  function linkifyAssetPaths(md) {
    if (!md) return md;
    const re = /(\/(?:static\/factory|media\/vault)\/[A-Za-z0-9/_.%-]+\.(?:pdf|csv|txt|md))/gi;
    let out = "";
    let last = 0;
    let m;
    while ((m = re.exec(md)) !== null) {
      const idx = m.index;
      const path = m[1];
      const before2 = md.slice(Math.max(0, idx - 2), idx);
      if (before2 === "](") {
        out += md.slice(last, re.lastIndex);
        last = re.lastIndex;
        continue;
      }
      out += md.slice(last, idx);
      const label = path.toLowerCase().indexOf("invoice") >= 0 ? "View Invoice Here" : "Open file";
      out += "[" + label + "](" + path + ")";
      last = re.lastIndex;
    }
    out += md.slice(last);
    return out;
  }

  function absoluteAssetUrl(u) {
    if (!u || u === "#") return u;
    const s = String(u);
    if (s.startsWith("/")) return window.location.origin + s;
    return s;
  }

  function renderReport(text) {
    if (!reportEl || !placeholderEl) {
      console.error("[THIRAMAI] Missing #report or #placeholder");
      alert("THIRAMAI UI error: report or placeholder element missing.");
      return;
    }
    hideLoading();
    let md = linkifyAssetPaths(text || "");
    if (typeof marked !== "undefined" && typeof marked.parse === "function") {
      if (typeof marked.setOptions === "function") {
        marked.setOptions({ gfm: true, breaks: true, headerIds: false, mangle: false });
      }
      let html = marked.parse(md);
      if (typeof DOMPurify !== "undefined") {
        html = DOMPurify.sanitize(html, {
          ADD_ATTR: ["target", "rel"],
          ALLOW_DATA_ATTR: false,
          ALLOW_UNKNOWN_PROTOCOL: false,
        });
      }
      reportEl.innerHTML = html;
      reportEl.querySelectorAll('a[href^="/static/"], a[href^="/media/"]').forEach(function (a) {
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener noreferrer");
      });
    } else {
      reportEl.innerHTML =
        '<pre class="whitespace-pre-wrap text-sm text-zinc-300">' + escapeHtml(md) + "</pre>";
    }
    placeholderEl.classList.add("hidden");
    reportEl.classList.remove("hidden");
    if (pdfBtn) pdfBtn.disabled = false;
  }

  const assetSearchEl = $("assetSearch");
  const assetListEl = $("assetList");
  const assetVaultStatusEl = $("assetVaultStatus");
  const assetRefreshBtn = $("assetRefreshBtn");
  const quickActionsPanel = $("quick-actions-panel");
  const quickActionsContainer = $("quick-actions-container");
  const quickActionsPlaceholder = $("quick-actions-placeholder");
  const invoiceGenerateBtn = $("invoiceGenerateBtn");
  const invoiceBtnSpinner = $("invoiceBtnSpinner");
  const invoiceBtnLabel = $("invoiceBtnLabel");
  const errorModal = $("errorModal");
  const errorModalTitle = $("errorModalTitle");
  const errorModalBody = $("errorModalBody");
  const errorModalClose = $("errorModalClose");
  const errorModalBackdrop = $("errorModalBackdrop");
  const toastRoot = $("toastRoot");
  const perfTonnage = $("perfTonnage");
  const perfRevenue = $("perfRevenue");
  const perfMachine = $("perfMachine");
  const perfMachineDetail = $("perfMachineDetail");
  const perfMeta = $("perfMeta");
  const perfStock = $("perfStock");

  const invoiceBtnDefaultLabel =
    invoiceBtnLabel && invoiceBtnLabel.textContent ? invoiceBtnLabel.textContent : "Create invoice";

  const inrDisplay = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
  const tonnageDisplay = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });

  function showErrorModal(title, body) {
    if (errorModalTitle) errorModalTitle.textContent = title || "Something went wrong";
    if (errorModalBody) errorModalBody.textContent = body || "";
    if (errorModal) {
      errorModal.classList.remove("hidden");
      errorModal.classList.add("flex");
    }
  }

  function hideErrorModal() {
    if (errorModal) {
      errorModal.classList.add("hidden");
      errorModal.classList.remove("flex");
    }
  }

  if (errorModalClose) {
    errorModalClose.addEventListener("click", hideErrorModal);
  }
  if (errorModalBackdrop) {
    errorModalBackdrop.addEventListener("click", hideErrorModal);
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && errorModal && !errorModal.classList.contains("hidden")) {
      hideErrorModal();
    }
  });

  function showToast(message, kind) {
    if (!toastRoot || !message) return;
    const el = document.createElement("div");
    let box =
      "thiramai-toast pointer-events-auto rounded-xl border px-4 py-3 text-sm shadow-lg font-medium ";
    if (kind === "success") {
      box += "border-neon/50 bg-zinc-950/95 text-neon";
    } else if (kind === "critical") {
      box += "border-red-500/70 bg-red-950/95 text-red-100";
    } else {
      box += "border-zinc-600 bg-zinc-950/95 text-zinc-200";
    }
    el.className = box;
    el.setAttribute("role", "alert");
    el.textContent = message;
    toastRoot.appendChild(el);
    const hold = kind === "critical" ? 6200 : 3200;
    setTimeout(function () {
      el.style.opacity = "0";
      el.style.transition = "opacity 0.35s ease";
      setTimeout(function () {
        el.remove();
      }, 400);
    }, hold);
  }

  function setInvoiceLoading(busy) {
    if (!invoiceGenerateBtn) return;
    if (busy) {
      invoiceGenerateBtn.classList.add("invoice-generate-busy");
      invoiceGenerateBtn.setAttribute("disabled", "disabled");
      invoiceGenerateBtn.setAttribute("aria-busy", "true");
      if (invoiceBtnSpinner) invoiceBtnSpinner.classList.remove("hidden");
      if (invoiceBtnLabel) invoiceBtnLabel.textContent = "Creating invoice…";
    } else {
      invoiceGenerateBtn.classList.remove("invoice-generate-busy");
      invoiceGenerateBtn.removeAttribute("disabled");
      invoiceGenerateBtn.removeAttribute("aria-busy");
      if (invoiceBtnSpinner) invoiceBtnSpinner.classList.add("hidden");
      if (invoiceBtnLabel) invoiceBtnLabel.textContent = invoiceBtnDefaultLabel;
    }
  }

  function isPositiveNumberString(s) {
    const t = String(s == null ? "" : s)
      .trim()
      .replace(/,/g, "");
    if (t === "") return false;
    const n = parseFloat(t);
    return Number.isFinite(n) && n > 0;
  }

  function setFieldInvalid(id, invalid) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle("invoice-field-invalid", !!invalid);
  }

  function clearInvoiceNumericErrors() {
    setFieldInvalid("invWeight", false);
    setFieldInvalid("invRate", false);
    setFieldInvalid("invLength", false);
    setFieldInvalid("invGrade", false);
  }

  function validateInvoiceForm() {
    clearInvoiceNumericErrors();
    const elLen = document.getElementById("invLength");
    const elWt = document.getElementById("invWeight");
    const elRate = document.getElementById("invRate");
    const elGrade = document.getElementById("invGrade");
    const lenOk = isPositiveNumberString(elLen && elLen.value);
    const wtOk = isPositiveNumberString(elWt && elWt.value);
    const rateOk = isPositiveNumberString(elRate && elRate.value);
    const gradeOk = !!(elGrade && String(elGrade.value).trim());

    if (!lenOk) setFieldInvalid("invLength", true);
    if (!wtOk) setFieldInvalid("invWeight", true);
    if (!rateOk) setFieldInvalid("invRate", true);
    if (!gradeOk) setFieldInvalid("invGrade", true);

    if (!lenOk || !wtOk || !rateOk || !gradeOk) {
      return {
        ok: false,
        message:
          "Check the highlighted fields. Length, grade, weight, and rate must be filled in. Weight and rate must be positive numbers (no letters or zero).",
      };
    }
    return { ok: true, message: "" };
  }

  function drawCashFlowRadar(cfr) {
    const poly = $("cashFlowRadarFill");
    const leg = $("cashFlowLegend");
    if (!poly || !cfr || typeof cfr !== "object") return;
    const L = Number(cfr.liquidity_inr) || 250000;
    const R = Number(cfr.machine_restart_inr) || 150000;
    const Rev = Number(cfr.indexed_revenue_inr) || 0;
    const Robo = Number(cfr.robotics_fund_inr);
    const roboFund = Number.isFinite(Robo) ? Robo : 0;
    const maxV = Math.max(L, R, Rev, roboFund, 1);
    const n1 = Math.min(1, L / maxV);
    const n2 = Math.min(1, R / maxV);
    const n3 = Math.min(1, Rev / maxV);
    const n4 = Math.min(1, roboFund / maxV);
    const cx = 130;
    const cy = 120;
    const rmax = 68;
    const angles = [-Math.PI / 2, 0, Math.PI / 2, Math.PI];
    function vertex(nv, i) {
      const a = angles[i];
      const rr = rmax * nv;
      return [cx + rr * Math.cos(a), cy + rr * Math.sin(a)];
    }
    const p0 = vertex(n1, 0);
    const p1 = vertex(n2, 1);
    const p2 = vertex(n3, 2);
    const p3 = vertex(n4, 3);
    poly.setAttribute(
      "points",
      p0[0] + "," + p0[1] + " " + p1[0] + "," + p1[1] + " " + p2[0] + "," + p2[1] + " " + p3[0] + "," + p3[1]
    );
    if (leg) {
      leg.innerHTML = "";
      const rem = cfr.remaining_cash_after_restart_inr;
      const net = cfr.net_after_restart_plus_revenue_inr;
      const tranches = cfr.pipe_sales_100kg_tranches != null ? cfr.pipe_sales_100kg_tranches : 0;
      const pctTranche =
        cfr.robotics_fund_pct_of_tranche_revenue != null ? cfr.robotics_fund_pct_of_tranche_revenue : 2;
      const rows = [
        ["Liquidity (Sovereign guardrail)", "Rs. " + inrDisplay.format(L)],
        ["Machine restart (alloc.)", "Rs. " + inrDisplay.format(R)],
        ["Indexed sales revenue", "Rs. " + inrDisplay.format(Rev)],
        [
          "Robotics Fund (pipe R&D)",
          "Rs. " + inrDisplay.format(roboFund) + " · " + tranches + "×100kg tranche(s) · " + pctTranche + "%/tranche",
        ],
        ["Cash after restart (excl. revenue)", "Rs. " + inrDisplay.format(rem != null ? rem : L - R)],
        ["Net (restart + indexed revenue)", "Rs. " + inrDisplay.format(net != null ? net : L - R + Rev)],
      ];
      rows.forEach(function (row) {
        const li = document.createElement("li");
        li.innerHTML =
          '<span class="text-zinc-500">' +
          row[0] +
          '</span> <span class="font-mono text-zinc-300">' +
          row[1] +
          "</span>";
        leg.appendChild(li);
      });
      const kgNote = document.createElement("li");
      kgNote.className = "mt-1 border-t border-zinc-800/80 pt-2 text-zinc-600";
      kgNote.textContent =
        "Indexed invoice kg (master_index): " +
        tonnageDisplay.format(Number(cfr.indexed_sales_kg) || 0) +
        " kg";
      leg.appendChild(kgNote);
    }
  }

  async function loadFinancialSummary() {
    if (!perfTonnage || !perfRevenue || !perfMachine) return;
    const base = window.location.origin + "/assets/financial-summary";
    const procEl = $("procurementAlert");
    const matEl = $("materialShortageAlert");
    const perfTsiScore = $("perfTsiScore");
    const perfTsiBand = $("perfTsiBand");
    try {
      const res = await fetch(base, { headers: { Accept: "application/json" } });
      const data = await res.json().catch(function () {
        return null;
      });
      if (!res.ok || !data || typeof data !== "object") {
        perfTonnage.textContent = "--";
        perfRevenue.textContent = "--";
        perfMachine.textContent = "Unavailable";
        if (perfMachineDetail) perfMachineDetail.textContent = "";
        if (perfMeta) perfMeta.textContent = "Could not load summary (HTTP " + (res ? res.status : "?") + ").";
        if (perfStock) perfStock.textContent = "--";
        if (procEl) {
          procEl.classList.remove("procurement-alert--animate");
          procEl.classList.add("hidden");
        }
        if (matEl) matEl.classList.add("hidden");
        if (perfTsiScore) perfTsiScore.textContent = "--";
        if (perfTsiBand) perfTsiBand.textContent = "";
        return;
      }
      const kg = typeof data.total_weight_kg === "number" ? data.total_weight_kg : 0;
      const tons = typeof data.total_tonnage === "number" ? data.total_tonnage : kg / 1000;
      perfTonnage.textContent = tonnageDisplay.format(tons) + " t (" + inrDisplay.format(kg) + " kg)";
      perfRevenue.textContent = "Rs. " + inrDisplay.format(data.total_revenue_inr || 0);
      perfMachine.textContent = data.machine_fix_status || "--";
      if (perfMachineDetail) {
        perfMachineDetail.textContent = data.machine_fix_detail || "";
      }
      if (perfMeta) {
        perfMeta.textContent =
          "Invoices with weight in index: " +
          (data.invoice_rows_with_weight != null ? data.invoice_rows_with_weight : "0") +
          " · with revenue_inr in note: " +
          (data.invoice_rows_with_revenue_inr != null ? data.invoice_rows_with_revenue_inr : "0") +
          " · vault backup entries: " +
          (data.sales_history_backup_entries != null ? data.sales_history_backup_entries : "0");
      }
      if (perfStock && data.estimated_stock_kg != null) {
        perfStock.textContent = inrDisplay.format(data.estimated_stock_kg) + " kg";
      }

      const pa = data.procurement_alert;
      if (perfMeta && pa && pa.rd_protoresin_note && !pa.active) {
        perfMeta.textContent += " · " + String(pa.rd_protoresin_note);
      }
      if (pa && pa.active && procEl) {
        procEl.classList.remove("hidden");
        procEl.classList.remove("procurement-alert--animate");
        void procEl.offsetWidth;
        procEl.classList.add("procurement-alert--animate");
        const pm = $("procurementAlertMsg");
        const pd = $("procurementAlertDetail");
        if (pm) pm.textContent = pa.message || "Sovereign Leader, optimal time to stock HDPE for Phase 2.";
        if (pd) pd.textContent = pa.detail || "";
      } else if (procEl) {
        procEl.classList.remove("procurement-alert--animate");
        procEl.classList.add("hidden");
      }

      const msa = data.material_shortage_alert;
      if (msa && msa.active && matEl) {
        matEl.classList.remove("hidden");
        const mh = $("materialShortageMsg");
        const md = $("materialShortageDetail");
        if (mh) mh.textContent = msa.message || "HQRS scrap insufficient for R&D fabrication.";
        if (md) md.textContent = msa.detail || "";
      } else if (matEl) {
        matEl.classList.add("hidden");
      }

      if (data.cash_flow_radar) {
        drawCashFlowRadar(data.cash_flow_radar);
      }
      const tsi = data.tsi;
      if (tsi && perfTsiScore) {
        perfTsiScore.textContent = tsi.score != null ? String(tsi.score) : "--";
        if (perfTsiBand) perfTsiBand.textContent = tsi.band ? String(tsi.band) : "";
      }
    } catch (err) {
      perfTonnage.textContent = "--";
      perfRevenue.textContent = "--";
      perfMachine.textContent = "Unavailable";
      if (perfMachineDetail) perfMachineDetail.textContent = "";
      if (perfMeta) perfMeta.textContent = "Network error loading financial summary.";
      if (perfStock) perfStock.textContent = "--";
      if (procEl) {
        procEl.classList.remove("procurement-alert--animate");
        procEl.classList.add("hidden");
      }
      const matErr = $("materialShortageAlert");
      if (matErr) matErr.classList.add("hidden");
      if (perfTsiScore) perfTsiScore.textContent = "--";
      if (perfTsiBand) perfTsiBand.textContent = "";
    }
  }

  document.querySelectorAll(".inv-num-field").forEach(function (inp) {
    inp.addEventListener("input", function () {
      inp.classList.remove("invoice-field-invalid");
    });
  });
  ["invLength", "invGrade"].forEach(function (fid) {
    const el = document.getElementById(fid);
    if (el) {
      el.addEventListener("input", function () {
        el.classList.remove("invoice-field-invalid");
      });
    }
  });

  let assetSearchDebounce = null;

  const FOLDER_SVG =
    '<svg class="qa-folder-icon h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M10 4H4c-1.11 0-2 .89-2 2v12c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2h-8l-2-2z"/></svg>';

  function setAssetVaultStatus(msg, isError) {
    if (!assetVaultStatusEl) return;
    assetVaultStatusEl.textContent = msg || "";
    assetVaultStatusEl.classList.toggle("text-red-400", !!isError);
    assetVaultStatusEl.classList.toggle("text-zinc-500", !isError);
  }

  async function loadAssets() {
    if (!assetListEl) return;
    const q = assetSearchEl && assetSearchEl.value ? assetSearchEl.value.trim() : "";
    const base = window.location.origin + "/assets";
    const url = q ? base + "?q=" + encodeURIComponent(q) : base;
    setAssetVaultStatus("Loading assets…");
    try {
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      const data = await res.json().catch(function () {
        return {};
      });
      if (!res.ok) {
        setAssetVaultStatus("HTTP " + res.status + " — could not list assets", true);
        return;
      }
      const items = Array.isArray(data.items) ? data.items : [];
      assetListEl.innerHTML = "";
      if (items.length === 0) {
        const li = document.createElement("li");
        li.className = "text-zinc-500 text-xs py-2";
        li.textContent = q ? "No matches for this search." : "No assets yet. Generate an invoice or add PDFs to vault/.";
        assetListEl.appendChild(li);
      } else {
        items.forEach(function (it) {
          const li = document.createElement("li");
          li.className =
            "flex flex-wrap items-center justify-between gap-2 rounded-md border border-zinc-800/60 bg-black/30 px-3 py-2";
          const left = document.createElement("div");
          left.className = "min-w-0 flex-1 flex items-start gap-2";
          const iconWrap = document.createElement("span");
          iconWrap.className = "mt-0.5 shrink-0";
          iconWrap.innerHTML = FOLDER_SVG;
          const textCol = document.createElement("div");
          textCol.className = "min-w-0 flex-1";
          const name = document.createElement("span");
          name.className = "font-mono text-xs text-neon-dim break-all";
          name.textContent = it.zone === "vault" ? "vault/" + it.relative_path : it.relative_path;
          const meta = document.createElement("div");
          meta.className = "mt-0.5 text-[11px] text-zinc-500";
          meta.textContent = (it.kind || "") + " · " + (it.mtime_iso || "").slice(0, 19) + "Z";
          textCol.appendChild(name);
          textCol.appendChild(meta);
          left.appendChild(iconWrap);
          left.appendChild(textCol);
          const href = absoluteAssetUrl(it.open_url || it.url || "#");
          const openA = document.createElement("a");
          openA.href = href;
          openA.target = "_blank";
          openA.rel = "noopener noreferrer";
          openA.className =
            "shrink-0 rounded-md border border-neon/40 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-neon hover:bg-neon/10";
          openA.textContent = it.name && /\.pdf$/i.test(it.name) ? "Open PDF" : "Open";
          const dl = document.createElement("a");
          dl.href = href;
          dl.download = it.name || "";
          dl.className =
            "shrink-0 rounded-md border border-zinc-600 px-3 py-1 text-xs uppercase tracking-wide text-zinc-400 hover:border-zinc-500";
          dl.textContent = "Download";
          li.appendChild(left);
          li.appendChild(openA);
          li.appendChild(dl);
          assetListEl.appendChild(li);
        });
      }
      setAssetVaultStatus(items.length + " asset(s)" + (q ? " (filtered)" : "") + ".");
    } catch (e) {
      console.error("[THIRAMAI] /assets", e);
      setAssetVaultStatus("Network error loading assets.", true);
    }
  }

  function scheduleAssetSearch() {
    if (assetSearchDebounce) clearTimeout(assetSearchDebounce);
    assetSearchDebounce = setTimeout(function () {
      loadAssets();
    }, 320);
  }

  function renderQuickActions(quickActions, options) {
    if (!quickActionsContainer || !quickActionsPanel) return;
    quickActionsContainer.innerHTML = "";
    if (!Array.isArray(quickActions) || quickActions.length === 0) {
      if (quickActionsPlaceholder) quickActionsPlaceholder.classList.remove("hidden");
      return;
    }
    if (quickActionsPlaceholder) quickActionsPlaceholder.classList.add("hidden");
    const invoiceLatest = options && options.invoiceLatest === true;
    quickActions.forEach(function (x) {
      const raw = x && x.url ? x.url : "#";
      const href = absoluteAssetUrl(raw);
      const kind = (x && x.kind ? String(x.kind) : "").toLowerCase();
      const isInvoice =
        kind === "invoice" ||
        kind === "pdf" ||
        (x && x.label && /\.pdf$/i.test(x.label) && String(x.label).toLowerCase().indexOf("inv") >= 0);
      let btnText = isInvoice ? "View Invoice" : "Click here to view";
      if (invoiceLatest) {
        btnText = "📄 VIEW LATEST INVOICE";
      }
      const a = document.createElement("a");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.className = "qa-neon-btn" + (invoiceLatest ? " qa-invoice-latest-btn" : "");
      a.setAttribute("role", "button");
      const span = document.createElement("span");
      span.textContent = btnText;
      a.appendChild(span);
      const sub = document.createElement("span");
      sub.className = "font-mono text-[10px] font-normal normal-case tracking-normal text-neon-dim/90 max-w-[14rem] truncate";
      sub.textContent = x && x.label ? x.label : "";
      if (sub.textContent) a.appendChild(sub);
      quickActionsContainer.appendChild(a);
      if (invoiceLatest && a.classList.contains("qa-invoice-latest-btn")) {
        a.classList.add("qa-just-created");
        setTimeout(function () {
          a.classList.remove("qa-just-created");
        }, 2200);
      }
    });
  }

  function applyChatQuickActions(data) {
    const qa = data && data.quick_actions;
    if (Array.isArray(qa) && qa.length > 0) {
      renderQuickActions(qa);
      return;
    }
    if (data && data.quick_action && data.quick_action.url) {
      renderQuickActions([
        {
          url: data.quick_action.url,
          label: data.quick_action.label || "invoice.pdf",
          kind: "invoice",
        },
      ]);
    }
  }

  function formatInvoiceApiError(data, status) {
    if (data && typeof data.message === "string" && data.message.trim()) return data.message.trim();
    if (data && data.detail) {
      if (typeof data.detail === "string") return data.detail;
      try {
        return JSON.stringify(data.detail);
      } catch (err) {
        return String(data.detail);
      }
    }
    return "Error creating invoice (HTTP " + status + ").";
  }

  function markdownInvoiceSuccessLines(quickActions) {
    const lines = ["**PDF links**"];
    (quickActions || []).forEach(function (x) {
      const u = absoluteAssetUrl(x && x.url ? x.url : "#");
      lines.push("- [View Invoice Here](" + u + ")");
    });
    return lines.join("\n");
  }

  async function generateInvoiceFromForm(ev) {
    if (ev) {
      ev.preventDefault();
      ev.stopPropagation();
    }

    function byId(id) {
      return document.getElementById(id);
    }

    const check = validateInvoiceForm();
    if (!check.ok) {
      setStatus(check.message, true);
      if (assetVaultStatusEl) {
        assetVaultStatusEl.textContent = check.message;
        assetVaultStatusEl.classList.add("text-red-400");
      }
      showErrorModal("Invalid invoice form", check.message);
      return;
    }

    const elLen = byId("invLength");
    const elWt = byId("invWeight");
    const elRate = byId("invRate");
    const elGrade = byId("invGrade");
    const elBuyer = byId("invBuyer");

    const len = parseFloat(String(elLen && elLen.value ? elLen.value : "0").replace(/,/g, ""));
    const wt = parseFloat(String(elWt && elWt.value ? elWt.value : "0").replace(/,/g, ""));
    const rate = parseFloat(String(elRate && elRate.value ? elRate.value : "0").replace(/,/g, ""));
    const grade = (elGrade && elGrade.value ? elGrade.value : "").trim();
    const buyer = (elBuyer && elBuyer.value ? elBuyer.value : "").trim() || "Buyer";

    const payload = {
      length: len,
      grade: grade,
      weight: wt,
      rate: rate,
      buyer: buyer,
    };
    console.log("[THIRAMAI] Form Data Captured:", payload);

    const apiBase = window.location.origin;
    const postUrl = apiBase + "/assets/invoice";
    console.log("[THIRAMAI] POST", postUrl);

    setInvoiceLoading(true);
    setStatus("Creating invoice…");
    if (assetVaultStatusEl) {
      assetVaultStatusEl.classList.remove("text-red-400");
      assetVaultStatusEl.textContent = "Posting invoice…";
    }

    try {
      if (!getThiramaiJwt()) {
        const msg = "Sign in from the main app first (JWT missing). Invoice API requires owner/manager Bearer token.";
        setStatus(msg, true);
        if (assetVaultStatusEl) {
          assetVaultStatusEl.textContent = msg;
          assetVaultStatusEl.classList.add("text-red-400");
        }
        showErrorModal("Authentication required", msg);
        setInvoiceLoading(false);
        return;
      }
      const res = await fetch(postUrl, {
        method: "POST",
        headers: invoiceAuthHeaders(),
        body: JSON.stringify(payload),
      });
      let data = {};
      try {
        data = await res.json();
      } catch (parseErr) {
        console.error("[THIRAMAI] Invoice response not JSON", parseErr);
        data = {};
      }
      console.log("[THIRAMAI] Response Received:", res.status, data);

      if (!res.ok) {
        const errText = formatInvoiceApiError(data, res.status);
        setStatus("Error creating invoice: " + errText, true);
        if (assetVaultStatusEl) {
          assetVaultStatusEl.textContent = errText;
          assetVaultStatusEl.classList.add("text-red-400");
        }
        showErrorModal("Invoice could not be created", errText);
        await loadAssets();
        await loadFinancialSummary();
        return;
      }

      let qa = Array.isArray(data.quick_actions) ? data.quick_actions : [];
      if (qa.length === 0 && data.relative_path) {
        const rel = String(data.relative_path).replace(/\\/g, "/");
        qa = [{ label: "View Invoice", url: "/static/factory/" + rel.replace(/^\//, ""), kind: "pdf" }];
      }

      if (qa.length === 0) {
        const errText = "Server OK but missing quick_actions — check API JSON.";
        setStatus(errText, true);
        showErrorModal("Unexpected server response", errText);
        await loadAssets();
        await loadFinancialSummary();
        return;
      }

      const msg =
        typeof data.response === "string" && data.response.trim()
          ? data.response.trim()
          : "Invoice created successfully";

      renderQuickActions(qa, { invoiceLatest: true });
      hideLoading();
      renderReport("## " + msg + "\n\n" + markdownInvoiceSuccessLines(qa));
      setStatus("Invoice ready — open the glowing button above or links in the report.");
      if (assetVaultStatusEl) {
        assetVaultStatusEl.classList.remove("text-red-400");
      }
      showToast("Invoice created successfully.", "success");
      await loadAssets();
      await loadFinancialSummary();
    } catch (e) {
      console.error("[THIRAMAI] Invoice fetch error", e);
      const errText = e && e.message ? e.message : String(e);
      setStatus("Error creating invoice: " + errText, true);
      if (assetVaultStatusEl) {
        assetVaultStatusEl.textContent = errText;
        assetVaultStatusEl.classList.add("text-red-400");
      }
      showErrorModal(
        "Cannot reach the server",
        "The dashboard must be opened from the same host as the API (for example http://127.0.0.1:8000/dashboard).\n\n" +
          errText
      );
      await loadAssets();
      await loadFinancialSummary();
    } finally {
      setInvoiceLoading(false);
    }
  }

  function showPlaceholder(message) {
    hideLoading();
    if (placeholderEl) {
      placeholderEl.classList.remove("hidden");
      placeholderEl.textContent =
        message || "Awaiting directive. Your Markdown strategy report will render here.";
    }
    if (reportEl) {
      reportEl.classList.add("hidden");
      reportEl.innerHTML = "";
    }
    if (pdfBtn) pdfBtn.disabled = true;
    if (reportMetaEl) reportMetaEl.textContent = "";
  }

  async function runQuery() {
    const q = (queryEl && queryEl.value ? queryEl.value : "").trim();
    if (!q) {
      setStatus("Enter a query first.", true);
      alert("THIRAMAI: Type a query in the box first.");
      return;
    }

    if (q.length > MAX_QUERY_CHARS) {
      setStatus("Query exceeds " + MAX_QUERY_CHARS + " characters. Shorten your brief.", true);
      alert(
        "THIRAMAI: Your query is longer than " +
          MAX_QUERY_CHARS +
          " characters. Please shorten it and try again."
      );
      return;
    }

    if (executeBtn) executeBtn.disabled = true;
    if (pdfBtn) pdfBtn.disabled = true;
    if (q.length > MAX_QUERY_CHARS - 500) {
      setStatus("Approaching " + MAX_QUERY_CHARS + " character limit. THIRAMAI IS SYNTHESIZING...", false, true);
    } else {
      setStatus("THIRAMAI IS SYNTHESIZING…");
    }
    if (reportMetaEl) reportMetaEl.textContent = "";
    showLoading();

    const url = buildChatUrl(q);
    console.log("[THIRAMAI] GET", url);

    try {
      const res = await fetch(url, {
        method: "GET",
        headers: { Accept: "application/json" },
      });

      let data = {};
      try {
        data = await res.json();
      } catch (parseErr) {
        console.error("[THIRAMAI] Response is not JSON", parseErr);
        const errMsg = "Server returned non-JSON (HTTP " + res.status + ")";
        alert("THIRAMAI /chat error:\n" + errMsg);
        hideLoading();
        showPlaceholder("Bad response — see alert.");
        setStatus(errMsg, true);
        return;
      }

      if (!res.ok) {
        const detail =
          typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
        const errMsg = "HTTP " + res.status + " — " + detail;
        console.error("[THIRAMAI] /chat failed:", errMsg);
        alert("THIRAMAI /chat failed:\n\n" + errMsg);
        hideLoading();
        showPlaceholder("Request failed — see alert.");
        setStatus(errMsg, true);
        return;
      }

      const text = data.response;
      if (typeof text !== "string" || !text.trim()) {
        const errMsg = "JSON missing non-empty 'response' string";
        console.error("[THIRAMAI]", errMsg, data);
        alert("THIRAMAI: " + errMsg + "\n\nCheck server logs.");
        hideLoading();
        showPlaceholder("Invalid JSON shape.");
        setStatus(errMsg, true);
        return;
      }

      renderReport(text);
      applyChatQuickActions(data);
      const words = text.trim().split(/\s+/).length;
      if (reportMetaEl) reportMetaEl.textContent = text.length + " chars · ~" + words + " words";
      setStatus("Report ready.");
      loadAssets();
    } catch (e) {
      const errMsg = e && e.message ? e.message : String(e);
      console.error("[THIRAMAI] Fetch/network error:", e);
      alert("THIRAMAI fetch failed (network or CORS):\n\n" + errMsg + "\n\nOpen /dashboard from the same host as the API (e.g. http://localhost:8000/dashboard).");
      hideLoading();
      showPlaceholder("Network error — see alert.");
      setStatus(errMsg, true);
    } finally {
      if (executeBtn) executeBtn.disabled = false;
      loadAssets();
    }
  }

  function downloadPdf() {
    if (!pdfBtn || pdfBtn.disabled || !reportEl || !reportEl.innerHTML.trim()) return;
    if (typeof html2pdf === "undefined") {
      const msg = "PDF library not loaded";
      console.error("[THIRAMAI]", msg);
      alert(msg);
      return;
    }
    setStatus("Building PDF…");
    const clone = reportEl.cloneNode(true);
    clone.classList.remove("hidden");
    clone.style.padding = "24px";
    clone.style.background = "#030303";
    clone.style.color = "#e4e4e7";
    const wrap = document.createElement("div");
    wrap.style.width = "210mm";
    wrap.style.boxSizing = "border-box";
    wrap.appendChild(clone);
    html2pdf()
      .set({
        margin: [10, 10, 10, 10],
        filename: "THIRAMAI_Strategy_Report.pdf",
        image: { type: "jpeg", quality: 0.95 },
        html2canvas: { scale: 2, useCORS: true, backgroundColor: "#030303" },
        jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
        pagebreak: { mode: ["css", "legacy"] },
      })
      .from(wrap)
      .save()
      .then(() => setStatus("PDF downloaded."))
      .catch((err) => {
        console.error("[THIRAMAI] PDF error", err);
        alert("PDF error: " + (err && err.message ? err.message : String(err)));
      });
  }

  if (executeBtn) {
    executeBtn.addEventListener("click", function (e) {
      e.preventDefault();
      console.log("Execute Button Clicked!");
      runQuery();
    });
  } else {
    console.error("[THIRAMAI] #executeBtn not found — wire-up failed.");
    alert("THIRAMAI: Button #executeBtn not found. Check index.html.");
  }

  if (pdfBtn) {
    pdfBtn.addEventListener("click", function () {
      downloadPdf();
    });
  }

  if (queryEl) {
    queryEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        runQuery();
      }
    });
  }

  if (assetSearchEl) {
    assetSearchEl.addEventListener("input", function () {
      scheduleAssetSearch();
    });
  }
  if (assetRefreshBtn) {
    assetRefreshBtn.addEventListener("click", function () {
      loadAssets();
      loadFinancialSummary();
    });
  }

  if (invoiceGenerateBtn) {
    invoiceGenerateBtn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      void generateInvoiceFromForm(e);
    });
  } else {
    console.error(
      "[THIRAMAI] #invoiceGenerateBtn not found — load /dashboard from FastAPI (e.g. http://127.0.0.1:8000/dashboard)."
    );
  }

  /* --- Digital Twin (Phase 5): simulated IoT + control panel --- */
  let twinUiSyncFromServer = false;
  let twinCriticalLatched = false;
  const twinLineBadge = $("twinLineBadge");
  const twinHydraulicNote = $("twinHydraulicNote");
  const twinTemp = $("twinTemp");
  const twinPressure = $("twinPressure");
  const twinRpm = $("twinRpm");
  const twinPower = $("twinPower");
  const twinKgHr = $("twinKgHr");
  const twinStock = $("twinStock");
  const twinBtnStart = $("twinBtnStart");
  const twinBtnStop = $("twinBtnStop");
  const twinHydraulicFixed = $("twinHydraulicFixed");
  const twinMaintenance = $("twinMaintenance");
  const twinControlStatus = $("twinControlStatus");

  function setTwinLed(stage, color) {
    const el = document.querySelector('[data-twin-led="' + stage + '"]');
    if (!el) return;
    el.classList.remove("twin-led--green", "twin-led--red", "twin-led--yellow", "twin-led--dim");
    if (color === "green" || color === "red" || color === "yellow") {
      el.classList.add("twin-led--" + color);
    } else {
      el.classList.add("twin-led--dim");
    }
  }

  function applyTwinPayload(data) {
    if (!data || typeof data !== "object") return;
    const stages = data.stages && typeof data.stages === "object" ? data.stages : {};
    [
      "hopper",
      "extruder",
      "die",
      "cooling_tank",
      "haul_off",
      "cutter",
    ].forEach(function (key) {
      const c = stages[key];
      if (c === "green" || c === "red" || c === "yellow") setTwinLed(key, c);
      else setTwinLed(key, "dim");
    });
    const s = data.sensors && typeof data.sensors === "object" ? data.sensors : {};
    if (twinTemp) twinTemp.textContent = (s.temperature_c != null ? s.temperature_c : "--") + " °C";
    if (twinPressure) twinPressure.textContent = (s.pressure_bar != null ? s.pressure_bar : "--") + " bar";
    if (twinRpm) twinRpm.textContent = (s.screw_rpm != null ? s.screw_rpm : "--") + " RPM";
    if (twinPower) twinPower.textContent = (s.power_kw != null ? s.power_kw : "--") + " kW";
    if (twinLineBadge) {
      twinLineBadge.textContent = "Line: " + String(data.line_mode || "--").toUpperCase();
    }
    if (twinHydraulicNote) {
      twinHydraulicNote.textContent = data.hydraulic_gate_reason ? String(data.hydraulic_gate_reason) : "";
    }
    if (twinKgHr) twinKgHr.textContent = data.production_kg_hr != null ? String(data.production_kg_hr) : "--";
    if (twinStock) twinStock.textContent = data.estimated_stock_kg != null ? String(data.estimated_stock_kg) : "--";
    if (perfStock && data.estimated_stock_kg != null) {
      perfStock.textContent = inrDisplay.format(data.estimated_stock_kg) + " kg";
    }

    const tgrid = document.querySelector(".twin-sensor-grid");
    if (tgrid) {
      tgrid.classList.toggle("twin-sensor-running", data.line_mode === "running");
    }

    twinUiSyncFromServer = true;
    if (twinHydraulicFixed) twinHydraulicFixed.checked = !!data.hydraulic_fixed;
    if (twinMaintenance) twinMaintenance.checked = !!data.maintenance_mode;
    twinUiSyncFromServer = false;

    if (data.critical_temperature) {
      if (!twinCriticalLatched) {
        twinCriticalLatched = true;
        showToast(
          "Critical alert: extruder temperature exceeded 210 °C — check cooling and barrel zones.",
          "critical"
        );
      }
    } else {
      twinCriticalLatched = false;
    }
  }

  async function fetchTwinLive() {
    try {
      const res = await fetch(window.location.origin + "/factory/live-status", {
        headers: { Accept: "application/json" },
      });
      const data = await res.json().catch(function () {
        return null;
      });
      if (res.ok && data) applyTwinPayload(data);
      else if (twinControlStatus) twinControlStatus.textContent = "Twin offline (HTTP " + res.status + ").";
    } catch (err) {
      if (twinControlStatus) twinControlStatus.textContent = "Twin poll failed — same-origin API required.";
    }
  }

  async function postTwinControl(payload) {
    try {
      const res = await fetch(window.location.origin + "/factory/twin-control", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(function () {
        return null;
      });
      if (res.ok && data) {
        applyTwinPayload(data);
        if (twinControlStatus) {
          twinControlStatus.textContent = "Control applied.";
          setTimeout(function () {
            if (twinControlStatus) twinControlStatus.textContent = "";
          }, 2200);
        }
        loadFinancialSummary();
      } else if (twinControlStatus) {
        twinControlStatus.textContent = "Control rejected (HTTP " + res.status + ").";
      }
    } catch (err) {
      if (twinControlStatus) twinControlStatus.textContent = "Control request failed.";
    }
  }

  if (twinBtnStart) {
    twinBtnStart.addEventListener("click", function () {
      postTwinControl({ operator_running: true });
    });
  }
  if (twinBtnStop) {
    twinBtnStop.addEventListener("click", function () {
      postTwinControl({ operator_running: false });
    });
  }
  if (twinHydraulicFixed) {
    twinHydraulicFixed.addEventListener("change", function () {
      if (twinUiSyncFromServer) return;
      postTwinControl({ hydraulic_fixed: !!twinHydraulicFixed.checked });
    });
  }
  if (twinMaintenance) {
    twinMaintenance.addEventListener("change", function () {
      if (twinUiSyncFromServer) return;
      postTwinControl({ maintenance_mode: !!twinMaintenance.checked });
    });
  }

  if ($("digital-twin-section")) {
    setInterval(fetchTwinLive, 5000);
    fetchTwinLive();
  }

  function setAiSuccessRing(pct) {
    const ring = $("aiRingProgress");
    if (!ring) return;
    const r = 44;
    const c = 2 * Math.PI * r;
    const p = Math.max(0, Math.min(100, Number(pct) || 0));
    ring.setAttribute("stroke-dasharray", String(c));
    ring.setAttribute("stroke-dashoffset", String(c * (1 - p / 100)));
  }

  function loadEmpireLab() {
    const pctEl = $("aiSuccessPct");
    const det = $("aiTrainingDetail");
    const scrapBig = $("aiScrapBig");
    const scrapDate = $("aiScrapDate");
    const scrapRef = $("aiScrapRef");
    const term = $("aiSimTerminal");
    const base = window.location.origin + "/empire/lab-status";
    fetch(base, { headers: { Accept: "application/json" } })
      .then(function (res) {
        return res.json().catch(function () {
          return null;
        });
      })
      .then(function (data) {
        if (!data || typeof data !== "object") {
          if (pctEl) pctEl.textContent = "--";
          if (term) term.textContent = "[SIM] Lab status unavailable.";
          setAiSuccessRing(0);
          return;
        }
        const t = data.robot_training;
        const si = data.scrap_inventory;
        let pct = null;
        if (t) {
          if (t.success_rate_pct != null) pct = Number(t.success_rate_pct);
          else if (t.success_rate != null) pct = Number(t.success_rate) * 100;
        }
        if (pct != null && !isNaN(pct)) {
          if (pctEl) pctEl.textContent = tonnageDisplay.format(pct) + "%";
          setAiSuccessRing(pct);
          const ic = t.iteration_count != null ? t.iteration_count : t.trials;
          if (det) {
            det.textContent =
              "iteration_count " +
              String(ic) +
              " · failure_point_newtons (mean) " +
              String(t.failure_point_newtons != null ? t.failure_point_newtons : "—") +
              " · PE100 μ " +
              String(t.mean_pe100_criterion_score != null ? t.mean_pe100_criterion_score : "—");
          }
          const tail = t.trial_log_tail;
          if (term) {
            if (Array.isArray(tail) && tail.length) {
              term.textContent = tail.join("\n");
            } else {
              term.textContent =
                "[SIM] Trial " +
                String(ic || 0) +
                ": (no tail in JSON — re-run python factory/robot_training_sim.py)";
            }
          }
        } else {
          if (pctEl) pctEl.textContent = "--";
          setAiSuccessRing(0);
          if (det) {
            det.textContent =
              "Run python factory/robot_training_sim.py to write vault/rd_core/robot_training_last.json.";
          }
          if (term) {
            term.textContent =
              "[SIM] No training batch yet.\n[SIM] Run: python factory/robot_training_sim.py";
          }
        }
        const scrapKg =
          si && si.total_scrap_kg != null
            ? Number(si.total_scrap_kg)
            : si && si.high_quality_scrap_kg != null
              ? Number(si.high_quality_scrap_kg)
              : null;
        if (scrapKg != null && !isNaN(scrapKg) && scrapBig) {
          scrapBig.textContent = tonnageDisplay.format(scrapKg) + " kg";
        } else if (scrapBig) {
          scrapBig.textContent = "-- kg";
        }
        if (scrapDate) {
          scrapDate.textContent =
            "last_updated: " + (si && si.last_updated != null ? String(si.last_updated) : "—");
        }
        if (scrapRef) {
          scrapRef.textContent =
            "Twin RUNNING profile · ~" +
            String(si && si.nominal_kg_hr_ref != null ? si.nominal_kg_hr_ref : 100) +
            " kg/hr nominal · HQRS = 2% of production mass.";
        }

        const fab = data.fabrication;
        const fabLab = $("fabQueueProgressLabel");
        const fabBar = $("fabQueueProgressFill");
        const fabMeta = $("fabQueueJobMeta");
        const fabEst = $("fabPrintSuccessEst");
        const fabG = $("fabGcodeMini");
        if (fab && typeof fab === "object") {
          const fp = fab.active_job ? Number(fab.simulated_print_progress_pct) : 0;
          const fpn = Math.max(0, Math.min(100, fp));
          if (fabLab) fabLab.textContent = "3D Printing… " + String(fpn) + "%";
          if (fabBar) fabBar.style.width = fpn + "%";
          if (fabEst) {
            if (fab.print_success_estimate_pct != null && !isNaN(Number(fab.print_success_estimate_pct))) {
              fabEst.textContent = String(fab.print_success_estimate_pct) + "%";
            } else {
              fabEst.textContent = "—";
            }
          }
          const aj = fab.active_job;
          if (fabMeta) {
            if (aj && typeof aj === "object") {
              fabMeta.textContent =
                String(aj.part_label || aj.part_id || "Job") +
                " · ~" +
                String(aj.estimated_print_minutes != null ? aj.estimated_print_minutes : "?") +
                " min · nozzle " +
                String(aj.nozzle_c != null ? aj.nozzle_c : 215) +
                "°C · PE100 " +
                String(aj.pe100_consumed_kg != null ? aj.pe100_consumed_kg : "?") +
                " kg";
            } else {
              fabMeta.textContent = "No active job — run python factory/fab_engine.py to enqueue Bushing-Joint V1.";
            }
          }
          if (fabG) {
            const gt = fab.gcode_tail;
            if (Array.isArray(gt) && gt.length) fabG.textContent = gt.join("\n");
            else fabG.textContent = "; No G-code manifest in fab_queue yet — run fab_engine.py";
          }
        }
      })
      .catch(function () {
        if (pctEl) pctEl.textContent = "--";
        setAiSuccessRing(0);
        if (term) term.textContent = "[SIM] Network error loading /empire/lab-status.";
      });
  }

  (function setupEmpireTabs() {
    const btnC = $("tabBtnCommand");
    const btnV = $("tabBtnVision");
    const panC = $("empire-panel-command");
    const panV = $("empire-panel-vision");
    if (!btnC || !btnV || !panC || !panV) return;
    function activateCommand() {
      panC.classList.remove("hidden");
      panV.classList.add("hidden");
      btnC.setAttribute("aria-selected", "true");
      btnV.setAttribute("aria-selected", "false");
      btnC.classList.add("empire-tab--active", "border-neon/35", "bg-zinc-900/80", "text-neon");
      btnC.classList.remove("border-transparent", "text-zinc-500");
      btnV.classList.remove("empire-tab--active", "border-neon/35", "bg-zinc-900/80", "text-neon");
      btnV.classList.add("border-transparent", "text-zinc-500");
    }
    function activateVision() {
      panV.classList.remove("hidden");
      panC.classList.add("hidden");
      btnV.setAttribute("aria-selected", "true");
      btnC.setAttribute("aria-selected", "false");
      btnV.classList.add("empire-tab--active", "border-neon/35", "bg-zinc-900/80", "text-amber-300");
      btnV.classList.remove("border-transparent", "text-zinc-500");
      btnC.classList.remove("empire-tab--active", "border-neon/35", "bg-zinc-900/80", "text-neon");
      btnC.classList.add("border-transparent", "text-zinc-500");
      loadEmpireLab();
    }
    btnC.addEventListener("click", activateCommand);
    btnV.addEventListener("click", activateVision);
  })();

  showPlaceholder(null);
  loadAssets();
  loadFinancialSummary();
});
