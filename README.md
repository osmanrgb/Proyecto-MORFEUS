# Morfeus 🎬

Generador automático de videos virales cortos (9:16) — tipo el meme de Sócrates + esqueleto — para hacer publicidad. Gratis, en la nube, en español.

```
producto + plantilla → trend scout → LLM (Groq) → edge-tts → MoviePy → MP4 9:16
```

## Qué hace

- Detecta automáticamente trends actuales por país (Google Trends + TikTok Creative Center) y los inyecta en el prompt del LLM.
- Genera el guion con un LLM gratis (Groq Llama 3.3 70B; fallback Gemini).
- Sintetiza voces neuronales en español con `edge-tts` (sin API key, sin tarjeta).
- Compone el video con animación: el personaje activo "rebota" con el audio y los subtítulos aparecen palabra-por-palabra estilo CapCut.
- Sistema de plantillas pluggable (`socrates_skeleton`, `abuelita_nieto`, o las tuyas).
- Soporte opcional de lip-sync real con SadTalker (requiere GPU).

## Uso rápido — Google Colab (recomendado)

Abrí [`colab/morfeus_colab.ipynb`](colab/morfeus_colab.ipynb) y seguí las celdas. Necesitas:

- Una API key de Groq (gratis, sin tarjeta): https://console.groq.com
- (Opcional) Una cuenta de Drive para guardar outputs y assets entre sesiones.
- (Opcional) Runtime con GPU sólo si vas a usar `--lipsync`.

## Uso local

```bash
pip install -e ".[all]"
export GROQ_API_KEY=tu_key       # Windows: setx GROQ_API_KEY "tu_key"
morfeus generate --product "Barbería Don Carlos en Tegucigalpa" --region MX
```

Salida: `outputs/video.mp4`. Necesitas **FFmpeg** en el `PATH` (`winget install ffmpeg` en Windows; `apt install ffmpeg` en Linux/Colab).

## Comandos disponibles

```bash
# Demo sin LLM (verifica el pipeline TTS + composición)
morfeus generate-demo --out outputs/demo.mp4 [--static]

# Generar desde un producto (LLM + trends automáticos)
morfeus generate --product "..." --template socrates_skeleton --region MX

# Generar desde un guion JSON propio
morfeus generate --script mi_guion.json --template socrates_skeleton

# Listar plantillas disponibles
morfeus templates list

# Crear una plantilla nueva con scaffold
morfeus templates new mi_trend --in /content/drive/MyDrive/Morfeus/templates

# Listar trends actuales
morfeus trends list --region MX
morfeus trends refresh --region MX
```

Flags clave de `generate`:

| Flag | Descripción |
|------|-------------|
| `--product TEXT` | Descripción del producto/servicio (requerido si no pasás `--script`) |
| `--script PATH` | JSON con guion propio (formato `{"turnos":[…]}`) |
| `--template NAME` | Nombre de plantilla o ruta a `template.yaml` |
| `--region MX` | País para el Trend Scout (MX, ES, AR, CO, CL, PE, US) |
| `--trend TEXT` | Sobreescribe el trend autodetectado |
| `--no-trend-scout` | Salta la detección de trends |
| `--llm auto\|groq\|gemini` | Provider del LLM (default: auto = Groq, fallback Gemini) |
| `--animated/--static` | Animación con bobbing + karaoke (default) o frame estático por turno |
| `--lipsync` | Sincronización de labios real con SadTalker (lento, requiere GPU) |
| `--save-script PATH` | Guarda el guion generado para revisar/editar |

## Plantillas

Una plantilla es un directorio con `template.yaml` que define personajes, voces edge-tts, posiciones y el prompt para el LLM. Plantillas incluidas:

- `socrates_skeleton` — Sócrates filosofando, esqueleto sarcástico cierra con el producto.
- `abuelita_nieto` — Abuelita pregunta inocentemente, nieto explica con gracia y mete el producto.

Para agregar la tuya: `morfeus templates new <nombre>` y editá el `template.yaml`. Si querés que vivan fuera del repo: `export MORFEUS_TEMPLATES_DIR=/ruta/a/tu/carpeta` (o varias separadas por `:` en Linux / `;` en Windows).

## Configuración por variables de entorno

| Variable | Para qué |
|----------|----------|
| `GROQ_API_KEY` | LLM primario (recomendado) |
| `GEMINI_API_KEY` | LLM fallback |
| `MORFEUS_TEMPLATES_DIR` | Directorio(s) extra donde buscar plantillas |
| `MORFEUS_CACHE_DIR` | Dónde cachear resultados del Trend Scout (default: `~/.morfeus_cache`) |
| `MORFEUS_SADTALKER_DIR` | Ruta al checkout de SadTalker (sólo para `--lipsync`) |

## Arquitectura

```
morfeus/
├── cli.py                   # entry point (click)
├── config.py                # modelos Pydantic
├── audio/
│   ├── tts.py               # edge-tts + pitch-shift opcional con FFmpeg
│   └── envelope.py          # RMS por frame para bobbing
├── script/
│   └── generator.py         # Groq + Gemini fallback, JSON estricto
├── trends/
│   ├── scout.py             # Google Trends + TikTok Creative Center
│   ├── matcher.py           # ranking heurístico vs producto
│   └── cache.py             # caché 24h
├── templates/
│   ├── loader.py            # registry pluggable, scaffold
│   ├── socrates_skeleton/   # plantilla #1
│   └── abuelita_nieto/      # plantilla #2
└── video/
    ├── stage.py             # compositor PIL (placeholders, subtítulos)
    ├── compose.py           # render estático (1 frame por turno)
    ├── animate.py           # render animado (bobbing + karaoke)
    └── lipsync.py           # subprocess a SadTalker (opcional)
```

## Estado

Todas las fases del plan implementadas. La validación end-to-end vive en el notebook de Colab.

## Licencia

MIT.
