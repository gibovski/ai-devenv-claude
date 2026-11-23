import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Catalogue, Check, Model, SecretStatus, SettingsT } from "../types";

const USAGE_BADGE: Record<string, string> = { "very-high": "●●●●", high: "●●●○", medium: "●●○○", low: "●○○○" };

function SecretField({ name, status, value, onChange }: { name: string; status?: SecretStatus[string]; value: string; onChange: (v: string) => void }) {
  return (
    <label>
      {status?.label ?? name}
      <input
        type="password"
        autoComplete="off"
        placeholder={status?.set ? "Saved. Type to replace, or clear to remove." : "Not set"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function CheckButton({ provider }: { provider: string }) {
  const [result, setResult] = useState<Check>();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      setResult(await api<Check>(`/api/settings/check/${provider}`, { method: "POST" }));
    } catch (e) {
      setResult({ ok: false, detail: (e as Error).message });
    }
    setBusy(false);
  };
  return (
    <span className="check">
      <button type="button" className="secondary" onClick={run} disabled={busy}>
        {busy ? "Checking…" : "Test connection"}
      </button>
      {result && <span className={result.ok ? "ok" : "error"}>{result.ok ? "✓ " : "✗ "}{result.detail}</span>}
    </span>
  );
}

function ModelSelect({ models, value, onChange, tiers }: { models: Model[]; value: string; onChange: (v: string) => void; tiers: Record<string, string> }) {
  const known = models.some((m) => m.id === value);
  const current = models.find((m) => m.id === value);
  return (
    <div>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {!known && value && <option value={value}>{value} (custom)</option>}
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {USAGE_BADGE[m.usage]} {m.label} ({tiers[m.usage] ?? m.usage})
          </option>
        ))}
      </select>
      {current && (
        <p className="muted small">
          {current.note}
          {current.price && ` · $${current.price.input}/$${current.price.output} per million tokens in/out`}
        </p>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export default function Settings() {
  const [s, setS] = useState<SettingsT>();
  const [secrets, setSecrets] = useState<SecretStatus>({});
  const [pending, setPending] = useState<Record<string, string>>({});
  const [cat, setCat] = useState<Catalogue>();
  const [msg, setMsg] = useState("");

  const load = async () => {
    const r = await api<{ settings: SettingsT; secrets: SecretStatus }>("/api/settings");
    setS(r.settings);
    setSecrets(r.secrets);
    setPending({});
  };
  useEffect(() => {
    load();
    api<Catalogue>("/api/models").then(setCat);
  }, []);
  if (!s || !cat) return <p>Loading…</p>;

  const set = (fn: (d: SettingsT) => void) => {
    const copy = structuredClone(s);
    fn(copy);
    setS(copy);
  };
  const secret = (name: string) => (
    <SecretField name={name} status={secrets[name]} value={pending[name] ?? ""} onChange={(v) => setPending({ ...pending, [name]: v })} />
  );

  const save = async () => {
    try {
      await api("/api/settings", { method: "PUT", json: s });
      const changed = Object.fromEntries(Object.entries(pending).filter(([, v]) => v !== undefined));
      if (Object.keys(changed).length) await api("/api/secrets", { method: "PUT", json: { values: changed } });
      await load();
      setMsg("Saved. Open Apply to deploy the change.");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <div className="stack">
      <h1>Settings</h1>
      <Section title="GitHub">
        {secret("github_token")}
        <CheckButton provider="github" />
        <div className="grid2">
          <label>
            Owner (user or org)
            <input value={s.github.owner} onChange={(e) => set((d) => void (d.github.owner = e.target.value))} />
          </label>
          <label>
            Default repository
            <input value={s.github.default_repo} onChange={(e) => set((d) => void (d.github.default_repo = e.target.value))} />
          </label>
          <label>
            Commit author name
            <input value={s.github.git_user_name} onChange={(e) => set((d) => void (d.github.git_user_name = e.target.value))} />
          </label>
          <label>
            Commit author email
            <input value={s.github.git_user_email} onChange={(e) => set((d) => void (d.github.git_user_email = e.target.value))} />
          </label>
        </div>
        <label className="inline">
          <input type="checkbox" checked={s.github.auto_merge} onChange={(e) => set((d) => void (d.github.auto_merge = e.target.checked))} />
          Auto-merge agent PRs when checks pass
        </label>
      </Section>

      <Section title="Claude">
        <p className="hint">
          Use your Claude Pro or Max subscription: run <code>claude setup-token</code> on any computer with Claude
          Code installed and paste the token here. All Claude agents share your subscription's usage limits, so more
          agents means you reach the limit sooner. An Anthropic API key is an optional pay-as-you-go alternative; if
          both are set, agents use the API key.
        </p>
        {secret("claude_code_oauth_token")}
        <CheckButton provider="claude" />
        {secret("anthropic_api_key")}
        <CheckButton provider="anthropic" />
      </Section>

      <Section title="OpenAI">
        {secret("openai_api_key")}
        <CheckButton provider="openai" />
      </Section>

      <Section title="Remote access (Cloudflare Tunnel)">
        <label className="inline">
          <input type="checkbox" checked={s.cloudflare.tunnel_enabled} onChange={(e) => set((d) => void (d.cloudflare.tunnel_enabled = e.target.checked))} />
          Run a tunnel so remote controllers (Claude, ChatGPT) and you can reach this environment from anywhere
        </label>
        <label className="inline">
          <input type="radio" name="cfmode" checked={s.cloudflare.mode === "quick"} onChange={() => set((d) => void (d.cloudflare.mode = "quick"))} />
          Quick tunnel: no Cloudflare account or domain needed
        </label>
        <label className="inline">
          <input type="radio" name="cfmode" checked={s.cloudflare.mode === "named"} onChange={() => set((d) => void (d.cloudflare.mode = "named"))} />
          My own domain on Cloudflare, protected by Cloudflare Access
        </label>
        {s.cloudflare.mode === "quick" ? (
          <p className="hint">
            You get a random <code>https://…trycloudflare.com</code> address, shown on the Controllers page after Apply. It changes
            whenever the tunnel restarts, and anyone with the address reaches the login page, so the admin password and controller
            tokens are the only protection. Use your own domain for a fixed address behind Cloudflare Access.
          </p>
        ) : (
          <>
            {secret("cloudflare_api_token")}
            <CheckButton provider="cloudflare" />
            <div className="grid2">
              <label>
                Account ID
                <input value={s.cloudflare.account_id} onChange={(e) => set((d) => void (d.cloudflare.account_id = e.target.value))} />
              </label>
              <label>
                Zone (domain)
                <input value={s.cloudflare.zone} placeholder="example.com" onChange={(e) => set((d) => void (d.cloudflare.zone = e.target.value))} />
              </label>
              <label>
                Hostname
                <input value={s.cloudflare.hostname} placeholder="devenv.example.com" onChange={(e) => set((d) => void (d.cloudflare.hostname = e.target.value))} />
              </label>
              <label>
                People allowed through Cloudflare Access (emails, comma separated)
                <input
                  value={s.cloudflare.access_emails.join(", ")}
                  onChange={(e) => set((d) => void (d.cloudflare.access_emails = e.target.value.split(",").map((x) => x.trim()).filter(Boolean)))}
                />
              </label>
            </div>
            <label className="inline">
              <input type="checkbox" checked={s.cloudflare.manage_with_terraform} onChange={(e) => set((d) => void (d.cloudflare.manage_with_terraform = e.target.checked))} />
              Create the tunnel, DNS record and Access policies with Terraform on Apply (needs the API token above)
            </label>
            {!s.cloudflare.manage_with_terraform && (
              <>
                {secret("cloudflare_tunnel_token")}
                <CheckButton provider="tunnel" />
              </>
            )}
          </>
        )}
      </Section>

      <Section title="Coding agents">
        <div className="grid2">
          <div>
            <label>
              Claude Code agents
              <input type="number" min={0} max={16} value={s.agents.claude.count} onChange={(e) => set((d) => void (d.agents.claude.count = Number(e.target.value)))} />
            </label>
            <ModelSelect models={cat.anthropic} tiers={cat.usage_tiers} value={s.agents.claude.model} onChange={(v) => set((d) => void (d.agents.claude.model = v))} />
          </div>
          <div>
            <label>
              OpenAI Codex agents
              <input type="number" min={0} max={16} value={s.agents.codex.count} onChange={(e) => set((d) => void (d.agents.codex.count = Number(e.target.value)))} />
            </label>
            <ModelSelect models={cat.openai} tiers={cat.usage_tiers} value={s.agents.codex.model} onChange={(v) => set((d) => void (d.agents.codex.model = v))} />
          </div>
        </div>
        <div className="grid2">
          <label>
            Attempts per task before it needs a human
            <input type="number" min={1} max={10} value={s.agents.max_attempts} onChange={(e) => set((d) => void (d.agents.max_attempts = Number(e.target.value)))} />
          </label>
        </div>
        <label className="inline">
          <input type="checkbox" checked={s.agents.openhands_enabled} onChange={(e) => set((d) => void (d.agents.openhands_enabled = e.target.checked))} />
          Also run OpenHands (optional web UI agent)
        </label>
      </Section>

      <div className="actions">
        <button onClick={save}>Save settings</button>
        <Link to="/apply">Review and apply →</Link>
        {msg && <span>{msg}</span>}
      </div>
    </div>
  );
}
