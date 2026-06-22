"""
Wrapper para llamadas a Ollama con reintentos, backoff y validacion JSON.
Modelos secuenciales — nunca en paralelo (VRAM limitada).
"""

import json
import logging
import os
import threading
import time
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

_metrics: dict[str, int] = {
    "calls": 0,
    "json_parse_failures": 0,
    "empty_responses": 0,
}
_metrics_lock = threading.Lock()


def _inc_metric(key: str) -> None:
    with _metrics_lock:
        _metrics[key] += 1


def get_llm_metrics() -> dict[str, int]:
    with _metrics_lock:
        return dict(_metrics)


def reset_llm_metrics() -> None:
    with _metrics_lock:
        for k in _metrics:
            _metrics[k] = 0


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_TIMEOUT = 180

MODEL_TECHNICAL = "gemma4:e4b"
MODEL_HR = "gemma4:e4b"
MODEL_COMPANY = "qwen2.5:7b"

MODEL_TEMPERATURES: dict[str, float] = {
    MODEL_TECHNICAL: 0.1,
    MODEL_HR: 0.0,
    MODEL_COMPANY: 0.0,
}


class OllamaError(Exception):
    """Error en llamada a Ollama."""


class OllamaJSONError(OllamaError):
    """El modelo no devolvio JSON valido tras reintentos."""


def _call_ollama_raw(
    model: str,
    prompt: str,
    temperature: float | None = None,
    think: bool = False,
    num_ctx: int = 8192,
) -> str:
    """Llamada directa a la API de Ollama. Sin reintentos."""
    temp = temperature if temperature is not None else MODEL_TEMPERATURES.get(model, 0.1)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "options": {"temperature": temp, "num_ctx": num_ctx},
    }
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=OLLAMA_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        if think and "think" in data:
            log.debug("Razonamiento de %s:\n%s", model, data["think"].strip())
        return data.get("response", "").strip()
    except requests.exceptions.ConnectionError as e:
        raise OllamaError(f"Ollama no disponible en {OLLAMA_BASE_URL}: {e}") from e
    except requests.exceptions.Timeout:
        raise OllamaError(f"Timeout ({OLLAMA_TIMEOUT}s) con modelo {model}")
    except requests.exceptions.HTTPError as e:
        raise OllamaError(f"HTTP {e.response.status_code} desde Ollama: {e}") from e


def _extract_json(text: str) -> Any:
    """Extrae JSON de respuesta del modelo, manejando texto extra."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if "```" in text:
        for block in text.split("```"):
            cleaned = block.strip().lstrip("json").strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                continue
    for sc, ec in [("{", "}"), ("[", "]")]:
        s, e = text.find(sc), text.rfind(ec)
        if s != -1 and e != -1 and e > s:
            try:
                return json.loads(text[s : e + 1])
            except json.JSONDecodeError:
                continue
    _inc_metric("json_parse_failures")
    raise OllamaJSONError(f"No se pudo extraer JSON de: {text[:200]}...")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(OllamaError),
    reraise=True,
)
def ollama_call(
    model: str,
    prompt: str,
    expect_json: bool = False,
    temperature: float | None = None,
    think: bool = False,
    num_ctx: int = 8192,
    json_retry_instruction: str = "\n\nResponde UNICAMENTE con JSON valido, sin texto adicional.",
) -> str | Any:
    """
    Llama a Ollama con reintentos y validacion JSON opcional.
    Returns: str si expect_json=False, dict/list si expect_json=True.
    Raises: OllamaError, OllamaJSONError
    """
    _inc_metric("calls")
    log.debug("Llamando a %s (expect_json=%s)", model, expect_json)
    start = time.time()
    text = _call_ollama_raw(model, prompt, temperature, think, num_ctx)
    if not text:
        _inc_metric("empty_responses")

    if not expect_json:
        log.debug("Respuesta de %s en %dms", model, int((time.time() - start) * 1000))
        return text

    try:
        result = _extract_json(text)
        log.debug("JSON valido de %s en %dms", model, int((time.time() - start) * 1000))
        return result
    except OllamaJSONError:
        log.warning("Respuesta no-JSON de %s, reintentando...", model)

    text_retry = _call_ollama_raw(
        model, prompt + json_retry_instruction, temperature, think, num_ctx
    )
    if not text_retry:
        _inc_metric("empty_responses")
    try:
        result = _extract_json(text_retry)
        log.debug("JSON valido de %s en segundo intento", model)
        return result
    except OllamaJSONError as e:
        log.error("No se obtuvo JSON valido de %s tras 2 intentos", model)
        raise OllamaJSONError(f"Modelo {model} no devolvio JSON valido") from e


def check_ollama_connection() -> dict[str, bool]:
    """Verifica disponibilidad de Ollama y modelos necesarios."""
    status: dict[str, bool] = {
        MODEL_TECHNICAL: False,
        MODEL_HR: False,
        MODEL_COMPANY: False,
    }
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
        r.raise_for_status()
        available = {m["name"] for m in r.json().get("models", [])}
        for model in status:
            status[model] = any(m == model or m.startswith(model.split(":")[0]) for m in available)
            log.info("[%s] %s", "OK" if status[model] else "FALTA", model)
    except requests.exceptions.ConnectionError:
        log.error("Ollama no esta ejecutandose en %s", OLLAMA_BASE_URL)
    return status


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    status = check_ollama_connection()
    if all(status.values()):
        result = ollama_call(
            model=MODEL_TECHNICAL,
            prompt='Responde con este JSON exacto: {"status": "ok", "test": true}',
            expect_json=True,
        )
        log.info("Test exitoso: %s", result)
    else:
        log.error("Modelos no disponibles. Ejecuta: ollama list")
