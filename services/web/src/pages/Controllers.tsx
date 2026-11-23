import { useState } from "react";
import { api } from "../api";
import { usePoll } from "../usePoll";
import type { InboxStatus } from "../types";

type Row = { name: string; created_at: string; last_used_at: string | null; revoked: number };
type Created = { name: string; token: string; mcp_url: string; mcp_url_with_token: string; openapi_url: string };

export default function Controllers() {
  const { data, reload } = usePoll<{ controllers: Row[]; urls: { local: string; public: string; tunnel_mode?: string; stable?: { url: string } } }>("/api/controllers", 0);
  const [name, setName] = useState("claude");
  const [created, setCreated] = useState<Created>();
  const [msg, setMsg] = useState("");
  const create = async () => {
    try {
      setCreated(await api<Created>("/api/controllers", { method: "POST", json: { name } }));
      setMsg("");
      reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const revoke = async (n: string) => {
    await api(`/api/controllers/${n}`, { method: "DELETE" });
    reload();
  };
  const base = data?.urls.public || data?.urls.local || "";
  return (
    <div className="stack">
      <h1>Controllers</h1>
      <p className="muted">
        A controller (Claude or ChatGPT) turns your ideas into queued tasks through the MCP server or the REST API. Each controller gets its own token.
        {!data?.urls.public && " Turn on the tunnel in Settings (no domain needed) so cloud-hosted controllers can reach this VM."}
        {data?.urls.stable?.url && " This workers.dev address stays the same when the tunnel restarts."}
        {data?.urls.tunnel_mode === "quick" && data?.urls.public && !data?.urls.stable?.url && " This quick-tunnel address changes when the tunnel restarts; update your controllers if it does."}
      </p>
      <InboxCard />
      <section className="card">
        <h2>Connection details</h2>
        <table>
          <tbody>
            <tr><th>MCP server</th><td><code>{base}/mcp</code></td></tr>
            <tr><th>OpenAPI</th><td><a href="/openapi.json">{base}/openapi.json</a> · <a href="/docs">interactive docs</a></td></tr>
          </tbody>
        </table>
      </section>
      <section className="card">
        <h2>New token</h2>
        <div className="actions">
          <select value={name} onChange={(e) => setName(e.target.value)}>
            <option value="claude">claude</option>
            <option value="chatgpt">chatgpt</option>
            <option value="script">script</option>
          </select>
          <button onClick={create}>Create token</button>
          {msg && <span className="error">{msg}</span>}
        </div>
        {created && (
          <div>
            <p><b>Copy these now; the token is not shown again.</b></p>
            <table>
              <tbody>
                <tr><th>Token</th><td><code>{created.token}</code></td></tr>
                <tr><th>MCP URL (header auth)</th><td><code>{created.mcp_url}</code> with <code>Authorization: Bearer {created.token}</code></td></tr>
                <tr><th>MCP URL (token in URL)</th><td><code>{created.mcp_url_with_token}</code></td></tr>
              </tbody>
            </table>
            <p className="muted small">
              Claude: Settings → Connectors → Add custom connector → paste the URL with the token. ChatGPT: Settings → Connectors (developer mode) → Create → paste
              the same URL. Claude Code: <code>claude mcp add --transport http devenv {created.mcp_url} --header "Authorization: Bearer …"</code>.
            </p>
          </div>
        )}
      </section>
      <section className="card">
        <h2>Tokens</h2>
        <table>
          <thead><tr><th>Name</th><th>Created</th><th>Last used</th><th /></tr></thead>
          <tbody>
            {data?.controllers.map((c) => (
              <tr key={c.name + c.created_at}>
                <td>{c.name}</td>
                <td>{c.created_at}</td>
                <td>{c.last_used_at ?? "never"}</td>
                <td>{c.revoked ? <span className="badge">revoked</span> : <button className="link" onClick={() => revoke(c.name)}>Revoke</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function InboxCard() {
  const { data } = usePoll<InboxStatus>("/api/inbox", 0);
  if (!data) return null;
  return (
    <section className="card">
      <h2>Plan through GitHub issues</h2>
      {data.enabled ? (
        <>
          <p className="muted">
            Any controller that can use GitHub (Claude in a cloud session, ChatGPT, a script or you) can queue work without
            reaching this VM: open an issue labelled <code>{data.label}</code> in{" "}
            <a href={data.url} target="_blank" rel="noreferrer">{data.repo}</a>. Progress and pull request links come back as
            comments, and the issue closes when the task is done.
            {data.last.error && <span className="error"> Last check failed: {data.last.error}</span>}
          </p>
          <pre className="log">{`Title: Add a DNS record module for status-page

Body:
repo: tofu-modules            (or owner/name, or new:my-project)
depends-on: #12               (other issues in ${data.repo})
complexity: small             (trivial, small, medium, large, hard)
reason: copies the existing record modules
attach: specs/dns.md          (a file in ${data.repo})

What to change, acceptance criteria and how to test it.`}</pre>
        </>
      ) : (
        <p className="muted">
          Turn on <b>Take tasks from GitHub issues</b> in Settings → GitHub so controllers that can't reach this VM (such as Claude
          cloud sessions) can queue work through issues instead.
        </p>
      )}
    </section>
  );
}
