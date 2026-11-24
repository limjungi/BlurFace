"""앱 아이콘(BlurFace.icns) 만들기: 어두운 둥근 사각형 + 모자이크로 가린 얼굴."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

OUT = Path(__file__).with_name("BlurFace.icns")


def draw(size: int = 1024) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 1024
    body = QRectF(100 * s, 100 * s, 824 * s, 824 * s)  # macOS 아이콘 격자
    g = QLinearGradient(body.topLeft(), body.bottomLeft())
    g.setColorAt(0, QColor("#2c2c30"))
    g.setColorAt(1, QColor("#141416"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(body, 185 * s, 185 * s)
    # 머리와 어깨 실루엣
    p.setBrush(QColor("#3a3a40"))
    shoulders = QPainterPath()
    shoulders.addRoundedRect(QRectF(250 * s, 690 * s, 524 * s, 300 * s), 230 * s, 230 * s)
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(body, 185 * s, 185 * s)
    p.setClipPath(clip)
    p.drawPath(shoulders)
    p.restore()
    # 얼굴 = 모자이크 칸 (파랑 계열), 타원 안만
    face = QPainterPath()
    face.addEllipse(QPointF(512 * s, 430 * s), 205 * s, 240 * s)
    p.save()
    p.setClipPath(face)
    cell = 68 * s
    colors = ["#0a84ff", "#409cff", "#0060df", "#5ac8fa", "#3478f6", "#64a8ff"]
    y, row = 180 * s, 0
    while y < 690 * s:
        x, col = 300 * s, 0
        while x < 730 * s:
            p.setBrush(QColor(colors[(row * 7 + col * 13 + (row * col * 5) ^ (row + 2 * col)) % len(colors)]))
            p.drawRect(QRectF(x, y, cell + 1, cell + 1))
            x += cell
            col += 1
        y += cell
        row += 1
    p.restore()
    p.end()
    return img


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841 (QPainter 글꼴 등 초기화)
    base = draw()
    iconset = OUT.with_suffix(".iconset")
    iconset.mkdir(exist_ok=True)
    for px in (16, 32, 128, 256, 512):
        for k in (1, 2):
            name = f"icon_{px}x{px}{'@2x' if k == 2 else ''}.png"
            base.scaled(px * k, px * k, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation).save(str(iconset / name))
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT)], check=True)
    base.save(str(OUT.with_suffix(".png")))
    for f in iconset.iterdir():
        f.unlink()
    iconset.rmdir()
    print(OUT)


if __name__ == "__main__":
    main()
