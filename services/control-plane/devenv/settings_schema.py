"""Settings schema. Non-secret settings live in the kv table; credentials live in the secret store."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .catalogue.loader import default_model

# Names of secrets the UI can set. They are write-only: the API reports only whether each is set.
SECRET_FIELDS = {
    "github_token": "GitHub personal access token (repo, workflow scopes)",
    "codex_auth_json": "ChatGPT sign-in for Codex (Plus/Pro/Business: paste the whole auth.json from `codex login`)",
    "openai_api_key": "OpenAI API key (optional, pay-as-you-go alternative)",
    "claude_code_oauth_token": "Claude subscription token (Pro/Max, from `claude setup-token`)",
    "anthropic_api_key": "Anthropic API key (optional, pay-as-you-go alternative)",
    "cloudflare_api_token": "Cloudflare API token",
    "cloudflare_tunnel_token": "Cloudflare Tunnel token (from Terraform or the dashboard)",
}


class GitHubSettings(BaseModel):
    owner: str = ""
    default_repo: str = ""
    git_user_name: str = "AI Dev Agent"
    git_user_email: str = "agent@devenv.local"
    auto_merge: bool = True


class CloudflareSettings(BaseModel):
    # quick: a free trycloudflare.com address, no account or domain needed (changes when it restarts).
    # named: your own hostname on a Cloudflare zone, protected by Cloudflare Access.
    mode: Literal["quick", "named"] = "quick"
    account_id: str = ""
    zone: str = ""
    hostname: str = ""
    tunnel_enabled: bool = False
    manage_with_terraform: bool = True
    access_emails: list[str] = Field(default_factory=list)
    # Quick tunnel only: a fixed https://<stable_name>.<your-subdomain>.workers.dev address that follows the
    # changing trycloudflare.com one (uses the API token and account ID above; free Workers plan).
    stable_enabled: bool = False
    stable_name: str = Field("", pattern=r"^$|^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class AgentPool(BaseModel):
    count: int = Field(0, ge=0, le=16)
    model: str = ""


class AgentSettings(BaseModel):
    claude: AgentPool = Field(default_factory=lambda: AgentPool(count=1, model=default_model("anthropic")))
    codex: AgentPool = Field(default_factory=lambda: AgentPool(count=0, model=default_model("openai")))
    openhands_enabled: bool = False
    max_attempts: int = Field(3, ge=1, le=10)


class Settings(BaseModel):
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    cloudflare: CloudflareSettings = Field(default_factory=CloudflareSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)

    @field_validator("agents")
    @classmethod
    def _models_known(cls, v: AgentSettings) -> AgentSettings:
        # Unknown model ids are allowed (the catalogue is advisory) but must be non-empty when a pool is used.
        for name, pool in (("claude", v.claude), ("codex", v.codex)):
            if pool.count and not pool.model:
                raise ValueError(f"agents.{name}.model is required when count > 0")
        return v
