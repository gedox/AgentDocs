"""Thin client for a local Ollama server."""

from __future__ import annotations

import json
import re
from typing import Iterator

import requests

OLLAMA_HOST = "http://localhost:11434"

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class OllamaError(RuntimeError):
    pass


def is_up(timeout: float = 2.0) -> bool:
    try:
        requests.get(f"{OLLAMA_HOST}/api/version", timeout=timeout)
        return True
    except requests.RequestException:
        return False


def list_models(timeout: float = 5.0) -> list[dict]:
    """Return [{name, size, parameter_size, family}, ...] sorted by name."""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise OllamaError(str(exc)) from exc

    out = []
    for m in resp.json().get("models", []):
        details = m.get("details", {})
        out.append(
            {
                "name": m.get("name", ""),
                "size": m.get("size", 0),
                "parameter_size": details.get("parameter_size", ""),
                "family": details.get("family", ""),
            }
        )
    return sorted(out, key=lambda m: m["name"].lower())


def generate_stream(
    model: str,
    prompt: str,
    system: str | None = None,
    options: dict | None = None,
    timeout: float = 600.0,
) -> Iterator[str]:
    """Stream generated text tokens from Ollama's /api/generate.

    ``<think>`` blocks are requested off and defensively stripped so callers get
    clean specification text.
    """
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "think": False,
        "options": options or {"temperature": 0.2},
    }
    if system:
        payload["system"] = system

    try:
        with requests.post(
            f"{OLLAMA_HOST}/api/generate", json=payload, stream=True, timeout=timeout
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    raise OllamaError(obj["error"])
                chunk = obj.get("response", "")
                if chunk:
                    yield chunk
                if obj.get("done"):
                    break
    except requests.RequestException as exc:
        raise OllamaError(str(exc)) from exc


def generate(model: str, prompt: str, system: str | None = None, options: dict | None = None) -> str:
    text = "".join(generate_stream(model, prompt, system=system, options=options))
    return _THINK_RE.sub("", text).strip()
