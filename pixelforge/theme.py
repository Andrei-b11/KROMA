"""Paleta de colores y hojas de estilo QSS para PixelForge.

Estética inspirada en editores modernos: fondo claro, paneles blancos,
esquinas redondeadas, acento coral y sombras suaves. Incluye variante oscura.
"""

LIGHT = {
    "bg":          "#CDD2D9",
    "panel":       "#EBEDF1",
    "panel_alt":   "#DFE3E8",
    "sidebar":     "#E4E7EC",
    "text":        "#2A2E35",
    "muted":       "#727884",
    "border":      "#C2C8D0",
    "accent":      "#F2693F",
    "accent_hi":   "#FF7B52",
    "accent_lo":   "#E2552C",
    "accent_soft": "#F6DACE",
    "danger":      "#E5484D",
    "track":       "#D2D7DE",
    "canvas":      "#D8DCE2",
    "shadow":      "rgba(60, 64, 72, 35)",
}

DARK = {
    "bg":          "#1C1E22",
    "panel":       "#26282D",
    "panel_alt":   "#2D3036",
    "sidebar":     "#26282D",
    "text":        "#E8EAED",
    "muted":       "#9AA0A8",
    "border":      "#34373D",
    "accent":      "#F2693F",
    "accent_hi":   "#FF7B52",
    "accent_lo":   "#E2552C",
    "accent_soft": "#3A2E2A",
    "danger":      "#E5484D",
    "track":       "#34373D",
    "canvas":      "#1F2125",
    "shadow":      "rgba(0, 0, 0, 90)",
}


def palette(dark: bool = False) -> dict:
    return DARK if dark else LIGHT


