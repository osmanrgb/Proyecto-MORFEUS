"""Síntesis de voz vía edge-tts (gratis, sin API key).

Devuelve, por cada turno: la ruta al MP3 generado, su duración en segundos,
y los timestamps por palabra (lista de WordBoundary). Los timestamps están
en segundos relativos al inicio del MP3 del turno.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import edge_tts

from morfeus.config import Script, TemplateCfg, VoiceCfg

# edge-tts entrega offsets en unidades de 100 nanosegundos.
HUNDRED_NS_PER_SECOND = 10_000_000


@dataclass
class WordBoundary:
    text: str
    start: float  # segundos
    end: float    # segundos


@dataclass
class TurnoRender:
    index: int
    speaker: str
    text: str
    audio_path: Path
    duration: float
    words: list[WordBoundary] = field(default_factory=list)


async def _synth_one(
    text: str,
    voice: VoiceCfg,
    output: Path,
) -> tuple[float, list[WordBoundary]]:
    """Sintetiza un turno y devuelve (duración_segundos, palabras)."""
    output.parent.mkdir(parents=True, exist_ok=True)

    communicate = edge_tts.Communicate(
        text,
        voice.edge_voice,
        rate=voice.rate,
        pitch=voice.pitch,
    )

    boundaries: list[WordBoundary] = []
    last_end = 0.0
    with output.open("wb") as f:
        async for chunk in communicate.stream():
            t = chunk.get("type")
            if t == "audio":
                f.write(chunk["data"])
            elif t == "WordBoundary":
                start = chunk["offset"] / HUNDRED_NS_PER_SECOND
                end = (chunk["offset"] + chunk["duration"]) / HUNDRED_NS_PER_SECOND
                boundaries.append(WordBoundary(text=chunk["text"], start=start, end=end))
                last_end = max(last_end, end)

    duration = last_end if last_end > 0 else _ffprobe_duration(output)
    return duration, boundaries


def _ffprobe_duration(path: Path) -> float:
    if shutil.which("ffprobe") is None:
        return 0.0
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _apply_pitch_shift(src: Path, dst: Path, semitones: float) -> None:
    """Pitch-shift preservando duración (asetrate + atempo)."""
    if abs(semitones) < 0.01:
        if src != dst:
            shutil.copyfile(src, dst)
        return
    if shutil.which("ffmpeg") is None:
        # sin ffmpeg, devolvemos el original sin modificar
        if src != dst:
            shutil.copyfile(src, dst)
        return

    factor = 2 ** (semitones / 12.0)
    sample_rate = 24000  # edge-tts default
    new_rate = int(sample_rate * factor)
    atempo = 1.0 / factor

    # ffmpeg's atempo requiere [0.5, 2.0]; encadenamos si estamos fuera de rango
    atempo_chain = []
    rem = atempo
    while rem < 0.5:
        atempo_chain.append("atempo=0.5")
        rem /= 0.5
    while rem > 2.0:
        atempo_chain.append("atempo=2.0")
        rem /= 2.0
    atempo_chain.append(f"atempo={rem:.6f}")

    flt = f"asetrate={new_rate}," + ",".join(atempo_chain) + f",aresample={sample_rate}"

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", flt, str(dst)],
        check=True,
    )


async def synth_script_async(
    script: Script,
    template: TemplateCfg,
    work_dir: Path,
) -> list[TurnoRender]:
    """Sintetiza todos los turnos del guion. Devuelve renders por turno."""
    work_dir.mkdir(parents=True, exist_ok=True)
    results: list[TurnoRender] = []

    for i, turno in enumerate(script.turnos):
        char = template.character(turno.speaker)
        raw_path = work_dir / f"turn_{i:03d}_raw.mp3"
        final_path = work_dir / f"turn_{i:03d}.mp3"

        duration, words = await _synth_one(turno.text, char.voice, raw_path)
        _apply_pitch_shift(raw_path, final_path, char.voice.pitch_shift_semitones)

        # Si aplicamos pitch-shift con compensación de atempo la duración se conserva,
        # pero por seguridad releemos con ffprobe cuando hay shift no trivial.
        if abs(char.voice.pitch_shift_semitones) >= 0.01:
            new_dur = _ffprobe_duration(final_path)
            if new_dur > 0:
                # reescala las palabras al nuevo tiempo
                if duration > 0:
                    scale = new_dur / duration
                    words = [
                        WordBoundary(text=w.text, start=w.start * scale, end=w.end * scale)
                        for w in words
                    ]
                duration = new_dur

        results.append(
            TurnoRender(
                index=i,
                speaker=turno.speaker,
                text=turno.text,
                audio_path=final_path,
                duration=duration,
                words=words,
            )
        )

    return results


def synth_script(script: Script, template: TemplateCfg, work_dir: Path) -> list[TurnoRender]:
    """Wrapper síncrono."""
    return asyncio.run(synth_script_async(script, template, work_dir))
