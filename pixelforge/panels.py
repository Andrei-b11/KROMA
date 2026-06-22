"""Paneles de configuración (lado derecho) para cada herramienta.

Cada herramienta es una subclase de :class:`Tool`. ``build()`` devuelve el
widget del panel; ``activate()`` prepara el lienzo; ``apply()`` confirma el
resultado en la imagen. La ventana principal orquesta todo.
"""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Qt, QUrl, QTimer, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QPushButton, QComboBox,
    QSpinBox, QCheckBox, QButtonGroup, QLineEdit, QListWidget, QListWidgetItem,
    QColorDialog, QFrame,
)

from . import imageops as ops, icons, theme
from .canvas import ImageCanvas


def _ic(mw, name):
    """QIcon Lucide coloreado según el tema actual."""
    return icons.make_icon(name, theme.palette(mw.dark)["text"])


# ----------------------------------------------------------------------------
# Helpers de UI
# ----------------------------------------------------------------------------

def _label(text, cls="fieldlabel"):
    lab = QLabel(text)
    lab.setProperty("class", cls)
    lab.setWordWrap(True)   # el texto se reajusta al ancho del panel
    return lab


def _slider_field(layout, name, mn, mx, val, fmt=str):
    row = QHBoxLayout()
    row.addWidget(_label(name))
    row.addStretch()
    vlab = _label(fmt(val), "value")
    row.addWidget(vlab)
    s = QSlider(Qt.Horizontal)
    s.setRange(mn, mx)
    s.setValue(val)
    s.valueChanged.connect(lambda v: vlab.setText(fmt(v)))
    layout.addLayout(row)
    layout.addWidget(s)
    return s


def _choice_group(layout, options, default=0, columns=3):
    """Crea botones exclusivos. Devuelve (QButtonGroup, [botones])."""
    group = QButtonGroup()
    group.setExclusive(True)
    grid = QVBoxLayout()
    grid.setSpacing(8)
    row = None
    buttons = []
    for i, opt in enumerate(options):
        if i % columns == 0:
            row = QHBoxLayout()
            row.setSpacing(8)
            grid.addLayout(row)
        b = QPushButton(opt)
        b.setProperty("class", "choice")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        if i == default:
            b.setChecked(True)
        group.addButton(b, i)
        row.addWidget(b)
        buttons.append(b)
    if row and len(options) % columns:
        for _ in range(columns - (len(options) % columns)):
            row.addStretch()
    layout.addLayout(grid)
    return group, buttons


def _card(layout):
    f = QFrame()
    f.setProperty("class", "card")
    v = QVBoxLayout(f)
    v.setContentsMargins(14, 14, 14, 14)
    v.setSpacing(10)
    layout.addWidget(f)
    return v


def _button(text, primary=False):
    b = QPushButton(text)
    b.setProperty("class", "choice")
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setObjectName("save")
    return b


# ----------------------------------------------------------------------------
# Base
# ----------------------------------------------------------------------------

class Tool:
    key = ""
    title = ""
    eyebrow = "Herramienta"
    apply_label = "APLICAR"
    use_footer = True
    requires_image = True
    can_batch = False   # ¿soporta "Aplicar a todas"?

    def __init__(self, mw):
        self.mw = mw
        self.base = None

    def process(self, img):
        """Transformación pura usada en modo lote. La definen las herramientas
        que soportan procesamiento por lotes."""
        return img

    # --- ciclo de vida ---
    def build(self) -> QWidget:
        return QWidget()

    def activate(self):
        c = self.mw.canvas
        c.discard_scratch()
        c.clear_preview()
        c.set_mode(ImageCanvas.MODE_NONE)
        self.base = self.mw.image()

    def apply(self):
        pass

    def cancel(self):
        c = self.mw.canvas
        c.clear_preview()
        c.discard_scratch()
        c.set_mode(ImageCanvas.MODE_NONE)
        self.mw.refresh_size()


# ----------------------------------------------------------------------------
# 1 · Optimización
# ----------------------------------------------------------------------------

