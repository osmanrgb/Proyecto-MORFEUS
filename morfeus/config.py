"""Modelos de datos compartidos (Pydantic)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Turno(BaseModel):
    """Un turno de diálogo en el guion."""

    speaker: str = Field(..., description="Identificador del personaje (ej. 'socrates', 'skeleton').")
    text: str = Field(..., min_length=1)


class Script(BaseModel):
    """Un guion completo: lista ordenada de turnos."""

    turnos: list[Turno]
    titulo: str | None = None
    producto: str | None = None


class VoiceCfg(BaseModel):
    """Configuración de voz TTS para un personaje."""

    edge_voice: str = Field(..., description="Nombre de voz edge-tts, ej. 'es-MX-JorgeNeural'.")
    rate: str = Field("+0%", description="Velocidad para edge-tts (ej. '+10%').")
    pitch: str = Field("+0Hz", description="Tono para edge-tts.")
    pitch_shift_semitones: float = Field(
        0.0,
        description="Pitch-shift extra aplicado en post con FFmpeg (negativo = más grave).",
    )


class CharacterCfg(BaseModel):
    """Definición de un personaje en una plantilla."""

    id: str
    display_name: str
    voice: VoiceCfg
    image: str | None = Field(
        None,
        description="Ruta relativa a la imagen PNG del personaje (transparente). Si None, se usa placeholder.",
    )
    position: Literal["top", "bottom", "left", "right"] = "top"


class TemplateCfg(BaseModel):
    """Definición de una plantilla de video (Sócrates+esqueleto, etc.)."""

    name: str
    description: str = ""
    characters: list[CharacterCfg]
    background_color: str = "#0a0a14"
    background_image: str | None = None
    music: str | None = None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    script_prompt: str | None = Field(
        None,
        description="Prompt para el LLM (Fase 2+). Aún no usado en Fase 1.",
    )

    def character(self, speaker_id: str) -> CharacterCfg:
        for c in self.characters:
            if c.id == speaker_id:
                return c
        raise KeyError(f"Personaje '{speaker_id}' no está en la plantilla '{self.name}'.")


class RenderResult(BaseModel):
    """Resultado de un render."""

    output_path: Path
    duration_seconds: float
    width: int
    height: int
