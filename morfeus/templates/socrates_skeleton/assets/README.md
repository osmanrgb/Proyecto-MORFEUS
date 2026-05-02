# Assets de la plantilla `socrates_skeleton`

Coloca aquí los archivos referenciados por `template.yaml`:

- `socrates.png` — imagen del busto de Sócrates con fondo transparente.
- `skeleton.png` — imagen del esqueleto/cráneo con fondo transparente.
- (opcional) `bg.jpg` o `bg.mp4` — fondo si quieres reemplazar el color sólido.
- (opcional) `music.mp3` — música de fondo royalty-free (Pixabay, YouTube Audio Library).

## Si no hay assets

El generador funciona sin imágenes: se usan **placeholders** (rectángulos con
el nombre del personaje) para que puedas validar el pipeline antes de invertir
tiempo en arte. Cuando tengas los PNGs definitivos, sólo cópialos aquí con
estos nombres exactos y el siguiente render los usará automáticamente.

## Generación rápida de imágenes

Opciones gratis:

- **Gemini Imagen 3** (free tier en aistudio.google.com).
- **FLUX.1-schnell** en HuggingFace Spaces.
- **DALL·E** (vía Bing Image Creator, gratis con cuenta Microsoft).

Prompts sugeridos:

- *Sócrates:* "Bust of Socrates, marble statue, neutral expression, transparent
  background, clean cutout, centered, vertical composition, high contrast."
- *Esqueleto:* "Cartoon skeleton head wearing sunglasses, sarcastic grin,
  transparent background, clean cutout, centered, vertical composition."

Después abre la imagen en remove.bg (gratis) si necesitas refinar el alpha.
