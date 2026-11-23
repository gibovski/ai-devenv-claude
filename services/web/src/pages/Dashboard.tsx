import { Link } from "react-router-dom";
import { usePoll } from "../usePoll";
import type { AgentStatus } from "../types";

function ago(s: number) {
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

export default function Dashboard() {
  const { data, error } = usePoll<AgentStatus>("/api/agents", 3000);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading…</p>;
  const q = data.queue;
  return (
    <div className="stack">
      <h1>Agents</h1>
      <div className="summary">
        {(["idle", "busy", "error", "offline"] as const).map((k) => (
          <div key={k}>
            <b>{data.summary[k] ?? 0}</b>
            <span className={`badge ${k}`}>{k}</span>
          </div>
        ))}
        <div>
          <b>
            {data.online.claude ?? 0}/{data.desired.claude ?? 0}
          </b>
          Claude agents online
        </div>
        <div>
          <b>
            {data.online.codex ?? 0}/{data.desired.codex ?? 0}
          </b>
          Codex agents online
        </div>
        <div>
          <b>{q.queued ?? 0}</b>queued
        </div>
        <div>
          <b>{(q.in_progress ?? 0) + (q.in_review ?? 0) + (q.deploying ?? 0)}</b>in flight
        </div>
        <div>
          <b>{q.needs_human ?? 0}</b>need you
        </div>
      </div>
      {data.agents.length === 0 && (
        <p className="muted">
          No agents have registered yet. Set agent counts and API keys in <Link to="/settings">Settings</Link>, then <Link to="/apply">Apply</Link>.
        </p>
      )}
      <div className="tiles">
        {data.agents.map((a) => (
          <div className="tile" key={a.id}>
            <h3>
              <span>{a.id}</span>
              <span className={`badge ${a.status}`}>{a.status}</span>
            </h3>
            <span className="muted small">
              {a.provider} · {a.model || "default model"}
            </span>
            {a.current_task ? (
              <span>
                Working on <Link to={`/tasks/${a.current_task.id}`}>#{a.current_task.id} {a.current_task.title}</Link>
              </span>
            ) : (
              <span className="muted">{a.message || "No task"}</span>
            )}
            <span className="muted small">
              {a.tasks_done} done · {a.tasks_failed} failed · heartbeat {ago(a.last_heartbeat_seconds)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
