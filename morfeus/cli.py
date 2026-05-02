"""CLI de Morfeus."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from morfeus.audio.tts import synth_script
from morfeus.config import Script
from morfeus.script.generator import (
    DEFAULT_TREND,
    LLMNotConfigured,
    ScriptGenerationError,
    generate_script,
)
from morfeus.templates.loader import (
    PACKAGE_TEMPLATES_DIR,
    list_templates,
    load_template,
    scaffold_template,
    search_paths,
    template_dir,
)
from morfeus.trends.cache import get_or_fetch_trends
from morfeus.trends.matcher import pick_trend, trend_to_prompt_phrase
from morfeus.video.animate import render_video_animated
from morfeus.video.compose import render_video
from morfeus.video.lipsync import (
    SadTalkerNotConfigured,
    generate_lipsync_videos,
)

console = Console()


def _load_script(path: Path) -> Script:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Script(**raw)


def _generate_from_script(
    script: Script,
    template_name: str,
    output: Path,
    keep_work_dir: bool,
    animated: bool = True,
    lipsync: bool = False,
) -> None:
    template = load_template(template_name)

    work_dir = Path(tempfile.mkdtemp(prefix="morfeus_"))
    try:
        console.print(f"[cyan]Plantilla:[/cyan] {template.name} ({len(template.characters)} personajes)")
        console.print(f"[cyan]Turnos:[/cyan] {len(script.turnos)}")
        mode = "estático"
        if animated:
            mode = "animado (karaoke + bobbing)"
            if lipsync:
                mode += " + lip-sync (SadTalker)"
        console.print(f"[cyan]Modo:[/cyan] {mode}")
        console.print(f"[cyan]Carpeta de trabajo:[/cyan] {work_dir}")

        with console.status("[bold cyan]Sintetizando voces (edge-tts)…[/bold cyan]"):
            turnos = synth_script(script, template, work_dir / "tts")
        total_audio = sum(t.duration for t in turnos)
        console.print(f"[green]✓[/green] {len(turnos)} pistas de audio, {total_audio:.1f}s totales.")

        lipsync_videos = None
        if lipsync:
            if not animated:
                console.print("[yellow]--lipsync requiere modo animado; activándolo.[/yellow]")
                animated = True
            try:
                with console.status("[bold cyan]Generando lip-sync con SadTalker (lento)…[/bold cyan]"):
                    lipsync_videos = generate_lipsync_videos(template, turnos, work_dir / "lipsync")
                console.print(f"[green]✓[/green] {len(lipsync_videos)} videos lip-sync generados.")
            except SadTalkerNotConfigured as exc:
                console.print(f"[red]Lip-sync no disponible:[/red] {exc}")
                console.print("[yellow]Continuando sin lip-sync.[/yellow]")
                lipsync_videos = None

        with console.status("[bold cyan]Componiendo video…[/bold cyan]"):
            if animated:
                result = render_video_animated(
                    template, turnos, output, work_dir / "video",
                    lipsync_videos=lipsync_videos,
                )
            else:
                result = render_video(template, turnos, output, work_dir / "video")

        console.print(f"[green]✓[/green] Video listo: [bold]{result.output_path}[/bold]")
        console.print(
            f"  duración={result.duration_seconds:.1f}s · {result.width}x{result.height}"
        )
    finally:
        if not keep_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
        else:
            console.print(f"[dim]Carpeta de trabajo conservada en {work_dir}[/dim]")


@click.group()
@click.version_option()
def main() -> None:
    """Morfeus — generador automático de videos virales."""


@main.command(name="generate-demo")
@click.option(
    "--template", "template_name",
    default="socrates_skeleton",
    show_default=True,
    help="Nombre de la plantilla a usar.",
)
@click.option(
    "--out", "output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("outputs/demo.mp4"),
    show_default=True,
    help="Ruta de salida del MP4.",
)
@click.option(
    "--animated/--static", default=True,
    help="Animado: bobbing del personaje activo + karaoke palabra-por-palabra. Estático: 1 frame por turno.",
)
@click.option(
    "--lipsync/--no-lipsync", default=False,
    help="Lip-sync con SadTalker (lento, requiere GPU + setup). Ver morfeus/video/lipsync.py.",
)
@click.option(
    "--keep-work-dir/--no-keep-work-dir", default=False,
    help="Conservar archivos intermedios para depurar.",
)
def generate_demo(
    template_name: str, output: Path, animated: bool, lipsync: bool, keep_work_dir: bool,
) -> None:
    """Genera un video usando el script_demo.json de la plantilla."""
    demo_path = template_dir(template_name) / "script_demo.json"
    if not demo_path.exists():
        console.print(f"[red]No existe demo para la plantilla '{template_name}': {demo_path}[/red]")
        sys.exit(1)
    script = _load_script(demo_path)
    _generate_from_script(
        script, template_name, output, keep_work_dir,
        animated=animated, lipsync=lipsync,
    )


@main.command(name="generate")
@click.option(
    "--script", "script_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="JSON con el guion. Si se omite, se generará automáticamente con --product.",
)
@click.option(
    "--product", "producto",
    help="Producto/servicio a promocionar (requerido si no se pasa --script).",
)
@click.option(
    "--trend",
    default=None,
    help="Tono / trend a inyectar al prompt del LLM. Si se omite, se autodetecta vía Trend Scout.",
)
@click.option(
    "--region",
    default="MX",
    show_default=True,
    help="Código de país (MX, ES, AR, CO, CL, PE, US) para el Trend Scout.",
)
@click.option(
    "--no-trend-scout/--trend-scout", default=False,
    help="Desactiva la detección automática de trends.",
)
@click.option(
    "--llm",
    type=click.Choice(["auto", "groq", "gemini"]),
    default="auto",
    show_default=True,
    help="Provider de LLM para generar el guion.",
)
@click.option(
    "--save-script", "save_script_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Si se pasa, guarda el guion generado en esta ruta como JSON.",
)
@click.option(
    "--template", "template_name",
    default="socrates_skeleton",
    show_default=True,
)
@click.option(
    "--out", "output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("outputs/video.mp4"),
    show_default=True,
)
@click.option(
    "--animated/--static", default=True,
    help="Animado: bobbing del personaje activo + karaoke palabra-por-palabra.",
)
@click.option(
    "--lipsync/--no-lipsync", default=False,
    help="Lip-sync con SadTalker (requiere GPU + setup previo).",
)
@click.option(
    "--keep-work-dir/--no-keep-work-dir", default=False,
)
def generate(
    script_path: Path | None,
    producto: str | None,
    trend: str | None,
    region: str,
    no_trend_scout: bool,
    llm: str,
    save_script_path: Path | None,
    template_name: str,
    output: Path,
    animated: bool,
    lipsync: bool,
    keep_work_dir: bool,
) -> None:
    """Genera un video desde un guion (JSON existente o generado por LLM)."""
    if script_path is None and not producto:
        raise click.UsageError("Pasa --script <archivo.json> o --product '<descripción>'.")

    if script_path is not None:
        script = _load_script(script_path)
    else:
        template = load_template(template_name)

        # Resolver el trend: explícito > scout > default.
        effective_trend = trend
        if effective_trend is None and not no_trend_scout:
            with console.status(f"[cyan]Buscando trends en {region}…[/cyan]"):
                trends = get_or_fetch_trends(region=region, limit=12)
            chosen = pick_trend(producto, trends)
            if chosen is not None:
                effective_trend = trend_to_prompt_phrase(chosen)
                console.print(
                    f"[green]✓[/green] Trend elegido: [bold]{chosen.name}[/bold] "
                    f"([dim]{chosen.source}[/dim])"
                )
            else:
                console.print("[yellow]Sin trends disponibles; usando tono por defecto.[/yellow]")
        if effective_trend is None:
            effective_trend = DEFAULT_TREND

        console.print(f"[cyan]Generando guion con LLM ({llm})…[/cyan]")
        try:
            script = generate_script(template, producto=producto, trend=effective_trend, provider=llm)
        except (LLMNotConfigured, ScriptGenerationError) as exc:
            console.print(f"[red]No se pudo generar el guion:[/red] {exc}")
            sys.exit(2)
        console.print(f"[green]✓[/green] Guion generado ({len(script.turnos)} turnos).")
        for t in script.turnos:
            console.print(f"  [dim]{t.speaker}:[/dim] {t.text}")
        if save_script_path is not None:
            save_script_path.parent.mkdir(parents=True, exist_ok=True)
            save_script_path.write_text(
                script.model_dump_json(indent=2, exclude_none=True),
                encoding="utf-8",
            )
            console.print(f"[dim]Guion guardado en {save_script_path}[/dim]")

    _generate_from_script(
        script, template_name, output, keep_work_dir,
        animated=animated, lipsync=lipsync,
    )


@main.group()
def templates() -> None:
    """Comandos sobre plantillas disponibles."""


@templates.command("list")
def templates_list() -> None:
    """Lista las plantillas registradas."""
    table = Table(title="Plantillas de Morfeus")
    table.add_column("Nombre", style="cyan")
    table.add_column("Personajes")
    table.add_column("Descripción")
    table.add_column("Origen", style="dim")
    for name, path in list_templates():
        try:
            cfg = load_template(name)
            chars = ", ".join(c.id for c in cfg.characters)
            desc = (cfg.description or "").strip().replace("\n", " ")
            if len(desc) > 60:
                desc = desc[:57] + "…"
            origin = "paquete" if path.is_relative_to(PACKAGE_TEMPLATES_DIR) else str(path.parent)
            table.add_row(name, chars, desc, origin)
        except Exception as exc:  # pragma: no cover
            table.add_row(name, "?", f"[red]Error: {exc}[/red]", str(path.parent))
    console.print(table)


@templates.command("paths")
def templates_paths() -> None:
    """Muestra los directorios donde se buscan plantillas."""
    table = Table(title="Search paths")
    table.add_column("#", justify="right")
    table.add_column("Ruta")
    table.add_column("Existe", justify="center")
    for i, p in enumerate(search_paths(), start=1):
        table.add_row(str(i), str(p), "✓" if p.exists() else "✗")
    console.print(table)
    console.print(
        "[dim]Define MORFEUS_TEMPLATES_DIR (separador: ';' en Windows, ':' en Unix) "
        "para añadir directorios extra (ej. tu Drive).[/dim]"
    )


@main.group()
def trends() -> None:
    """Comandos sobre trends actuales."""


@trends.command("list")
@click.option("--region", default="MX", show_default=True)
@click.option("--limit", default=10, show_default=True)
@click.option("--refresh/--cached", default=False, help="Forzar nuevo fetch ignorando la caché.")
def trends_list(region: str, limit: int, refresh: bool) -> None:
    """Lista los trends actuales detectados (de la caché si está fresca)."""
    items = get_or_fetch_trends(region=region, limit=limit, force_refresh=refresh)
    if not items:
        console.print(
            f"[yellow]No se obtuvieron trends para {region}. ¿Sin internet o "
            "Google Trends caído?[/yellow]"
        )
        return
    table = Table(title=f"Trends · {region}")
    table.add_column("#", justify="right")
    table.add_column("Trend", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Fuente", style="dim")
    table.add_column("Descripción")
    for i, t in enumerate(items, start=1):
        table.add_row(
            str(i),
            t.name,
            f"{t.score:.1f}",
            t.source,
            t.description,
        )
    console.print(table)


@trends.command("refresh")
@click.option("--region", default="MX", show_default=True)
def trends_refresh(region: str) -> None:
    """Refresca la caché de trends ahora mismo."""
    items = get_or_fetch_trends(region=region, force_refresh=True)
    console.print(f"[green]✓[/green] {len(items)} trends almacenados en caché para {region}.")


@templates.command("new")
@click.argument("name")
@click.option(
    "--in", "parent_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Directorio padre donde crear la plantilla.",
)
def templates_new(name: str, parent_dir: Path) -> None:
    """Crea una plantilla nueva con scaffold mínimo."""
    try:
        path = scaffold_template(name, parent_dir)
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    console.print(f"[green]✓[/green] Plantilla creada en {path}")
    console.print(
        f"[dim]Para usarla: agrega su padre a MORFEUS_TEMPLATES_DIR o pásala "
        f"como ruta directa a --template.[/dim]"
    )


if __name__ == "__main__":
    main()