class CompressTool(Tool):
    key = "compress"
    title = "Comprimir imagen"
    eyebrow = "Optimización"
    apply_label = "COMPRIMIR"
    can_batch = True

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(14)
        v.addWidget(_label("Reduce el peso en disco manteniendo la calidad visual.",
                            "muted"))
        v.addWidget(_label("Formato de salida"))
        self.fmt = QComboBox(); self.fmt.addItems(["JPG", "WEBP", "PNG", "BMP", "TIFF"])
        v.addWidget(self.fmt)
        self.q = _slider_field(v, "Calidad", 10, 100, 80, lambda x: f"{x}")
        info = _card(v)
        self.info = _label("—", "muted")
        info.addWidget(self.info)
        v.addStretch()
        self.fmt.currentIndexChanged.connect(self._estimate)
        self.q.valueChanged.connect(self._estimate)
        return w

    def activate(self):
        super().activate()
        self._estimate()

    def _estimate(self):
        img = self.base
        if not img:
            return
        fmt = self.fmt.currentText()
        cur = ops.estimate_size(img, "PNG", 95)
        new = ops.estimate_size(img, fmt, self.q.value())
        pct = 100 - int(new / cur * 100) if cur else 0
        self.info.setText(
            f"Original (PNG): {_human(cur)}\nEstimado {fmt}: {_human(new)}  "
            f"({pct:+d}%)")

    def apply(self):
        fmt, q = self.fmt.currentText(), self.q.value()
        if self.mw.apply_to_all and len(self.mw.docs) > 1:
            with self.mw.busy("Comprimiendo lote…"):
                self.mw.apply_processed(
                    lambda im: ops.compress(im, q, fmt)[0],
                    f"Comprimir ({fmt})", export=(fmt, q))
            return
        out, nbytes = ops.compress(self.base, q, fmt)
        self.mw.set_export(fmt, q)
        self.mw.commit(out, f"Comprimir → {_human(nbytes)}")
        self.mw.toast(f"Comprimido: {_human(nbytes)} ({fmt})")


class RemoveBgTool(Tool):
    key = "removebg"
    title = "Eliminar fondo"
    eyebrow = "IA · Optimización"
    apply_label = "APLICAR"

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(14)
        v.addWidget(_label("Aísla el sujeto y obtén un PNG transparente.", "muted"))
        self.ai = QCheckBox("Usar IA (rembg) si está disponible")
        self.ai.setChecked(self.mw.rembg_available)
        self.ai.setEnabled(self.mw.rembg_available)
        if not self.mw.rembg_available:
            self.ai.setText("IA (rembg) no instalada — método por color")
        v.addWidget(self.ai)
        self.tol = _slider_field(v, "Tolerancia de color", 5, 150, 45)
        self.feather = _slider_field(v, "Suavizado de borde", 0, 8, 1)
        prev = _button("Previsualizar"); prev.setIcon(_ic(self.mw, "eye"))
        prev.clicked.connect(self._preview)
        v.addWidget(prev)
        v.addWidget(_label("El método por color funciona mejor con fondos lisos.",
                            "muted"))

        # --- retoque manual: borrador para limpiar restos de fondo ---
        card = _card(v)
        card.addWidget(_label("Retoque manual"))
        self.erase = QCheckBox("Activar pincel (borrar / restaurar a mano)")
        self.erase.toggled.connect(self._toggle_erase)
        card.addWidget(self.erase)
        self.ebmode, _ = _choice_group(card, ["Borrar", "Restaurar"],
                                       default=0, columns=2)
        self.ebmode.idClicked.connect(
            lambda i: setattr(self.mw.canvas, "erase_mode",
                              "erase" if i == 0 else "restore"))
        self.brush = _slider_field(card, "Tamaño del pincel", 4, 90, 26)
        self.brush.valueChanged.connect(
            lambda v: setattr(self.mw.canvas, "brush_size", v))
        card.addWidget(_label("«Borrar» hace transparentes los restos de fondo; "
                              "«Restaurar» recupera lo borrado por error.", "muted"))
        v.addStretch()
        self._erasing = False
        return w

    def _toggle_erase(self, on):
        c = self.mw.canvas
        self._erasing = on
        if on:
            c.brush_size = self.brush.value()
            c.erase_mode = "erase" if self.ebmode.checkedId() == 0 else "restore"
            # asegura que haya un resultado (fondo quitado) sobre el que borrar
            if not c.has_preview():
                with self.mw.busy("Procesando fondo…"):
                    c.set_preview(self._compute())
            c.set_mode(ImageCanvas.MODE_ERASE)
        else:
            c.set_mode(ImageCanvas.MODE_NONE)

    def _compute(self):
        return ops.remove_background(
            self.base, self.tol.value(), self.ai.isChecked(), self.feather.value())

    def _preview(self):
        def run():
            with self.mw.busy():
                self.mw.canvas.set_preview(self._compute())
        self.mw.toast("Procesando fondo…", ms=800)
        QTimer.singleShot(30, run)

    def apply(self):
        c = self.mw.canvas
        if self._erasing and c.has_erase():
            out = c.erased_pil()
        elif c.has_preview():
            out = c.displayed()
        else:
            with self.mw.busy("Procesando fondo…"):
                out = self._compute()
        self.mw.set_export("PNG", 95)
        self.mw.commit(out.convert("RGBA"), "Eliminar fondo")
        self.mw.toast("Fondo eliminado (PNG transparente)")


