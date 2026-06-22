"""Ventana principal de PixelForge: barra superior, panel lateral de
herramientas, lienzo central y panel de ajustes."""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager

from PIL import Image
from PySide6.QtCore import (Qt, QTimer, QSize, QRect, QEvent, QPoint, QSettings,
                            Signal)
from PySide6.QtGui import (QIcon, QKeySequence, QShortcut, QFont, QPainter,
                           QColor, QPen, QPixmap, QPainterPath, QAction, QPalette)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QPushButton,
    QToolButton, QScrollArea, QFileDialog, QInputDialog, QButtonGroup,
    QSizePolicy, QGridLayout, QStackedWidget, QSlider, QApplication, QCheckBox,
    QMessageBox, QMenu, QSplitter, QLineEdit, QDialog,
)

from . import theme, imageops as ops, icons
from .canvas import ImageCanvas
from .panels import TOOLS, TOOL_MAP

# Recursos (icono de la app) en la carpeta assets/ junto al proyecto.
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets")
APP_ICON = os.path.join(_ASSETS, "Kroma_app_icon.png")
APP_ICON_ICO = os.path.join(_ASSETS, "Kroma_app_icon.ico")


def _round_window(widget):
    """Redondea las esquinas de una ventana sin marco (DWM, Windows 11)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        val = ctypes.c_int(2)   # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(widget.winId()), 33, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


class Doc:
    """Un documento de imagen con su línea de tiempo (historial) y formato de
    exportación. El historial es una lista ``(etiqueta, imagen)`` con un índice
    que apunta al estado actual; permite deshacer, rehacer y saltar a cualquier
    punto."""

    UNDO_LIMIT = 30        # pasos de historial (configurable)
    DEFAULT_QUALITY = 92   # calidad de exportación por defecto (configurable)

    def __init__(self, image, name, path=None):
        self.name = name
        self.path = path
        self.history: list[tuple[str, Image.Image]] = [
            ("Imagen original", image.convert("RGBA"))]
        self.index = 0
        self.export_format = "PNG"
        self.export_quality = Doc.DEFAULT_QUALITY

    @property
    def image(self) -> Image.Image:
        return self.history[self.index][1]

    def push(self, image, label="Cambio"):
        del self.history[self.index + 1:]          # descarta la rama de rehacer
        self.history.append((label, image.convert("RGBA")))
        if len(self.history) > Doc.UNDO_LIMIT + 1:  # +1 por el original
            del self.history[:len(self.history) - (Doc.UNDO_LIMIT + 1)]
        self.index = len(self.history) - 1

    def can_undo(self) -> bool:
        return self.index > 0

    def can_redo(self) -> bool:
        return self.index < len(self.history) - 1

    def undo(self):
        if self.can_undo():
            self.index -= 1

    def redo(self):
        if self.can_redo():
            self.index += 1

    def goto(self, i):
        if 0 <= i < len(self.history):
            self.index = i


class Thumb(QFrame):
    """Miniatura clicable de la tira de imágenes (con botón de cierre)."""

    SIZE = 74
    CLOSE = 18

    def __init__(self, mw, index, pixmap, active):
        super().__init__()
        self.mw = mw
        self.index = index
        self._pm = pixmap
        self.setProperty("class", "thumb")
        self.setProperty("active", "true" if active else "false")
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(mw.docs[index].name)

    def _close_rect(self):
        return QRect(self.SIZE - self.CLOSE - 2, 2, self.CLOSE, self.CLOSE)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.rect().adjusted(5, 5, -5, -5)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.setClipPath(path)
        if self._pm:
            scaled = self._pm.scaled(r.size(), Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
            x = r.x() + (r.width() - scaled.width()) // 2
            y = r.y() + (r.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        p.setClipping(False)
        # botón de cierre
        cr = self._close_rect()
        p.setBrush(QColor(42, 46, 53, 220))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cr)
        p.setPen(QPen(Qt.white, 1.6))
        m = 5
        p.drawLine(cr.left() + m, cr.top() + m, cr.right() - m, cr.bottom() - m)
        p.drawLine(cr.right() - m, cr.top() + m, cr.left() + m, cr.bottom() - m)

    def mousePressEvent(self, e):
        if self._close_rect().contains(e.position().toPoint()):
            self.mw.close_doc(self.index)
        else:
            self.mw.set_active(self.index)


class TitleBar(QFrame):
    """Barra de título propia: arrastrar para mover, doble clic para maximizar.

    Los botones (menús y controles de ventana) consumen sus propios clics, así
    que solo el área vacía inicia el desplazamiento de la ventana.
    """

    HEIGHT = 38

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.setObjectName("titlebar")
        self.setFixedHeight(self.HEIGHT)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            wh = self.window().windowHandle()
            if wh is not None:
                wh.startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.mw._toggle_max()


class EditableTitle(QLineEdit):
    """Nombre del documento editable in situ: doble clic (o lápiz) para editar,
    Enter o perder el foco para confirmar."""

    renamed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("docTitle")
        self.setReadOnly(True)
        self.setFrame(False)
        self.setCursor(Qt.PointingHandCursor)
        self.editingFinished.connect(self._finish)

    def start_edit(self):
        if self.isReadOnly() and self.isEnabled():
            self.setReadOnly(False)
            self.setCursor(Qt.IBeamCursor)
            self.setFocus()
            self.selectAll()

    def mouseDoubleClickEvent(self, e):
        if self.isReadOnly():
            self.start_edit()
        else:
            super().mouseDoubleClickEvent(e)

    def _finish(self):
        if not self.isReadOnly():
            self.setReadOnly(True)
            self.setCursor(Qt.PointingHandCursor)
            self.deselect()
            self.renamed.emit(self.text())


class KromaDialog(QDialog):
    """Diálogo con la misma estética que la ventana principal: sin marco,
    barra de título propia, esquinas redondeadas y tema de la app. El contenido
    se añade a ``self.body``."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setObjectName("dlg")
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        bar = QFrame(); bar.setObjectName("dlgTitlebar"); bar.setFixedHeight(36)
        bl = QHBoxLayout(bar); bl.setContentsMargins(12, 0, 6, 0); bl.setSpacing(8)
        ico = QLabel(); ico.setFixedSize(16, 16)
        pm = QPixmap(APP_ICON)
        if not pm.isNull():
            pm = pm.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(2); ico.setPixmap(pm)
        tl = QLabel(title); tl.setObjectName("dlgTitle")
        bl.addWidget(ico); bl.addWidget(tl); bl.addStretch()
        close = QToolButton(); close.setProperty("class", "winbtn")
        close.setObjectName("winClose"); close.setFixedSize(40, 36)
        close.setIconSize(QSize(14, 14)); close.setCursor(Qt.PointingHandCursor)
        close.setIcon(icons.make_icon("x", theme.palette(parent.dark)["muted"]))
        close.clicked.connect(self.reject)
        bl.addWidget(close)
        bar.mousePressEvent = self._bar_press
        outer.addWidget(bar)

        self.body = QWidget(); self.body.setObjectName("dlgBody")
        outer.addWidget(self.body, 1)

    def _bar_press(self, e):
        if e.button() == Qt.LeftButton:
            wh = self.windowHandle()
            if wh is not None:
                wh.startSystemMove()

    def showEvent(self, e):
        super().showEvent(e)
        _round_window(self)
        par = self.parent()
        if par is not None:
            g = par.frameGeometry()
            self.move(g.center() - self.rect().center())


