"""The one GLM client wrapper. Every Dwight GLM call goes through here.

GLM is served through Sciforium's OpenAI-compatible Chat Completions API, so
this uses the `openai` client pointed at DWIGHT_GLM_BASE_URL.

Env vars (see /.env.example):
  SCIFORIUM_API_KEY (or DWIGHT_GLM_API_KEY)  API key. Required only when GLM is called.
  DWIGHT_GLM_BASE_URL                  default https://api.sciforium.com/v1
  DWIGHT_GLM_TIER                      default tier for calls that don't pass one
  DWIGHT_GLM_MODEL_{FLAGSHIP,STANDARD,LIGHT}  model name per tier
  DWIGHT_GLM_MODEL_POOL                comma-separated models; calls with no tier round-robin over it
  DWIGHT_GLM_EMBED_MODEL               embeddings model (default embedding-3)
  DWIGHT_GLM_THINKING                  unset (default: not sent), "disabled" or "enabled"

Per call, `thinking=False` turns the model's reasoning off through the chat template
(`chat_template_kwargs`), which is what Sciforium's DeepSeek deployment honours; the
Z.ai-style `thinking` field above is accepted there but ignored. `thinking=None` (the
default) sends nothing extra. Measured on classify (ticket 15): ~5x faster, see
DWIGHT_CLASSIFY_THINKING in dwight/classifier/run.py.

Usage:
    from pydantic import BaseModel
    from dwight import glm

    class Out(BaseModel):
        summary: str
        complexity: Literal["low", "med", "high"]

    out = glm.chat_json([{"role": "user", "content": "..."}], schema=Out, tier="standard")

Rule: never ask GLM for dollar figures. Code prices everything (ADRs 0006, 0007).
"""
from __future__ import annotations

import json
import re
import itertools
import threading
from functools import lru_cache
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from dwight import config

T = TypeVar("T", bound=BaseModel)


class GLMNotConfigured(RuntimeError):
    pass


class GLMBadOutput(RuntimeError):
    pass


@lru_cache(maxsize=1)
def client():
    if not config.GLM_API_KEY:
        raise GLMNotConfigured("Set SCIFORIUM_API_KEY in .env to call GLM")
    from openai import OpenAI  # imported lazily so nothing needs it unless GLM is used

    return OpenAI(api_key=config.GLM_API_KEY, base_url=config.GLM_BASE_URL, max_retries=3, timeout=120)


_pool_cycle = itertools.cycle(config.GLM_MODEL_POOL) if config.GLM_MODEL_POOL else None
_pool_lock = threading.Lock()


def model_for(tier: str | None = None) -> str:
    """The model for a call. No tier + a configured pool = next model in the pool
    (round-robin, thread-safe). Callers that need one model for a whole Session,
    like the agent harness, call this once and pass the result as `tier`."""
    if tier is None and _pool_cycle is not None:
        with _pool_lock:
            return next(_pool_cycle)
    tier = tier or config.GLM_DEFAULT_TIER
    if tier in config.GLM_TIER_MODELS:
        return config.GLM_TIER_MODELS[tier]
    return tier  # allow passing a model name directly


def _extra_body(thinking: bool | None = None) -> dict:
    body: dict = {"thinking": {"type": config.GLM_THINKING}} if config.GLM_THINKING else {}
    if thinking is not None:
        body["chat_template_kwargs"] = {"thinking": thinking, "enable_thinking": thinking}
    return body


def chat(messages: list[dict], *, tier: str | None = None, temperature: float = 0.2,
         max_tokens: int | None = None, thinking: bool | None = None, **kwargs: Any) -> str:
    """Plain text completion. Returns the assistant message content.
    With no tier and a pool of 2+ models, an API error fails over to the next model."""
    from openai import APIError

    attempts = len(config.GLM_MODEL_POOL) if tier is None and len(config.GLM_MODEL_POOL) > 1 else 1
    for i in range(attempts):
        try:
            resp = client().chat.completions.create(
                model=model_for(tier), messages=messages, temperature=temperature,
                max_tokens=max_tokens, extra_body=_extra_body(thinking), **kwargs)
            return resp.choices[0].message.content or ""
        except APIError:
            if i == attempts - 1:
                raise
    raise AssertionError("unreachable")


def _parse_json(text: str) -> Any:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def chat_json(messages: list[dict], *, schema: type[T] | None = None, tier: str | None = None,
              temperature: float = 0.1, retries: int = 2, max_tokens: int | None = None,
              thinking: bool | None = None) -> T | Any:
    """Structured JSON output. Uses response_format=json_object, puts the JSON
    schema in the system prompt when `schema` is given, validates with pydantic
    and retries (feeding the error back) on invalid output."""
    msgs = list(messages)
    if schema is not None:
        msgs = [{"role": "system", "content":
                 "Reply with a single JSON object only, no prose. It must validate against this JSON Schema:\n"
                 + json.dumps(schema.model_json_schema())}] + msgs
    last_err: Exception | None = None
    for _ in range(retries + 1):
        extra = {} if thinking is None else {"thinking": thinking}
        text = chat(msgs, tier=tier, temperature=temperature, max_tokens=max_tokens,
                    response_format={"type": "json_object"}, **extra)
        try:
            data = _parse_json(text)
            return schema.model_validate(data) if schema is not None else data
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
            msgs = msgs + [{"role": "assistant", "content": text},
                           {"role": "user", "content": f"That output was invalid: {e}. Reply again with valid JSON only."}]
    raise GLMBadOutput(f"GLM did not return valid JSON after {retries + 1} tries: {last_err}")


def embed(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    """Embeddings (for clustering Discoveries, ticket 11)."""
    resp = client().embeddings.create(model=model or config.GLM_EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]