class UpscaleTool(Tool):
    key = "upscale"
    title = "Ampliar (Upscale)"
    eyebrow = "IA · Optimización"
    apply_label = "AMPLIAR"

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(14)
        v.addWidget(_label("Aumenta la resolución reconstruyendo detalle.", "muted"))
        v.addWidget(_label("Factor de escala"))
        self.group, _ = _choice_group(v, ["2×", "3×", "4×"], default=0)
        self.enhance = QCheckBox("Realzar nitidez y detalle")
        self.enhance.setChecked(True)
        v.addWidget(self.enhance)
        self.out_lab = _label("—", "muted")
        c = _card(v); c.addWidget(self.out_lab)
        v.addStretch()
        self.group.idClicked.connect(self._update)
        return w

    def _factor(self):
        return [2, 3, 4][self.group.checkedId()]

    def activate(self):
        super().activate()
        self._update()

    def _update(self):
        if self.base:
            f = self._factor()
            self.out_lab.setText(
                f"{self.base.width}×{self.base.height} → "
                f"{self.base.width*f}×{self.base.height*f}")

    def apply(self):
        with self.mw.busy("Ampliando…"):
            out = ops.upscale(self.base, self._factor(), self.enhance.isChecked())
        self.mw.commit(out, f"Ampliar {self._factor()}×")
        self.mw.toast(f"Ampliada a {out.width}×{out.height}")


# ----------------------------------------------------------------------------
# 2 · Modificación
# ----------------------------------------------------------------------------

class ResizeTool(Tool):
    key = "resize"
    title = "Redimensionar"
    eyebrow = "Modificación"
    apply_label = "REDIMENSIONAR"
    can_batch = True

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(14)
        v.addWidget(_label("Define píxeles exactos o usa porcentajes.", "muted"))
        row = QHBoxLayout()
        self.wspin = QSpinBox(); self.wspin.setRange(1, 20000)
        self.hspin = QSpinBox(); self.hspin.setRange(1, 20000)
        col1 = QVBoxLayout(); col1.addWidget(_label("Ancho (px)")); col1.addWidget(self.wspin)
        col2 = QVBoxLayout(); col2.addWidget(_label("Alto (px)")); col2.addWidget(self.hspin)
        row.addLayout(col1); row.addLayout(col2)
        v.addLayout(row)
        self.lock = QCheckBox("Mantener proporción"); self.lock.setChecked(True)
        v.addWidget(self.lock)
        v.addWidget(_label("Escala rápida"))
        prow = QHBoxLayout()
        for pct in (25, 50, 75):
            b = _button(f"{pct}%")
            b.clicked.connect(lambda _=False, p=pct: self._scale_pct(p))
            prow.addWidget(b)
        v.addLayout(prow)
        v.addStretch()
        self.wspin.valueChanged.connect(self._w_changed)
        self.hspin.valueChanged.connect(self._h_changed)
        self._guard = False
        return w

    def activate(self):
        super().activate()
        if self.base:
            self._guard = True
            self.wspin.setValue(self.base.width)
            self.hspin.setValue(self.base.height)
            self._ratio = self.base.width / self.base.height
            self._guard = False

    def _w_changed(self, v):
        if self._guard or not self.lock.isChecked():
            return
        self._guard = True
        self.hspin.setValue(max(1, round(v / self._ratio)))
        self._guard = False

    def _h_changed(self, v):
        if self._guard or not self.lock.isChecked():
            return
        self._guard = True
        self.wspin.setValue(max(1, round(v * self._ratio)))
        self._guard = False

    def _scale_pct(self, pct):
        if not self.base:
            return
        self._guard = True
        self.wspin.setValue(max(1, round(self.base.width * pct / 100)))
        self.hspin.setValue(max(1, round(self.base.height * pct / 100)))
        self._guard = False

    def apply(self):
        ww, hh = self.wspin.value(), self.hspin.value()
        if self.mw.apply_to_all and len(self.mw.docs) > 1:
            self.mw.apply_processed(lambda im: ops.resize(im, ww, hh),
                                    f"Redimensionar {ww}×{hh}")
            return
        out = ops.resize(self.base, ww, hh)
        self.mw.commit(out, f"Redimensionar {out.width}×{out.height}")
        self.mw.toast(f"Nuevo tamaño {out.width}×{out.height}")


