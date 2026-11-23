export type Pool = { count: number; model: string };
export type SettingsT = {
  github: { owner: string; default_repo: string; git_user_name: string; git_user_email: string; auto_merge: boolean };
  cloudflare: { account_id: string; zone: string; hostname: string; tunnel_enabled: boolean };
  agents: { claude: Pool; codex: Pool; openhands_enabled: boolean; max_attempts: number };
};
export type SecretStatus = Record<string, { label: string; set: boolean; updated_at?: string }>;
export type Model = { id: string; label: string; usage: string; note?: string; price?: { input: number; output: number } };
export type Catalogue = { anthropic: Model[]; openai: Model[]; usage_tiers: Record<string, string> };
export type Check = { ok: boolean; detail: string };
