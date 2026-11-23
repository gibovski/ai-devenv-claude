import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { usePoll } from "../usePoll";
import type { Task } from "../types";

const FILTERS = ["open", "all", "ready", "blocked", "in_progress", "in_review", "needs_human", "done"];

export function Badge({ s }: { s: string }) {
  return <span className={`badge ${s}`}>{s.replace("_", " ")}</span>;
}

function NewTask({ onCreated, tasks }: { onCreated: () => void; tasks: Task[] }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [repo, setRepo] = useState("");
  const [deps, setDeps] = useState<number[]>([]);
  const [files, setFiles] = useState<FileList | null>(null);
  const [msg, setMsg] = useState("");
  if (!open) return <button onClick={() => setOpen(true)}>New task</button>;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const t = await api<Task>("/api/tasks", { method: "POST", json: { title, description, repo, depends_on: deps } });
      if (files?.length) {
        const fd = new FormData();
        Array.from(files).forEach((f) => fd.append("files", f));
        await api(`/api/tasks/${t.id}/attachments`, { method: "POST", body: fd });
      }
      setTitle("");
      setDescription("");
      setDeps([]);
      setFiles(null);
      setOpen(false);
      onCreated();
    } catch (err) {
      setMsg((err as Error).message);
    }
  };
  return (
    <form className="card" onSubmit={submit}>
      <h2>New task</h2>
      <label>
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} required />
      </label>
      <label>
        Description
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label>
        Repository: name or owner/name, new:name to create one, blank for the default
        <input value={repo} placeholder="my-app, me/my-app or new:my-new-app" onChange={(e) => setRepo(e.target.value)} />
      </label>
      <label>
        Depends on
        <select multiple value={deps.map(String)} onChange={(e) => setDeps(Array.from(e.target.selectedOptions).map((o) => Number(o.value)))}>
          {tasks
            .filter((t) => t.status !== "cancelled")
            .map((t) => (
              <option key={t.id} value={t.id}>
                #{t.id} {t.title}
              </option>
            ))}
        </select>
      </label>
      <label>
        Files for the agent
        <input type="file" multiple onChange={(e) => setFiles(e.target.files)} />
      </label>
      {msg && <p className="error">{msg}</p>}
      <div className="actions">
        <button type="submit">Queue task</button>
        <button type="button" className="secondary" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ImportPlan({ onCreated }: { onCreated: () => void }) {
  const [msg, setMsg] = useState("");
  const upload = async (f: File | undefined) => {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await api<Task[]>("/api/tasks/import", { method: "POST", body: fd });
      setMsg(`Queued ${r.length} tasks.`);
      onCreated();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <label className="inline">
      <span className="muted">Import plan (YAML, JSON or TSV):</span>
      <input type="file" accept=".yaml,.yml,.json,.tsv,.txt" onChange={(e) => upload(e.target.files?.[0])} />
      {msg && <span>{msg}</span>}
    </label>
  );
}

export default function Queue() {
  const { data, error, reload } = usePoll<Task[]>("/api/tasks", 4000);
  const [filter, setFilter] = useState("open");
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>Loading…</p>;
  const shown = data.filter((t) => {
    if (filter === "all") return true;
    if (filter === "open") return !["done", "cancelled"].includes(t.status);
    return t.state === filter;
  });
  return (
    <div className="stack">
      <h1>Work queue</h1>
      <div className="actions">
        <NewTask onCreated={reload} tasks={data} />
        <ImportPlan onCreated={reload} />
      </div>
      <div className="actions">
        {FILTERS.map((f) => (
          <button key={f} className={f === filter ? "" : "secondary"} onClick={() => setFilter(f)}>
            {f.replace("_", " ")} ({f === "all" ? data.length : f === "open" ? data.filter((t) => !["done", "cancelled"].includes(t.status)).length : data.filter((t) => t.state === f).length})
          </button>
        ))}
      </div>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Task</th>
            <th>Status</th>
            <th>Dependencies</th>
            <th>Agent / PR</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((t) => (
            <tr key={t.id}>
              <td>{t.id}</td>
              <td>
                <Link to={`/tasks/${t.id}`}>{t.title}</Link>
                <div className="muted small">
                  {t.description.slice(0, 140)}
                  {t.description.length > 140 && "…"}
                </div>
                <div className="muted small">
                  {t.repo || "no repo"} {typeof t.attachments === "number" && t.attachments > 0 && `· 📎 ${t.attachments}`}
                </div>
              </td>
              <td>
                <Badge s={t.state} />
                {t.attempts > 0 && <div className="muted small">attempt {t.attempts}/{t.max_attempts}</div>}
              </td>
              <td>
                <div className="deps">
                  {t.deps.length === 0 && <span className="muted">none</span>}
                  {t.deps.map((d) => (
                    <Link key={d.id} to={`/tasks/${d.id}`} title={d.title}>
                      <span className={`badge ${d.status}`}>
                        #{d.id} {d.status.replace("_", " ")}
                      </span>
                    </Link>
                  ))}
                </div>
              </td>
              <td className="small">
                {t.worker_id && <div>{t.worker_id}</div>}
                {t.pr_url && (
                  <a href={t.pr_url} target="_blank" rel="noreferrer">
                    PR
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
