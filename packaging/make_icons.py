"""Make the app icons from TurboCAT's 16x16 pixel-art cat (turbocat/icons/mark.svg), kept crisp:
turbocat.png (Linux), turbocat.ico (Windows) and turbocat.icns (macOS), in packaging/build-icons.
Needs PySide6 and Pillow."""
import os
import sys

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(os.path.dirname(HERE), "turbocat", "icons", "mark.svg")
OUT = os.path.join(HERE, "build-icons")


def render(size):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    QSvgRenderer(SVG).render(p)
    p.end()
    return img


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication(sys.argv[:1])
    os.makedirs(OUT, exist_ok=True)
    png = os.path.join(OUT, "turbocat.png")
    render(512).save(png)
    big = Image.open(png).convert("RGBA")
    big.save(os.path.join(OUT, "turbocat.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(os.path.join(OUT, "turbocat.icns"))
    print("icons in", OUT)
    del app


if __name__ == "__main__":
    main()