class CropTool(Tool):
    key = "crop"
    title = "Recortar"
    eyebrow = "Modificación"
    apply_label = "RECORTAR"

    RATIOS = [("Libre", None), ("1:1", 1), ("4:3", 4/3), ("16:9", 16/9),
              ("3:2", 3/2), ("9:16", 9/16)]

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(14)
        v.addWidget(_label("Arrastra el cuadro o fuerza una proporción.", "muted"))
        v.addWidget(_label("Proporción"))
        self.group, _ = _choice_group(
            v, [r[0] for r in self.RATIOS], default=0, columns=3)
        self.size_lab = _label("—", "value")
        c = _card(v); c.addWidget(self.size_lab)
        v.addStretch()
        self.group.idClicked.connect(self._ratio_changed)
        return w

    def activate(self):
        super().activate()
        self.mw.canvas.set_mode(ImageCanvas.MODE_CROP)
        self.mw.canvas.set_crop_ratio(None)
        self.mw.canvas.cropChanged.connect(self._update)
        self._update()

    def _ratio_changed(self, idx):
        self.mw.canvas.set_crop_ratio(self.RATIOS[idx][1])
        self._update()

    def _update(self):
        r = self.mw.canvas.crop_rect
        if r:
            self.size_lab.setText(f"{int(r.width())} × {int(r.height())} px")

    def apply(self):
        r = self.mw.canvas.crop_rect
        if not r:
            return
        box = (int(r.left()), int(r.top()), int(r.right()), int(r.bottom()))
        out = ops.crop(self.base, box)
        self.mw.commit(out, "Recortar")
        self.mw.toast(f"Recortada a {out.width}×{out.height}")

    def cancel(self):
        try:
            self.mw.canvas.cropChanged.disconnect(self._update)
        except (RuntimeError, TypeError):
            pass
        super().cancel()


class RotateTool(Tool):
    key = "rotate"
    title = "Girar y voltear"
    eyebrow = "Modificación"
    use_footer = False

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12)
        v.addWidget(_label("Corrige la orientación de la imagen.", "muted"))
        actions = [
            ("rotate-ccw", "Girar 90° izquierda", lambda: self._rot(-90)),
            ("rotate-cw", "Girar 90° derecha", lambda: self._rot(90)),
            ("refresh-cw", "Girar 180°", lambda: self._rot(180)),
            ("flip-horizontal", "Voltear horizontal", lambda: self._flip(True)),
            ("flip-vertical", "Voltear vertical", lambda: self._flip(False)),
        ]
        for icon, text, fn in actions:
            b = _button(text); b.setIcon(_ic(self.mw, icon))
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(fn)
            v.addWidget(b)
        v.addStretch()
        return w

    def _rot(self, deg):
        img = self.mw.image()
        if img:
            self.mw.commit(ops.rotate(img, deg), f"Girar {deg}°")

    def _flip(self, h):
        img = self.mw.image()
        if img:
            self.mw.commit(ops.flip(img, h), "Voltear")


# ----------------------------------------------------------------------------
# 3 · Conversión
# ----------------------------------------------------------------------------

