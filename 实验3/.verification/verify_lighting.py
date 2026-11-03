"""检查真实 OpenGL 帧和用户交互；在仓库根目录用 .venv 运行。"""
from pathlib import Path
import math
import sys

import numpy as np
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from OpenGL import GL as gl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task1_lighting import LightingWindow, X_POSITIONS, Y_POSITIONS

app = QApplication([])
window = LightingWindow()
window.show()
view = window.view
QTest.qWait(700)
assert view.isValid() and not view.error, view.error


def frame():
    view.update()
    QTest.qWait(80)
    image = view.grabFramebuffer().convertToFormat(17)  # QImage.Format_RGBA8888
    raw = image.bits()
    raw.setsize(image.byteCount())
    return np.frombuffer(raw, np.uint8).reshape(image.height(), image.width(), 4).copy()[:, :, :3]


def sphere_patch(pixels, row, column):
    h, w = pixels.shape[:2]
    distance = view.distance * max(1, 1.20 / (view.width() / view.height()))
    scale = h / (2 * math.tan(math.radians(20)) * distance)
    x = round(w / 2 + X_POSITIONS[column] * scale)
    y = round(h / 2 - Y_POSITIONS[row] * scale)
    return pixels[y-5:y+6, x-5:x+6]


baseline = frame()
assert len(view.label_overlay.labels) == 12
view.set_parameter('light_ambient', 0)
no_ambient = frame()
assert np.array_equal(sphere_patch(baseline, 0, 0), sphere_patch(no_ambient, 0, 0))
assert sphere_patch(baseline, 1, 0).mean() > sphere_patch(no_ambient, 1, 0).mean() + 30

for index in range(3):
    view.set_parameter('light_rgb', 0, index)
dark = frame()
for row in range(3):
    for column in range(3):
        assert sphere_patch(dark, row, column).max() <= 2
    emitted = sphere_patch(dark, row, 3).mean(axis=(0, 1))
    assert emitted[0] > 65 and emitted[1] > 40 and emitted[2] > 40

view.setFocus()
view.reset_parameters()
original = view.light_position[:]
for key, axis in ((Qt.Key_D, 0), (Qt.Key_W, 1), (Qt.Key_Q, 2)):
    QTest.keyClick(view, key)
    assert view.light_position[axis] > original[axis]
    assert window.controls['light_position', axis].value() == view.light_position[axis]
for key, axis in ((Qt.Key_R, 0), (Qt.Key_G, 1), (Qt.Key_B, 2)):
    QTest.keyClick(view, key, Qt.ShiftModifier)
    assert view.light_rgb[axis] == 0.95
    QTest.keyClick(view, key)
    assert view.light_rgb[axis] == 1

window.controls['specular_strength', None].setValue(0.25)
assert view.specular_strength == 0.25
view.reset_parameters()
before = frame()
start = QPointF(view.rect().center())
app.sendEvent(view, QMouseEvent(QMouseEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
app.sendEvent(view, QMouseEvent(QMouseEvent.MouseMove, start + QPointF(80, 30), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
app.sendEvent(view, QMouseEvent(QMouseEvent.MouseButtonRelease, start + QPointF(80, 30), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
assert view.yaw != 0 and view.pitch != 0
assert np.mean(np.abs(frame().astype(float) - before)) > 2
distance = view.distance
app.sendEvent(view, QWheelEvent(start, start, view.rect().topLeft(), view.rect().topLeft() + __import__('PyQt5.QtCore', fromlist=['QPoint']).QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
assert view.distance < distance
QTest.keyClick(view, Qt.Key_Space)
assert (view.yaw, view.pitch, view.distance) == (0, 0, 21)
QTest.keyClick(view, Qt.Key_Home)
assert view.light_position == [0, 30, 30]
view.makeCurrent()
assert gl.glGetError() == gl.GL_NO_ERROR
view.doneCurrent()
window.close()
print('PASS: real rendering, ambient isolation, emission without light, XYZ/RGB keys, UI sync, drag/zoom/reset, GL errors')
