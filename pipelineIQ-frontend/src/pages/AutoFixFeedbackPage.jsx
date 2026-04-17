import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api from "../api/client";

const OUTCOME_OPTIONS = [
  { value: "resolved", label: "Resolved completely" },
  { value: "partially_resolved", label: "Partially resolved" },
  { value: "not_resolved", label: "Did not resolve it" },
];

const QUALITY_OPTIONS = [
  { value: "excellent", label: "Excellent" },
  { value: "acceptable", label: "Acceptable" },
  { value: "poor", label: "Poor" },
];

export default function AutoFixFeedbackPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [form, setForm] = useState({
    outcome: "resolved",
    automation_quality: "acceptable",
    should_auto_apply_similar: true,
    notes: "",
  });

  useEffect(() => {
    const fetchFeedback = async () => {
      if (!token) {
        setError("Missing feedback token.");
        setLoading(false);
        return;
      }
      try {
        const response = await api.get("/autofix/feedback", { params: { token } });
        setData(response.data);
        const feedback = response.data.feedback || {};
        if (feedback.status === "submitted") {
          setForm({
            outcome: feedback.outcome || "resolved",
            automation_quality: feedback.automation_quality || "acceptable",
            should_auto_apply_similar: typeof feedback.should_auto_apply_similar === "boolean" ? feedback.should_auto_apply_similar : true,
            notes: feedback.notes || "",
          });
        }
      } catch (err) {
        setError(err?.response?.data?.detail || "Failed to load auto-fix feedback form.");
      } finally {
        setLoading(false);
      }
    };
    fetchFeedback();
  }, [token]);

  const submitFeedback = async () => {
    setSubmitting(true);
    setMessage("");
    try {
      await api.post(`/autofix/feedback?token=${encodeURIComponent(token)}`, form);
      setMessage("Thanks. This feedback has been saved and will be used to improve future auto-fix suggestions.");
      const refreshed = await api.get("/autofix/feedback", { params: { token } });
      setData(refreshed.data);
    } catch (err) {
      setMessage(err?.response?.data?.detail || "Failed to submit feedback.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loader" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="dashboard-page">
        <div className="empty-state">
          <h2>Auto-fix feedback unavailable</h2>
          <p>{error || "This feedback form could not be loaded."}</p>
          <Link to="/" className="btn-primary">Home</Link>
        </div>
      </div>
    );
  }

  const feedback = data.feedback || {};
  const execution = data.execution || {};
  const pipelineRun = data.pipeline_run || {};
  const alreadySubmitted = feedback.status === "submitted";

  return (
    <div className="dashboard-page autofix-report-page">
      <section className="workspace-panel">
        <div className="panel-heading">
          <h2>PipelineIQ Auto-fix Feedback</h2>
          <p>Share how this merged auto-fix worked in production so future fixes get smarter.</p>
        </div>

        <div className="report-kv-grid">
          <div className="report-kv-card">
            <span>Repository</span>
            <strong>{pipelineRun.repository_full_name || "n/a"}</strong>
          </div>
          <div className="report-kv-card">
            <span>Workflow</span>
            <strong>{pipelineRun.workflow_name || "workflow_run"}</strong>
          </div>
          <div className="report-kv-card">
            <span>Branch</span>
            <strong>{execution.target_branch || pipelineRun.branch || "n/a"}</strong>
          </div>
          <div className="report-kv-card">
            <span>Risk score</span>
            <strong>{typeof execution.risk_score === "number" ? execution.risk_score : "n/a"}</strong>
          </div>
        </div>

        <section className="report-section full">
          <h4>Fix summary</h4>
          <p>{execution.fix_summary || "No fix summary captured."}</p>
          {execution.pr_url ? <p><a href={execution.pr_url} target="_blank" rel="noreferrer">Open merged PR</a></p> : null}
        </section>

        <section className="report-section full">
          <h4>Outcome</h4>
          <div className="autofix-feedback-options">
            {OUTCOME_OPTIONS.map((option) => (
              <label key={option.value} className="feedback-option">
                <input
                  type="radio"
                  name="outcome"
                  value={option.value}
                  checked={form.outcome === option.value}
                  disabled={alreadySubmitted || submitting}
                  onChange={(event) => setForm((prev) => ({ ...prev, outcome: event.target.value }))}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="report-section full">
          <h4>Automation quality</h4>
          <div className="autofix-feedback-options">
            {QUALITY_OPTIONS.map((option) => (
              <label key={option.value} className="feedback-option">
                <input
                  type="radio"
                  name="automation_quality"
                  value={option.value}
                  checked={form.automation_quality === option.value}
                  disabled={alreadySubmitted || submitting}
                  onChange={(event) => setForm((prev) => ({ ...prev, automation_quality: event.target.value }))}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="report-section full">
          <h4>Reuse similar fixes automatically?</h4>
          <div className="autofix-feedback-options">
            <label className="feedback-option">
              <input
                type="radio"
                name="should_auto_apply_similar"
                checked={form.should_auto_apply_similar === true}
                disabled={alreadySubmitted || submitting}
                onChange={() => setForm((prev) => ({ ...prev, should_auto_apply_similar: true }))}
              />
              <span>Yes, similar cases can be auto-applied</span>
            </label>
            <label className="feedback-option">
              <input
                type="radio"
                name="should_auto_apply_similar"
                checked={form.should_auto_apply_similar === false}
                disabled={alreadySubmitted || submitting}
                onChange={() => setForm((prev) => ({ ...prev, should_auto_apply_similar: false }))}
              />
              <span>No, keep similar cases manual</span>
            </label>
          </div>
        </section>

        <section className="report-section full">
          <h4>Engineer notes</h4>
          <textarea
            className="auth-input"
            rows={5}
            value={form.notes}
            disabled={alreadySubmitted || submitting}
            onChange={(event) => setForm((prev) => ({ ...prev, notes: event.target.value }))}
            placeholder="What went well, what was wrong, and what should the agent do differently next time?"
          />
        </section>

        {!alreadySubmitted ? (
          <div className="workspace-actions">
            <button className="btn-primary" disabled={submitting} onClick={submitFeedback}>
              {submitting ? "Submitting…" : "Submit feedback"}
            </button>
          </div>
        ) : (
          <div className="notice-banner success subtle">
            Feedback already submitted on {feedback.submitted_at ? new Date(feedback.submitted_at).toLocaleString() : "this execution"}.
          </div>
        )}

        {message ? <p style={{ marginTop: "12px" }}>{message}</p> : null}
      </section>
    </div>
  );
}