class ConvertTool(Tool):
    key = "convert"
    title = "Convertir formato"
    eyebrow = "Conversión"
    apply_label = "CONVERTIR"
    can_batch = True

    NOTES = {
        "JPG": "JPG no admite transparencia: el fondo será blanco.",
        "PNG": "PNG conserva la transparencia (sin pérdida).",
        "WEBP": "WEBP: formato web moderno con buena compresión.",
        "GIF": "GIF: paleta limitada a 256 colores.",
        "BMP": "BMP: sin compresión, archivos grandes. Sin transparencia.",
        "TIFF": "TIFF: alta calidad con compresión LZW sin pérdida.",
        "ICO": "ICO: icono de Windows multi-tamaño (hasta 256 px).",
    }

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(14)
        v.addWidget(_label("Cambia la extensión del archivo de salida.", "muted"))
        v.addWidget(_label("Convertir a"))
        self.fmt = QComboBox()
        self.fmt.addItems(["JPG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "ICO"])
        v.addWidget(self.fmt)
        self.q = _slider_field(v, "Calidad (JPG/WEBP)", 10, 100, 90)
        info = _card(v)
        self.info = _label("—", "muted")
        info.addWidget(self.info)
        self.note = _label("", "muted")
        v.addWidget(self.note)
        v.addStretch()
        self.fmt.currentTextChanged.connect(self._update)
        self.q.valueChanged.connect(self._update)
        return w

    def activate(self):
        super().activate()
        self._update()

    def _convert(self, img):
        """Devuelve la imagen lista para el formato destino (aplana JPG/BMP)."""
        fmt = self.fmt.currentText()
        if fmt in ("JPG", "BMP"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            return bg.convert("RGBA")
        return img

    def _update(self):
        f = self.fmt.currentText()
        self.note.setText(self.NOTES.get(f, ""))
        if self.base:
            new = ops.estimate_size(self.base, f, self.q.value())
            self.info.setText(f"Tamaño estimado {f}: {_human(new)}")

    def apply(self):
        fmt, q = self.fmt.currentText(), self.q.value()
        if self.mw.apply_to_all and len(self.mw.docs) > 1:
            self.mw.apply_processed(self._convert, f"Convertir → {fmt}",
                                    export=(fmt, q))
            return
        self.mw.set_export(fmt, q)
        self.mw.commit(self._convert(self.base), f"Convertir → {fmt}")
        self.mw.toast(f"Listo para exportar como {fmt}. Pulsa DESCARGAR.")


class GifTool(Tool):
    key = "gif"
    title = "Crear GIF animado"
    eyebrow = "Conversión"
    use_footer = False
    requires_image = False

    def __init__(self, mw):
        super().__init__(mw)
        self.frames: list[Image.Image] = []

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12)
        v.addWidget(_label("Ordena varias imágenes en un bucle animado.", "muted"))
        add = _button("  Añadir imágenes"); add.setIcon(_ic(self.mw, "plus"))
        add.clicked.connect(self._add)
        v.addWidget(add)
        self.list = QListWidget()
        self.list.setMaximumHeight(180)
        v.addWidget(self.list)
        row = QHBoxLayout()
        up = _button(""); up.setIcon(_ic(self.mw, "chevron-up")); up.setToolTip("Subir")
        down = _button(""); down.setIcon(_ic(self.mw, "chevron-down")); down.setToolTip("Bajar")
        rm = _button(""); rm.setIcon(_ic(self.mw, "trash-2")); rm.setToolTip("Quitar")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        rm.clicked.connect(self._remove)
        for b in (up, down, rm):
            row.addWidget(b)
        v.addLayout(row)
        self.dur = _slider_field(v, "Duración por fotograma", 50, 2000, 300,
                                 lambda x: f"{x} ms")
        self.loop = QCheckBox("Repetir en bucle"); self.loop.setChecked(True)
        v.addWidget(self.loop)
        exp = _button("Exportar GIF…", primary=True)
        exp.clicked.connect(self._export)
        v.addWidget(exp)
        v.addStretch()
        return w

    def _add(self):
        paths = self.mw.ask_open_multi()
        for p in paths:
            try:
                img = ops.load_image(p)
                self.frames.append(img)
                self.list.addItem(QListWidgetItem(p.split("/")[-1].split("\\")[-1]))
            except Exception:
                pass
        self._show_first()

    def _move(self, d):
        i = self.list.currentRow()
        j = i + d
        if i < 0 or not (0 <= j < len(self.frames)):
            return
        self.frames[i], self.frames[j] = self.frames[j], self.frames[i]
        it = self.list.takeItem(i)
        self.list.insertItem(j, it)
        self.list.setCurrentRow(j)
        self._show_first()

    def _remove(self):
        i = self.list.currentRow()
        if i >= 0:
            self.frames.pop(i)
            self.list.takeItem(i)
            self._show_first()

    def _show_first(self):
        if self.frames:
            self.mw.canvas.set_image(self.frames[0])
            self.mw.refresh_size()

    def _export(self):
        if len(self.frames) < 2:
            self.mw.toast("Añade al menos 2 imágenes")
            return
        path = self.mw.ask_save("animacion.gif", "GIF (*.gif)")
        if not path:
            return
        data = ops.build_gif(self.frames, self.dur.value(), self.loop.isChecked())
        with open(path, "wb") as f:
            f.write(data)
        self.mw.toast(f"GIF guardado ({_human(len(data))})")


class Html2ImgTool(Tool):
    key = "html2img"
    title = "HTML a imagen"
    eyebrow = "Conversión"
    use_footer = False
    requires_image = False

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12)
        v.addWidget(_label("Captura una página web como imagen.", "muted"))
        v.addWidget(_label("URL"))
        self.url = QLineEdit("https://")
        v.addWidget(self.url)
        row = QHBoxLayout()
        cw = QVBoxLayout(); cw.addWidget(_label("Ancho (px)"))
        self.wspin = QSpinBox(); self.wspin.setRange(320, 4000); self.wspin.setValue(1280)
        cw.addWidget(self.wspin); row.addLayout(cw)
        v.addLayout(row)
        self.full = QCheckBox("Página completa"); self.full.setChecked(True)
        v.addWidget(self.full)
        self.cap = _button("Capturar", primary=True)
        self.cap.clicked.connect(self._capture)
        v.addWidget(self.cap)
        self.status = _label("", "muted")
        v.addWidget(self.status)
        v.addStretch()
        self._view = None
        return w

    def _capture(self):
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception:
            self.mw.toast("QtWebEngine no disponible")
            return
        url = self.url.text().strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.status.setText("Cargando…")
        self.cap.setEnabled(False)
        view = QWebEngineView()
        self._view = view
        view.resize(self.wspin.value(), 900)
        view.move(-10000, -10000)
        view.show()
        view.load(QUrl(url))

        def grab():
            pix = view.grab()
            img = ops.qimage_to_pil(pix.toImage())
            self.mw.commit(img, "HTML→imagen")
            self.mw.toast("Página capturada")
            self.status.setText("")
            self.cap.setEnabled(True)
            view.deleteLater()
            self._view = None

        def on_load(ok):
            if not ok:
                self.status.setText("Error al cargar la URL")
                self.cap.setEnabled(True)
                view.deleteLater()
                return
            if self.full.isChecked():
                def resized(h):
                    h = int(h) if h else 900
                    view.resize(self.wspin.value(), max(400, min(h, 12000)))
                    QTimer.singleShot(600, grab)
                view.page().runJavaScript(
                    "document.body.scrollHeight", 0, resized)
            else:
                QTimer.singleShot(600, grab)

        view.loadFinished.connect(on_load)


# ----------------------------------------------------------------------------
# 4 · Edición creativa
# ----------------------------------------------------------------------------

class EditorTool(Tool):
    key = "editor"
    title = "Editor de fotos"
    eyebrow = "Creativa"
    apply_label = "GUARDAR EDICIÓN"

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12)
        v.addWidget(_label("Ajustes, filtros y dibujo libre.", "muted"))
        self.bright = _slider_field(v, "Brillo", 0, 200, 100, lambda x: f"{x}%")
        self.contrast = _slider_field(v, "Contraste", 0, 200, 100, lambda x: f"{x}%")
        self.sat = _slider_field(v, "Saturación", 0, 200, 100, lambda x: f"{x}%")
        v.addWidget(_label("Filtro"))
        self.filter = QComboBox(); self.filter.addItems(ops.FILTERS)
        v.addWidget(self.filter)

        c = _card(v)
        c.addWidget(_label("Pincel"))
        self.draw = QCheckBox("Activar dibujo")
        c.addWidget(self.draw)
        brow = QHBoxLayout()
        self.colorbtn = _button("Color"); self.colorbtn.setIcon(_ic(self.mw, "droplet"))
        self.colorbtn.clicked.connect(self._pick_color)
        clear = _button("Borrar trazos"); clear.setIcon(_ic(self.mw, "eraser"))
        clear.clicked.connect(lambda: self.mw.canvas.clear_scratch())
        brow.addWidget(self.colorbtn); brow.addWidget(clear)
        c.addLayout(brow)
        self.bsize = _slider_field(c, "Grosor", 2, 80, 14)

        v.addStretch()
        for s in (self.bright, self.contrast, self.sat):
            s.valueChanged.connect(self._update)
        self.filter.currentTextChanged.connect(self._update)
        self.draw.toggled.connect(self._toggle_draw)
        self.bsize.valueChanged.connect(
            lambda v: setattr(self.mw.canvas, "brush_size", v))
        self._brush = QColor("#F2693F")
        return w

    def _pick_color(self):
        col = QColorDialog.getColor(self._brush, self.mw, "Color de pincel")
        if col.isValid():
            self._brush = col
            self.mw.canvas.brush_color = col

    def _toggle_draw(self, on):
        self.mw.canvas.set_mode(
            ImageCanvas.MODE_DRAW if on else ImageCanvas.MODE_NONE)

    def _processed(self):
        img = ops.apply_filter(self.base, self.filter.currentText())
        return ops.adjust(img, self.bright.value()/100,
                          self.contrast.value()/100, self.sat.value()/100)

    def _update(self):
        if self.base:
            self.mw.canvas.set_preview(self._processed())

    def apply(self):
        out = self._processed()
        scratch = self.mw.canvas.scratch_pil()
        if scratch is not None:
            out = Image.alpha_composite(out.convert("RGBA"), scratch)
        self.mw.commit(out, "Editar foto")
        self.mw.toast("Edición aplicada")


