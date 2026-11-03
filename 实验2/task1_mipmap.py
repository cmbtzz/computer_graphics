"""编程任务1：OpenGL 走廊纹理映射与六种过滤方式比较。"""

import argparse
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image
from OpenGL import GL as gl
from OpenGL.GLU import gluLookAt, gluPerspective
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QSurfaceFormat
from PyQt5.QtWidgets import (
    QActionGroup, QApplication, QCheckBox, QComboBox, QHBoxLayout,
    QLabel, QMainWindow, QMenu, QOpenGLWidget, QPushButton, QVBoxLayout, QWidget,
)


# 缩小时的六种合法过滤方式；放大过滤只允许 NEAREST / LINEAR。
FILTERS = (
    ("GL_NEAREST", gl.GL_NEAREST, "最近邻：速度快，近处有像素块，远处容易闪烁。"),
    ("GL_LINEAR", gl.GL_LINEAR, "双线性：单层内插值，远处仍可能出现走样。"),
    ("GL_NEAREST_MIPMAP_NEAREST", gl.GL_NEAREST_MIPMAP_NEAREST,
     "选择最近的 Mipmap 层，层内最近邻；可观察层间过渡。"),
    ("GL_LINEAR_MIPMAP_NEAREST", gl.GL_LINEAR_MIPMAP_NEAREST,
     "选择最近的 Mipmap 层，层内双线性；层间仍有跳变。"),
    ("GL_NEAREST_MIPMAP_LINEAR", gl.GL_NEAREST_MIPMAP_LINEAR,
     "相邻两层之间线性插值，各层内使用最近邻采样。"),
    ("GL_LINEAR_MIPMAP_LINEAR", gl.GL_LINEAR_MIPMAP_LINEAR,
     "三线性：层内双线性、层间线性，减轻远处走样与层间跳变。"),
)

END_WALL_IMAGE = Path(__file__).resolve().parent / "assets" / "corridor_end_cat.png"


