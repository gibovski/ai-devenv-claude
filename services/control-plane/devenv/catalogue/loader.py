"""Loads the model catalogue (devenv/catalogue/models.yaml, overridable with DEVENV_MODELS_FILE)."""

import os
from functools import lru_cache
from importlib import resources
from pathlib import Path

import yaml

TIER_ORDER = ["very-high", "high", "medium", "low"]


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
    return data


def model_ids(provider: str) -> set[str]:
    return {m["id"] for m in catalogue().get(provider, [])}


def default_model(provider: str) -> str:
    models = catalogue().get(provider, [])
    return next((m["id"] for m in models if m.get("default")), models[0]["id"])
