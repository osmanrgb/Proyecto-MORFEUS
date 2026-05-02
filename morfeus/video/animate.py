"""Render animado: bobbing del personaje activo + subtítulos karaoke palabra-por-palabra.

El envolvente de amplitud (calculado en `morfeus.audio.envelope`) controla un
escalado periódico del personaje activo. El subtítulo muestra la palabra
actualmente pronunciada en grande (estilo CapCut).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from moviepy import AudioFileClip, VideoClip, VideoFileClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont

from morfeus.audio.envelope import compute_envelope, envelope_at
from morfeus.audio.tts import TurnoRender, WordBoundary
from morfeus.config import CharacterCfg, RenderResult, TemplateCfg
from morfeus.video.stage import (
    CHARACTER_BOX_HEIGHT_RATIO,
    CHARACTER_PADDING_RATIO,
    _load_character_image,
    _load_font,
)

# Profundidad del bobbing: el personaje activo crece hasta este factor con env=1.
ACTIVE_SCALE_GAIN = 0.08
# Bobbing vertical en píxeles a env=1 (movimiento sutil hacia arriba).
ACTIVE_Y_GAIN_PX = 18


@dataclass
class CharacterPlacement:
    char: CharacterCfg
    base_image: Image.Image
    base_x: int
    base_y: int
    base_w: int
    base_h: int


def _layout_characters(template: TemplateCfg) -> list[CharacterPlacement]:
    W, H = template.width, template.height
    box_h = int(H * CHARACTER_BOX_HEIGHT_RATIO)
    box_w = int(W * (1 - 2 * CHARACTER_PADDING_RATIO))
    pad_x = (W - box_w) // 2

    placements: list[CharacterPlacement] = []
    for char in template.characters:
        img = _load_character_image(char, box_w, box_h)
        if char.position == "top":
            y = int(H * 0.06)
        elif char.position == "bottom":
            y = int(H - H * 0.06 - img.height)
        else:
            y = (H - img.height) // 2
        x = pad_x + (box_w - img.width) // 2
        placements.append(
            CharacterPlacement(
                char=char,
                base_image=img,
                base_x=x,
                base_y=y,
                base_w=img.width,
                base_h=img.height,
            )
        )
    return placements


def _render_background(template: TemplateCfg) -> Image.Image:
    W, H = template.width, template.height
    if template.background_image and Path(template.background_image).exists():
        bg = Image.open(template.background_image).convert("RGB").resize((W, H), Image.LANCZOS)
        return bg.convert("RGBA")
    return Image.new("RGBA", (W, H), template.background_color)


def _current_word(words: list[WordBoundary], t: float) -> WordBoundary | None:
    if not words:
        return None
    for w in words:
        if w.start <= t < w.end:
            return w
    # Si estamos entre palabras, mostrar la última pronunciada.
    past = [w for w in words if w.end <= t]
    return past[-1] if past else words[0]


def _render_karaoke_word(
    text: str,
    canvas_w: int,
    canvas_h: int,
    pulse: float,
) -> Image.Image:
    """Renderiza una sola palabra grande, con un leve pulso de escala."""
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    if not text:
        return img
    draw = ImageDraw.Draw(img)

    base_size = max(96, canvas_w // 9)
    size = int(base_size * (1.0 + 0.06 * pulse))
    font = _load_font(size)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Banda inferior, ~10% del alto desde abajo.
    y = canvas_h - th - int(canvas_h * 0.08)
    x = (canvas_w - tw) // 2

    # Sombra para legibilidad.
    draw.text(
        (x, y),
        text,
        fill=(255, 220, 60, 255),
        font=font,
        stroke_width=8,
        stroke_fill=(0, 0, 0, 255),
    )
    return img


def _scale_with_alpha(img: Image.Image, factor: float) -> Image.Image:
    if abs(factor - 1.0) < 1e-3:
        return img
    new_w = max(1, int(img.width * factor))
    new_h = max(1, int(img.height * factor))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _composite_frame(
    template: TemplateCfg,
    background: Image.Image,
    placements: list[CharacterPlacement],
    active_speaker: str,
    envelope_value: float,
    word_text: str,
    active_override: Image.Image | None = None,
) -> Image.Image:
    """Compone un frame.

    Si `active_override` se pasa (RGBA), se usa como imagen del personaje
    activo en lugar de su `base_image` estática (para lip-sync).
    """
    canvas = background.copy()

    for p in placements:
        is_active = p.char.id == active_speaker
        if is_active:
            src = active_override if active_override is not None else p.base_image
            # Si el override no respeta el aspect del box, lo encajamos en el box base.
            if active_override is not None:
                src = src.copy()
                src.thumbnail((p.base_w, p.base_h), Image.LANCZOS)
            scale = 1.0 + ACTIVE_SCALE_GAIN * envelope_value
            scaled = _scale_with_alpha(src, scale)
            offset_x = p.base_x - (scaled.width - p.base_w) // 2
            offset_y = p.base_y - (scaled.height - p.base_h) // 2
            offset_y -= int(ACTIVE_Y_GAIN_PX * envelope_value)
            canvas.alpha_composite(scaled, (offset_x, offset_y))
        else:
            dim = p.base_image.copy()
            alpha = dim.split()[-1].point(lambda a: int(a * 0.35))
            dim.putalpha(alpha)
            canvas.alpha_composite(dim, (p.base_x, p.base_y))

    if word_text:
        sub = _render_karaoke_word(word_text, template.width, template.height, envelope_value)
        canvas.alpha_composite(sub, (0, 0))

    return canvas


def render_video_animated(
    template: TemplateCfg,
    turnos: list[TurnoRender],
    output_path: Path,
    work_dir: Path,
    lipsync_videos: dict[int, Path] | None = None,
) -> RenderResult:
    """Versión animada del compositor: VideoClip(make_frame) por turno.

    Si `lipsync_videos[turn_index]` existe, los frames del MP4 lip-sync se usan
    como imagen del personaje activo durante ese turno.
    """
    if not turnos:
        raise ValueError("La lista de turnos está vacía; no hay nada que renderizar.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    background = _render_background(template)
    placements = _layout_characters(template)
    fps = template.fps
    lipsync_videos = lipsync_videos or {}

    clips = []
    open_lipsync_clips: list[VideoFileClip] = []
    total_duration = 0.0

    try:
        for turno in turnos:
            envelope = compute_envelope(turno.audio_path, fps)
            words = turno.words
            active = turno.speaker

            ls_path = lipsync_videos.get(turno.index)
            ls_clip: VideoFileClip | None = None
            if ls_path is not None and Path(ls_path).exists():
                ls_clip = VideoFileClip(str(ls_path))
                open_lipsync_clips.append(ls_clip)

            def make_frame(t, _e=envelope, _w=words, _active=active, _ls=ls_clip):
                frame_idx = int(t * fps)
                e_val = envelope_at(_e, frame_idx)
                cur = _current_word(_w, t)
                word_text = cur.text if cur else ""
                override = None
                if _ls is not None:
                    sample_t = min(t, max(0.0, _ls.duration - 1.0 / fps))
                    arr = _ls.get_frame(sample_t)
                    override = Image.fromarray(arr).convert("RGBA")
                frame = _composite_frame(
                    template, background, placements,
                    active_speaker=_active,
                    envelope_value=e_val,
                    word_text=word_text,
                    active_override=override,
                )
                return np.asarray(frame.convert("RGB"))

            audio = AudioFileClip(str(turno.audio_path))
            dur = audio.duration if audio.duration else turno.duration
            clip = VideoClip(make_frame, duration=dur).with_fps(fps).with_audio(audio)
            clips.append(clip)
            total_duration += dur

        final = concatenate_videoclips(clips, method="chain")
        final.write_videofile(
            str(output_path),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
            logger=None,
        )
        final.close()
    finally:
        for c in clips:
            c.close()
        for c in open_lipsync_clips:
            c.close()

    return RenderResult(
        output_path=output_path,
        duration_seconds=total_duration,
        width=template.width,
        height=template.height,
    )
