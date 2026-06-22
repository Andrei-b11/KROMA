"""Operaciones de imagen (Pillow + numpy) y conversión PIL <-> Qt.

Cada función recibe y devuelve imágenes PIL (modo RGBA salvo que se indique),
para que la UI no dependa de los detalles del procesamiento.
"""
from __future__ import annotations

import io
import math

import numpy as np
from PIL import (
    Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageColor
)
from PySide6.QtGui import QImage

# ---------------------------------------------------------------------------
# Conversión PIL <-> Qt
# ---------------------------------------------------------------------------

def pil_to_qimage(img: Image.Image) -> QImage:
    """Convierte una imagen PIL a QImage (formato RGBA8888)."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
    return qimg.copy()  # copy para que sea dueño de su buffer


def qimage_to_pil(qimg: QImage) -> Image.Image:
    qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.constBits()
    arr = np.frombuffer(memoryview(ptr), dtype=np.uint8).reshape((h, qimg.bytesPerLine()))
    arr = arr[:, : w * 4].reshape((h, w, 4))
    return Image.fromarray(arr.copy(), "RGBA")


def load_image(path) -> Image.Image:
    """Abre una imagen corrigiendo su orientación EXIF y la devuelve en RGBA.

    Las fotos de móvil suelen guardar la rotación en metadatos EXIF; sin esta
    corrección se ven giradas. Centralizar la apertura aquí evita ese problema
    en todas las herramientas.
    """
    img = Image.open(path)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img.convert("RGBA")


# ---------------------------------------------------------------------------
# 1 · Optimización y calidad
# ---------------------------------------------------------------------------

def estimate_size(img: Image.Image, fmt: str = "PNG", quality: int = 80) -> int:
    """Bytes estimados al guardar con un formato/calidad dados."""
    buf = io.BytesIO()
    save_image(img, buf, fmt, quality)
    return buf.tell()


def save_image(img: Image.Image, fp, fmt: str = "PNG", quality: int = 80):
    """Guarda una imagen aplicando opciones por formato."""
    fmt = fmt.upper()
    if fmt in ("JPG", "JPEG"):
        rgb = Image.new("RGB", img.size, (255, 255, 255))
        rgb.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        rgb.save(fp, "JPEG", quality=quality, optimize=True, progressive=True)
    elif fmt == "WEBP":
        img.save(fp, "WEBP", quality=quality, method=6)
    elif fmt == "PNG":
        # quality 0-100 -> nivel de compresión 9-0 + cuantización opcional
        if quality < 90:
            colors = max(8, int(256 * (quality / 100)))
            q = img.convert("RGBA").quantize(colors=colors, method=Image.FASTOCTREE)
            q.save(fp, "PNG", optimize=True)
        else:
            img.save(fp, "PNG", optimize=True, compress_level=6)
    elif fmt == "GIF":
        img.convert("P", palette=Image.ADAPTIVE).save(fp, "GIF")
    elif fmt == "BMP":
        rgb = Image.new("RGB", img.size, (255, 255, 255))
        rgb.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        rgb.save(fp, "BMP")
    elif fmt in ("TIF", "TIFF"):
        img.save(fp, "TIFF", compression="tiff_lzw")
    elif fmt == "ICO":
        # ICO multi-tamaño: solo tamaños que quepan en la imagen original.
        mx = max(img.size)
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= mx]
        img.save(fp, "ICO", sizes=sizes or [(32, 32)])
    else:
        img.save(fp, fmt)


def compress(img: Image.Image, quality: int, fmt: str) -> tuple[Image.Image, int]:
    """Recodifica para reducir peso. Devuelve (imagen_resultante, bytes)."""
    buf = io.BytesIO()
    save_image(img, buf, fmt, quality)
    buf.seek(0)
    out = Image.open(buf).convert("RGBA")
    out.load()
    return out, buf.getbuffer().nbytes


def remove_background(img: Image.Image, tolerance: int = 40,
                      use_ai: bool = False, feather: int = 1) -> Image.Image:
    """Aísla el sujeto eliminando el fondo.

    Si ``use_ai`` y rembg está disponible, usa la red neuronal U2-Net.
    En caso contrario aplica relleno por inundación desde los bordes con la
    tolerancia indicada (ideal para fondos lisos o uniformes).
    """
    if use_ai:
        try:
            import rembg  # type: ignore
            buf = io.BytesIO()
            img.convert("RGBA").save(buf, "PNG")
            out = rembg.remove(buf.getvalue())
            return Image.open(io.BytesIO(out)).convert("RGBA")
        except Exception:
            pass  # cae al método clásico

    rgb = img.convert("RGB")
    work = rgb.copy()
    w, h = work.size
    marker = (1, 254, 2)
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for s in seeds:
        ImageDraw.floodfill(work, s, marker, thresh=float(tolerance))
    mask = np.all(np.array(work) == marker, axis=-1)

    out = img.convert("RGBA")
    alpha = np.array(out)[:, :, 3].copy()
    alpha[mask] = 0
    alpha_img = Image.fromarray(alpha, "L")
    if feather > 0:
        alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(feather))
    out.putalpha(alpha_img)
    return out


def upscale(img: Image.Image, factor: float, enhance: bool = True) -> Image.Image:
    """Aumenta la resolución con remuestreo LANCZOS y realce de detalle."""
    w, h = img.size
    new = (max(1, int(w * factor)), max(1, int(h * factor)))
    out = img.resize(new, Image.LANCZOS)
    if enhance:
        out = out.filter(ImageFilter.UnsharpMask(radius=2, percent=110, threshold=2))
        out = ImageEnhance.Contrast(out).enhance(1.04)
    return out


# ---------------------------------------------------------------------------
# 2 · Modificación y estructura
# ---------------------------------------------------------------------------

def resize(img: Image.Image, width: int, height: int) -> Image.Image:
    return img.resize((max(1, width), max(1, height)), Image.LANCZOS)


def crop(img: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    x0, y0, x1, y1 = box
    x0, x1 = sorted((max(0, x0), min(img.width, x1)))
    y0, y1 = sorted((max(0, y0), min(img.height, y1)))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return img
    return img.crop((x0, y0, x1, y1))


def rotate(img: Image.Image, degrees: int) -> Image.Image:
    return img.rotate(-degrees, expand=True)


def flip(img: Image.Image, horizontal: bool) -> Image.Image:
    return img.transpose(Image.FLIP_LEFT_RIGHT if horizontal else Image.FLIP_TOP_BOTTOM)


# ---------------------------------------------------------------------------
# 3 · Conversión de formatos
# ---------------------------------------------------------------------------

def build_gif(frames: list[Image.Image], duration_ms: int = 300,
              loop: bool = True, size: tuple[int, int] | None = None) -> bytes:
    """Crea un GIF animado a partir de una secuencia de imágenes."""
    if not frames:
        raise ValueError("Sin fotogramas")
    if size is None:
        size = frames[0].size
    norm = [f.convert("RGBA").resize(size, Image.LANCZOS) for f in frames]
    flat = []
    for f in norm:
        bg = Image.new("RGBA", size, (255, 255, 255, 255))
        bg.alpha_composite(f)
        flat.append(bg.convert("P", palette=Image.ADAPTIVE))
    buf = io.BytesIO()
    flat[0].save(buf, "GIF", save_all=True, append_images=flat[1:],
                 duration=duration_ms, loop=0 if loop else 1, disposal=2)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 4 · Edición creativa
# ---------------------------------------------------------------------------

def adjust(img: Image.Image, brightness=1.0, contrast=1.0,
           saturation=1.0) -> Image.Image:
    out = img
    if brightness != 1.0:
        out = ImageEnhance.Brightness(out).enhance(brightness)
    if contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    if saturation != 1.0:
        out = ImageEnhance.Color(out).enhance(saturation)
    return out


FILTERS = ["Original", "Grises", "Sepia", "Invertir", "Vívido", "Frío",
           "Cálido", "Desenfoque", "Nitidez", "Viñeta", "Vintage", "Posterizar"]


def _vignette(rgb: Image.Image, strength: float = 0.8) -> Image.Image:
    """Oscurece progresivamente las esquinas (efecto viñeta)."""
    w, h = rgb.size
    yy, xx = np.ogrid[:h, :w]
    cx, cy = w / 2.0, h / 2.0
    dist = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    mask = np.clip(1.0 - strength * np.clip(dist - 0.55, 0, None) * 1.6, 0.0, 1.0)
    arr = np.asarray(rgb, dtype=np.float32) * mask[..., None]
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")


def apply_filter(img: Image.Image, name: str) -> Image.Image:
    rgba = img.convert("RGBA")
    rgb = rgba.convert("RGB")
    alpha = rgba.split()[-1]

    if name == "Grises":
        rgb = ImageOps.grayscale(rgb).convert("RGB")
    elif name == "Sepia":
        g = ImageOps.grayscale(rgb)
        rgb = ImageOps.colorize(g, black="#2b1d0e", white="#fff1c9").convert("RGB")
    elif name == "Invertir":
        rgb = ImageOps.invert(rgb)
    elif name == "Vívido":
        rgb = ImageEnhance.Color(rgb).enhance(1.6)
        rgb = ImageEnhance.Contrast(rgb).enhance(1.12)
    elif name == "Frío":
        r, g, b = rgb.split()
        b = b.point(lambda v: min(255, int(v * 1.18)))
        r = r.point(lambda v: int(v * 0.92))
        rgb = Image.merge("RGB", (r, g, b))
    elif name == "Cálido":
        r, g, b = rgb.split()
        r = r.point(lambda v: min(255, int(v * 1.16)))
        b = b.point(lambda v: int(v * 0.9))
        rgb = Image.merge("RGB", (r, g, b))
    elif name == "Desenfoque":
        rgb = rgb.filter(ImageFilter.GaussianBlur(3))
    elif name == "Nitidez":
        rgb = rgb.filter(ImageFilter.UnsharpMask(2, 150, 3))
    elif name == "Viñeta":
        rgb = _vignette(rgb)
    elif name == "Vintage":
        rgb = ImageEnhance.Color(rgb).enhance(0.7)
        rgb = ImageEnhance.Contrast(rgb).enhance(0.92)
        r, g, b = rgb.split()
        r = r.point(lambda v: min(255, int(v * 1.1 + 12)))
        b = b.point(lambda v: int(v * 0.88))
        rgb = _vignette(Image.merge("RGB", (r, g, b)), strength=0.6)
    elif name == "Posterizar":
        rgb = ImageOps.posterize(rgb, 3)

    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _load_font(size: int, bold_impact: bool = True) -> ImageFont.FreeTypeFont:
    candidates = (["impact.ttf", "Impact.ttf", "C:/Windows/Fonts/impact.ttf"]
                  if bold_impact else [])
    candidates += ["arialbd.ttf", "C:/Windows/Fonts/arialbd.ttf",
                   "DejaVuSans-Bold.ttf"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def add_meme_text(img: Image.Image, top: str = "", bottom: str = "",
                  font_scale: float = 1.0) -> Image.Image:
    """Superpone texto estilo meme (Impact blanco con contorno negro)."""
    out = img.convert("RGBA")
    draw = ImageDraw.Draw(out)
    w, h = out.size
    size = max(14, int(h * 0.11 * font_scale))
    font = _load_font(size)
    stroke = max(2, size // 12)

    def draw_centered(text, y_top):
        text = text.upper()
        if not text:
            return
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        tw = bbox[2] - bbox[0]
        x = (w - tw) / 2 - bbox[0]
        draw.text((x, y_top), text, font=font, fill="white",
                  stroke_width=stroke, stroke_fill="black")

    if top:
        draw_centered(top, int(h * 0.03))
    if bottom:
        bbox = draw.textbbox((0, 0), bottom.upper(), font=font, stroke_width=stroke)
        th = bbox[3] - bbox[1]
        draw_centered(bottom, int(h - th - h * 0.05))
    return out


# ---------------------------------------------------------------------------
# 5 · Seguridad y privacidad
# ---------------------------------------------------------------------------

ANCHORS = {
    "Sup. Izq.": (0, 0), "Sup. Centro": (1, 0), "Sup. Der.": (2, 0),
    "Centro Izq.": (0, 1), "Centro": (1, 1), "Centro Der.": (2, 1),
    "Inf. Izq.": (0, 2), "Inf. Centro": (1, 2), "Inf. Der.": (2, 2),
}


def _anchor_pos(canvas, item, anchor, margin):
    ax, ay = ANCHORS.get(anchor, (2, 2))
    cw, ch = canvas
    iw, ih = item
    x = [margin, (cw - iw) // 2, cw - iw - margin][ax]
    y = [margin, (ch - ih) // 2, ch - ih - margin][ay]
    return int(x), int(y)


def watermark_text(img: Image.Image, text: str, opacity: int = 50,
                   scale: float = 1.0, anchor: str = "Inf. Der.",
                   color: str = "#FFFFFF", tile: bool = False) -> Image.Image:
    base = img.convert("RGBA")
    w, h = base.size
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    size = max(10, int(h * 0.06 * scale))
    font = _load_font(size, bold_impact=False)
    rgba = ImageColor.getrgb(color) + (int(255 * opacity / 100),)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    if tile:
        step_x, step_y = tw + size * 2, th + size * 2
        for yy in range(0, h, step_y):
            for xx in range(0, w, step_x):
                draw.text((xx, yy), text, font=font, fill=rgba)
        layer = layer.rotate(30, expand=False)
    else:
        x, y = _anchor_pos((w, h), (tw, th), anchor, int(size * 0.6))
        draw.text((x, y), text, font=font, fill=rgba)

    return Image.alpha_composite(base, layer)


def watermark_logo(img: Image.Image, logo: Image.Image, opacity: int = 50,
                   scale: float = 0.2, anchor: str = "Inf. Der.") -> Image.Image:
    base = img.convert("RGBA")
    w, h = base.size
    lw = max(1, int(w * scale))
    lh = max(1, int(logo.height * (lw / logo.width)))
    lg = logo.convert("RGBA").resize((lw, lh), Image.LANCZOS)
    if opacity < 100:
        a = lg.split()[-1].point(lambda v: int(v * opacity / 100))
        lg.putalpha(a)
    x, y = _anchor_pos((w, h), (lw, lh), anchor, int(min(w, h) * 0.03))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(lg, (x, y), lg)
    return Image.alpha_composite(base, layer)


def pixelate_region(img: Image.Image, box, blocks: int = 16) -> Image.Image:
    """Pixela una región rectangular con cuadrícula de ``blocks`` celdas."""
    out = img.convert("RGBA")
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, x1 = sorted((max(0, x0), min(out.width, x1)))
    y0, y1 = sorted((max(0, y0), min(out.height, y1)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return out
    region = out.crop((x0, y0, x1, y1))
    bw = max(1, blocks)
    small = region.resize((max(1, bw), max(1, int(bw * (y1 - y0) / (x1 - x0)))),
                          Image.NEAREST)
    region = small.resize(region.size, Image.NEAREST)
    out.paste(region, (x0, y0))
    return out


def blur_region(img: Image.Image, box, radius: int = 12) -> Image.Image:
    out = img.convert("RGBA")
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, x1 = sorted((max(0, x0), min(out.width, x1)))
    y0, y1 = sorted((max(0, y0), min(out.height, y1)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return out
    region = out.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(radius))
    out.paste(region, (x0, y0))
    return out


def opencv_available() -> bool:
    """¿Está instalado OpenCV (cv2)?"""
    try:
        import importlib.util
        return importlib.util.find_spec("cv2") is not None
    except Exception:
        return False


def remove_watermark(img: Image.Image, boxes, expand: int = 3) -> Image.Image:
    """Reconstruye (inpaint) las regiones marcadas para borrar marcas de agua,
    logos o texto superpuesto, rellenando con el contexto de alrededor.

    ``expand`` dilata la selección unos píxeles para cubrir el halo/borde de la
    marca (clave para que no quede residuo). Usa OpenCV (``cv2.inpaint``, Telea)
    si está disponible; si no, un relleno por difusión en numpy.
    """
    rgba = img.convert("RGBA")
    arr = np.ascontiguousarray(np.array(rgba))
    h, w = arr.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for box in boxes:
        x0, y0, x1, y1 = [int(v) for v in box]
        x0, x1 = sorted((max(0, x0), min(w, x1)))
        y0, y1 = sorted((max(0, y0), min(h, y1)))
        if x1 - x0 >= 1 and y1 - y0 >= 1:
            mask[y0:y1, x0:x1] = 255
    if not mask.any():
        return rgba
    try:
        import cv2  # type: ignore
        # array contiguo: OpenCV falla con vistas no contiguas (causa del
        # resultado «en negro» al caer al método de respaldo).
        rgb = np.ascontiguousarray(arr[:, :, :3])
        alpha = np.ascontiguousarray(arr[:, :, 3])
        if expand > 0:
            k = np.ones((expand * 2 + 1, expand * 2 + 1), np.uint8)
            mask = cv2.dilate(mask, k)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        # radio pequeño (3): radios grandes solo emborronan más.
        out = cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA)
        rgb2 = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        # reconstruir también el alfa: si la marca está sobre fondo
        # transparente, la zona vuelve a quedar transparente.
        alpha2 = cv2.inpaint(alpha, mask, 3, cv2.INPAINT_TELEA)
        res = arr.copy()
        res[:, :, :3] = rgb2
        res[:, :, 3] = alpha2
        return Image.fromarray(res, "RGBA")
    except Exception:
        if expand > 0:
            mask = _dilate(mask, expand)
        return _inpaint_diffusion(arr, mask)


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Dilatación binaria simple (sin OpenCV) por desplazamientos sucesivos."""
    m = mask > 0
    for _ in range(radius):
        m = (m | np.roll(m, 1, 0) | np.roll(m, -1, 0)
             | np.roll(m, 1, 1) | np.roll(m, -1, 1))
    return (m * 255).astype(np.uint8)


