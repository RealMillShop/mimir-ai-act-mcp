const form = document.getElementById("audit-form");
const submitBtn = document.getElementById("submit");
const resultSection = document.getElementById("result");
const summary = document.getElementById("result-summary");
const violationsList = document.getElementById("result-violations");
const recsDetails = document.getElementById("result-recommendations");
const disclaimerEl = document.getElementById("result-disclaimer");
const leadCta = document.getElementById("lead-cta");

const STATUS_LABEL = {
  compliant: "COMPLIANT",
  needs_review: "NEEDS REVIEW",
  non_compliant: "NON-COMPLIANT",
};

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const payload = {
    text: document.getElementById("text").value.trim(),
    deployment_type: document.getElementById("deployment_type").value,
  };
  if (!payload.text) return;

  submitBtn.disabled = true;
  submitBtn.textContent = "Auditing…";
  resultSection.hidden = true;
  leadCta.hidden = true;

  try {
    const res = await fetch("/api/ai-act-audit/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const report = await res.json();
    renderReport(report);
  } catch (err) {
    summary.innerHTML = `<strong>Error:</strong> ${escapeHtml(err.message)}`;
    violationsList.innerHTML = "";
    recsDetails.hidden = true;
    disclaimerEl.textContent = "";
    resultSection.hidden = false;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Audit";
  }
});

function renderReport(report) {
  const statusLabel = STATUS_LABEL[report.compliance_status] || report.compliance_status;

  summary.innerHTML =
    `<span class="status ${escapeHtml(report.compliance_status)}">${escapeHtml(statusLabel)}</span> ` +
    `· risk score <strong>${escapeHtml(String(report.risk_score))}/10</strong> ` +
    `· ${report.violations.length} violation${report.violations.length === 1 ? "" : "s"}`;

  violationsList.innerHTML = report.violations
    .map(
      (v) => `
    <li>
      <strong>${escapeHtml(v.title)}</strong>
      <span class="violation-severity ${escapeHtml(v.severity)}">${escapeHtml(v.severity)}</span>
      <span class="violation-id">${escapeHtml(v.violation_id)} · ${escapeHtml(v.article)} · in force ${escapeHtml(v.deadline)}</span>
      <p>${escapeHtml(v.explanation)}</p>
      <details><summary>Evidence</summary><blockquote>${escapeHtml(v.evidence)}</blockquote></details>
      <div class="fix"><strong>Fix:</strong> ${escapeHtml(v.suggested_fix)}</div>
    </li>`
    )
    .join("");

  if (report.general_recommendations && report.general_recommendations.length) {
    recsDetails.hidden = false;
    recsDetails.querySelector("ul").innerHTML = report.general_recommendations
      .map((r) => `<li>${escapeHtml(r)}</li>`)
      .join("");
  } else {
    recsDetails.hidden = true;
  }

  disclaimerEl.textContent = report.disclaimer;
  resultSection.hidden = false;
  leadCta.hidden = report.violations.length === 0;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
