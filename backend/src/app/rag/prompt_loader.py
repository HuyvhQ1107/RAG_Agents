"""Centralized versioned prompt loader (T029, Constitution VII)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: str
    model_role: str
    system_prompt: str
    user_template: str

    def render(self, **kwargs: object) -> tuple[str, str]:
        str_kwargs = {k: str(v) for k, v in kwargs.items()}
        sys_rendered = self.system_prompt
        for k, v in str_kwargs.items():
            sys_rendered = sys_rendered.replace("{" + k + "}", v)
        user_rendered = self.user_template.format(**str_kwargs)
        return sys_rendered, user_rendered


def _prompts_dir() -> Path:
    here = Path(__file__).resolve()
    # backend/src/app/rag/prompt_loader.py -> backend/prompts
    return here.parents[3] / "prompts"


@lru_cache(maxsize=32)
def load_prompt(name: str, version: str = "v1") -> PromptTemplate:
    path = _prompts_dir() / f"{name}.{version}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PromptTemplate(
        id=str(data["id"]),
        version=str(data["version"]),
        model_role=str(data.get("model_role", "answer")),
        system_prompt=str(data["system_prompt"]),
        user_template=str(data["user_template"]),
    )
