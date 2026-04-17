import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import api from "../api/client";

const TABS = ["overview", "monitor", "errors", "diagnosis", "autofix"];

function normalizeString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function bandFromWorkspaceThresholds(score, riskProfile, fallbackBand = "") {
  if (typeof score !== "number" || !riskProfile) {
    return normalizeString(fallbackBand);
  }
  const autoFixBelow = Number(riskProfile.auto_fix_below);
  const requireApprovalAbove = Number(riskProfile.require_approval_above);
  if (score <= autoFixBelow) return "low";
  if (score <= requireApprovalAbove) return "medium";
  return "high";
}

function normalizeMonitorReport(item) {
  const report = item?.monitor_report_json || {};
  return {
    name: normalizeString(report.name || item?.workflow_name || ""),
    branch: normalizeString(report.branch || item?.branch || ""),
    status: normalizeString(report.status || item?.health_status || "FAILURE").toUpperCase(),
    time: normalizeString(report.time || item?.updated_at || ""),
    error: normalizeString(report.error || ""),
  };
}

function normalizeDiagnosisReport(item) {
  const report = item?.diagnosis_report_json || {};
  const risk = item?.risk_report_json || {};
  const riskInputs = item?.risk_inputs_json || {};
  return {
    name: normalizeString(report.name || item?.workflow_name || ""),
    commitTitle: normalizeString(item?.commit_title || report.name || item?.workflow_name || ""),
    branch: normalizeString(item?.display_branch || report.branch || item?.branch || ""),
    issuePreview: normalizeString(item?.issue_preview || ""),
    errorType: normalizeString(report.error_type || ""),
    possibleCauses: Array.isArray(report.possible_causes) ? report.possible_causes.filter((entry) => typeof entry === "string" && entry.trim()) : [],
    latestWorkingChange: normalizeString(report.latest_working_change || ""),
    riskScore: typeof risk.risk_score === "number" ? risk.risk_score : item?.risk_score,
    riskBand: normalizeString(risk.risk_band || item?.risk_band || ""),
    scoreBreakdown: Array.isArray(riskInputs.score_breakdown) ? riskInputs.score_breakdown.filter((entry) => entry && typeof entry === "object") : [],
    summary: normalizeString(risk.plain_english_summary || ""),
    recommendedAction: normalizeString(risk.recommended_action || ""),
    reversibilityNote: normalizeString(risk.reversibility_note || ""),
    autofixStatus: normalizeString(item?.autofix_status || ""),
    autofixMode: normalizeString(item?.autofix_mode || ""),
    autofixReportUrl: normalizeString(item?.autofix_report_url || ""),
    autofixPrUrl: normalizeString(item?.autofix_pr_url || ""),
    autofixError: normalizeString(item?.autofix_error || ""),
    autofixFeedbackUrl: normalizeString(item?.autofix_feedback_url || ""),
    autofixFeedbackStatus: normalizeString(item?.autofix_feedback_status || ""),
  };
}

function normalizeAutofixReport(item) {
  return {
    id: normalizeString(item?.id || ""),
    workflowName: normalizeString(item?.workflow_name || ""),
    branch: normalizeString(item?.branch || item?.target_branch || ""),
    mode: normalizeString(item?.mode || ""),
    status: normalizeString(item?.execution_status || ""),
    riskScore: typeof item?.risk_score === "number" ? item.risk_score : null,
    summary: normalizeString(item?.fix_summary || ""),
    prUrl: normalizeString(item?.pr_url || ""),
    reportUrl: normalizeString(item?.report_url || ""),
    feedbackUrl: normalizeString(item?.resolution_feedback_url || ""),
    feedbackStatus: normalizeString(item?.resolution_feedback_status || ""),
    loopBlockedReason: normalizeString(item?.loop_blocked_reason || ""),
    updatedAt: normalizeString(item?.updated_at || ""),
  };
}

function StatusPill({ value }) {
  const normalized = (value || "unknown").toLowerCase();
  return <span className={`status-pill ${normalized}`}>{value || "unknown"}</span>;
}

function RiskBadge({ score, band, error }) {
  if (error) {
    return (
      <div className="risk-badge" style={{ borderColor: "var(--red-5)", color: "var(--red-11)" }}>
        <strong>ERR</strong>
        <span>Risk failed</span>
      </div>
    );
  }

  const normalizedBand = normalizeString(band).toLowerCase() || "unknown";
  const scoreLabel = typeof score === "number" ? score : "--";

  return (
    <div className={`risk-badge ${normalizedBand}`}>
      <strong>{scoreLabel}</strong>
      <span>{normalizedBand === "unknown" ? "Risk pending" : `${normalizedBand} risk`}</span>
    </div>
  );
}

export default function WorkspacePage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);
  const [backfillingRisk, setBackfillingRisk] = useState(false);
  const [runningAutofixById, setRunningAutofixById] = useState({});
  const [backfillMessage, setBackfillMessage] = useState("");
  const [autofixMessage, setAutofixMessage] = useState("");
  const [expandedDiagnosisId, setExpandedDiagnosisId] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");

  const [isEditingPolicy, setIsEditingPolicy] = useState(false);
  const [policyForm, setPolicyForm] = useState({
    auto_fix_below: 30,
    require_approval_above: 60,
    production_branch: "main"
  });
  const [policyError, setPolicyError] = useState("");

  const installationState = searchParams.get("installation");
  const setupAction = searchParams.get("setup_action");

  const fetchDashboard = async () => {
    try {
      const { data } = await api.get(`/workspaces/${id}/repository-dashboard`);
      setDashboard(data);
    } catch (err) {
      console.error("Failed to load repository dashboard", err);
      setDashboard(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboard();
    const intervalId = window.setInterval(() => {
      fetchDashboard();
    }, 6000);

    const onFocus = () => {
      fetchDashboard();
    };

    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", onFocus);
    };
  }, [id]);

  const beginInstallFlow = () => {
    window.open(`/api/workspaces/${id}/github/install`, "_blank");
  };

  const disconnectInstallation = async () => {
    if (!confirm("Disconnect the GitHub App from this workspace?")) return;

    setDisconnecting(true);
    try {
      await api.delete(`/workspaces/${id}/github/installation`);
      await fetchDashboard();
    } catch (err) {
      console.error("Failed to disconnect GitHub App", err);
    } finally {
      setDisconnecting(false);
    }
  };

  const backfillRiskReports = async () => {
    setBackfillMessage("");
    setBackfillingRisk(true);
    try {
      const { data } = await api.post(`/workspaces/${id}/diagnosis/backfill-risk`);
      await fetchDashboard();
      setBackfillMessage(`Risk backfill complete: updated ${data.updated} of ${data.processed} diagnosis reports.`);
    } catch (err) {
      console.error("Failed to backfill risk reports", err);
      const detail = err?.response?.data?.detail;
      setBackfillMessage(typeof detail === "string" ? detail : "Failed to backfill risk reports.");
    } finally {
      setBackfillingRisk(false);
    }
  };

  const runAutofixForDiagnosis = async (pipelineRunId) => {
    if (!pipelineRunId) return;
    if (!workspace?.slack_devops_mention) {
      const mention = window.prompt("Enter the DevOps engineer Slack mention (example: @alice or <@U12345>) for auto-fix notifications:");
      if (!mention || !mention.trim()) {
        setAutofixMessage("Auto-fix requires a DevOps Slack mention before notifications can be sent.");
        return;
      }
      try {
        await api.put(`/workspaces/${id}`, { slack_devops_mention: mention.trim() });
      } catch (err) {
        const detail = err?.response?.data?.detail;
        setAutofixMessage(typeof detail === "string" ? detail : "Failed to save DevOps Slack mention.");
        return;
      }
    }
    setAutofixMessage("");
    setRunningAutofixById((prev) => ({ ...prev, [pipelineRunId]: true }));
    try {
      await api.post(`/workspaces/${id}/diagnosis/${pipelineRunId}/run-autofix`);
      await fetchDashboard();
      setAutofixMessage("Auto-fix reprocessing started for the selected diagnosis report.");
    } catch (err) {
      console.error("Failed to run auto-fix for diagnosis report", err);
      const detail = err?.response?.data?.detail;
      setAutofixMessage(typeof detail === "string" ? detail : "Failed to run auto-fix for this diagnosis report.");
    } finally {
      setRunningAutofixById((prev) => {
        const next = { ...prev };
        delete next[pipelineRunId];
        return next;
      });
    }
  };

  const handleEditPolicyClick = () => {
    setPolicyForm({
      auto_fix_below: dashboard?.workspace?.risk_profile?.auto_fix_below ?? 30,
      require_approval_above: dashboard?.workspace?.risk_profile?.require_approval_above ?? 60,
      production_branch: dashboard?.workspace?.risk_profile?.production_branch || dashboard?.workspace?.github_default_branch || "main"
    });
    setPolicyError("");
    setIsEditingPolicy(true);
  };

  const handleSavePolicy = async (e) => {
    e.preventDefault();
    setPolicyError("");
    const data = {
      risk_profile: {
        auto_fix_below: Number(policyForm.auto_fix_below),
        require_approval_above: Number(policyForm.require_approval_above),
        production_branch: policyForm.production_branch
      }
    };
    if (data.risk_profile.auto_fix_below >= data.risk_profile.require_approval_above) {
      setPolicyError("Auto-merge value must be strictly less than manual approval value.");
      return;
    }
    try {
      await api.put(`/workspaces/${id}`, data);
      await fetchDashboard();
      setIsEditingPolicy(false);
    } catch (err) {
      setPolicyError(err?.response?.data?.detail || "Failed to update risk profile");
    }
  };

  const workspace = dashboard?.workspace;
  const health = dashboard?.health;
  const monitorLogs = dashboard?.monitor_logs || [];
  const errors = dashboard?.errors || [];
  const diagnosisReports = dashboard?.diagnosis_reports || [];
  const autofixReports = dashboard?.autofix_reports || [];

  useEffect(() => {
    if (!diagnosisReports.some((item) => item.id === expandedDiagnosisId)) {
      setExpandedDiagnosisId(null);
    }
  }, [diagnosisReports, expandedDiagnosisId]);

  const activeTabContent = useMemo(() => {
    if (!dashboard || !workspace) return null;

    if (activeTab === "monitor") {
      return monitorLogs.length ? (
        <div className="dashboard-feed">
          {monitorLogs.map((item) => {
            const report = normalizeMonitorReport(item);
            return (
              <article key={item.id} className="feed-card">
                <div className="feed-card-top">
                  <div>
                    <h3>{report.name || "workflow_run"}</h3>
                    <p>{report.branch || "unknown branch"}</p>
                  </div>
                  <StatusPill value={report.status} />
                </div>

                <div className="report-kv-grid">
                  <div className="report-kv-card">
                    <span>Workflow</span>
                    <strong>{report.name || "n/a"}</strong>
                  </div>
                  <div className="report-kv-card">
                    <span>Branch</span>
                    <strong>{report.branch || "n/a"}</strong>
                  </div>
                  <div className="report-kv-card">
                    <span>Time</span>
                    <strong>{report.time ? new Date(report.time).toLocaleString() : "n/a"}</strong>
                  </div>
                </div>

                {report.status === "FAILURE" && report.error ? (
                  <section className="report-section full">
                    <h4>Error</h4>
                    <pre className="log-preview">{report.error}</pre>
                  </section>
                ) : null}

                <div className="feed-meta">
                  <span>Monitor agent: {item.monitor_provider || "deterministic"}</span>
                  <span>{new Date(item.updated_at).toLocaleString()}</span>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-inline">No monitor activity yet for this repository.</div>
      );
    }

    if (activeTab === "errors") {
      return errors.length ? (
        <div className="dashboard-feed">
          {errors.map((item) => (
            <article key={item.id} className="feed-card error">
              <div className="feed-card-top">
                <div>
                  <h3>{item.workflow_name || item.event_type}</h3>
                  <p>{item.branch || "unknown branch"}</p>
                </div>
                <StatusPill value={item.conclusion || item.health_status} />
              </div>
              <p className="feed-summary">{item.error_summary || item.monitor_summary || "No error summary captured yet."}</p>
              {item.diagnosis_error ? <p className="inline-error">Diagnosis status: {item.diagnosis_error}</p> : null}
              <div className="feed-meta">
                <span>Diagnosis: {item.diagnosis_status}</span>
                <span>{new Date(item.updated_at).toLocaleString()}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-inline">No failing runs are currently recorded for this repository.</div>
      );
    }

    if (activeTab === "diagnosis") {
      return (
        <div className="diagnosis-tab">
          <div className="diagnosis-toolbar">
            <div>
              <h3>Diagnosis Reports</h3>
              <p>Fetch current compare context and backfill risk scores for older diagnosis records.</p>
            </div>
            <button type="button" className="btn-secondary" onClick={backfillRiskReports} disabled={backfillingRisk || !diagnosisReports.length}>
              {backfillingRisk ? "Backfilling risk…" : "Backfill Risk Scores"}
            </button>
          </div>

          {backfillMessage ? <div className="notice-banner success subtle">{backfillMessage}</div> : null}
          {autofixMessage ? <div className="notice-banner subtle">{autofixMessage}</div> : null}

          {diagnosisReports.length ? (
            <div className="dashboard-feed">
              {diagnosisReports.map((item) => {
                const report = normalizeDiagnosisReport(item);
                const isExpanded = expandedDiagnosisId === item.id;
                const canRunAutofix = item.health_status === "failing" && item.diagnosis_status === "completed";
                const isRunningAutofix = Boolean(runningAutofixById[item.id]);
                const effectiveRiskBand = bandFromWorkspaceThresholds(report.riskScore, workspace.risk_profile, report.riskBand);
                return (
                  <article key={item.id} className={`feed-card diagnosis ${isExpanded ? "expanded" : "collapsed"}`}>
                    <div className="diagnosis-accordion-header">
                      <div className="diagnosis-accordion-summary">
                        <div>
                          <h3>{report.commitTitle || "Unknown commit"}</h3>
                          <p>{report.branch || "unknown branch"}</p>
                        </div>
                        <p className="diagnosis-issue-preview">{report.issuePreview || report.errorType || "No issue summary captured."}</p>
                      </div>
                      <div className="diagnosis-card-top-right accordion-actions">
                        <RiskBadge score={report.riskScore} band={effectiveRiskBand} error={item.risk_error} />
                        <div className="accordion-meta">
                          <StatusPill value={item.diagnosis_status} />
                          <button
                            type="button"
                            className="btn-secondary"
                            disabled={!canRunAutofix || isRunningAutofix}
                            onClick={() => runAutofixForDiagnosis(item.id)}
                          >
                            {isRunningAutofix ? "Running Auto-fix…" : "Run Auto-fix"}
                          </button>
                          <button
                            type="button"
                            className="accordion-toggle"
                            onClick={() => setExpandedDiagnosisId(isExpanded ? null : item.id)}
                          >
                            {isExpanded ? "Collapse" : "Expand"}
                          </button>
                        </div>
                      </div>
                    </div>

                    {isExpanded ? (
                      <>
                        {item.risk_error ? (
                          <p className="inline-error inline-risk-error">Risk calculation failed: {item.risk_error}</p>
                        ) : null}

                        <div className="diagnosis-facts">
                          <span className="diag-chip">Error: {report.errorType || "unknown"}</span>
                          {report.recommendedAction ? <span className="diag-chip">Action: {report.recommendedAction.replaceAll("_", " ")}</span> : null}
                        </div>

                        <section className="report-section full">
                          <h4>Possible causes</h4>
                          <ul>
                            {report.possibleCauses.length ? (
                              report.possibleCauses.map((cause, index) => <li key={`${item.id}-cause-${index}`}>{cause}</li>)
                            ) : (
                              <li>No causes captured.</li>
                            )}
                          </ul>
                        </section>

                        <section className="report-section full">
                          <h4>Latest working change</h4>
                          <p>{report.latestWorkingChange || "No diff summary captured."}</p>
                        </section>

                        {report.summary ? (
                          <section className="report-section full">
                            <h4>Risk summary</h4>
                            <p>{report.summary}</p>
                          </section>
                        ) : null}

                        {report.scoreBreakdown.length ? (
                          <section className="report-section full">
                            <h4>Risk score breakdown</h4>
                            <div className="risk-breakdown-table">
                              <div className="risk-breakdown-header">
                                <span>Factor</span>
                                <span>Observed value</span>
                                <span>Points</span>
                              </div>
                              {report.scoreBreakdown.map((entry, index) => (
                                <div key={`${item.id}-breakdown-${index}`} className="risk-breakdown-row">
                                  <span>{normalizeString(entry.title || entry.label || "Factor")}</span>
                                  <span>{normalizeString(entry.value || entry.detail || "-")}</span>
                                  <strong className={Number(entry.points) > 0 ? "positive" : Number(entry.points) < 0 ? "negative" : ""}>
                                    {Number(entry.points) > 0 ? `+${entry.points}` : `${entry.points ?? 0}`}
                                  </strong>
                                </div>
                              ))}
                            </div>
                          </section>
                        ) : null}

                        {report.reversibilityNote ? (
                          <section className="report-section full">
                            <h4>Rollback note</h4>
                            <p>{report.reversibilityNote}</p>
                          </section>
                        ) : null}

                        {report.autofixStatus ? (
                          <section className="report-section full">
                            <h4>Auto-fix workflow</h4>
                            <p>Mode: {report.autofixMode || "n/a"} | Status: {report.autofixStatus}</p>
                            {report.autofixError ? <p>{report.autofixError}</p> : null}
                            {report.autofixPrUrl ? <p><a href={report.autofixPrUrl} target="_blank" rel="noreferrer">Open PR</a></p> : null}
                            {report.autofixMode !== "auto_merge" && report.autofixReportUrl ? <p><a href={report.autofixReportUrl} target="_blank" rel="noreferrer">Open signed report</a></p> : null}
                            {report.autofixMode !== "auto_merge" && report.autofixFeedbackUrl ? <p><a href={report.autofixFeedbackUrl} target="_blank" rel="noreferrer">Open feedback form</a></p> : null}
                            {report.autofixFeedbackStatus ? <p>Feedback: {report.autofixFeedbackStatus}</p> : null}
                          </section>
                        ) : null}

                        <div className="feed-meta">
                          <span>
                            Diagnosis agent: {item.diagnosis_provider || "pending"}
                            {item.risk_provider ? ` • Risk agent: ${item.risk_provider}` : ""}
                          </span>
                          <span>{new Date(item.updated_at).toLocaleString()}</span>
                        </div>
                      </>
                    ) : null}
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="empty-inline">Diagnosis reports appear only after a failure.</div>
          )}
        </div>
      );
    }

    if (activeTab === "autofix") {
      return autofixReports.length ? (
        <div className="dashboard-feed">
          {autofixReports.map((item) => {
            const report = normalizeAutofixReport(item);
            return (
              <article key={report.id || item.id} className="feed-card diagnosis">
                <div className="feed-card-top">
                  <div>
                    <h3>{report.workflowName || "workflow_run"}</h3>
                    <p>{report.branch || "unknown branch"}</p>
                  </div>
                  <StatusPill value={report.status || "unknown"} />
                </div>

                <div className="report-kv-grid">
                  <div className="report-kv-card">
                    <span>Mode</span>
                    <strong>{report.mode || "n/a"}</strong>
                  </div>
                  <div className="report-kv-card">
                    <span>Risk score</span>
                    <strong>{typeof report.riskScore === "number" ? report.riskScore : "n/a"}</strong>
                  </div>
                  <div className="report-kv-card">
                    <span>Updated</span>
                    <strong>{report.updatedAt ? new Date(report.updatedAt).toLocaleString() : "n/a"}</strong>
                  </div>
                  <div className="report-kv-card">
                    <span>Feedback</span>
                    <strong>{report.feedbackStatus || "not requested"}</strong>
                  </div>
                </div>

                <section className="report-section full">
                  <h4>Summary</h4>
                  <p>{report.summary || "No fix summary captured."}</p>
                </section>

                {report.loopBlockedReason ? (
                  <p className="inline-error">{report.loopBlockedReason}</p>
                ) : null}

                <div className="workspace-actions" style={{ marginTop: "8px" }}>
                  {report.prUrl ? (
                    <a className="btn-secondary" href={report.prUrl} target="_blank" rel="noreferrer">Open PR</a>
                  ) : null}
                  {report.mode !== "auto_merge" && report.reportUrl ? (
                    <a className="btn-secondary" href={report.reportUrl} target="_blank" rel="noreferrer">Open Signed Report</a>
                  ) : null}
                  {report.mode !== "auto_merge" && report.feedbackUrl ? (
                    <a className="btn-secondary" href={report.feedbackUrl} target="_blank" rel="noreferrer">Open Feedback Form</a>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-inline">No auto-fix reports yet. Run Auto-fix from a diagnosis card to generate one.</div>
      );
    }

    return (
      <div className="workspace-overview-grid">
        <article className="workspace-panel">
          <div className="panel-heading">
            <h2>Repository connection</h2>
            <p>Repository access is scoped to the GitHub App installation selected for this workspace.</p>
          </div>
          {workspace.connected ? (
            <div className="connection-summary">
              <div className="summary-item">
                <span>Repository</span>
                <strong>{workspace.github_repo_full_name}</strong>
              </div>
              <div className="summary-item">
                <span>Default branch</span>
                <strong>{workspace.github_default_branch || "main"}</strong>
              </div>
              <div className="summary-item">
                <span>Installation ID</span>
                <strong>{workspace.github_installation_id}</strong>
              </div>
              <div className="summary-item">
                <span>Connected at</span>
                <strong>{workspace.connected_at ? new Date(workspace.connected_at).toLocaleString() : "Pending"}</strong>
              </div>
            </div>
          ) : (
            <div className="empty-inline">No repository is connected yet. Install the GitHub App to start receiving workflow reports.</div>
          )}
        </article>

        <article className="workspace-panel">
          <div className="panel-heading">
            <h2>Pipeline health summary</h2>
            <p>Minimal event-driven view built only from completed workflow runs.</p>
          </div>
          <div className="health-grid">
            <div className="health-card">
              <span>Current status</span>
              <strong>{health?.status || "unknown"}</strong>
            </div>
            <div className="health-card">
              <span>Total runs</span>
              <strong>{health?.total_events ?? 0}</strong>
            </div>
            <div className="health-card">
              <span>Failures</span>
              <strong>{health?.failing_count ?? 0}</strong>
            </div>
            <div className="health-card">
              <span>Successes</span>
              <strong>{health?.healthy_count ?? 0}</strong>
            </div>
          </div>
        </article>

        <article className="workspace-panel">
          <div className="panel-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <h2>Auto-fix policy</h2>
              <p>These workspace thresholds decide whether PipelineIQ auto-merges, opens a PR for approval, or only produces a signed review report.</p>
            </div>
            {!isEditingPolicy && (
              <button className="btn-secondary" onClick={handleEditPolicyClick}>
                Edit Policy
              </button>
            )}
          </div>
          {isEditingPolicy ? (
            <form onSubmit={handleSavePolicy} className="auth-form" style={{ maxWidth: "400px", marginTop: "1rem" }}>
              {policyError && <div className="notice-banner warning">{policyError}</div>}
              <div className="form-group">
                <label>Auto-merge up to</label>
                <input 
                  type="number" 
                  value={policyForm.auto_fix_below} 
                  onChange={(e) => setPolicyForm({...policyForm, auto_fix_below: e.target.value})}
                  min="1" max="100" required 
                />
              </div>
              <div className="form-group">
                <label>Manual approval up to</label>
                <input 
                  type="number" 
                  value={policyForm.require_approval_above} 
                  onChange={(e) => setPolicyForm({...policyForm, require_approval_above: e.target.value})}
                  min="1" max="100" required 
                />
              </div>
              <div className="form-group">
                <label>Protected branch</label>
                <input 
                  type="text" 
                  value={policyForm.production_branch} 
                  onChange={(e) => setPolicyForm({...policyForm, production_branch: e.target.value})}
                  required 
                />
              </div>
              <div className="workspace-actions" style={{ marginTop: "1rem" }}>
                <button type="submit" className="btn-primary">Save Changes</button>
                <button type="button" className="btn-secondary" onClick={() => setIsEditingPolicy(false)}>Cancel</button>
              </div>
            </form>
          ) : (
            <div className="connection-summary">
              <div className="summary-item">
                <span>Auto-merge up to</span>
                <strong>{workspace.risk_profile?.auto_fix_below ?? 30}</strong>
              </div>
              <div className="summary-item">
                <span>Manual approval up to</span>
                <strong>{workspace.risk_profile?.require_approval_above ?? 60}</strong>
              </div>
              <div className="summary-item">
                <span>Report only above</span>
                <strong>{workspace.risk_profile?.require_approval_above ?? 60}</strong>
              </div>
              <div className="summary-item">
                <span>Protected branch</span>
                <strong>{workspace.risk_profile?.production_branch || workspace.github_default_branch || "main"}</strong>
              </div>
            </div>
          )}
        </article>
      </div>
    );
  }, [activeTab, autofixReports, backfillMessage, backfillingRisk, dashboard, diagnosisReports, errors, expandedDiagnosisId, health, monitorLogs, workspace, isEditingPolicy, policyForm, policyError]);

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loader" />
      </div>
    );
  }

  if (!dashboard || !workspace) {
    return (
      <div className="dashboard-page">
        <div className="empty-state">
          <h2>Workspace not found</h2>
          <Link to="/dashboard" className="btn-primary">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-page">
      <header className="workspace-header">
        <div className="workspace-header-left">
          <Link to="/dashboard" className="back-link">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            Dashboard
          </Link>
          <h1>{workspace.name}</h1>
          <p className="workspace-description">
            {workspace.github_repo_full_name
              ? `Repository dashboard for ${workspace.github_repo_full_name}`
              : "Connect a repository to activate workflow monitoring and diagnosis reporting."}
          </p>
        </div>
        <div className="workspace-actions">
          <button className="btn-primary" onClick={beginInstallFlow}>
            {workspace.connected ? "Reconfigure Repository" : "Add Repository"}
          </button>
          {workspace.connected ? (
            <Link to="/dashboard" className="btn-secondary">
              View Dashboard
            </Link>
          ) : null}
          {workspace.connected ? (
            <button className="btn-secondary" onClick={disconnectInstallation} disabled={disconnecting}>
              {disconnecting ? "Disconnecting…" : "Disconnect"}
            </button>
          ) : null}
        </div>
      </header>

      {installationState === "success" ? (
        <div className="notice-banner success">
          GitHub App installation {setupAction === "update" ? "updated" : "completed"} for this repository dashboard.
        </div>
      ) : null}

      {installationState && installationState !== "success" ? (
        <div className="notice-banner warning">
          GitHub App setup did not finish cleanly. Try the install flow again from this page.
        </div>
      ) : null}

      {workspace.connected && (
        <section className="dashboard-kpis">
          <article className="kpi-card">
            <span>Latest status</span>
            <strong>{health?.status || "unknown"}</strong>
            <p>{health?.latest_conclusion ? `Latest conclusion: ${health.latest_conclusion}` : "No completed runs yet."}</p>
          </article>
          <article className="kpi-card">
            <span>Completed runs</span>
            <strong>{monitorLogs.length}</strong>
            <p>Only completed workflow_run events are counted.</p>
          </article>
          <article className="kpi-card">
            <span>Failures</span>
            <strong>{errors.length}</strong>
            <p>Diagnosis is triggered only after a failure.</p>
          </article>
          <article className="kpi-card">
            <span>Auto-fix reports</span>
            <strong>{autofixReports.length}</strong>
            <p>Manual runs and generated signed reports appear in the Auto-fix tab.</p>
          </article>
        </section>
      )}

      <section className="workspace-panel">
        {workspace.connected && (
          <div className="dashboard-tabs">
            {TABS.map((tab) => (
              <button key={tab} type="button" className={`dashboard-tab ${activeTab === tab ? "active" : ""}`} onClick={() => setActiveTab(tab)}>
                {tab}
              </button>
            ))}
          </div>
        )}
        <div className="tab-panel">{activeTabContent}</div>
      </section>
    </div>
  );
}
