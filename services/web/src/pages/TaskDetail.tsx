import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { usePoll } from "../usePoll";
import type { Attachment, Task, TaskEvent } from "../types";
import { Badge } from "./Queue";
import { ModelFields, modelSummary, useCatalogue, type ModelChoice } from "../components/ModelFields";

export default function TaskDetail() {
  const { id } = useParams();
  const task = usePoll<Task>(`/api/tasks/${id}`, 4000);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const last = useRef(0);
  const [msg, setMsg] = useState("");
  const cat = useCatalogue();
  const [editing, setEditing] = useState<ModelChoice | null>(null);

  useEffect(() => {
    last.current = 0;
    setEvents([]);
    let timer: ReturnType<typeof setTimeout>;
    let alive = true;
    const poll = async () => {
      try {
        const evs = await api<TaskEvent[]>(`/api/tasks/${id}/events?after=${last.current}`);
        if (alive && evs.length) {
          last.current = evs[evs.length - 1].id;
          setEvents((e) => [...e, ...evs]);
        }
      } catch {
        /* retry */
      }
      if (alive) timer = setTimeout(poll, 3000);
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id]);

  const t = task.data;
  if (task.error) return <p className="error">{task.error}</p>;
  if (!t) return <p>Loading…</p>;
  const attachments = Array.isArray(t.attachments) ? (t.attachments as Attachment[]) : [];

  const act = async (action: string) => {
    try {
      await api(`/api/tasks/${t.id}`, { method: "PATCH", json: { action } });
      task.reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const saveModel = async () => {
    if (!editing) return;
    try {
      await api(`/api/tasks/${t.id}`, {
        method: "PATCH",
        json: { ...editing, model_reason: `set by hand (was ${modelSummary(t, cat)})` },
      });
      setEditing(null);
      task.reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    await api(`/api/tasks/${t.id}/attachments`, { method: "POST", body: fd });
    task.reload();
  };
  const remove = async (aid: number) => {
    await api(`/api/tasks/${t.id}/attachments/${aid}`, { method: "DELETE" });
    task.reload();
  };

  return (
    <div className="stack">
      <p>
        <Link to="/queue">← Queue</Link>
      </p>
      <h1>
        #{t.id} {t.title} <Badge s={t.state} />
      </h1>
      <section className="card">
        <p style={{ whiteSpace: "pre-wrap" }}>{t.description || <span className="muted">No description.</span>}</p>
        <table>
          <tbody>
            <tr><th>Repository</th><td>{t.repo || "none"} → {t.base_branch}</td></tr>
            <tr><th>Branch</th><td>{t.branch || "—"}</td></tr>
            <tr><th>Pull request</th><td>{t.pr_url ? <a href={t.pr_url} target="_blank" rel="noreferrer">{t.pr_url}</a> : "—"}</td></tr>
            <tr><th>Deploy</th><td>{t.deploy_status || "—"}</td></tr>
            <tr>
              <th>Model</th>
              <td>
                {modelSummary(t, cat)}
                {t.model_reason && <div className="muted small">{t.model_reason}</div>}
                {editing ? (
                  <div className="stack">
                    <ModelFields value={editing} onChange={setEditing} />
                    <div className="actions">
                      <button onClick={saveModel}>Save</button>
                      <button className="secondary" onClick={() => setEditing(null)}>Cancel</button>
                    </div>
                    <p className="muted small">Applies the next time an agent starts this task.</p>
                  </div>
                ) : (
                  <button className="link" onClick={() => setEditing({ complexity: t.complexity, model: t.model, effort: t.effort })}>
                    Change
                  </button>
                )}
              </td>
            </tr>
            <tr><th>Agent</th><td>{t.worker_id || "—"} (provider: {t.provider})</td></tr>
            <tr><th>Attempts</th><td>{t.attempts}/{t.max_attempts}</td></tr>
            <tr><th>Priority</th><td>{t.priority}</td></tr>
            {t.last_error && <tr><th>Last error</th><td className="error">{t.last_error}</td></tr>}
          </tbody>
        </table>
        <div className="actions">
          {!["done", "cancelled"].includes(t.status) && <button className="secondary" onClick={() => act("cancel")}>Cancel</button>}
          {["needs_human", "failed", "cancelled", "done"].includes(t.status) && <button className="secondary" onClick={() => act("requeue")}>Requeue</button>}
          {t.status !== "done" && <button className="secondary" onClick={() => act("mark_done")}>Mark done</button>}
          {msg && <span className="error">{msg}</span>}
        </div>
      </section>
      <section className="card">
        <h2>Dependencies</h2>
        <div className="deps">
          {t.deps.length === 0 && <span className="muted">None</span>}
          {t.deps.map((d) => (
            <Link key={d.id} to={`/tasks/${d.id}`}><span className={`badge ${d.status}`}>#{d.id} {d.title} · {d.status}</span></Link>
          ))}
        </div>
        <h2>Waiting on this task</h2>
        <div className="deps">
          {(t.dependents ?? []).length === 0 && <span className="muted">None</span>}
          {(t.dependents ?? []).map((d) => (
            <Link key={d.id} to={`/tasks/${d.id}`}><span className={`badge ${d.status}`}>#{d.id} {d.title} · {d.status}</span></Link>
          ))}
        </div>
      </section>
      <section className="card">
        <h2>Files</h2>
        <p className="muted small">These are copied into the agent's workspace when the task is allocated.</p>
        <table>
          <tbody>
            {attachments.map((a) => (
              <tr key={a.id}>
                <td><a href={`/api/tasks/${t.id}/attachments/${a.id}/content`}>{a.filename}</a></td>
                <td>{(a.size / 1024).toFixed(1)} KB</td>
                <td><button className="link" onClick={() => remove(a.id)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <input type="file" multiple onChange={(e) => upload(e.target.files)} />
      </section>
      <section className="card">
        <h2>Activity and agent log</h2>
        <pre className="log">
          {events.map((e) => `${e.at.slice(0, 19).replace("T", " ")} ${e.kind.padEnd(6)} ${e.worker_id ? `[${e.worker_id}] ` : ""}${e.message}`).join("\n")}
        </pre>
      </section>
    </div>
  );
}