def build_qss(dark: bool = False) -> str:
    c = palette(dark)
    return f"""
* {{
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
    color: {c['text']};
    outline: none;
}}
QWidget#root {{ background: {c['bg']}; }}

/* ---------- Barra de título personalizada ---------- */
QFrame#titlebar {{
    background: {c['panel_alt']};
    border-bottom: 1px solid {c['border']};
}}
QLabel#winTitle {{ color: {c['muted']}; font-weight: 600; font-size: 12px; }}

QToolButton.menubtn {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 5px 11px;
    color: {c['text']};
    font-weight: 600;
}}
QToolButton.menubtn:hover {{ background: {c['panel']}; }}
QToolButton.menubtn:pressed,
QToolButton.menubtn[checked="true"] {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QToolButton.menubtn::menu-indicator {{ image: none; width: 0; }}

QToolButton.winbtn {{
    background: transparent;
    border: none;
    border-radius: 0;
}}
QToolButton.winbtn:hover {{ background: {c['track']}; }}
QToolButton#winClose:hover {{ background: {c['danger']}; }}

QMenu {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 28px 8px 12px;
    border-radius: 8px;
    margin: 1px 2px;
    color: {c['text']};
}}
QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QMenu::item:disabled {{ color: {c['muted']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

/* ---------- Top bar ---------- */
QFrame#topbar {{
    background: {c['panel']};
    border-bottom: 1px solid {c['border']};
}}
QLabel#logo {{ font-size: 16px; font-weight: 700; color: {c['text']}; }}
QLabel#logoMark {{ color: {c['accent']}; font-size: 17px; font-weight: 700; }}
QLabel#docTitle {{ font-size: 14px; font-weight: 600; }}
/* Nombre del documento editable (parece etiqueta hasta el doble clic) */
QLineEdit#docTitle {{
    font-size: 14px; font-weight: 600;
    background: transparent; border: none; border-radius: 7px;
    padding: 3px 8px; color: {c['text']};
}}
QLineEdit#docTitle:!read-only {{
    background: {c['panel_alt']};
    border: 1px solid {c['accent']};
}}

QPushButton.pill {{
    background: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 14px;
    padding: 6px 14px;
    font-weight: 600;
    color: {c['muted']};
}}
QPushButton.pill:hover {{ border-color: {c['accent']}; color: {c['text']}; }}
QPushButton#sizePill {{
    background: transparent;
    border: 1px solid {c['border']};
    border-radius: 14px;
    padding: 6px 14px;
    color: {c['muted']};
    font-weight: 600;
}}
QPushButton#quickBg {{
    background: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 14px;
    padding: 6px 14px;
    font-weight: 700;
    color: {c['text']};
}}
QPushButton#quickBg:hover {{ background: {c['accent_soft']}; border-color: {c['accent']}; }}

QPushButton#download {{
    background: {c['accent']};
    color: white;
    border: none;
    border-radius: 14px;
    padding: 8px 18px;
    font-weight: 700;
}}
QPushButton#download:hover {{ background: {c['accent_hi']}; }}
QPushButton#download:pressed {{ background: {c['accent_lo']}; }}

QLabel#avatar {{
    background: {c['accent_soft']};
    color: {c['accent']};
    border-radius: 16px;
    font-weight: 700;
    min-width: 32px; min-height: 32px;
    qproperty-alignment: AlignCenter;
}}

QToolButton.iconbtn, QPushButton.iconbtn {{
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 6px;
    color: {c['muted']};
}}
QToolButton.iconbtn:hover, QPushButton.iconbtn:hover {{
    background: {c['panel_alt']};
    color: {c['text']};
}}

/* ---------- Sidebar ---------- */
QFrame#sidebar {{
    background: {c['sidebar']};
    border-right: 1px solid {c['border']};
}}
QToolButton.side {{
    background: transparent;
    border: none;
    border-radius: 11px;
    padding: 8px 12px;
    color: {c['muted']};
    text-align: left;
    font-weight: 600;
}}
QToolButton.side:hover {{ background: {c['panel_alt']}; color: {c['text']}; }}
QToolButton.side:checked {{
    background: {c['accent']};
    color: white;
}}
QFrame.sep {{ background: {c['border']}; max-height: 1px; min-height: 1px; }}

/* ---------- Canvas / stage ---------- */
QWidget#stage {{ background: {c['bg']}; }}
QLabel#canvasLabel {{ color: {c['muted']}; font-weight: 600; }}

QPushButton.chip {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 7px 16px;
    font-weight: 600;
    color: {c['text']};
}}
QPushButton.chip:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}

/* ---------- Right panel ---------- */
QFrame#panel {{
    background: {c['panel']};
    border-left: 1px solid {c['border']};
}}
QLabel.eyebrow {{ color: {c['accent']}; font-weight: 700; font-size: 11px; letter-spacing: 1px; }}
QLabel.panelTitle {{ font-size: 17px; font-weight: 700; }}
QLabel.muted {{ color: {c['muted']}; }}
QLabel.fieldlabel {{ color: {c['muted']}; font-weight: 600; font-size: 12px; }}
QLabel.value {{ color: {c['text']}; font-weight: 700; }}

QFrame.card {{
    background: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 14px;
}}

QPushButton#cancel {{
    background: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 13px;
    padding: 11px;
    font-weight: 700;
    color: {c['text']};
}}
QPushButton#cancel:hover {{ background: {c['track']}; }}
QPushButton#save {{
    background: {c['accent']};
    color: white;
    border: none;
    border-radius: 13px;
    padding: 11px;
    font-weight: 700;
}}
QPushButton#save:hover {{ background: {c['accent_hi']}; }}
QPushButton#save:pressed {{ background: {c['accent_lo']}; }}
QPushButton#save:disabled {{ background: {c['track']}; color: {c['muted']}; }}

/* ---------- Inputs ---------- */
QSlider::groove:horizontal {{
    height: 6px; border-radius: 3px; background: {c['track']};
}}
QSlider::sub-page:horizontal {{
    height: 6px; border-radius: 3px; background: {c['accent']};
}}
QSlider::handle:horizontal {{
    background: white; border: 2px solid {c['accent']};
    width: 16px; height: 16px; border-radius: 9px; margin: -6px 0;
}}
QSlider::handle:horizontal:hover {{ background: {c['accent_soft']}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: {c['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    selection-background-color: {c['accent_soft']};
    selection-color: {c['text']};
    padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}

QPushButton.choice {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 11px;
    padding: 9px 12px;
    font-weight: 600;
    color: {c['text']};
}}
QPushButton.choice:hover {{ border-color: {c['accent']}; }}
QPushButton.choice:checked {{
    background: {c['accent_soft']};
    border-color: {c['accent']};
    color: {c['accent']};
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 6px;
    border: 1px solid {c['border']}; background: {c['panel']};
}}
QCheckBox::indicator:checked {{
    background: {c['accent']}; border-color: {c['accent']};
}}

/* ---------- Splitter (paneles redimensionables) ---------- */
QSplitter#bodySplitter::handle {{ background: {c['border']}; }}
QSplitter#bodySplitter::handle:horizontal {{ width: 6px; }}
QSplitter#bodySplitter::handle:hover {{ background: {c['accent']}; }}
QSplitter#bodySplitter::handle:pressed {{ background: {c['accent_lo']}; }}

/* ---------- Scroll ---------- */
QScrollArea {{ border: none; background: transparent; }}
/* el contenido del scroll del panel debe ser transparente (no heredar
   un fondo oscuro de la paleta del sistema en modo claro) */
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QWidget#panelBody {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QListWidget {{
    background: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 12px;
    padding: 4px;
}}
QListWidget::item {{ border-radius: 8px; padding: 6px; }}
QListWidget::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}

/* ---------- Welcome ---------- */
QFrame#welcomeCard {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 20px;
}}
QLabel.catTitle {{ font-weight: 700; color: {c['text']}; }}
QPushButton.catBtn {{
    background: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 8px 10px;
    text-align: left;
    color: {c['text']};
}}
QPushButton.catBtn:hover {{ background: {c['accent_soft']}; border-color: {c['accent']}; color: {c['accent']}; }}
QFrame#dropzone {{
    background: {c['panel_alt']};
    border: 2px dashed {c['border']};
    border-radius: 16px;
}}
QFrame#dropzone[hover="true"] {{ border-color: {c['accent']}; background: {c['accent_soft']}; }}

/* ---------- Tira de miniaturas ---------- */
QScrollArea#strip {{
    background: {c['panel']};
    border: 1px solid {c['border']};
    border-radius: 14px;
}}
QFrame.thumb {{
    background: {c['panel_alt']};
    border: 2px solid {c['border']};
    border-radius: 12px;
}}
QFrame.thumb[active="true"] {{ border-color: {c['accent']}; }}
QPushButton.thumbAdd {{
    background: {c['panel_alt']};
    border: 2px dashed {c['border']};
    border-radius: 12px;
    color: {c['muted']};
    font-size: 22px; font-weight: 700;
}}
QPushButton.thumbAdd:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}

QToolTip {{
    background: {c['text']}; color: {c['panel']};
    border: none; border-radius: 6px; padding: 5px 8px;
}}

/* ---------- Diálogos con estética de la app (Kroma) ---------- */
QDialog#dlg {{ background: {c['panel']}; }}
QFrame#dlgTitlebar {{
    background: {c['panel_alt']};
    border-bottom: 1px solid {c['border']};
}}
QLabel#dlgTitle {{ font-weight: 700; font-size: 13px; }}
QWidget#dlgBody {{ background: {c['panel']}; }}

/* ---------- Pestañas de documentos / proyectos ---------- */
QTabBar#docTabs {{ background: transparent; }}
QTabBar#docTabs::tab {{
    background: {c['panel_alt']};
    color: {c['muted']};
    border: 1px solid {c['border']};
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: 7px 14px;
    margin-right: 4px;
    font-weight: 600;
    max-width: 220px;
}}
QTabBar#docTabs::tab:selected {{
    background: {c['panel']};
    color: {c['text']};
    border-color: {c['accent']};
}}
QTabBar#docTabs::tab:hover {{ color: {c['text']}; }}
QToolButton#tabAdd {{
    background: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 9px;
    color: {c['muted']};
    font-size: 15px; font-weight: 700;
    padding: 4px 10px;
}}
QToolButton#tabAdd:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
"""