class MemeTool(Tool):
    key = "meme"
    title = "Crear meme"
    eyebrow = "Creativa"
    apply_label = "GENERAR MEME"

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12)
        v.addWidget(_label("Texto Impact blanco con contorno negro.", "muted"))
        v.addWidget(_label("Texto superior"))
        self.top = QLineEdit(); v.addWidget(self.top)
        v.addWidget(_label("Texto inferior"))
        self.bottom = QLineEdit(); v.addWidget(self.bottom)
        self.scale = _slider_field(v, "Tamaño de fuente", 50, 200, 100,
                                   lambda x: f"{x}%")
        v.addStretch()
        self.top.textChanged.connect(self._update)
        self.bottom.textChanged.connect(self._update)
        self.scale.valueChanged.connect(self._update)
        return w

    def _render(self):
        return ops.add_meme_text(self.base, self.top.text(), self.bottom.text(),
                                 self.scale.value()/100)

    def _update(self):
        if self.base:
            self.mw.canvas.set_preview(self._render())

    def apply(self):
        self.mw.commit(self._render(), "Crear meme")
        self.mw.toast("Meme generado")


# ----------------------------------------------------------------------------
# 5 · Seguridad y privacidad
# ----------------------------------------------------------------------------

class WatermarkTool(Tool):
    key = "watermark"
    title = "Marca de agua"
    eyebrow = "Privacidad"
    apply_label = "APLICAR"
    can_batch = True

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12)
        v.addWidget(_label("Protege tus imágenes con texto o logo.", "muted"))
        self.kind, _ = _choice_group(v, ["Texto", "Logo"], default=0, columns=2)
        self.text = QLineEdit("© Mi marca")
        v.addWidget(self.text)
        self.logo_btn = _button("Cargar logo…"); self.logo_btn.setIcon(_ic(self.mw, "image"))
        self.logo_btn.clicked.connect(self._load_logo)
        v.addWidget(self.logo_btn)
        self.opacity = _slider_field(v, "Opacidad", 5, 100, 50, lambda x: f"{x}%")
        self.scale = _slider_field(v, "Tamaño", 5, 100, 30, lambda x: f"{x}%")
        v.addWidget(_label("Posición"))
        self.anchor = QComboBox(); self.anchor.addItems(list(ops.ANCHORS.keys()))
        self.anchor.setCurrentText("Inf. Der.")
        v.addWidget(self.anchor)
        crow = QHBoxLayout()
        self.colorbtn = _button("Color de texto"); self.colorbtn.setIcon(_ic(self.mw, "droplet"))
        self.colorbtn.clicked.connect(self._pick_color)
        crow.addWidget(self.colorbtn)
        v.addLayout(crow)
        self.tile = QCheckBox("Mosaico (repetir en diagonal)")
        v.addWidget(self.tile)
        batch = _button("Aplicar a lote…"); batch.setIcon(_ic(self.mw, "files"))
        batch.clicked.connect(self._batch)
        v.addWidget(batch)
        v.addStretch()

        self._color = "#FFFFFF"
        self._logo = None
        for wdg in (self.text, self.anchor):
            (wdg.textChanged if isinstance(wdg, QLineEdit)
             else wdg.currentTextChanged).connect(self._update)
        for s in (self.opacity, self.scale):
            s.valueChanged.connect(self._update)
        self.tile.toggled.connect(self._update)
        self.kind.idClicked.connect(self._update)
        return w

    def _pick_color(self):
        col = QColorDialog.getColor(QColor(self._color), self.mw, "Color")
        if col.isValid():
            self._color = col.name()
            self._update()

    def _load_logo(self):
        p = self.mw.ask_open_image()
        if p:
            self._logo = ops.load_image(p)
            self.kind.button(1).setChecked(True)
            self._update()

    def _render(self, img):
        if self.kind.checkedId() == 1 and self._logo is not None:
            return ops.watermark_logo(img, self._logo, self.opacity.value(),
                                      self.scale.value()/100,
                                      self.anchor.currentText())
        return ops.watermark_text(img, self.text.text(), self.opacity.value(),
                                  self.scale.value()/100 * 2,
                                  self.anchor.currentText(), self._color,
                                  self.tile.isChecked())

    def _update(self):
        if self.base:
            self.mw.canvas.set_preview(self._render(self.base))

    def apply(self):
        if self.mw.apply_to_all and len(self.mw.docs) > 1:
            self.mw.apply_processed(self._render, "Marca de agua")
            return
        self.mw.commit(self._render(self.base), "Marca de agua")
        self.mw.toast("Marca de agua aplicada")

    def _batch(self):
        paths = self.mw.ask_open_multi()
        if not paths:
            return
        folder = self.mw.ask_folder()
        if not folder:
            return
        n = 0
        with self.mw.busy("Aplicando marca al lote…"):
            for p in paths:
                try:
                    img = ops.load_image(p)
                    out = self._render(img)
                    name = p.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
                    ops.save_image(out, f"{folder}/{name}_wm.png", "PNG", 95)
                    n += 1
                except Exception:
                    pass
        self.mw.toast(f"Marca aplicada a {n} imagen(es)")