def make_textures(size=512):
    """用固定种子生成可重复的砖墙、木地板、灰泥天花板和棋盘纹理。"""
    rng = np.random.default_rng(2026)
    y, x = np.mgrid[:size, :size]
    noise = rng.normal(0, 5, (size, size, 1))
    brick_x = (x + (y // 64 % 2) * 64) % 128
    mortar = (y % 64 < 5) | (brick_x < 5)
    wall = np.clip(np.array([157, 78, 63]) + noise, 0, 255)
    wall[mortar] = np.array([187, 178, 163]) + noise[mortar]
    grain = 8 * np.sin(x * .30 + 3 * np.sin(y * .02))
    floor = np.clip(np.array([154, 115, 67]) + noise + grain[..., None], 0, 255)
    floor[(x % 128 < 4) | ((y + (x // 128 % 2) * 128) % 256 < 3)] *= .45
    ceiling = np.clip(np.array([205, 206, 200]) + noise * 1.8, 0, 255)
    checker = np.repeat(np.where((x // 8 + y // 8) % 2, 240, 20)[..., None], 3, axis=2)
    return [a.astype(np.uint8) for a in (wall, floor, ceiling, checker)]


class CorridorView(QOpenGLWidget):
    changed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(0)  # 保留真实的纹理过滤差异。
        self.setFormat(fmt)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(640, 440)
        self.filter_index = 5
        self.checker = False
        self.repeat = 2.0
        self.textures = []
        self.error = ""
        self.last_mouse = None
        self.reset_camera()

    def reset_camera(self):
        self.eye = np.array([0., 0., 4.])
        self.yaw, self.pitch = 0., 0.
        self.update()

    def initializeGL(self):
        try:
            gl.glClearColor(.015, .018, .025, 1)
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_LIGHTING)
            gl.glEnable(gl.GL_TEXTURE_2D)
            gl.glTexEnvi(gl.GL_TEXTURE_ENV, gl.GL_TEXTURE_ENV_MODE, gl.GL_REPLACE)
            # 照片独立于四张可重复材质，并翻转行方向以匹配 OpenGL 的纹理原点。
            with Image.open(END_WALL_IMAGE) as end_image:
                end_pixels = np.asarray(end_image.convert("RGB").transpose(Image.Transpose.FLIP_TOP_BOTTOM))
            pixels_list = make_textures() + [end_pixels]
            self.textures = [int(t) for t in gl.glGenTextures(len(pixels_list))]
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
            for index, (texture, pixels) in enumerate(zip(self.textures, pixels_list)):
                gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
                wrap = gl.GL_CLAMP_TO_EDGE if index == 4 else gl.GL_REPEAT
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, wrap)
                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, wrap)
                # 各纹理均构造直到 1×1 的完整链，避免缺层导致纹理不完整。
                image, level = Image.fromarray(pixels), 0
                while True:
                    gl.glTexImage2D(gl.GL_TEXTURE_2D, level, gl.GL_RGB,
                                    image.width, image.height, 0, gl.GL_RGB,
                                    gl.GL_UNSIGNED_BYTE, np.asarray(image))
                    if image.size == (1, 1):
                        break
                    image = image.resize((max(1, image.width // 2),
                                          max(1, image.height // 2)), Image.Resampling.BOX)
                    level += 1
            self.context().aboutToBeDestroyed.connect(self.cleanup)
        except Exception as exc:
            self.error = str(exc)
            self.failed.emit(self.error)

    def paintGL(self):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        if self.error or not self.textures:
            return
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gluPerspective(60, self.width() / max(1, self.height()), .05, 160)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        direction = np.array([math.sin(yaw) * math.cos(pitch), math.sin(pitch),
                              -math.cos(yaw) * math.cos(pitch)])
        gluLookAt(*self.eye, *(self.eye + direction), 0, 1, 0)
        # 四个长表面展示透视缩小；尽头用 6×4 的照片端面封闭。
        surfaces = (
            (0, ((-3, -2, 6), (-3, -2, -100), (-3, 2, -100), (-3, 2, 6)), 53, 2),
            (0, ((3, -2, -100), (3, -2, 6), (3, 2, 6), (3, 2, -100)), 53, 2),
            (1, ((-3, -2, 6), (3, -2, 6), (3, -2, -100), (-3, -2, -100)), 3, 53),
            (2, ((-3, 2, -100), (3, 2, -100), (3, 2, 6), (-3, 2, 6)), 3, 53),
            (4, ((-3, -2, -100), (3, -2, -100), (3, 2, -100), (-3, 2, -100)), 1, 1),
        )
        for texture_index, vertices, u, v in surfaces:
            # 棋盘模式只替换墙壁、地板和天花板，照片始终完整显示一次。
            selected = 3 if self.checker and texture_index != 4 else texture_index
            repeat = 1.0 if texture_index == 4 else self.repeat
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.textures[selected])
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, FILTERS[self.filter_index][1])
            mag = gl.GL_NEAREST if self.filter_index in (0, 2, 4) else gl.GL_LINEAR
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, mag)
            gl.glBegin(gl.GL_QUADS)
            for uv, vertex in zip(((0, 0), (u, 0), (u, v), (0, v)), vertices):
                gl.glTexCoord2f(uv[0] * repeat, uv[1] * repeat)
                gl.glVertex3f(*vertex)
            gl.glEnd()

    def set_filter(self, index):
        self.filter_index = index
        self.changed.emit()
        self.update()

    def set_checker(self, checked):
        self.checker = checked
        self.update()

    def move(self, forward=0., side=0., vertical=0.):
        yaw = math.radians(self.yaw)
        self.eye += forward * np.array([math.sin(yaw), 0, -math.cos(yaw)])
        self.eye += side * np.array([math.cos(yaw), 0, math.sin(yaw)])
        self.eye[0] = np.clip(self.eye[0], -2.7, 2.7)
        self.eye[1] = np.clip(self.eye[1] + vertical, -1.7, 1.7)
        self.eye[2] = np.clip(self.eye[2], -94, 5.5)
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        movements = {
            Qt.Key_W: (.6, 0, 0), Qt.Key_Up: (.6, 0, 0),
            Qt.Key_S: (-.6, 0, 0), Qt.Key_Down: (-.6, 0, 0),
            Qt.Key_A: (0, -.3, 0), Qt.Key_Left: (0, -.3, 0),
            Qt.Key_D: (0, .3, 0), Qt.Key_Right: (0, .3, 0),
            Qt.Key_Q: (0, 0, -.2), Qt.Key_E: (0, 0, .2),
        }
        if key in movements:
            self.move(*movements[key])
        elif Qt.Key_1 <= key <= Qt.Key_6:
            self.set_filter(key - Qt.Key_1)
        elif key == Qt.Key_R:
            self.reset_camera()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        self.move(forward=event.angleDelta().y() / 120 * 1.2)

    def mousePressEvent(self, event):
        self.setFocus()
        self.last_mouse = event.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.last_mouse is not None:
            delta = event.pos() - self.last_mouse
            self.yaw = float(np.clip(self.yaw + delta.x() * .15, -75, 75))
            self.pitch = float(np.clip(self.pitch - delta.y() * .15, -65, 65))
            self.update()
        self.last_mouse = event.pos()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        group = QActionGroup(menu)
        for index, (name, _, _) in enumerate(FILTERS):
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(index == self.filter_index)
            group.addAction(action)
            action.triggered.connect(lambda checked, i=index: self.set_filter(i))
        menu.addSeparator()
        menu.addAction("重置视角 (R)", self.reset_camera)
        menu.exec_(event.globalPos())

    def cleanup(self):
        if self.textures:
            self.makeCurrent()
            gl.glDeleteTextures(self.textures)
            self.textures = []
            self.doneCurrent()


class MipmapWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("编程任务1 · 纹理映射与 Mipmap")
        self.resize(1120, 760)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        row = QHBoxLayout()
        row.addWidget(QLabel("纹理过滤："))
        self.filters = QComboBox()
        self.filters.addItems([item[0] for item in FILTERS])
        self.filters.setCurrentIndex(5)
        row.addWidget(self.filters)
        checker = QCheckBox("高频棋盘纹理")
        row.addWidget(checker)
        row.addStretch()
        reset = QPushButton("重置视角")
        row.addWidget(reset)
        layout.addLayout(row)
        self.view = CorridorView()
        layout.addWidget(self.view, 1)
        self.description = QLabel(FILTERS[5][2])
        layout.addWidget(self.description)
        layout.addWidget(QLabel("右键：弹出过滤菜单　|　1–6：切换过滤　|　WASD / 方向键：移动　|　Q/E：升降\n"
                                "左键拖动：环顾　|　滚轮：前后移动　|　R：重置；观察远处纹理的闪烁和过渡。"))
        self.filters.currentIndexChanged.connect(self.view.set_filter)
        checker.toggled.connect(self.view.set_checker)
        reset.clicked.connect(self.view.reset_camera)
        self.view.changed.connect(self.sync_filter)
        self.view.failed.connect(lambda message: self.description.setText("OpenGL 初始化失败：" + message))

    def sync_filter(self):
        self.filters.blockSignals(True)
        self.filters.setCurrentIndex(self.view.filter_index)
        self.filters.blockSignals(False)
        self.description.setText(FILTERS[self.view.filter_index][2])

    def closeEvent(self, event):
        self.view.cleanup()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filter", type=int, choices=range(1, 7), default=6)
    parser.add_argument("--checker", action="store_true")
    parser.add_argument("--screenshot", type=Path, help="保存渲染区截图后退出")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    window = MipmapWindow()
    window.filters.setCurrentIndex(args.filter - 1)
    window.findChild(QCheckBox).setChecked(args.checker)
    window.show()
    window.view.setFocus()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            ok = not window.view.error and window.view.grabFramebuffer().save(str(args.screenshot))
            window.close()
            app.exit(0 if ok else 1)
        QTimer.singleShot(800, capture)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
