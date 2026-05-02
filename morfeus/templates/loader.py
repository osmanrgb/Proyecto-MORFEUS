"""Carga plantillas desde YAML.

Búsqueda de plantillas, en este orden:
  1. Directorios listados en la variable de entorno `MORFEUS_TEMPLATES_DIR`
     (separados por `os.pathsep`). Útil para apuntar a Google Drive desde Colab.
  2. El directorio empaquetado `morfeus/templates/`.

Una "plantilla" es cualquier directorio que contenga un archivo `template.yaml`
válido (ver `morfeus.config.TemplateCfg`).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from morfeus.config import TemplateCfg

PACKAGE_TEMPLATES_DIR = Path(__file__).parent
_ENV_VAR = "MORFEUS_TEMPLATES_DIR"


def _extra_dirs() -> list[Path]:
    raw = os.environ.get(_ENV_VAR, "")
    if not raw:
        return []
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]


def search_paths() -> list[Path]:
    """Lista de directorios donde se buscan plantillas (en orden)."""
    return [*_extra_dirs(), PACKAGE_TEMPLATES_DIR]


def _resolve_yaml(name_or_path: str) -> Path:
    """Acepta tanto el nombre de una plantilla como una ruta directa al YAML/dir."""
    p = Path(name_or_path).expanduser()
    if p.is_file() and p.name == "template.yaml":
        return p.resolve()
    if p.is_dir() and (p / "template.yaml").exists():
        return (p / "template.yaml").resolve()

    for base in search_paths():
        candidate = base / name_or_path / "template.yaml"
        if candidate.exists():
            return candidate.resolve()

    paths = ", ".join(str(b) for b in search_paths())
    raise FileNotFoundError(
        f"No existe la plantilla '{name_or_path}'. Buscado en: {paths}"
    )


def _resolve_relative_assets(cfg: TemplateCfg, base: Path) -> TemplateCfg:
    for ch in cfg.characters:
        if ch.image and not Path(ch.image).is_absolute():
            ch.image = str((base / ch.image).resolve())
    if cfg.background_image and not Path(cfg.background_image).is_absolute():
        cfg.background_image = str((base / cfg.background_image).resolve())
    if cfg.music and not Path(cfg.music).is_absolute():
        cfg.music = str((base / cfg.music).resolve())
    return cfg


def load_template(name_or_path: str) -> TemplateCfg:
    yaml_path = _resolve_yaml(name_or_path)
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    cfg = TemplateCfg(**raw)
    return _resolve_relative_assets(cfg, yaml_path.parent)


def template_dir(name_or_path: str) -> Path:
    return _resolve_yaml(name_or_path).parent


def list_templates() -> list[tuple[str, Path]]:
    """Lista (nombre, ruta_dir) de todas las plantillas accesibles, sin duplicados."""
    seen: dict[str, Path] = {}
    for base in search_paths():
        if not base.exists():
            continue
        for sub in sorted(base.iterdir()):
            if sub.is_dir() and (sub / "template.yaml").exists() and sub.name not in seen:
                seen[sub.name] = sub
    return list(seen.items())


SCAFFOLD_YAML = """\
name: {name}
description: >-
  Describe brevemente la plantilla aquí.

width: 1080
height: 1920
fps: 30
background_color: "#0a0a14"

characters:
  - id: speaker_a
    display_name: Personaje A
    position: top
    image: assets/speaker_a.png
    voice:
      edge_voice: es-MX-JorgeNeural
      rate: "+0%"
      pitch: "+0Hz"
      pitch_shift_semitones: 0.0
  - id: speaker_b
    display_name: Personaje B
    position: bottom
    image: assets/speaker_b.png
    voice:
      edge_voice: es-MX-DaliaNeural
      rate: "+0%"
      pitch: "+0Hz"
      pitch_shift_semitones: 0.0

script_prompt: |
  Eres un guionista viral. Escribe un diálogo corto entre Personaje A y B
  promocionando: {{producto}}.
  Trend / tono: {{trend}}.
  Devuelve SOLO un objeto JSON con la forma:
  {{"turnos": [{{"speaker": "speaker_a"|"speaker_b", "text": "..."}}, ...]}}
"""

SCAFFOLD_DEMO = """\
{
  "titulo": "Demo {name}",
  "producto": "Mi producto",
  "turnos": [
    {"speaker": "speaker_a", "text": "Esto es un guion de prueba para la plantilla {name}."},
    {"speaker": "speaker_b", "text": "¡Genial! Cámbiame por algo más viral cuando estés listo."}
  ]
}
"""


def scaffold_template(name: str, parent: Path) -> Path:
    """Crea una plantilla nueva en `parent/name/`. Devuelve la ruta del directorio creado."""
    target = parent / name
    if target.exists():
        raise FileExistsError(f"Ya existe: {target}")
    (target / "assets").mkdir(parents=True)
    (target / "template.yaml").write_text(SCAFFOLD_YAML.format(name=name), encoding="utf-8")
    (target / "script_demo.json").write_text(SCAFFOLD_DEMO.format(name=name), encoding="utf-8")
    return target
