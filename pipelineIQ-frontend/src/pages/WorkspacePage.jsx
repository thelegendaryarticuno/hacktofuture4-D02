import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import api from "../api/client";

export default function WorkspacePage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const [workspace, setWorkspace] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState(false);

  const installationState = searchParams.get("installation");
  const setupAction = searchParams.get("setup_action");

  const fetchWorkspace = async () => {
    try {
      const { data } = await api.get(`/workspaces/${id}`);
      setWorkspace(data);
      if (data.github_installation_id) {
        const eventsResponse = await api.get(`/workspaces/${id}/github/events`);
        setEvents(eventsResponse.data);
      } else {
        setEvents([]);
      }
    } catch (err) {
      console.error("Failed to load workspace", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWorkspace();
  }, [id]);

  const beginInstallFlow = () => {
    window.location.href = `/api/workspaces/${id}/github/install`;
  };

  const disconnectInstallation = async () => {
    if (!confirm("Disconnect the GitHub App from this workspace?")) return;

    setDisconnecting(true);
    try {
      await api.delete(`/workspaces/${id}/github/installation`);
      await fetchWorkspace();
    } catch (err) {
      console.error("Failed to disconnect GitHub App", err);
    } finally {
      setDisconnecting(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loader" />
      </div>
    );
  }

  if (!workspace) {
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
            {workspace.description ||
              "Workspace for GitHub App installation, webhook intake, and downstream agent processing."}
          </p>
        </div>
        <div className="workspace-actions">
          <button className="btn-primary" onClick={beginInstallFlow}>
            {workspace.connected ? "Reconfigure Repository" : "Add Repository"}
          </button>
          {workspace.connected && (
            <button
              className="btn-secondary"
              onClick={disconnectInstallation}
              disabled={disconnecting}
            >
              {disconnecting ? "Disconnecting…" : "Disconnect"}
            </button>
          )}
        </div>
      </header>

      {installationState === "success" && (
        <div className="notice-banner success">
          GitHub App installation {setupAction === "update" ? "updated" : "completed"} for this workspace.
        </div>
      )}

      {installationState && installationState !== "success" && (
        <div className="notice-banner warning">
          GitHub App setup did not finish cleanly. Try the install flow again from this workspace.
        </div>
      )}

      <section className="workspace-panel-grid">
        <article className="workspace-panel">
          <div className="panel-heading">
            <h2>Repository connection</h2>
            <p>This connection is granted through the GitHub App installation, not the user OAuth token.</p>
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
                <span>GitHub account</span>
                <strong>
                  {workspace.github_account_login || "Unknown"}{" "}
                  {workspace.github_account_type ? `(${workspace.github_account_type})` : ""}
                </strong>
              </div>
              <div className="summary-item">
                <span>Visibility</span>
                <strong>{workspace.github_repo_private ? "Private" : "Public"}</strong>
              </div>
              <div className="summary-item">
                <span>Connected at</span>
                <strong>
                  {workspace.connected_at
                    ? new Date(workspace.connected_at).toLocaleString()
                    : "Pending"}
                </strong>
              </div>
              {workspace.github_repo_html_url && (
                <a
                  className="repo-inline-link"
                  href={workspace.github_repo_html_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open repository on GitHub
                </a>
              )}
            </div>
          ) : (
            <div className="empty-inline">
              No repository is connected yet. Use the button above to open the GitHub App installation flow and grant access to the repository you want this workspace to monitor.
            </div>
          )}
        </article>

        <article className="workspace-panel">
          <div className="panel-heading">
            <h2>Risk profile</h2>
            <p>These thresholds drive how your agents can escalate, request approval, or attempt safe fixes.</p>
          </div>

          <div className="risk-grid">
            <div className="risk-card">
              <span>Production branch</span>
              <strong>{workspace.risk_profile.production_branch}</strong>
            </div>
            <div className="risk-card">
              <span>Require approval above</span>
              <strong>{workspace.risk_profile.require_approval_above}</strong>
            </div>
            <div className="risk-card">
              <span>Auto-fix below</span>
              <strong>{workspace.risk_profile.auto_fix_below}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="workspace-panel">
        <div className="panel-heading">
          <h2>Webhook monitor</h2>
          <p>Once the GitHub App is installed, GitHub sends events like `workflow_run`, `workflow_job`, `push`, and `check_run` directly to the backend webhook endpoint.</p>
        </div>

        {!workspace.connected ? (
          <div className="empty-inline">
            Install the GitHub App first. After that, webhook deliveries will start appearing here for your future diagnosis and monitor agents.
          </div>
        ) : events.length === 0 ? (
          <div className="empty-inline">
            The GitHub App is connected. Webhook deliveries have not arrived yet, or the repository has not produced new activity since installation.
          </div>
        ) : (
          <div className="event-list">
            {events.map((event) => (
              <article key={event.delivery_id} className="event-card">
                <div>
                  <span className="event-type">{event.event_type}</span>
                  {event.action && <span className="event-action">{event.action}</span>}
                </div>
                <p>{event.repository_full_name || workspace.github_repo_full_name}</p>
                <time>{new Date(event.received_at).toLocaleString()}</time>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
