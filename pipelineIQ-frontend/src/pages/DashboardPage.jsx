import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import api from "../api/client";
import WorkspaceCard from "../components/WorkspaceCard";
import Modal from "../components/Modal";

export default function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [productionBranch, setProductionBranch] = useState("main");
  const [requireApprovalAbove, setRequireApprovalAbove] = useState(60);
  const [autoFixBelow, setAutoFixBelow] = useState(30);
  const [creating, setCreating] = useState(false);

  const fetchWorkspaces = async () => {
    try {
      const { data } = await api.get("/workspaces");
      setWorkspaces(data);
    } catch (err) {
      console.error("Failed to load workspaces", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWorkspaces();
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!formName.trim()) return;
    setCreating(true);
    try {
      const { data } = await api.post("/workspaces", {
        name: formName.trim(),
        description: formDesc.trim() || null,
        risk_profile: {
          production_branch: productionBranch.trim() || "main",
          require_approval_above: Number(requireApprovalAbove),
          auto_fix_below: Number(autoFixBelow),
        },
      });
      setFormName("");
      setFormDesc("");
      setProductionBranch("main");
      setRequireApprovalAbove(60);
      setAutoFixBelow(30);
      setShowCreate(false);
      navigate(`/workspace/${data.id}`);
    } catch (err) {
      console.error("Failed to create workspace", err);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this workspace and all connected repos?")) return;
    try {
      await api.delete(`/workspaces/${id}`);
      setWorkspaces((prev) => prev.filter((w) => w.id !== id));
    } catch (err) {
      console.error("Failed to delete workspace", err);
    }
  };

  const installationNotice = searchParams.get("installation");

  return (
    <div className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h1>
            Welcome back,{" "}
            <span className="gradient-text">
              {user?.display_name || user?.username}
            </span>
          </h1>
          <p className="dashboard-subtitle">
            Review your GitHub orgs, create a workspace, and connect a repository through the GitHub App install flow.
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => setShowCreate(true)}
          id="create-workspace-btn"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New Workspace
        </button>
      </header>

      {installationNotice && installationNotice !== "success" && (
        <div className="notice-banner warning">
          GitHub App setup was interrupted. Open a workspace and try the repository connection again.
        </div>
      )}

      <section className="dashboard-section">
        <div className="section-heading">
          <h2>Your GitHub organizations</h2>
          <p>These come from GitHub OAuth using the `read:user` and `read:org` scopes.</p>
        </div>

        {user?.organizations?.length ? (
          <div className="org-grid">
            {user.organizations.map((org) => (
              <article key={org.id} className="org-card">
                <img src={org.avatar_url} alt={org.login} className="org-avatar" />
                <div>
                  <h3>{org.login}</h3>
                  <p>{org.description || "GitHub organization available to this account."}</p>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-inline">
            No organizations were returned for this GitHub account. You can still create a workspace and install the GitHub App on a personal repository.
          </div>
        )}
      </section>

      <section className="dashboard-section">
        <div className="section-heading">
          <h2>Workspaces</h2>
          <p>Each workspace stores one GitHub App installation context, one primary repository, and your risk profile thresholds.</p>
        </div>

        {loading ? (
          <div className="loading-screen">
            <div className="loader" />
          </div>
        ) : workspaces.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" opacity="0.4">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                <line x1="8" y1="21" x2="16" y2="21" />
                <line x1="12" y1="17" x2="12" y2="21" />
              </svg>
            </div>
            <h2>No workspaces yet</h2>
            <p>Create your first workspace, define the risk profile, then install the GitHub App on the repository you want to monitor.</p>
            <button className="btn-primary" onClick={() => setShowCreate(true)}>
              Create Workspace
            </button>
          </div>
        ) : (
          <div className="workspace-grid">
            {workspaces.map((ws) => (
              <WorkspaceCard
                key={ws.id}
                workspace={ws}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </section>

      {/* Create Workspace Modal */}
      <Modal
        isOpen={showCreate}
        onClose={() => setShowCreate(false)}
        title="Create Workspace"
      >
        <form onSubmit={handleCreate} className="modal-form">
          <div className="form-group">
            <label htmlFor="ws-name">Name</label>
            <input
              id="ws-name"
              type="text"
              placeholder="My Awesome Project"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              autoFocus
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="ws-desc">Description (optional)</label>
            <textarea
              id="ws-desc"
              placeholder="What's this workspace for?"
              value={formDesc}
              onChange={(e) => setFormDesc(e.target.value)}
              rows={3}
            />
          </div>
          <div className="form-grid">
            <div className="form-group">
              <label htmlFor="branch-name">Production branch</label>
              <input
                id="branch-name"
                type="text"
                value={productionBranch}
                onChange={(e) => setProductionBranch(e.target.value)}
                placeholder="main"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="approval-threshold">Require approval above</label>
              <input
                id="approval-threshold"
                type="number"
                min="0"
                max="100"
                value={requireApprovalAbove}
                onChange={(e) => setRequireApprovalAbove(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="autofix-threshold">Auto-fix below</label>
              <input
                id="autofix-threshold"
                type="number"
                min="0"
                max="100"
                value={autoFixBelow}
                onChange={(e) => setAutoFixBelow(e.target.value)}
                required
              />
            </div>
          </div>
          <div className="modal-actions">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setShowCreate(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={creating || !formName.trim()}
            >
              {creating ? "Creating…" : "Create"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
