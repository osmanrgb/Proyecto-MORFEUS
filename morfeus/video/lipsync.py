"""Lip-sync opcional con SadTalker.

SadTalker (https://github.com/OpenTalker/SadTalker) genera un video de un
rostro hablando a partir de una imagen estática + un audio. Requiere GPU
(Colab T4 alcanza) y una instalación previa con pesos descargados.

Esta integración es por subprocess: NO importamos torch/SadTalker en el
proceso de Morfeus para no contaminar el entorno. La ruta al checkout de
SadTalker se indica con `MORFEUS_SADTALKER_DIR` (que contiene `inference.py`).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from morfeus.audio.tts import TurnoRender
from morfeus.config import TemplateCfg

log = logging.getLogger("morfeus.video.lipsync")


class SadTalkerNotConfigured(RuntimeError):
    """SadTalker no está disponible (ni la variable de entorno ni el script)."""


def _sadtalker_dir() -> Path:
    raw = os.environ.get("MORFEUS_SADTALKER_DIR")
    if not raw:
        raise SadTalkerNotConfigured(
            "MORFEUS_SADTALKER_DIR no está definido.\n"
            "Pasos para configurar SadTalker en Colab:\n"
            "  1. !git clone https://github.com/OpenTalker/SadTalker.git\n"
            "  2. !cd SadTalker && bash scripts/download_models.sh\n"
            "  3. %env MORFEUS_SADTALKER_DIR=/content/SadTalker\n"
        )
    p = Path(raw).expanduser().resolve()
    if not (p / "inference.py").exists():
        raise SadTalkerNotConfigured(
            f"No existe inference.py en {p}. Revisa MORFEUS_SADTALKER_DIR."
        )
    return p


def _ensure_wav(mp3_path: Path, wav_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg no está instalado / no está en el PATH.")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3_path),
         "-ar", "16000", "-ac", "1", str(wav_path)],
        check=True,
    )


def generate_lipsync_for_turn(
    image_path: Path,
    audio_mp3: Path,
    work_dir: Path,
) -> Path:
    """Corre SadTalker para un turno y devuelve la ruta del MP4 generado."""
    sad_dir = _sadtalker_dir()
    work_dir.mkdir(parents=True, exist_ok=True)

    wav_path = work_dir / (audio_mp3.stem + ".wav")
    _ensure_wav(audio_mp3, wav_path)

    out_dir = work_dir / "out"
    out_dir.mkdir(exist_ok=True)

    cmd = [
        sys.executable, str(sad_dir / "inference.py"),
        "--driven_audio", str(wav_path),
        "--source_image", str(image_path),
        "--result_dir", str(out_dir),
        "--still",
        "--preprocess", "full",
    ]
    log.info("Ejecutando SadTalker: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(sad_dir))

    # SadTalker crea un subdirectorio nuevo por cada corrida; tomamos el último mp4.
    mp4s = sorted(out_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4s:
        raise RuntimeError(f"SadTalker no produjo MP4 en {out_dir}")
    return mp4s[0]


def generate_lipsync_videos(
    template: TemplateCfg,
    turnos: list[TurnoRender],
    work_dir: Path,
) -> dict[int, Path]:
    """Genera un MP4 lip-sync por turno (sólo para el personaje que habla)."""
    sad_dir = _sadtalker_dir()  # falla temprano si no está configurado
    log.info("Usando SadTalker en %s", sad_dir)

    out: dict[int, Path] = {}
    for turno in turnos:
        char = template.character(turno.speaker)
        if not char.image or not Path(char.image).exists():
            log.warning(
                "Turno %s: personaje '%s' no tiene imagen real; salto lip-sync.",
                turno.index, turno.speaker,
            )
            continue
        turn_dir = work_dir / f"turn_{turno.index:03d}"
        try:
            mp4 = generate_lipsync_for_turn(Path(char.image), turno.audio_path, turn_dir)
            out[turno.index] = mp4
        except subprocess.CalledProcessError as exc:
            log.error("SadTalker falló en turno %s: %s", turno.index, exc)
            # No interrumpimos toda la corrida; ese turno cae a animación normal.

    return out
