"""Kroma — punto de entrada de la aplicación.

Uso:
    python main.py
    python main.py foto.jpg
"""
import os
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from pixelforge.main_window import MainWindow, APP_ICON, APP_ICON_ICO


def main():
    # En Windows, asegura que la barra de tareas use el icono de Kroma
    # (y no el genérico de Python) agrupando bajo un AppUserModelID propio.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Kroma.Editor")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Kroma")
    app.setApplicationDisplayName("Kroma")

    icon_path = APP_ICON_ICO if os.path.exists(APP_ICON_ICO) else APP_ICON
    app.setWindowIcon(QIcon(icon_path))

    win = MainWindow()
    win.show()
    # Permite abrir una imagen pasada como argumento: python main.py foto.jpg
    if len(sys.argv) > 1:
        win.load_path(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