class PixelateTool(Tool):
    key = "pixelate"
    title = "Pixelar / Desenfocar"
    eyebrow = "Privacidad"
    apply_label = "APLICAR"

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12)
        v.addWidget(_label("Arrastra para seleccionar zonas sensibles.", "muted"))
        self.mode, _ = _choice_group(v, ["Pixelar", "Desenfocar"], default=0,
                                     columns=2)
        self.intensity = _slider_field(v, "Intensidad", 4, 60, 16)
        face = _button("Detectar caras (OpenCV)"); face.setIcon(_ic(self.mw, "scan-face"))
        face.clicked.connect(self._detect)
        v.addWidget(face)
        clear = _button("Limpiar selección"); clear.setIcon(_ic(self.mw, "eraser"))
        clear.clicked.connect(lambda: self.mw.canvas.clear_rects())
        v.addWidget(clear)
        v.addStretch()
        return w

    def activate(self):
        super().activate()
        self.mw.canvas.set_mode(ImageCanvas.MODE_RECT)

    def _detect(self):
        boxes = ops.detect_faces(self.base)
        if boxes is None:
            self.mw.toast("OpenCV no instalado — selección manual")
            return
        if not boxes:
            self.mw.toast("No se detectaron caras")
            return
        from PySide6.QtCore import QRectF
        for (x0, y0, x1, y1) in boxes:
            self.mw.canvas.add_rect(QRectF(x0, y0, x1 - x0, y1 - y0))
        self.mw.toast(f"{len(boxes)} cara(s) detectada(s)")

    def apply(self):
        out = self.base
        rects = self.mw.canvas.rects
        if not rects:
            self.mw.toast("Selecciona al menos una zona")
            return
        for r in rects:
            box = (r.left(), r.top(), r.right(), r.bottom())
            if self.mode.checkedId() == 0:
                out = ops.pixelate_region(out, box, self.intensity.value())
            else:
                out = ops.blur_region(out, box, self.intensity.value())
        self.mw.commit(out, "Pixelar/Desenfocar")
        self.mw.canvas.clear_rects()
        self.mw.toast("Zonas protegidas")