# Definición del menú lateral: (clave, etiqueta, icono-lucide, separador-antes)
SIDE_ITEMS = [
    ("home", "Inicio", "house", False),
    ("open", "Abrir imagen", "folder-open", False),
    ("compress", "Comprimir", "shrink", True),
    ("removebg", "Eliminar fondo", "scissors", False),
    ("upscale", "Ampliar (IA)", "scaling", False),
    ("resize", "Redimensionar", "ruler", True),
    ("crop", "Recortar", "crop", False),
    ("rotate", "Girar", "rotate-cw", False),
    ("convert", "Convertir", "arrow-left-right", True),
    ("gif", "Crear GIF", "film", False),
    ("html2img", "HTML a imagen", "globe", False),
    ("editor", "Editor de fotos", "palette", True),
    ("meme", "Crear meme", "smile", False),
    ("watermark", "Marca de agua", "droplet", False),
    ("pixelate", "Pixelar / Desenfocar", "grid-3x3", False),
    ("unwatermark", "Quitar marca de agua", "sparkles", False),
]


# Mapas de formato <-> extensión compartidos por guardar/exportar.
EXT_MAP = {"PNG": ".png", "JPG": ".jpg", "WEBP": ".webp", "GIF": ".gif",
           "BMP": ".bmp", "TIFF": ".tiff", "ICO": ".ico"}
EXT_TO_FMT = {"jpg": "JPG", "jpeg": "JPG", "png": "PNG", "webp": "WEBP",
              "gif": "GIF", "bmp": "BMP", "tif": "TIFF", "tiff": "TIFF",
              "ico": "ICO"}


def _field_label(text):
    lab = QLabel(text)
    lab.setProperty("class", "fieldlabel")
    return lab


class MainWindow(QMainWindow):
    RESIZE_MARGIN = 6   # px de borde sensibles para redimensionar (sin marco)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kroma — Editor de imágenes")
        if os.path.exists(APP_ICON_ICO) or os.path.exists(APP_ICON):
            self.setWindowIcon(QIcon(APP_ICON_ICO if os.path.exists(APP_ICON_ICO)
                                     else APP_ICON))
        # Ventana sin marco: usamos una barra de título propia.
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.resize(1280, 800)
        self.setMinimumSize(1040, 660)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

        self.docs: list[Doc] = []
        self.active = -1
        self.apply_to_all = False
        self.dark = False
        self.current_tool = None
        self._last_dir = ""   # última carpeta usada en diálogos de archivo
        self.recent_files: list[str] = []   # rutas abiertas recientemente
        self._edge_cursor = False   # ¿cursor de redimensión activo?

        # Ajustes configurables (persistidos con QSettings)
        self.max_images = 20
        self.default_quality = 92
        self.undo_limit = 30
        self._load_settings()
        self._side_group = QButtonGroup(self)
        self._side_group.setExclusive(True)
        self._side_icons = []   # [(QToolButton, lucide_name)]
        self._static_icons = []  # [(widget, lucide_name, role)]

        self.rembg_available = self._check_rembg()

        self._build_ui()
        self._shortcuts()
        self.apply_theme()
        # Filtro para redimensionar desde los bordes (ventana sin marco).
        QApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        outer.addWidget(self._build_titlebar())
        outer.addWidget(self._build_topbar())

        # Cuerpo con divisores arrastrables: barra lateral | lienzo | panel.
        body = QSplitter(Qt.Horizontal); body.setObjectName("bodySplitter")
        body.setHandleWidth(6)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_stage())
        body.addWidget(self._build_panel())
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        body.setSizes([210, 750, 320])
        if getattr(self, "_saved_splitter", None):
            try:
                body.setSizes([int(x) for x in self._saved_splitter])
            except Exception:
                pass
        body.splitterMoved.connect(lambda *_: self._update_sidebar_labels())
        self.body_splitter = body
        outer.addWidget(body, 1)

    def _build_titlebar(self):
        bar = TitleBar(self)
        lay = QHBoxLayout(bar); lay.setContentsMargins(10, 0, 0, 0); lay.setSpacing(2)

        self.title_icon = QLabel(); self.title_icon.setFixedSize(18, 18)
        self._set_logo(self.title_icon, 18)
        lay.addWidget(self.title_icon)
        lay.addSpacing(8)

        # menús de aplicación (no de edición de imagen)
        for label, builder in (("Archivo", self._menu_file),
                               ("Ver", self._menu_view),
                               ("Ayuda", self._menu_help)):
            b = QToolButton(); b.setText(label)
            b.setProperty("class", "menubtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setPopupMode(QToolButton.InstantPopup)
            b.setMenu(self._lazy_menu(builder))
            lay.addWidget(b)

        lay.addStretch()
        self.win_title = QLabel("Kroma"); self.win_title.setObjectName("winTitle")
        lay.addWidget(self.win_title)
        lay.addStretch()

        # controles de ventana
        self.btn_min = self._win_button("minus", self.showMinimized, "Minimizar")
        self.btn_max = self._win_button("square", self._toggle_max, "Maximizar",
                                        track=False)
        self.btn_close = self._win_button("x", self.close, "Cerrar", close=True)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)
        return bar

    def _win_button(self, icon, slot, tip, close=False, track=True):
        b = QToolButton(); b.setProperty("class", "winbtn")
        if close:
            b.setObjectName("winClose")
        b.setToolTip(tip)
        b.setFixedSize(46, TitleBar.HEIGHT)
        b.setIconSize(QSize(15, 15))
        b.clicked.connect(lambda: slot())
        if track:   # los iconos fijos los recolorea el tema; el de maximizar no
            self._static_icons.append((b, icon, "muted"))
        return b

    # --- ventana ---
    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._update_max_icon()

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _update_max_icon(self):
        if not hasattr(self, "btn_max"):
            return
        col = theme.palette(self.dark)["muted"]
        maxed = self.isMaximized()
        self.btn_max.setIcon(icons.make_icon("restore" if maxed else "square", col))
        self.btn_max.setToolTip("Restaurar" if maxed else "Maximizar")

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self._update_max_icon()
        super().changeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        self._update_sidebar_labels()
        if not getattr(self, "_rounded_applied", False):
            self._rounded_applied = True
            self._apply_rounded_corners()

    def _apply_rounded_corners(self):
        """Redondea las esquinas de la ventana sin marco usando DWM (Win 11)."""
        _round_window(self)

    def _set_logo(self, label, size):
        """Coloca el icono de Kroma (assets) escalado y nítido en un QLabel."""
        pm = QPixmap(APP_ICON)
        if pm.isNull():
            return
        pm = pm.scaled(size * 2, size * 2, Qt.KeepAspectRatio,
                       Qt.SmoothTransformation)
        pm.setDevicePixelRatio(2)
        label.setPixmap(pm)

    def _sync_window_title(self):
        d = self.doc()
        name = d.name if d else None
        if hasattr(self, "win_title"):
            self.win_title.setText(name or "Kroma")
        self.setWindowTitle(f"{name} — Kroma" if name
                            else "Kroma — Editor de imágenes")

    # --- menús de la barra de título ---
    def _lazy_menu(self, populate):
        """Crea un QMenu que se rellena al desplegarse (refleja estado actual)."""
        m = QMenu(self)
        def refresh():
            m.clear()
            populate(m)
        m.aboutToShow.connect(refresh)
        return m

    def _act(self, menu, icon, text, slot, shortcut=None, enabled=True):
        a = QAction(icons.make_icon(icon, theme.palette(self.dark)["text"]), text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setEnabled(enabled)
        a.triggered.connect(lambda _=False: slot())
        menu.addAction(a)
        return a

    def _menu_file(self, m):
        has_doc = self.doc() is not None
        self._act(m, "folder-open", "Abrir imagen…", self.open_image, "Ctrl+O")
        m.addMenu(self._recent_submenu())
        m.addSeparator()
        self._act(m, "save", "Descargar / Guardar…", self.download, "Ctrl+S",
                  enabled=has_doc)
        self._act(m, "files", "Guardar todas…", self.download_all,
                  enabled=len(self.docs) > 1)
        m.addSeparator()
        self._act(m, "pencil", "Renombrar…", self._rename, enabled=has_doc)
        self._act(m, "x", "Cerrar imagen", lambda: self.close_doc(self.active),
                  "Ctrl+W", enabled=has_doc)
        m.addSeparator()
        self._act(m, "log-out", "Salir", self.close, "Ctrl+Q")

    def _menu_view(self, m):
        self._act(m, "sun" if self.dark else "moon",
                  "Tema claro" if self.dark else "Tema oscuro", self.toggle_theme)
        self._act(m, "maximize", "Ajustar a la ventana",
                  lambda: self.canvas.fit_to_view(), enabled=self.doc() is not None)
        m.addSeparator()
        self._act(m, "square", "Pantalla completa", self._toggle_fullscreen, "F11")
        m.addSeparator()
        self._act(m, "settings", "Configuración…", self._open_settings)

    def _menu_help(self, m):
        self._act(m, "keyboard", "Atajos de teclado", self._show_shortcuts)
        self._act(m, "info", "Acerca de PixelForge", self._show_about)

    def _recent_submenu(self):
        sub = QMenu("Abrir reciente", self)
        sub.setIcon(icons.make_icon("clock", theme.palette(self.dark)["text"]))
        if not self.recent_files:
            sub.addAction("(sin archivos recientes)").setEnabled(False)
        else:
            for p in self.recent_files:
                sub.addAction(os.path.basename(p)).triggered.connect(
                    lambda _=False, pp=p: self.add_doc(pp))
            sub.addSeparator()
            sub.addAction("Limpiar recientes").triggered.connect(
                self.recent_files.clear)
        return sub

    def _add_recent(self, path):
        if not path:
            return
        path = os.path.abspath(path)
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        del self.recent_files[8:]

    # --- configuración ---
    def _settings_store(self):
        return QSettings("Kroma", "Kroma")

    def _load_settings(self):
        s = self._settings_store()
        self.max_images = int(s.value("max_images", 20))
        self.default_quality = int(s.value("default_quality", 92))
        self.undo_limit = int(s.value("undo_limit", 30))
        self.dark = s.value("dark", False, type=bool)
        self._last_dir = s.value("last_dir", "") or ""
        rec = s.value("recent", [])
        self.recent_files = [p for p in (rec if isinstance(rec, list) else [])
                             if isinstance(p, str)]
        self._saved_geometry = s.value("geometry")
        self._saved_splitter = s.value("splitter")
        Doc.UNDO_LIMIT = self.undo_limit
        Doc.DEFAULT_QUALITY = self.default_quality
        if self._saved_geometry is not None:
            try:
                self.restoreGeometry(self._saved_geometry)
            except Exception:
                pass

    def _save_settings(self):
        s = self._settings_store()
        s.setValue("max_images", self.max_images)
        s.setValue("default_quality", self.default_quality)
        s.setValue("undo_limit", self.undo_limit)
        s.setValue("dark", self.dark)
        s.setValue("last_dir", self._last_dir)
        s.setValue("recent", self.recent_files)
        s.setValue("geometry", self.saveGeometry())
        if hasattr(self, "body_splitter"):
            s.setValue("splitter", self.body_splitter.sizes())

    def closeEvent(self, e):
        self._save_settings()
        super().closeEvent(e)

    def _open_settings(self):
        from PySide6.QtWidgets import (QFormLayout, QSpinBox, QComboBox,
                                       QDialogButtonBox)
        dlg = KromaDialog(self, "Configuración")
        v = QVBoxLayout(dlg.body); v.setContentsMargins(22, 18, 22, 18); v.setSpacing(16)

        head = QLabel("Configuración"); head.setProperty("class", "panelTitle")
        v.addWidget(head)

        form = QFormLayout(); form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft)

        max_spin = QSpinBox(); max_spin.setRange(1, 200); max_spin.setValue(self.max_images)
        max_spin.setSuffix("  imágenes")
        form.addRow(_field_label("Límite de imágenes a subir"), max_spin)

        q_spin = QSpinBox(); q_spin.setRange(10, 100); q_spin.setValue(self.default_quality)
        q_spin.setSuffix("  %")
        form.addRow(_field_label("Calidad de exportación por defecto"), q_spin)

        undo_spin = QSpinBox(); undo_spin.setRange(5, 100); undo_spin.setValue(self.undo_limit)
        undo_spin.setSuffix("  pasos")
        form.addRow(_field_label("Historial de deshacer"), undo_spin)

        theme_combo = QComboBox(); theme_combo.addItems(["Claro", "Oscuro"])
        theme_combo.setCurrentIndex(1 if self.dark else 0)
        form.addRow(_field_label("Tema"), theme_combo)
        v.addLayout(form)

        hint = QLabel("El límite controla cuántas imágenes puedes tener abiertas "
                      "a la vez (subir, arrastrar o por lotes).")
        hint.setWordWrap(True); hint.setProperty("class", "muted")
        v.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Guardar")
        bb.button(QDialogButtonBox.Save).setObjectName("save")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.button(QDialogButtonBox.Cancel).setObjectName("cancel")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)

        if dlg.exec() != QDialog.Accepted:
            return
        self.max_images = max_spin.value()
        self.default_quality = q_spin.value()
        self.undo_limit = undo_spin.value()
        Doc.UNDO_LIMIT = self.undo_limit
        Doc.DEFAULT_QUALITY = self.default_quality
        new_dark = theme_combo.currentIndex() == 1
        if new_dark != self.dark:
            self.dark = new_dark
            self.apply_theme()
        self._save_settings()
        self.toast("Configuración guardada")

    def _show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle("Acerca de Kroma")
        box.setText(
            "<b>Kroma</b><br>Editor de imágenes de escritorio.<br><br>"
            "Optimiza, edita, convierte y protege tus imágenes.<br>"
            "Python + PySide6 · Pillow · numpy")
        if os.path.exists(APP_ICON):
            box.setIconPixmap(QPixmap(APP_ICON).scaled(
                64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        box.exec()

    def _show_shortcuts(self):
        QMessageBox.information(
            self, "Atajos de teclado",
            "Abrir\tCtrl+O\nDescargar\tCtrl+S\nGuardar todas\t—\n"
            "Cerrar imagen\tCtrl+W\nDeshacer\tCtrl+Z\nRehacer\tCtrl+Y\n"
            "Aplicar herramienta\tEnter\nCancelar herramienta\tEsc\n"
            "Pantalla completa\tF11\nSalir\tCtrl+Q\nZoom\trueda del ratón")

    # --- redimensionado de la ventana sin marco (desde los bordes) ---
    def _edge_at(self, pos):
        m = self.RESIZE_MARGIN
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        edges = Qt.Edges()
        if not (0 <= x < w and 0 <= y < h):
            return edges
        if x <= m:
            edges |= Qt.LeftEdge
        if x >= w - m:
            edges |= Qt.RightEdge
        if y <= m:
            edges |= Qt.TopEdge
        if y >= h - m:
            edges |= Qt.BottomEdge
        return edges

    @staticmethod
    def _cursor_for(edges):
        left, right = bool(edges & Qt.LeftEdge), bool(edges & Qt.RightEdge)
        top, bottom = bool(edges & Qt.TopEdge), bool(edges & Qt.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        return Qt.SizeVerCursor

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.MouseMove, QEvent.MouseButtonPress) \
                and not self.isMaximized() and not self.isFullScreen() \
                and QApplication.activeModalWidget() is None:
            wh = self.windowHandle()
            if wh is not None:
                gp = event.globalPosition().toPoint()
                edges = self._edge_at(self.mapFromGlobal(gp))
                if et == QEvent.MouseMove and not (event.buttons() & Qt.LeftButton):
                    if edges:
                        cur = self._cursor_for(edges)
                        if self._edge_cursor:
                            QApplication.changeOverrideCursor(cur)
                        else:
                            QApplication.setOverrideCursor(cur)
                            self._edge_cursor = True
                    elif self._edge_cursor:
                        QApplication.restoreOverrideCursor()
                        self._edge_cursor = False
                elif et == QEvent.MouseButtonPress \
                        and event.button() == Qt.LeftButton and edges:
                    if self._edge_cursor:
                        QApplication.restoreOverrideCursor()
                        self._edge_cursor = False
                    wh.startSystemResize(edges)
                    return True
        return super().eventFilter(obj, event)

    def _build_topbar(self):
        bar = QFrame(); bar.setObjectName("topbar"); bar.setFixedHeight(58)
        lay = QHBoxLayout(bar); lay.setContentsMargins(16, 8, 16, 8); lay.setSpacing(10)

        self.logo_mark = QLabel(); self.logo_mark.setObjectName("logoMark")
        self.logo_mark.setFixedSize(24, 24)
        self._set_logo(self.logo_mark, 24)
        logo = QLabel("Kroma"); logo.setObjectName("logo")
        lay.addWidget(self.logo_mark); lay.addWidget(logo)

        self.dim_pill = QPushButton("  Dimensiones")
        self.dim_pill.setProperty("class", "pill")
        self.dim_pill.setIconSize(QSize(16, 16))
        self.size_pill = QPushButton("—"); self.size_pill.setObjectName("sizePill")
        self.quick_bg = QPushButton("  QUITAR FONDO"); self.quick_bg.setObjectName("quickBg")
        self.quick_bg.setIconSize(QSize(16, 16))
        self.quick_bg.setCursor(Qt.PointingHandCursor)
        self.quick_bg.clicked.connect(lambda: self.select_tool("removebg"))
        for b in (self.dim_pill, self.size_pill, self.quick_bg):
            lay.addWidget(b)

        lay.addStretch()
        self.doc_title = EditableTitle(); self.doc_title.setText("Sin imagen")
        self.doc_title.setAlignment(Qt.AlignCenter)
        self.doc_title.setMaximumWidth(380)
        self.doc_title.setToolTip("Doble clic para renombrar")
        self.doc_title.renamed.connect(self._rename_inline)
        lay.addWidget(self.doc_title)
        self.rename_btn = self._icon_button("pencil", "Renombrar (doble clic en el nombre)")
        self.rename_btn.clicked.connect(self._rename)
        lay.addWidget(self.rename_btn)
        lay.addStretch()

        self.undo_btn = self._icon_button("undo-2", "Deshacer (Ctrl+Z)")
        self.redo_btn = self._icon_button("redo-2", "Rehacer (Ctrl+Y)")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        lay.addWidget(self.undo_btn); lay.addWidget(self.redo_btn)

        self.history_btn = self._icon_button("history", "Historial de cambios")
        self.history_btn.clicked.connect(self._show_history)
        lay.addWidget(self.history_btn)

        self.settings_btn = self._icon_button("settings", "Configuración")
        self.settings_btn.clicked.connect(self._open_settings)
        lay.addWidget(self.settings_btn)

        avatar = QLabel("UI"); avatar.setObjectName("avatar"); avatar.setFixedSize(32, 32)
        lay.addWidget(avatar)

        self.download_btn = QPushButton("  DESCARGAR"); self.download_btn.setObjectName("download")
        self.download_btn.setIconSize(QSize(16, 16))
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.clicked.connect(self.download)
        lay.addWidget(self.download_btn)

        # registrar iconos estáticos para recoloreado por tema
        # (el logo de Kroma no se recolorea: es una imagen con su propio color)
        self._static_icons += [
            (self.dim_pill, "frame", "muted"),
            (self.quick_bg, "scissors", "text"),
            (self.rename_btn, "pencil", "muted"),
            (self.undo_btn, "undo-2", "muted"),
            (self.redo_btn, "redo-2", "muted"),
            (self.history_btn, "history", "muted"),
            (self.settings_btn, "settings", "muted"),
            (self.download_btn, "download", "white"),
        ]
        return bar

    def _build_sidebar(self):
        bar = QFrame(); bar.setObjectName("sidebar")
        bar.setMinimumWidth(60); bar.setMaximumWidth(280)
        self.sidebar = bar
        lay = QVBoxLayout(bar); lay.setContentsMargins(10, 12, 10, 12); lay.setSpacing(4)
        lay.setAlignment(Qt.AlignTop)

        for key, label, icon, sep in SIDE_ITEMS:
            if sep:
                line = QFrame(); line.setProperty("class", "sep")
                lay.addWidget(line)
            btn = self._side_button(key, label, icon)
            if key not in ("open", "home"):
                self._side_group.addButton(btn)
            lay.addWidget(btn)

        lay.addStretch()
        return bar

    def _side_button(self, key, label, icon):
        """Botón de la barra lateral: icono + etiqueta (icono solo si estrecho)."""
        btn = QToolButton(); btn.setToolTip(label); btn.setText(label)
        btn.setProperty("class", "side")
        btn.setCheckable(key not in ("open", "home"))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setIconSize(QSize(22, 22)); btn.setMinimumHeight(42)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.clicked.connect(lambda _=False, k=key: self.select_tool(k))
        btn.setProperty("toolkey", key)
        self._side_icons.append((btn, icon))
        return btn

    def _update_sidebar_labels(self):
        """Muestra las etiquetas cuando la barra es ancha; si no, solo iconos."""
        if not hasattr(self, "sidebar"):
            return
        expanded = self.sidebar.width() >= 120
        style = (Qt.ToolButtonTextBesideIcon if expanded
                 else Qt.ToolButtonIconOnly)
        for btn, _ in self._side_icons:
            btn.setToolButtonStyle(style)

    def _build_stage(self):
        self.stage = QStackedWidget(); self.stage.setObjectName("stage")
        self.stage.addWidget(self._build_welcome())   # index 0
        self.stage.addWidget(self._build_canvas())     # index 1
        return self.stage

    def _build_welcome(self):
        wrap = QWidget(); wrap.setObjectName("stage")
        outer = QVBoxLayout(wrap); outer.setAlignment(Qt.AlignCenter)
        card = QFrame(); card.setObjectName("welcomeCard")
        card.setMaximumWidth(720)
        v = QVBoxLayout(card); v.setContentsMargins(28, 28, 28, 28); v.setSpacing(18)

        head = QHBoxLayout(); head.setSpacing(12); head.setAlignment(Qt.AlignLeft)
        wlogo = QLabel(); wlogo.setFixedSize(44, 44)
        self._set_logo(wlogo, 44)
        title = QLabel("Kroma")
        tf = QFont(); tf.setPointSize(22); tf.setBold(True); title.setFont(tf)
        head.addWidget(wlogo); head.addWidget(title); head.addStretch()
        sub = QLabel("Optimiza, edita, convierte y protege tus imágenes."); sub.setProperty("class", "muted")
        v.addLayout(head); v.addWidget(sub)

        grid = QGridLayout(); grid.setSpacing(14)
        cats = [
            ("1 · Optimización (IA)", [("compress", "Comprimir"), ("removebg", "Eliminar fondo"), ("upscale", "Ampliar")]),
            ("2 · Modificación", [("resize", "Redimensionar"), ("crop", "Recortar"), ("rotate", "Girar")]),
            ("3 · Conversión", [("convert", "Convertir formato"), ("gif", "Crear GIF"), ("html2img", "HTML a imagen")]),
            ("4 · Creativa", [("editor", "Editor de fotos"), ("meme", "Crear meme")]),
            ("5 · Privacidad", [("watermark", "Marca de agua"), ("pixelate", "Pixelar cara"), ("unwatermark", "Quitar marca de agua")]),
        ]
        for i, (cat, items) in enumerate(cats):
            col = QVBoxLayout(); col.setSpacing(6)
            ct = QLabel(cat); ct.setProperty("class", "catTitle"); col.addWidget(ct)
            for key, name in items:
                b = QPushButton(name); b.setProperty("class", "catBtn")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, k=key: self.select_tool(k))
                col.addWidget(b)
            col.addStretch()
            holder = QWidget(); holder.setLayout(col)
            grid.addWidget(holder, i // 3, i % 3)
        v.addLayout(grid)

        drop = QFrame(); drop.setObjectName("dropzone"); drop.setMinimumHeight(120)
        dv = QVBoxLayout(drop); dv.setAlignment(Qt.AlignCenter)
        icon = QLabel(); icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(icons.make_pixmap("upload", theme.palette(self.dark)["accent"], 36))
        t1 = QLabel("Arrastra una imagen aquí o haz clic para subir"); t1.setAlignment(Qt.AlignCenter)
        t2 = QLabel("JPG · PNG · WEBP · GIF · BMP · TIFF · ICO"); t2.setProperty("class", "muted"); t2.setAlignment(Qt.AlignCenter)
        dv.addWidget(icon); dv.addWidget(t1); dv.addWidget(t2)
        drop.mousePressEvent = lambda e: self.open_image()
        v.addWidget(drop)

        outer.addWidget(card)
        return wrap

    def _build_canvas(self):
        wrap = QWidget(); wrap.setObjectName("stage")
        v = QVBoxLayout(wrap); v.setContentsMargins(24, 18, 24, 18); v.setSpacing(12)
        self.canvas_label = QLabel("imagen.png"); self.canvas_label.setObjectName("canvasLabel")
        self.canvas_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.canvas_label)

        self.canvas = ImageCanvas()
        self.canvas.zoomChanged.connect(self._on_zoom_changed)
        v.addWidget(self.canvas, 1)

        # tira de miniaturas (multi-imagen)
        self.strip = QScrollArea(); self.strip.setObjectName("strip")
        self.strip.setWidgetResizable(True)
        self.strip.setFixedHeight(96)
        self.strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.strip_inner = QWidget()
        self.strip_lay = QHBoxLayout(self.strip_inner)
        self.strip_lay.setContentsMargins(8, 8, 8, 8); self.strip_lay.setSpacing(8)
        self.strip_lay.setAlignment(Qt.AlignLeft)
        self.strip.setWidget(self.strip_inner)
        v.addWidget(self.strip)
        self.strip.hide()

        tb = QHBoxLayout(); tb.setAlignment(Qt.AlignCenter); tb.setSpacing(10)
        self.reset_btn = QPushButton("  Restablecer"); self.reset_btn.setProperty("class", "chip")
        self.reset_btn.setIconSize(QSize(16, 16))
        self.reset_btn.setCursor(Qt.PointingHandCursor); self.reset_btn.clicked.connect(self.reset_image)
        self.fit_btn = QPushButton("  Ajustar"); self.fit_btn.setProperty("class", "chip")
        self.fit_btn.setIconSize(QSize(16, 16))
        self.fit_btn.setCursor(Qt.PointingHandCursor); self.fit_btn.clicked.connect(lambda: self.canvas.fit_to_view())
        tb.addWidget(self.reset_btn); tb.addWidget(self.fit_btn)
        v.addLayout(tb)
        self._static_icons += [
            (self.reset_btn, "rotate-ccw", "text"),
            (self.fit_btn, "maximize", "text"),
        ]

        zrow = QHBoxLayout(); zrow.setAlignment(Qt.AlignCenter); zrow.setSpacing(10)
        zrow.addWidget(QLabel("Zoom"))
        self.zoom = QSlider(Qt.Horizontal); self.zoom.setFixedWidth(220)
        self.zoom.setRange(10, 300); self.zoom.setValue(100)
        self.zoom.valueChanged.connect(lambda v: self.canvas.set_zoom(v))
        self.zoom_val = QLabel("100%")
        zrow.addWidget(self.zoom); zrow.addWidget(self.zoom_val)
        v.addLayout(zrow)
        return wrap

    def _build_panel(self):
        panel = QFrame(); panel.setObjectName("panel")
        panel.setMinimumWidth(260); panel.setMaximumWidth(560)
        v = QVBoxLayout(panel); v.setContentsMargins(20, 18, 20, 18); v.setSpacing(14)

        self.panel_eyebrow = QLabel("HERRAMIENTA"); self.panel_eyebrow.setProperty("class", "eyebrow")
        self.panel_title = QLabel("Bienvenido"); self.panel_title.setProperty("class", "panelTitle")
        v.addWidget(self.panel_eyebrow); v.addWidget(self.panel_title)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self._make_placeholder())
        v.addWidget(self.scroll, 1)

        self.batch_check = QCheckBox("Aplicar a todas las imágenes")
        self.batch_check.toggled.connect(self._on_batch_toggled)
        self.batch_check.hide()
        v.addWidget(self.batch_check)

        foot = QHBoxLayout(); foot.setSpacing(10)
        self.cancel_btn = QPushButton("CANCELAR"); self.cancel_btn.setObjectName("cancel")
        self.save_btn = QPushButton("APLICAR"); self.save_btn.setObjectName("save")
        for b in (self.cancel_btn, self.save_btn):
            b.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.save_btn.clicked.connect(self._on_apply)
        foot.addWidget(self.cancel_btn); foot.addWidget(self.save_btn)
        self.foot_widget = QWidget(); self.foot_widget.setLayout(foot)
        v.addWidget(self.foot_widget)
        self.foot_widget.hide()
        return panel

    def _make_placeholder(self):
        """Contenido por defecto del panel derecho (estado «Bienvenido»)."""
        lab = QLabel("Selecciona una herramienta del menú izquierdo, pulsa "
                     "«Inicio» o sube una imagen para empezar.")
        lab.setWordWrap(True); lab.setProperty("class", "muted")
        ph = QWidget(); ph.setObjectName("panelBody")
        phl = QVBoxLayout(ph); phl.setContentsMargins(0, 0, 0, 0)
        phl.addWidget(lab); phl.addStretch()
        return ph

    def go_home(self):
        """Vuelve a la pantalla de inicio (categorías + zona de subida)."""
        if self.current_tool:
            self.current_tool.cancel()
            self.current_tool = None
        self.stage.setCurrentIndex(0)
        self.panel_eyebrow.setText("HERRAMIENTA")
        self.panel_title.setText("Bienvenido")
        self.scroll.setWidget(self._make_placeholder())
        self.foot_widget.hide()
        self.batch_check.hide()
        self._sync_side_buttons(None)

    def _icon_button(self, lucide_name, tip):
        b = QPushButton(); b.setProperty("class", "iconbtn")
        b.setToolTip(tip); b.setCursor(Qt.PointingHandCursor)
        b.setFixedSize(34, 34); b.setIconSize(QSize(18, 18))
        return b

    def _shortcuts(self):
        QShortcut(QKeySequence.Undo, self, self.undo)
        QShortcut(QKeySequence.Redo, self, self.redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)
        QShortcut(QKeySequence.Open, self, self.open_image)
        QShortcut(QKeySequence.Save, self, self.download)
        # Esc cancela la herramienta activa; Enter aplica si hay pie de acciones.
        QShortcut(QKeySequence("Escape"), self, self._on_cancel)
        QShortcut(QKeySequence("Return"), self, self._apply_shortcut)
        QShortcut(QKeySequence("Enter"), self, self._apply_shortcut)
        QShortcut(QKeySequence("Ctrl+W"), self, lambda: self.close_doc(self.active))
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)
        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)

    def _apply_shortcut(self):
        if self.current_tool and self.foot_widget.isVisible():
            self.current_tool.apply()

    # ------------------------------------------------------------- documentos
    def doc(self) -> "Doc | None":
        if 0 <= self.active < len(self.docs):
            return self.docs[self.active]
        return None

    def image(self):
        d = self.doc()
        return d.image if d else None

    def commit(self, img, label=None):
        d = self.doc()
        if d is None:
            return
        d.push(img, label or "Cambio")
        self.canvas.set_image(d.image)
        self.refresh_size()
        self._update_history_buttons()
        self._rebuild_filmstrip()

    def apply_processed(self, fn, label, export=None):
        """Aplica ``fn(img)->img`` a la imagen activa o a todas (modo lote)."""
        if self.apply_to_all and len(self.docs) > 1:
            targets = self.docs
        else:
            targets = [self.doc()]
        n = 0
        for d in targets:
            if d is None:
                continue
            d.push(fn(d.image), label)
            if export:
                d.export_format, d.export_quality = export
            n += 1
        cur = self.doc()
        if cur:
            self.canvas.set_image(cur.image)
        self.refresh_size(); self._update_history_buttons(); self._rebuild_filmstrip()
        if self.current_tool:
            self.current_tool.base = self.image()
        if n > 1:
            self.toast(f"{label}: aplicado a {n} imágenes")
        else:
            self.toast(label)

    def undo(self):
        d = self.doc()
        if not d or not d.can_undo():
            return
        d.undo()
        self.canvas.set_image(d.image)
        self.refresh_size(); self._update_history_buttons(); self._rebuild_filmstrip()
        if self.current_tool:
            self.current_tool.base = d.image

    def redo(self):
        d = self.doc()
        if not d or not d.can_redo():
            return
        d.redo()
        self.canvas.set_image(d.image)
        self.refresh_size(); self._update_history_buttons(); self._rebuild_filmstrip()
        if self.current_tool:
            self.current_tool.base = d.image

    def _update_history_buttons(self):
        d = self.doc()
        self.undo_btn.setEnabled(bool(d and d.can_undo()))
        self.redo_btn.setEnabled(bool(d and d.can_redo()))

    def _show_history(self):
        d = self.doc()
        if not d:
            self.toast("No hay imagen abierta")
            return
        m = QMenu(self)
        for i, (label, _) in enumerate(d.history):
            a = m.addAction(("●  " if i == d.index else "○  ") + f"{i+1}.  {label}")
            a.triggered.connect(lambda _=False, idx=i: self._history_goto(idx))
        m.exec(self.history_btn.mapToGlobal(self.history_btn.rect().bottomLeft()))

    def _history_goto(self, idx):
        d = self.doc()
        if not d:
            return
        d.goto(idx)
        self.canvas.set_image(d.image)
        self.refresh_size(); self._update_history_buttons(); self._rebuild_filmstrip()
        if self.current_tool:
            self.current_tool.base = d.image

    def reset_image(self):
        if self.current_tool:
            self.current_tool.cancel()
            self.current_tool.activate()
        self.canvas.fit_to_view()

    def refresh_size(self):
        img = self.canvas.displayed() or self.image()
        self.size_pill.setText(f"{img.width} × {img.height}" if img else "—")

    # --- multi-documento ---
    def set_active(self, index):
        if not (0 <= index < len(self.docs)):
            return
        self.active = index
        d = self.doc()
        self.canvas.set_image(d.image)
        self.doc_title.setText(os.path.splitext(d.name)[0])
        self.canvas_label.setText(d.name)
        self._sync_window_title()
        self.refresh_size(); self._update_history_buttons(); self._rebuild_filmstrip()
        if self.current_tool:
            self.current_tool.cancel()
            self.current_tool.activate()
        QTimer.singleShot(20, self.canvas.fit_to_view)

    def add_doc(self, path, activate=True):
        if len(self.docs) >= self.max_images:
            self.toast(f"Límite de {self.max_images} imágenes alcanzado "
                       f"(cámbialo en Configuración)")
            return False
        try:
            img = ops.load_image(path)
        except Exception as e:
            self.toast(f"No se pudo abrir: {e}")
            return False
        self._last_dir = os.path.dirname(path) or self._last_dir
        self._add_recent(path)
        self.docs.append(Doc(img, os.path.basename(path), path))
        self.stage.setCurrentIndex(1)
        if activate or self.active < 0:
            self.set_active(len(self.docs) - 1)
        else:
            self._rebuild_filmstrip()
        self._update_batch_checkbox()
        return True

    def close_doc(self, index):
        if not (0 <= index < len(self.docs)):
            return
        self.docs.pop(index)
        if not self.docs:
            self.active = -1
            self.canvas.set_image(None)
            self.stage.setCurrentIndex(0)
            self.doc_title.setText("Sin imagen")
            self.refresh_size()
            self._sync_window_title()
        else:
            self.active = min(self.active, len(self.docs) - 1)
            self.set_active(self.active)
        self._rebuild_filmstrip()
        self._update_batch_checkbox()

    def _rebuild_filmstrip(self):
        if not hasattr(self, "strip_lay"):
            return
        while self.strip_lay.count():
            item = self.strip_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, d in enumerate(self.docs):
            t = d.image.copy(); t.thumbnail((120, 120))
            pm = QPixmap.fromImage(ops.pil_to_qimage(t))
            self.strip_lay.addWidget(Thumb(self, i, pm, i == self.active))
        add = QPushButton("＋"); add.setProperty("class", "thumbAdd")
        add.setFixedSize(Thumb.SIZE, Thumb.SIZE); add.setCursor(Qt.PointingHandCursor)
        add.setToolTip("Añadir imágenes")
        add.clicked.connect(self.open_image)
        self.strip_lay.addWidget(add)
        self.strip.setVisible(len(self.docs) > 1)

    def _update_batch_checkbox(self):
        show = bool(self.current_tool
                    and getattr(self.current_tool, "can_batch", False)
                    and len(self.docs) > 1)
        self.batch_check.setVisible(show)
        if show:
            self.batch_check.setText(f"Aplicar a las {len(self.docs)} imágenes")

    def _on_batch_toggled(self, on):
        self.apply_to_all = on

    # ------------------------------------------------------------- abrir/guardar
    def open_image(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Abrir imágenes", self._last_dir,
            "Imágenes (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.ico)")
        for i, p in enumerate(paths):
            self.add_doc(p, activate=(i == 0))

    def load_path(self, path):
        self.add_doc(path, activate=True)

    def download(self):
        d = self.doc()
        if not d:
            self.toast("No hay imagen para descargar")
            return
        if len(self.docs) > 1:
            box = QMessageBox(self)
            box.setWindowTitle("Descargar")
            box.setText(f"Tienes {len(self.docs)} imágenes abiertas.")
            this_btn = box.addButton("Solo esta", QMessageBox.AcceptRole)
            all_btn = box.addButton("Todas (carpeta)", QMessageBox.ActionRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is all_btn:
                return self.download_all()
            if box.clickedButton() is not this_btn:
                return
        default = os.path.join(
            self._last_dir,
            os.path.splitext(d.name)[0] + EXT_MAP.get(d.export_format, ".png"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Descargar imagen", default,
            "PNG (*.png);;JPG (*.jpg);;WEBP (*.webp);;GIF (*.gif);;"
            "BMP (*.bmp);;TIFF (*.tiff);;ICO (*.ico)")
        if not path:
            return
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        fmt = EXT_TO_FMT.get(ext, d.export_format)
        try:
            ops.save_image(d.image, path, fmt, d.export_quality)
            self._last_dir = os.path.dirname(path) or self._last_dir
            self.toast(f"Guardada: {os.path.basename(path)}")
        except Exception as e:
            self.toast(f"Error al guardar: {e}")

    def download_all(self):
        """Exporta todas las imágenes abiertas a una carpeta."""
        if len(self.docs) < 2:
            return self.download()
        folder = self.ask_folder()
        if not folder:
            return
        for d in self.docs:
            name = os.path.splitext(d.name)[0] + EXT_MAP.get(d.export_format, ".png")
            try:
                ops.save_image(d.image, f"{folder}/{name}", d.export_format,
                               d.export_quality)
            except Exception:
                pass
        self.toast(f"{len(self.docs)} imágenes guardadas en la carpeta")

    def set_export(self, fmt, quality):
        d = self.doc()
        if d:
            d.export_format = fmt
            d.export_quality = quality

    def _rename(self):
        """Inicia la edición inline del nombre (lápiz o menú Archivo)."""
        if self.doc():
            self.doc_title.start_edit()

    def _rename_inline(self, newbase):
        """Confirma el nombre editado in situ, conservando la extensión."""
        d = self.doc()
        if not d:
            self.doc_title.setText("Sin imagen")
            return
        newbase = newbase.strip()
        if not newbase:
            self.doc_title.setText(os.path.splitext(d.name)[0])
            return
        ext = os.path.splitext(d.name)[1]
        d.name = newbase + ext
        self.doc_title.setText(os.path.splitext(d.name)[0])
        self.canvas_label.setText(d.name)
        self._sync_window_title()
        self._rebuild_filmstrip()

    # ------------------------------------------------------------- herramientas
    def select_tool(self, key):
        if key == "home":
            self.go_home()
            return
        if key == "open":
            self.open_image()
            self._sync_side_buttons()
            return
        if self.image() is None and TOOL_MAP[key].requires_image:
            self.open_image()
            if self.image() is None:
                self._sync_side_buttons()
                return

        if self.current_tool:
            self.current_tool.cancel()

        tool = TOOL_MAP[key](self)
        self.current_tool = tool
        self.panel_eyebrow.setText(tool.eyebrow.upper())
        self.panel_title.setText(tool.title)

        widget = tool.build()
        holder = QWidget(); hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0); hl.addWidget(widget)
        self.scroll.setWidget(holder)

        tool.activate()
        if tool.use_footer:
            self.save_btn.setText(tool.apply_label)
            self.foot_widget.show()
        else:
            self.foot_widget.hide()
        self._update_batch_checkbox()

        if self.image() is not None and self.stage.currentIndex() == 0:
            self.stage.setCurrentIndex(1)
        self._sync_side_buttons(key)
        self.refresh_size()

    def _sync_side_buttons(self, active=None):
        for b in self._side_group.buttons():
            b.setChecked(b.property("toolkey") == active)
        self._refresh_icons()

    def _on_apply(self):
        if self.current_tool:
            self.current_tool.apply()

    def _on_cancel(self):
        if self.current_tool:
            self.current_tool.cancel()

    # ------------------------------------------------------------- varios
    def _on_zoom_changed(self, percent):
        self.zoom.blockSignals(True)
        self.zoom.setValue(percent)
        self.zoom.blockSignals(False)
        self.zoom_val.setText(f"{percent}%")

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_theme()
        self._save_settings()

    def apply_theme(self):
        c = theme.palette(self.dark)
        app = QApplication.instance()
        # Fijar la paleta evita que widgets sin estilo hereden los colores
        # del sistema (p. ej. fondo negro del modo oscuro de Windows en
        # nuestro modo claro).
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(c["bg"]))
        pal.setColor(QPalette.Base, QColor(c["panel"]))
        pal.setColor(QPalette.AlternateBase, QColor(c["panel_alt"]))
        pal.setColor(QPalette.Text, QColor(c["text"]))
        pal.setColor(QPalette.WindowText, QColor(c["text"]))
        pal.setColor(QPalette.Button, QColor(c["panel"]))
        pal.setColor(QPalette.ButtonText, QColor(c["text"]))
        pal.setColor(QPalette.ToolTipBase, QColor(c["panel"]))
        pal.setColor(QPalette.ToolTipText, QColor(c["text"]))
        pal.setColor(QPalette.PlaceholderText, QColor(c["muted"]))
        pal.setColor(QPalette.Highlight, QColor(c["accent"]))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        app.setPalette(pal)
        app.setStyleSheet(theme.build_qss(self.dark))
        self._refresh_icons()

    def _refresh_icons(self):
        pal = theme.palette(self.dark)
        roles = {"muted": pal["muted"], "text": pal["text"],
                 "accent": pal["accent"], "white": "#ffffff"}
        for btn, name in self._side_icons:
            color = "#ffffff" if btn.isChecked() else pal["muted"]
            btn.setIcon(icons.make_icon(name, color))
        for widget, name, role in self._static_icons:
            color = roles.get(role, pal["text"])
            if isinstance(widget, QLabel):
                s = widget.width() or 22
                pm = icons.make_pixmap(name, color, s * 2)
                pm.setDevicePixelRatio(2)
                widget.setPixmap(pm)
            else:
                widget.setIcon(icons.make_icon(name, color))
        self._update_max_icon()

    @contextmanager
    def busy(self, msg=None):
        """Muestra cursor de espera (y opcionalmente un aviso) durante una
        operación pesada para que la UI no parezca colgada."""
        if msg:
            self.toast(msg, ms=600)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()

    def toast(self, msg, ms=2600):
        if not hasattr(self, "_toast"):
            self._toast = QLabel(self)
            self._toast.setStyleSheet(
                "background:#2A2E35; color:white; padding:10px 18px;"
                "border-radius:12px; font-weight:600;")
            self._toast.setAlignment(Qt.AlignCenter)
            self._toast.hide()
        self._toast.setText(msg)
        self._toast.adjustSize()
        self._toast.move((self.width() - self._toast.width()) // 2,
                         self.height() - self._toast.height() - 40)
        self._toast.show(); self._toast.raise_()
        QTimer.singleShot(ms, self._toast.hide)

    # diálogos auxiliares usados por las herramientas
    def ask_open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar imagen", self._last_dir,
            "Imágenes (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.ico)")
        if path:
            self._last_dir = os.path.dirname(path) or self._last_dir
        return path or None

    def ask_open_multi(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar imágenes", self._last_dir,
            "Imágenes (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.ico)")
        if paths:
            self._last_dir = os.path.dirname(paths[0]) or self._last_dir
        return paths or []

    def ask_save(self, default_name, filt):
        start = os.path.join(self._last_dir, default_name) if self._last_dir else default_name
        path, _ = QFileDialog.getSaveFileName(self, "Guardar", start, filt)
        if path:
            self._last_dir = os.path.dirname(path) or self._last_dir
        return path or None

    def ask_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Carpeta de destino", self._last_dir) or None
        if folder:
            self._last_dir = folder
        return folder

    @staticmethod
    def _check_rembg():
        try:
            import importlib.util
            return importlib.util.find_spec("rembg") is not None
        except Exception:
            return False

    # arrastrar y soltar
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile()]
        for i, p in enumerate(paths):
            self.add_doc(p, activate=(i == 0))
