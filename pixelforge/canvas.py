"""Lienzo de imagen interactivo: zoom, recorte, pincel y selección de regiones."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import (QPainter, QPixmap, QColor, QPen, QBrush, QImage,
                           QPainterPath, QPainterPathStroker)
from PySide6.QtWidgets import QWidget

from . import imageops


class ImageCanvas(QWidget):
    """Muestra una imagen PIL y soporta varias interacciones según el modo."""

    MODE_NONE = "none"
    MODE_CROP = "crop"
    MODE_RECT = "rect"     # selección de rectángulos (pixelar/desenfocar)
    MODE_DRAW = "draw"     # pincel libre (editor)
    MODE_ERASE = "erase"   # borrador manual (limpiar fondo a mano)

    cropChanged = Signal()
    rectsChanged = Signal()
    zoomChanged = Signal(int)

    HANDLE = 9  # radio en px de los tiradores

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 320)
        self.setFocusPolicy(Qt.StrongFocus)   # para capturar Espacio (paneo)

        self._image: "imageops.Image.Image | None" = None
        self._preview = None          # override temporal de visualización
        self._pixmap: QPixmap | None = None
        self._checker = self._make_checker()

        self._zoom = 1.0
        self._fit = True

        # paneo (desplazamiento de la imagen)
        self._pan = QPointF(0, 0)
        self._panning = False
        self._pan_last = QPointF()
        self._space = False           # ¿barra espaciadora pulsada? (paneo)

        self.mode = self.MODE_NONE

        # recorte
        self.crop_rect: QRectF | None = None
        self.crop_ratio: float | None = None
        self._drag = None             # 'move' | esquina | 'new'
        self._drag_off = QPointF()

        # rectángulos de selección
        self.rects: list[QRectF] = []
        self._new_rect_start: QPointF | None = None
        self._new_rect: QRectF | None = None

        # pincel
        self._scratch: QImage | None = None
        self.brush_color = QColor("#F2693F")
        self.brush_size = 14
        self._last_pt: QPointF | None = None

        # borrador manual (edita el alfa de la imagen mostrada)
        self._erase_img: QImage | None = None
        self._erase_src: QImage | None = None   # original para "restaurar"
        self.erase_mode = "erase"               # "erase" | "restore"

    # ---------------- imagen ----------------
    def set_image(self, img):
        self._image = img.convert("RGBA") if img else None
        self._preview = None
        self._scratch = None
        self._erase_img = None
        self._pan = QPointF(0, 0)
        self.crop_rect = None
        self.rects = []
        if self._image is not None and self.mode == self.MODE_DRAW:
            self._ensure_scratch()
        self._rebuild_pixmap()
        if self._image is not None and self.mode == self.MODE_ERASE:
            self.start_erase()
        if self._fit:
            self.fit_to_view()
        self.update()

    def image(self):
        return self._image

    def set_preview(self, img):
        """Muestra ``img`` temporalmente sin modificar la imagen base."""
        self._preview = img.convert("RGBA") if img else None
        self._rebuild_pixmap()
        self.update()

    def clear_preview(self):
        self._preview = None
        self._rebuild_pixmap()
        self.update()

    def displayed(self):
        return self._preview if self._preview is not None else self._image

    def has_preview(self):
        return self._preview is not None

    def _rebuild_pixmap(self):
        src = self.displayed()
        self._pixmap = QPixmap.fromImage(imageops.pil_to_qimage(src)) if src else None

    # ---------------- modos ----------------
    def set_mode(self, mode):
        self.mode = mode
        if mode == self.MODE_CROP and self.crop_rect is None and self._image:
            w, h = self._image.size
            inset_x, inset_y = w * 0.08, h * 0.08
            self.crop_rect = QRectF(inset_x, inset_y, w - 2 * inset_x, h - 2 * inset_y)
            self.cropChanged.emit()
        if mode == self.MODE_DRAW:
            self._ensure_scratch()
        if mode == self.MODE_ERASE:
            self.start_erase()
        elif self._erase_img is not None:
            self._erase_img = None
            self._rebuild_pixmap()
        self._update_cursor()
        self.update()

    def set_crop_ratio(self, ratio):
        self.crop_ratio = ratio
        if ratio and self.crop_rect and self._image:
            r = self.crop_rect
            new_h = r.width() / ratio
            self.crop_rect = QRectF(r.x(), r.y(), r.width(), new_h)
            self._clamp_crop()
            self.cropChanged.emit()
            self.update()

    def clear_rects(self):
        self.rects = []
        self._new_rect = None
        self.rectsChanged.emit()
        self.update()

    def add_rect(self, r: QRectF):
        self.rects.append(r)
        self.rectsChanged.emit()
        self.update()

    # ---------------- pincel ----------------
    def _ensure_scratch(self):
        if self._image is None:
            return
        if self._scratch is None or self._scratch.size() != \
                QImage(self._image.width, self._image.height, QImage.Format_ARGB32).size():
            self._scratch = QImage(self._image.width, self._image.height,
                                   QImage.Format_ARGB32)
            self._scratch.fill(Qt.transparent)

    def clear_scratch(self):
        if self._scratch:
            self._scratch.fill(Qt.transparent)
            self.update()

    def discard_scratch(self):
        self._scratch = None
        self.update()

    def scratch_pil(self):
        return imageops.qimage_to_pil(self._scratch) if self._scratch else None

    def has_strokes(self):
        return self._scratch is not None

    # ---------------- borrador manual ----------------
    def start_erase(self):
        """Captura la imagen mostrada en una capa editable para borrar a mano.
        Guarda también el original para poder restaurar zonas borradas."""
        src = self.displayed()
        if src is None:
            self._erase_img = None
            self._erase_src = None
            return
        self._erase_img = imageops.pil_to_qimage(src).convertToFormat(
            QImage.Format_ARGB32)
        self._erase_src = self._erase_img.copy()
        self._pixmap = QPixmap.fromImage(self._erase_img)
        self.update()

    def _paint_brush(self, a: QPointF, b: QPointF):
        """Aplica el pincel del borrador: borra o restaura según ``erase_mode``."""
        if self.erase_mode == "restore":
            self._paint_restore(a, b)
        else:
            self._paint_erase(a, b)

    def _paint_erase(self, a: QPointF, b: QPointF):
        if self._erase_img is None:
            return
        p = QPainter(self._erase_img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setPen(QPen(Qt.transparent, self.brush_size, Qt.SolidLine,
                      Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(a, b)
        p.end()
        self._pixmap = QPixmap.fromImage(self._erase_img)

    def _paint_restore(self, a: QPointF, b: QPointF):
        """Devuelve los píxeles originales (color + alfa) bajo el trazo."""
        if self._erase_img is None or self._erase_src is None:
            return
        path = QPainterPath(); path.moveTo(a); path.lineTo(b)
        stroker = QPainterPathStroker()
        stroker.setWidth(max(1, self.brush_size))
        stroker.setCapStyle(Qt.RoundCap); stroker.setJoinStyle(Qt.RoundJoin)
        shape = stroker.createStroke(path)
        p = QPainter(self._erase_img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setClipPath(shape)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, self._erase_src)
        p.end()
        self._pixmap = QPixmap.fromImage(self._erase_img)

    def has_erase(self):
        return self._erase_img is not None

    def erased_pil(self):
        return imageops.qimage_to_pil(self._erase_img) if self._erase_img else None

    # ---------------- zoom ----------------
    def set_zoom(self, percent):
        self._fit = False
        self._zoom = max(0.1, percent / 100.0)
        self.zoomChanged.emit(int(self._zoom * 100))
        self.update()

    def fit_to_view(self):
        if not self._image:
            return
        self._fit = True
        self._pan = QPointF(0, 0)
        m = 48
        sw = (self.width() - m) / self._image.width
        sh = (self.height() - m) / self._image.height
        self._zoom = max(0.1, min(sw, sh, 1.0))
        self.zoomChanged.emit(int(self._zoom * 100))
        self.update()

    def resizeEvent(self, e):
        if self._fit:
            self.fit_to_view()
        super().resizeEvent(e)

    # ---------------- geometría ----------------
    def _image_rect(self) -> QRectF:
        if not self._image:
            return QRectF()
        dw = self._image.width * self._zoom
        dh = self._image.height * self._zoom
        x = (self.width() - dw) / 2 + self._pan.x()
        y = (self.height() - dh) / 2 + self._pan.y()
        return QRectF(x, y, dw, dh)

    def _to_image(self, p) -> QPointF:
        r = self._image_rect()
        if r.width() == 0:
            return QPointF()
        return QPointF((p.x() - r.x()) / self._zoom, (p.y() - r.y()) / self._zoom)

    def _to_widget(self, p: QPointF) -> QPointF:
        r = self._image_rect()
        return QPointF(r.x() + p.x() * self._zoom, r.y() + p.y() * self._zoom)

    def _crop_handles(self):
        if not self.crop_rect:
            return {}
        r = self.crop_rect
        return {
            "tl": QPointF(r.left(), r.top()),
            "tr": QPointF(r.right(), r.top()),
            "bl": QPointF(r.left(), r.bottom()),
            "br": QPointF(r.right(), r.bottom()),
        }

    def _clamp_crop(self):
        if not (self.crop_rect and self._image):
            return
        w, h = self._image.size
        r = self.crop_rect
        x = max(0, min(r.x(), w - 10))
        y = max(0, min(r.y(), h - 10))
        rw = max(10, min(r.width(), w - x))
        rh = max(10, min(r.height(), h - y))
        self.crop_rect = QRectF(x, y, rw, rh)

    # ---------------- pintado ----------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._pixmap:
            return
        r = self._image_rect()

        # fondo de transparencia (tablero de ajedrez)
        p.save()
        p.setClipRect(r)
        p.drawTiledPixmap(r, self._checker)
        p.restore()

        p.drawPixmap(r, self._pixmap, QRectF(self._pixmap.rect()))

        if self._scratch is not None:
            p.drawImage(r, self._scratch, QRectF(self._scratch.rect()))

        if self.mode == self.MODE_CROP and self.crop_rect:
            self._paint_crop(p)
        if self.mode == self.MODE_RECT:
            self._paint_rects(p)

    def _paint_crop(self, p: QPainter):
        full = self._image_rect()
        cr = QRectF(self._to_widget(self.crop_rect.topLeft()),
                    self._to_widget(self.crop_rect.bottomRight()))
        # oscurecer fuera del recorte
        path = QPainterPath()
        path.addRect(full)
        inner = QPainterPath()
        inner.addRect(cr)
        p.fillPath(path.subtracted(inner), QColor(0, 0, 0, 110))

        p.setPen(QPen(QColor("#F2693F"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(cr)
        # tercios
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for i in (1, 2):
            x = cr.left() + cr.width() * i / 3
            y = cr.top() + cr.height() * i / 3
            p.drawLine(QPointF(x, cr.top()), QPointF(x, cr.bottom()))
            p.drawLine(QPointF(cr.left(), y), QPointF(cr.right(), y))
        # tiradores
        p.setBrush(QBrush(QColor("#F2693F")))
        p.setPen(QPen(Qt.white, 2))
        for pt in self._crop_handles().values():
            wp = self._to_widget(pt)
            p.drawEllipse(wp, self.HANDLE, self.HANDLE)

    def _paint_rects(self, p: QPainter):
        p.setPen(QPen(QColor("#F2693F"), 2, Qt.DashLine))
        p.setBrush(QColor(242, 105, 63, 40))
        for r in self.rects:
            wr = QRectF(self._to_widget(r.topLeft()), self._to_widget(r.bottomRight()))
            p.drawRect(wr)
        if self._new_rect:
            wr = QRectF(self._to_widget(self._new_rect.topLeft()),
                        self._to_widget(self._new_rect.bottomRight()))
            p.drawRect(wr)

    # ---------------- ratón ----------------
    def mousePressEvent(self, e):
        if not self._image:
            return
        # Paneo: botón central, Espacio + izquierdo, o izquierdo sin herramienta.
        if e.button() == Qt.MiddleButton or \
                (e.button() == Qt.LeftButton
                 and (self.mode == self.MODE_NONE or self._space)):
            self._panning = True
            self._pan_last = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return
        ip = self._to_image(e.position())

        if self.mode == self.MODE_CROP:
            self._drag = self._hit_crop(e.position())
            if self._drag == "move":
                self._drag_off = ip - self.crop_rect.topLeft()
            elif self._drag is None:
                self.crop_rect = QRectF(ip, ip)
                self._drag = "br"
        elif self.mode == self.MODE_RECT:
            self._new_rect_start = ip
            self._new_rect = QRectF(ip, ip)
        elif self.mode == self.MODE_DRAW:
            self._ensure_scratch()
            self._last_pt = ip
            self._paint_stroke(ip, ip)
        elif self.mode == self.MODE_ERASE:
            self._last_pt = ip
            self._paint_brush(ip, ip)
        self.update()

    def mouseMoveEvent(self, e):
        if not self._image:
            return
        if self._panning:
            self._pan += e.position() - self._pan_last
            self._pan_last = e.position()
            self.update()
            return
        ip = self._to_image(e.position())
        if self.mode == self.MODE_CROP:
            self._update_hover_cursor(e.position())
        if not (e.buttons() & Qt.LeftButton):
            return

        if self.mode == self.MODE_CROP and self._drag:
            self._do_crop_drag(ip)
        elif self.mode == self.MODE_RECT and self._new_rect_start is not None:
            self._new_rect = QRectF(self._new_rect_start, ip).normalized()
        elif self.mode == self.MODE_DRAW and self._last_pt is not None:
            self._paint_stroke(self._last_pt, ip)
            self._last_pt = ip
        elif self.mode == self.MODE_ERASE and self._last_pt is not None:
            self._paint_brush(self._last_pt, ip)
            self._last_pt = ip
        self.update()

    def mouseReleaseEvent(self, e):
        if self._panning:
            self._panning = False
            self._update_cursor()
            return
        if self.mode == self.MODE_ERASE:
            self._last_pt = None
            self.update()
            return
        if self.mode == self.MODE_CROP and self._drag:
            self._clamp_crop()
            self.crop_rect = self.crop_rect.normalized()
            self._drag = None
            self.cropChanged.emit()
        elif self.mode == self.MODE_RECT and self._new_rect:
            r = self._new_rect.normalized()
            if r.width() > 4 and r.height() > 4:
                self.rects.append(r)
                self.rectsChanged.emit()
            self._new_rect = None
            self._new_rect_start = None
        elif self.mode == self.MODE_DRAW:
            self._last_pt = None
        self.update()

    def wheelEvent(self, e):
        step = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
        self.set_zoom(int(self._zoom * step * 100))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            if not self._panning:
                self.setCursor(Qt.OpenHandCursor)
            e.accept(); return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            if not self._panning:
                self._update_cursor()
            e.accept(); return
        super().keyReleaseEvent(e)

    def _hit_crop(self, wpos):
        for name, pt in self._crop_handles().items():
            if (self._to_widget(pt) - wpos).manhattanLength() <= self.HANDLE * 2:
                return name
        cr = QRectF(self._to_widget(self.crop_rect.topLeft()),
                    self._to_widget(self.crop_rect.bottomRight()))
        return "move" if cr.contains(wpos) else None

    def _do_crop_drag(self, ip):
        r = self.crop_rect
        if self._drag == "move":
            np = ip - self._drag_off
            self.crop_rect = QRectF(np, r.size())
        else:
            left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
            if "l" in self._drag:
                left = ip.x()
            if "r" in self._drag:
                right = ip.x()
            if "t" in self._drag:
                top = ip.y()
            if "b" in self._drag:
                bottom = ip.y()
            new = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()
            if self.crop_ratio:
                new.setHeight(new.width() / self.crop_ratio)
            self.crop_rect = new
        self.cropChanged.emit()

    def _paint_stroke(self, a: QPointF, b: QPointF):
        if not self._scratch:
            return
        p = QPainter(self._scratch)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self.brush_color, self.brush_size, Qt.SolidLine,
                   Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(a, b)
        p.end()

    # ---------------- cursores ----------------
    def _update_cursor(self):
        if self.mode in (self.MODE_DRAW, self.MODE_ERASE):
            self.setCursor(Qt.CrossCursor)
        elif self.mode == self.MODE_NONE:
            self.setCursor(Qt.OpenHandCursor)   # sugiere que se puede panear
        else:
            self.setCursor(Qt.ArrowCursor)

    def _update_hover_cursor(self, wpos):
        hit = self._hit_crop(wpos)
        cursors = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
                   "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
                   "move": Qt.SizeAllCursor}
        self.setCursor(cursors.get(hit, Qt.ArrowCursor))

    # ---------------- util ----------------
    @staticmethod
    def _make_checker():
        s = 12
        pm = QPixmap(s * 2, s * 2)
        pm.fill(QColor("#ffffff"))
        p = QPainter(pm)
        p.fillRect(0, 0, s, s, QColor("#e9ebee"))
        p.fillRect(s, s, s, s, QColor("#e9ebee"))
        p.end()
        return pm
