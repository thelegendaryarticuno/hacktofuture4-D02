import { Link } from "react-router-dom";

export default function WorkspaceCard({ workspace, onDelete }) {
  const statusLabel = workspace.connected
    ? "GitHub App connected"
    : "Needs repository connection";

  return (
    <div className="workspace-card">
      <div className="workspace-card-header">
        <div className="workspace-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
        </div>
        <button
          className="workspace-delete"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDelete(workspace.id);
          }}
          title="Delete workspace"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>
      </div>

      <Link to={`/workspace/${workspace.id}`} className="workspace-card-body">
        <h3>{workspace.name}</h3>
        <p className="workspace-desc">
          {workspace.description || "No description"}
        </p>
        <p className="workspace-repo">
          {workspace.github_repo_full_name || "No repository linked yet"}
        </p>
        <div className="workspace-meta">
          <span className={`repo-badge ${workspace.connected ? "connected" : "pending"}`}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 6 9 17l-5-5" />
            </svg>
            {statusLabel}
          </span>
          <span className="workspace-date">
            {new Date(workspace.created_at).toLocaleDateString()}
          </span>
        </div>
      </Link>
    </div>
  );
}
