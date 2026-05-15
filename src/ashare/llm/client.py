"""Minimal LLM client protocol and Phase 2 fixture client."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMResponse:
    content: str
    raw_response: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    def complete(self, *, announcement_id: str, prompt: str) -> LLMResponse:
        """Return an LLM response for one announcement prompt."""


class FixtureLLMClient:
    """Read deterministic JSON responses from local fixture files."""

    def __init__(self, response_dir: str | Path, variant: str | None = None) -> None:
        self.response_dir = Path(response_dir)
        self.variant = variant

    def complete(self, *, announcement_id: str, prompt: str) -> LLMResponse:
        response_path = self._response_path(announcement_id)
        data = json.loads(response_path.read_text(encoding="utf-8"))
        content_value = data.get("content") if isinstance(data, dict) else None
        if isinstance(content_value, str):
            content = content_value
        elif content_value is not None:
            content = json.dumps(content_value, ensure_ascii=False, sort_keys=True)
        else:
            content = json.dumps(data, ensure_ascii=False, sort_keys=True)
        return LLMResponse(
            content=content,
            raw_response={
                "fixture_path": str(response_path),
                "response": data,
            },
        )

    def _response_path(self, announcement_id: str) -> Path:
        names = []
        if self.variant:
            names.append(f"{announcement_id}.{self.variant}.json")
        names.append(f"{announcement_id}.json")
        for name in names:
            path = self.response_dir / name
            if path.is_file():
                return path
        raise FileNotFoundError(
            f"No fixture LLM response found for {announcement_id} in {self.response_dir}"
        )


class OpenAICompatibleLLMClient:
    """Optional OpenAI-compatible client path, kept out of the default dependency set."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if not model:
            raise ValueError("--model is required for openai-compatible LLM mode.")
        if importlib.util.find_spec("openai") is None:
            raise RuntimeError(
                "openai package is not installed. Install the optional llm extra to use "
                "openai-compatible mode."
            )

        resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for openai-compatible LLM mode.")

        from openai import OpenAI

        self.model = model
        self.client = OpenAI(api_key=resolved_api_key, base_url=base_url)

    def complete(self, *, announcement_id: str, prompt: str) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        return LLMResponse(
            content=content,
            raw_response=response.model_dump(mode="json"),
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )
