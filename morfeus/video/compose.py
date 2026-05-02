"""Compositor de video: une stage + subtítulos + audio en un MP4 9:16.

Fase 1 — versión estática: un frame fijo por turno (cambia el personaje activo
y el subtítulo). Fase 3 añadirá animación frame-by-frame.
"""

from __future__ import annotations

from pathlib import Path

from moviepy import AudioFileClip, ImageClip, concatenate_videoclips
from PIL import Image

from morfeus.audio.tts import TurnoRender
from morfeus.config import RenderResult, TemplateCfg
from morfeus.video.stage import render_stage, render_subtitle


def _frame_for_turn(template: TemplateCfg, turno: TurnoRender, frames_dir: Path) -> Path:
    """Compone el PNG estático del turno y lo guarda en disco."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    stage = render_stage(template, active_speaker=turno.speaker)
    subtitle = render_subtitle(turno.text, template.width, template.height)
    composed = Image.alpha_composite(stage, subtitle).convert("RGB")
    out = frames_dir / f"frame_{turno.index:03d}.png"
    composed.save(out, format="PNG", optimize=True)
    return out


def render_video(
    template: TemplateCfg,
    turnos: list[TurnoRender],
    output_path: Path,
    work_dir: Path,
) -> RenderResult:
    """Une todos los turnos en un único MP4 9:16."""
    if not turnos:
        raise ValueError("La lista de turnos está vacía; no hay nada que renderizar.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = work_dir / "frames"

    clips = []
    total_duration = 0.0
    for t in turnos:
        frame_path = _frame_for_turn(template, t, frames_dir)
        audio = AudioFileClip(str(t.audio_path))
        # La duración real del MP4 la marca el audio para evitar drift.
        dur = audio.duration if audio.duration else t.duration
        clip = (
            ImageClip(str(frame_path))
            .with_duration(dur)
            .with_audio(audio)
        )
        clips.append(clip)
        total_duration += dur

    final = concatenate_videoclips(clips, method="chain")
    final.write_videofile(
        str(output_path),
        fps=template.fps,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=4,
        logger=None,  # silencioso; el CLI imprime su propio progreso
    )
    final.close()
    for c in clips:
        c.close()

    return RenderResult(
        output_path=output_path,
        duration_seconds=total_duration,
        width=template.width,
        height=template.height,
    )
