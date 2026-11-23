"""Loads the model catalogue (devenv/catalogue/models.yaml, overridable with DEVENV_MODELS_FILE)."""

import os
from functools import lru_cache
from importlib import resources
from pathlib import Path

import yaml

TIER_ORDER = ["very-high", "high", "medium", "low"]
EFFORTS = ["", "low", "medium", "high", "xhigh", "max"]
# Worker provider name → catalogue section.
PROVIDER_SECTION = {"claude": "anthropic", "codex": "openai"}


@lru_cache
def catalogue() -> dict:
    override = os.environ.get("DEVENV_MODELS_FILE")
    text = (
        Path(override).read_text()
        if override
        else resources.files("devenv.catalogue").joinpath("models.yaml").read_text()
    )
    data = yaml.safe_load(text)
    for provider in ("anthropic", "openai"):
        for m in data.get(provider, []):
            if m.get("usage") not in TIER_ORDER:
                raise ValueError(f"model {m.get('id')}: usage must be one of {TIER_ORDER}")
        data[provider].sort(key=lambda m: TIER_ORDER.index(m["usage"]))
    for level, row in (data.get("complexity") or {}).items():
        if row.get("effort", "") not in EFFORTS:
            raise ValueError(f"complexity {level}: effort must be one of {EFFORTS}")
        for provider in ("anthropic", "openai"):
            if row.get(provider) and row[provider] not in {m["id"] for m in data.get(provider, [])}:
                raise ValueError(f"complexity {level}: {row[provider]} is not a listed {provider} model")
    return data


def model_ids(provider: str) -> set[str]:
    return {m["id"] for m in catalogue().get(provider, [])}


def default_model(provider: str) -> str:
    models = catalogue().get(provider, [])
    return next((m["id"] for m in models if m.get("default")), models[0]["id"])


def complexity_levels() -> list[str]:
    return list((catalogue().get("complexity") or {}).keys())


def model_provider(model: str) -> str:
    """Catalogue section (anthropic | openai) a model belongs to, guessing for models not listed."""
    for section in ("anthropic", "openai"):
        if model in model_ids(section):
            return section
    return "anthropic" if model.startswith("claude") else "openai"


def choose_model(task: dict, worker_provider: str) -> dict:
    """The model and effort a worker of this provider should use for the task, and why.

    An explicit task model wins when it belongs to the worker's provider; otherwise the complexity rating
    maps to a model; otherwise the worker keeps its Settings model (model "")."""
    section = PROVIDER_SECTION.get(worker_provider, "")
    level = (catalogue().get("complexity") or {}).get(task.get("complexity") or "", {})
    effort = task.get("effort") or level.get("effort", "")
    model = task.get("model") or ""
    if model and model_provider(model) == section:
        return {"model": model, "effort": effort, "source": "task"}
    if level.get(section):
        return {"model": level[section], "effort": effort, "source": f"complexity {task['complexity']}"}
    return {"model": "", "effort": task.get("effort") or "", "source": "settings"}
