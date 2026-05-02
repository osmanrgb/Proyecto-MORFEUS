"""Genera los assets de imagen (escenario, personajes, subtítulos) con Pillow.

En Fase 1 esto produce un PNG estático del 'escenario' (fondo + personajes en sus
posiciones) más helpers para renderizar subtítulos. Fase 3 añadirá animación
sincronizada con el audio.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from morfeus.config import CharacterCfg, TemplateCfg

CHARACTER_BOX_HEIGHT_RATIO = 0.42  # cada personaje ocupa hasta el 42% del alto
CHARACTER_PADDING_RATIO = 0.04


# --- Fuentes ----------------------------------------------------------------

_FONT_CANDIDATES = [
    # Linux / Colab
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


# --- Personajes -------------------------------------------------------------

def _placeholder_character(width: int, height: int, label: str, color: str) -> Image.Image:
    """Genera un placeholder colorido cuando no hay PNG real del personaje."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = 16
    draw.rounded_rectangle(
        [pad, pad, width - pad, height - pad],
        radius=48,
        fill=color,
        outline=(255, 255, 255, 220),
        width=6,
    )

    font = _load_font(size=max(48, height // 8))
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((width - tw) // 2, (height - th) // 2),
        label,
        fill=(255, 255, 255, 255),
        font=font,
        stroke_width=4,
        stroke_fill=(0, 0, 0, 255),
    )
    return img


def _load_character_image(char: CharacterCfg, target_w: int, target_h: int) -> Image.Image:
    """Carga el PNG del personaje (manteniendo aspect ratio) o devuelve placeholder."""
    if char.image and Path(char.image).exists():
        img = Image.open(char.image).convert("RGBA")
        img.thumbnail((target_w, target_h), Image.LANCZOS)
        return img

    color_for = {
        "socrates": "#4a3a2a",
        "skeleton": "#1a1a1a",
    }
    return _placeholder_character(
        target_w, target_h,
        label=char.display_name,
        color=color_for.get(char.id, "#3a3a5a"),
    )


# --- Escena -----------------------------------------------------------------

def render_stage(
    template: TemplateCfg,
    active_speaker: str | None,
) -> Image.Image:
    """Renderiza el escenario completo (fondo + ambos personajes).

    El personaje activo se muestra con opacidad 100%; el inactivo al 35%.
    """
    W, H = template.width, template.height

    # Fondo
    if template.background_image and Path(template.background_image).exists():
        bg = Image.open(template.background_image).convert("RGB")
        bg = bg.resize((W, H), Image.LANCZOS)
        canvas = bg.convert("RGBA")
    else:
        canvas = Image.new("RGBA", (W, H), template.background_color)

    # Posiciones por personaje (top/bottom). Asumimos máximo 2 personajes con top y bottom.
    box_h = int(H * CHARACTER_BOX_HEIGHT_RATIO)
    box_w = int(W * (1 - 2 * CHARACTER_PADDING_RATIO))
    pad_x = (W - box_w) // 2

    for char in template.characters:
        char_img = _load_character_image(char, box_w, box_h)
        if char.position == "top":
            y = int(H * 0.06)
        elif char.position == "bottom":
            y = int(H - H * 0.06 - char_img.height)
        elif char.position == "left":
            y = (H - char_img.height) // 2
        else:  # right
            y = (H - char_img.height) // 2

        # Centrar horizontalmente dentro del box
        x = pad_x + (box_w - char_img.width) // 2

        # Dim si no es el activo: reducir alpha multiplicativamente al 35%
        if active_speaker is not None and char.id != active_speaker:
            alpha = char_img.split()[-1].point(lambda a: int(a * 0.35))
            char_img.putalpha(alpha)

        canvas.alpha_composite(char_img, (x, y))

    return canvas


# --- Subtítulos -------------------------------------------------------------

def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for w in words:
        candidate = " ".join(current + [w])
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current.append(w)
        else:
            lines.append(" ".join(current))
            current = [w]
    if current:
        lines.append(" ".join(current))
    return lines


def render_subtitle(text: str, width: int, height: int) -> Image.Image:
    """Renderiza el subtítulo del turno actual sobre fondo transparente.

    El tamaño devuelto es (width, h_subtitle) donde h_subtitle se ajusta al texto.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = max(56, width // 18)
    font = _load_font(font_size)

    side_pad = int(width * 0.06)
    max_text_w = width - 2 * side_pad

    lines = _wrap_text(text, font, max_text_w, draw)
    if not lines:
        return img

    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])
    line_gap = font_size // 4
    total_h = sum(line_heights) + line_gap * (len(lines) - 1)

    y = height - total_h - int(height * 0.05)
    for line, lh in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (width - lw) // 2
        draw.text(
            (x, y),
            line,
            fill=(255, 255, 255, 255),
            font=font,
            stroke_width=6,
            stroke_fill=(0, 0, 0, 255),
        )
        y += lh + line_gap

    return img