def _inpaint_diffusion(arr: np.ndarray, mask: np.ndarray,
                       iterations: int = 200) -> Image.Image:
    """Relleno por difusión (Jacobi): cada píxel oculto se reemplaza por la
    media de sus vecinos, iterando para propagar el contexto circundante.

    Reconstruye los 4 canales (RGBA), de modo que si la marca está sobre fondo
    transparente, el alfa difundido la deja transparente."""
    ch = arr.astype(np.float32)
    m = mask > 0
    known = ~m
    if known.any():
        for c in range(ch.shape[2]):
            ch[:, :, c][m] = ch[known][:, c].mean()
    for _ in range(iterations):
        up = np.roll(ch, 1, axis=0)
        down = np.roll(ch, -1, axis=0)
        left = np.roll(ch, 1, axis=1)
        right = np.roll(ch, -1, axis=1)
        avg = (up + down + left + right) * 0.25
        ch[m] = avg[m]
    return Image.fromarray(ch.clip(0, 255).astype(np.uint8), "RGBA")


def detect_faces(img: Image.Image):
    """Detecta rostros con OpenCV si está disponible. Devuelve lista de cajas."""
    try:
        import cv2  # type: ignore
        arr = np.array(img.convert("RGB"))[:, :, ::-1].copy()
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
        return [(int(x), int(y), int(x + w), int(y + h)) for (x, y, w, h) in faces]
    except Exception:
        return None
