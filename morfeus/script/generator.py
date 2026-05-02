"""Generación del guion vía LLM (Groq como primario, Gemini como fallback).

Ambos providers tienen free tier generoso y no requieren tarjeta. Sólo se
necesita una de las dos variables de entorno:

  GROQ_API_KEY     — https://console.groq.com (Llama 3.3 70B, super rápido)
  GEMINI_API_KEY   — https://aistudio.google.com (Gemini 1.5 Flash)

Si ninguna está disponible, el caller debe usar `--script` con un JSON propio.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from morfeus.config import Script, TemplateCfg

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
DEFAULT_TREND = "humor seco, ritmo rápido, gancho final viral"

SYSTEM_INSTRUCTION = (
    "Eres un guionista experto en videos virales cortos en español para TikTok, "
    "Reels y Shorts. Devuelves SIEMPRE JSON válido y nada más, sin texto extra "
    "ni cercas de código. El JSON debe seguir EXACTAMENTE el esquema pedido."
)


class LLMNotConfigured(RuntimeError):
    """Ninguna API de LLM está configurada."""


class ScriptGenerationError(RuntimeError):
    """El LLM respondió pero la respuesta no se pudo convertir a un Script válido."""


@dataclass
class GenerationContext:
    template: TemplateCfg
    producto: str
    trend: str = DEFAULT_TREND

    def build_prompt(self) -> str:
        prompt_tpl = self.template.script_prompt or _default_prompt(self.template)
        speaker_ids = "|".join(f'"{c.id}"' for c in self.template.characters)
        prompt = prompt_tpl.format(producto=self.producto, trend=self.trend)
        # Reforzamos el esquema al final para reducir respuestas inválidas.
        prompt += (
            "\n\nEsquema EXACTO del JSON a devolver:\n"
            '{ "turnos": [ { "speaker": ' + speaker_ids + ', "text": "..." } ] }\n'
            "Reglas: 4 a 6 turnos, alternando los speakers; cada `text` entre "
            "8 y 22 palabras; el último turno debe contener un llamado a la "
            "acción mencionando el producto."
        )
        return prompt


def _default_prompt(template: TemplateCfg) -> str:
    chars = ", ".join(f"{c.id} ({c.display_name})" for c in template.characters)
    return (
        f"Escribe un diálogo viral entre los personajes [{chars}]. "
        "Producto: {producto}. Trend / tono: {trend}. Idioma: español neutro."
    )


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _generate_with_groq(prompt: str, model: str | None = None) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMNotConfigured("GROQ_API_KEY no está definido.")

    try:
        from groq import Groq  # type: ignore[import-untyped]
    except ImportError as exc:
        raise LLMNotConfigured(
            "Instala el extra: `pip install morfeus[llm]` o `pip install groq`."
        ) from exc

    client = Groq(api_key=api_key)
    resp = client.chat.completions.create(
        model=model or DEFAULT_GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.85,
        max_tokens=1024,
    )
    return resp.choices[0].message.content or ""


def _generate_with_gemini(prompt: str, model: str | None = None) -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise LLMNotConfigured("GEMINI_API_KEY no está definido.")

    try:
        import google.generativeai as genai  # type: ignore[import-untyped]
    except ImportError as exc:
        raise LLMNotConfigured(
            "Instala el extra: `pip install morfeus[llm]` o `pip install google-generativeai`."
        ) from exc

    genai.configure(api_key=api_key)
    g = genai.GenerativeModel(
        model_name=model or DEFAULT_GEMINI_MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.85,
            "max_output_tokens": 1024,
        },
    )
    resp = g.generate_content(prompt)
    return resp.text or ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_FENCED = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(raw: str) -> dict:
    """Extrae JSON aunque venga envuelto en code fences o con texto extra."""
    text = raw.strip()
    m = _FENCED.search(text)
    if m:
        text = m.group(1).strip()
    # Buscar el primer { y el último } como ancla de fallback.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _validate_script(data: dict, template: TemplateCfg) -> Script:
    valid_speakers = {c.id for c in template.characters}
    if not isinstance(data, dict) or "turnos" not in data:
        raise ScriptGenerationError(f"Respuesta sin 'turnos': {data!r}")
    turnos = data["turnos"]
    if not isinstance(turnos, list) or not turnos:
        raise ScriptGenerationError("'turnos' debe ser una lista no vacía.")
    for i, t in enumerate(turnos):
        if not isinstance(t, dict) or "speaker" not in t or "text" not in t:
            raise ScriptGenerationError(f"Turno {i} mal formado: {t!r}")
        if t["speaker"] not in valid_speakers:
            raise ScriptGenerationError(
                f"Turno {i} usa speaker '{t['speaker']}' que no está en la plantilla "
                f"(válidos: {sorted(valid_speakers)})."
            )
    return Script(**{**data, "producto": data.get("producto") or None})


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def generate_script(
    template: TemplateCfg,
    producto: str,
    trend: str | None = None,
    provider: str = "auto",
) -> Script:
    """Genera un Script para el producto usando la plantilla.

    provider: 'auto' (Groq, fallback Gemini), 'groq', o 'gemini'.
    """
    ctx = GenerationContext(
        template=template,
        producto=producto,
        trend=trend or DEFAULT_TREND,
    )
    prompt = ctx.build_prompt()

    errors: list[str] = []
    candidates = (
        ["groq", "gemini"] if provider == "auto" else [provider]
    )

    for prov in candidates:
        try:
            raw = (_generate_with_groq if prov == "groq" else _generate_with_gemini)(prompt)
            data = _extract_json(raw)
            script = _validate_script(data, template)
            script.producto = producto
            return script
        except LLMNotConfigured as exc:
            errors.append(f"[{prov}] no configurado: {exc}")
            continue
        except (json.JSONDecodeError, ScriptGenerationError) as exc:
            errors.append(f"[{prov}] respuesta inválida: {exc}")
            continue
        except Exception as exc:  # API error, rate limit, etc.
            errors.append(f"[{prov}] error: {exc}")
            continue

    raise ScriptGenerationError(
        "No se pudo generar el guion con ningún provider:\n  " + "\n  ".join(errors)
    )
