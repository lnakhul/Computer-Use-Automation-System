"""OpenAI-compatible structured decision provider."""

from __future__ import annotations

import json

import httpx
from pydantic import TypeAdapter, ValidationError

from automation.discovery.contracts import AgentDecisionProvider, DecisionProviderError
from automation.discovery.models import AgentDecision
from automation.surface.contracts import SurfaceObservation


class OpenAICompatibleDecisionProvider:
    """Calls a chat-completions-compatible endpoint and validates JSON output."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float = 30) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._decision_adapter = TypeAdapter(AgentDecision)

    def decide(self, goal: str, observation: SurfaceObservation) -> AgentDecision:
        request_body = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Choose exactly one next decision for a computer-use task. "
                        "Return only JSON matching the supplied schema. Never include hidden reasoning; "
                        "reasoning_summary must be a brief operational summary."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "goal": goal,
                        "observation": {
                            "location": observation.current_location,
                            "title": observation.title,
                            "visible_text": observation.visible_text,
                            "dialog_text": observation.dialog_text,
                        },
                    }),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_decision",
                    "strict": True,
                    "schema": self._decision_adapter.json_schema(),
                },
            },
        }
        try:
            response = httpx.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=request_body,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            response_content = response.json()["choices"][0]["message"]["content"]
            return self._decision_adapter.validate_json(response_content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValidationError, ValueError) as error:
            raise DecisionProviderError("configured model did not return a valid structured decision") from error