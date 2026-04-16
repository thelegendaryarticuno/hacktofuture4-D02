import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import api from "../api/client";

const TABS = ["overview", "monitor", "errors", "diagnosis"];

function normalizeString(value) {
  return typeof value === "string" ? value.trim() : "";
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
  return {
    name: normalizeString(report.name || item?.workflow_name || ""),
    branch: normalizeString(report.branch || item?.branch || ""),
    errorType: normalizeString(report.error_type || ""),
    possibleCauses: Array.isArray(report.possible_causes) ? report.possible_causes.filter((entry) => typeof entry === "string" && entry.trim()) : [],
    latestWorkingChange: normalizeString(report.latest_working_change || ""),
  };
}

function StatusPill({ value }) {
  const normalized = (value || "unknown").toLowerCase();
  return <span className={`status-pill ${normalized}`}>{value || "unknown"}</span>;
}

export default function WorkspacePage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);
  const [activeTab, setActiveTab] = useState("overview");

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

  const workspace = dashboard?.workspace;
  const health = dashboard?.health;
  const monitorLogs = dashboard?.monitor_logs || [];
  const errors = dashboard?.errors || [];
  const diagnosisReports = dashboard?.diagnosis_reports || [];

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
      return diagnosisReports.length ? (
        <div className="dashboard-feed">
          {diagnosisReports.map((item) => {
            const report = normalizeDiagnosisReport(item);
            return (
              <article key={item.id} className="feed-card diagnosis">
                <div className="feed-card-top">
                  <div>
                    <h3>{report.name || "workflow_run"}</h3>
                    <p>{report.branch || "unknown branch"}</p>
                  </div>
                  <StatusPill value={item.diagnosis_status} />
                </div>

                <div className="diagnosis-facts">
                  <span className="diag-chip">Error: {report.errorType || "unknown"}</span>
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

                <div className="feed-meta">
                  <span>Diagnosis agent: {item.diagnosis_provider || "pending"}</span>
                  <span>{new Date(item.updated_at).toLocaleString()}</span>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-inline">Diagnosis reports appear only after a failure.</div>
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
      </div>
    );
  }, [activeTab, dashboard, diagnosisReports, errors, health, monitorLogs, workspace]);

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
            <span>Reports</span>
            <strong>{diagnosisReports.length}</strong>
            <p>Failure reports show a short cause list and latest working change.</p>
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
