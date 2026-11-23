import { useEffect, useState } from "react";
import { api } from "../api";

type Server = { name: string; type: string; description: string; agents: string[]; enabled: boolean };
type Data = {
  path: string;
  yaml: string;
  error: string;
  rendered_at: string;
  version: number;
  summary: { servers: Server[]; claude_plugins: string[]; marketplaces: string[]; rendered: Record<string, Record<string, string>> } | null;
};

export default function Plugins() {
  const [data, setData] = useState<Data>();
  const [text, setText] = useState("");
  const [msg, setMsg] = useState("");
  const load = async () => {
    const d = await api<Data>("/api/plugins");
    setData(d);
    setText(d.yaml);
  };
  useEffect(() => {
    load();
  }, []);
  if (!data) return <p>Loading…</p>;
  const validate = async () => {
    const r = await api<{ ok: boolean; error?: string }>("/api/plugins/validate", { method: "POST", json: { yaml: text } });
    setMsg(r.ok ? "Valid." : r.error ?? "Invalid");
  };
  const save = async () => {
    try {
      const r = await api<{ changed: boolean; version: number }>("/api/plugins", { method: "PUT", json: { yaml: text } });
      setMsg(r.changed ? `Saved. Agents reload with config version ${r.version}.` : "Saved (no change).");
      load();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <div className="stack">
      <h1>Plugins and MCP servers</h1>
      <p className="muted">
        Defined as code in <code>mcp/mcp.yaml</code> (on this VM: <code>{data.path}</code>). Changes are rendered into each agent's config and idle agents restart
        to load them. Config version {data.version}
        {data.rendered_at && `, rendered ${data.rendered_at}`}.
      </p>
      {data.error && <p className="error">{data.error}</p>}
      {data.summary && (
        <section className="card">
          <h2>MCP servers</h2>
          <table>
            <thead><tr><th>Name</th><th>Type</th><th>Agents</th><th>Status</th><th>Description</th></tr></thead>
            <tbody>
              {data.summary.servers.map((s) => (
                <tr key={s.name}>
                  <td>{s.name}</td>
                  <td>{s.type}</td>
                  <td>{s.agents.join(", ")}</td>
                  <td><span className={`badge ${s.enabled ? "ready" : ""}`}>{s.enabled ? "enabled" : "disabled"}</span></td>
                  <td>{s.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>Claude Code plugins</h2>
          <p>{data.summary.claude_plugins.length ? data.summary.claude_plugins.join(", ") : <span className="muted">None enabled</span>}</p>
          <p className="muted small">Marketplaces: {data.summary.marketplaces.join(", ") || "none"}</p>
        </section>
      )}
      <section className="card">
        <h2>Edit mcp.yaml</h2>
        <textarea style={{ minHeight: 360, fontFamily: "monospace", fontSize: 13 }} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
        <div className="actions">
          <button className="secondary" onClick={validate}>Validate</button>
          <button onClick={save}>Save and reload agents</button>
          {msg && <span>{msg}</span>}
        </div>
        <p className="muted small">Edits here change this VM only. Commit the same change to mcp/mcp.yaml in the repo so the next image keeps it.</p>
      </section>
      {data.summary && (
        <section className="card">
          <h2>Rendered config</h2>
          {Object.entries(data.summary.rendered).map(([agent, files]) =>
            Object.entries(files).map(([name, content]) => (
              <details key={agent + name}>
                <summary>{agent}: {name}</summary>
                <pre>{content}</pre>
              </details>
            )),
          )}
        </section>
      )}
    </div>
  );
}