class UnwatermarkTool(Tool):
    key = "unwatermark"
    title = "Quitar marca de agua"
    eyebrow = "Privacidad"
    apply_label = "QUITAR"

    def build(self):
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(12)
        v.addWidget(_label("Selecciona la marca de agua, logo o texto a borrar; "
                           "la zona se reconstruye con el fondo de alrededor.",
                           "muted"))
        self.expand = _slider_field(v, "Expandir selección (cubrir bordes)",
                                    0, 12, 3, lambda x: f"{x} px")
        engine = ("Motor: OpenCV (reconstrucción avanzada)."
                  if ops.opencv_available()
                  else "OpenCV no instalado — relleno por difusión "
                       "(mejor en zonas pequeñas).")
        v.addWidget(_label(engine, "muted"))
        clear = _button("Limpiar selección"); clear.setIcon(_ic(self.mw, "eraser"))
        clear.clicked.connect(lambda: self.mw.canvas.clear_rects())
        v.addWidget(clear)
        v.addWidget(_label("Consejo: ajusta el recuadro lo más pegado posible a "
                           "la marca para un mejor resultado.", "muted"))
        v.addStretch()
        return w

    def activate(self):
        super().activate()
        self.mw.canvas.set_mode(ImageCanvas.MODE_RECT)

    def apply(self):
        rects = self.mw.canvas.rects
        if not rects:
            self.mw.toast("Selecciona al menos una zona")
            return
        boxes = [(r.left(), r.top(), r.right(), r.bottom()) for r in rects]
        with self.mw.busy("Reconstruyendo…"):
            out = ops.remove_watermark(self.base, boxes, self.expand.value())
        self.mw.commit(out, "Quitar marca de agua")
        self.mw.canvas.clear_rects()
        self.mw.toast("Marca de agua eliminada")


# ----------------------------------------------------------------------------
def _human(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


TOOLS = [CompressTool, RemoveBgTool, UpscaleTool, ResizeTool, CropTool,
         RotateTool, ConvertTool, GifTool, Html2ImgTool, EditorTool,
         MemeTool, WatermarkTool, PixelateTool, UnwatermarkTool]

TOOL_MAP = {t.key: t for t in TOOLS}
