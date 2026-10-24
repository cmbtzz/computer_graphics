"""实验三编程任务1：十二个球体的光照与材质比较。"""

import argparse
import math
from pathlib import Path
import sys

from OpenGL import GL as gl
from OpenGL.GLU import (
    GLU_SMOOTH, gluDeleteQuadric, gluLookAt, gluNewQuadric,
    gluPerspective, gluProject, gluQuadricNormals, gluSphere,
)
from PyQt5.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QSurfaceFormat
from PyQt5.QtWidgets import (
    QApplication, QColorDialog, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QOpenGLWidget, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)


ROW_NAMES = ("无环境光", "白色环境光", "有色环境光")
COL_NAMES = ("漫反射", "漫反射 + 低高光", "漫反射 + 强高光", "漫反射 + 自发光")
SHORT_COL_NAMES = ("仅漫反射", "低高光", "强高光", "自发光")
X_POSITIONS = (-5.4, -1.8, 1.8, 5.4)
Y_POSITIONS = (3.4, 0.0, -3.4)


class LabelOverlay(QWidget):
    """用独立的 Qt 透明覆盖层画中文，避免固定管线状态影响文字。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.labels = []

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QColor("#dce5f4"))
        painter.setFont(QFont("Microsoft YaHei", 9))
        for x, y, text in self.labels:
            painter.drawText(QRectF(x - 105, y, 210, 42), Qt.AlignHCenter | Qt.AlignTop, text)
        painter.setPen(QColor("#91a4be"))
        painter.drawText(16, 25, "三行：无环境 / 白色环境 / 有色环境　　四列：漫反射 / 低高光 / 强高光 / 自发光")


class LightingView(QOpenGLWidget):
    changed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        fmt = QSurfaceFormat()
        # 固定管线的 glLight/glMaterial 使用兼容上下文。
        fmt.setVersion(2, 1)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setMinimumSize(720, 560)
        self.setFocusPolicy(Qt.StrongFocus)
        self.sphere_list = None
        self.error = ""
        self.last_mouse = None
        self.label_overlay = LabelOverlay(self)
        self.reset_parameters()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.label_overlay.setGeometry(self.rect())

    def reset_parameters(self):
        self.light_position = [0.0, 30.0, 30.0]
        self.light_rgb = [1.0, 1.0, 1.0]
        self.light_ambient = 0.4
        self.diffuse_color = [0.10, 0.50, 0.80]
        self.emission_color = [0.30, 0.20, 0.20]
        self.diffuse_strength = 1.0
        self.ambient_strength = 1.0
        self.specular_strength = 1.0
        self.low_shininess = 5.0
        self.high_shininess = 100.0
        self.emission_strength = 1.0
        self.reset_camera()

    def reset_camera(self):
        self.yaw, self.pitch, self.distance = 0.0, 0.0, 21.0
        self.changed.emit()
        self.update()

    def initializeGL(self):
        try:
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glEnable(gl.GL_NORMALIZE)
            quadric = gluNewQuadric()
            if not quadric:
                raise RuntimeError("无法创建球体几何")
            try:
                gluQuadricNormals(quadric, GLU_SMOOTH)
                self.sphere_list = gl.glGenLists(1)
                if not self.sphere_list:
                    raise RuntimeError("无法创建 OpenGL 显示列表，请检查显卡兼容模式")
                gl.glNewList(self.sphere_list, gl.GL_COMPILE)
                gluSphere(quadric, 0.95, 64, 48)
                gl.glEndList()
            finally:
                gluDeleteQuadric(quadric)
            self.context().aboutToBeDestroyed.connect(self.cleanup)
        except Exception as exc:
            self.error = str(exc)
            self.failed.emit(self.error)

    def material_for(self, row, column):
        """每次完整指定四个材质分量，避免上一颗球的状态泄漏。"""
        ambient_tints = ((0, 0, 0), (0.7, 0.7, 0.7), (0.8, 0.8, 0.2))
        ambient = [v * self.ambient_strength for v in ambient_tints[row]]
        diffuse = [v * self.diffuse_strength for v in self.diffuse_color]
        specular = self.specular_strength
        return {
            "ambient": (*ambient, 1.0),
            "diffuse": (*diffuse, 1.0),
            "specular": ((specular,) * 3 + (1.0,)) if column in (1, 2) else (0, 0, 0, 1),
            "emission": tuple(v * self.emission_strength for v in self.emission_color) + (1.0,)
            if column == 3 else (0, 0, 0, 1),
            "shininess": self.low_shininess if column == 1 else self.high_shininess,
        }

    def paintGL(self):
        # 每帧明确设置固定管线的渲染状态。
        ratio = self.devicePixelRatioF()
        gl.glViewport(0, 0, round(self.width() * ratio), round(self.height() * ratio))
        gl.glClearColor(0.0, 0.08, 0.08, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        if self.error or not self.sphere_list:
            return
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_COLOR_MATERIAL)
        gl.glEnable(gl.GL_NORMALIZE)
        gl.glShadeModel(gl.GL_SMOOTH)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        # 窄窗口时增加距离，使四列球体仍可完整显示。
        aspect = self.width() / max(1, self.height())
        gluPerspective(40.0, aspect, 0.1, 120.0)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        distance = self.distance * max(1.0, 1.20 / aspect)
        gluLookAt(distance * math.sin(yaw) * math.cos(pitch),
                  distance * math.sin(pitch),
                  distance * math.cos(yaw) * math.cos(pitch), 0, 0, 0, 0, 1, 0)

        gl.glEnable(gl.GL_LIGHTING)
        gl.glEnable(gl.GL_LIGHT0)
        # 清空默认全局环境光，保证第一行确实没有环境光贡献。
        gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT, (0, 0, 0, 1))
        # 示例图的高光主要在各球上方，采用固定管线的无限远观察者近似。
        gl.glLightModeli(gl.GL_LIGHT_MODEL_LOCAL_VIEWER, gl.GL_FALSE)
        # 在相机变换之后、各球体变换之前设置位置，灯光固定在世界坐标中。
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_POSITION, (*self.light_position, 1.0))
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_AMBIENT,
                     tuple(v * self.light_ambient for v in self.light_rgb) + (1.0,))
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_DIFFUSE, (*self.light_rgb, 1.0))
        gl.glLightfv(gl.GL_LIGHT0, gl.GL_SPECULAR, (*self.light_rgb, 1.0))
        gl.glLightf(gl.GL_LIGHT0, gl.GL_CONSTANT_ATTENUATION, 1.0)
        gl.glLightf(gl.GL_LIGHT0, gl.GL_LINEAR_ATTENUATION, 0.0)
        gl.glLightf(gl.GL_LIGHT0, gl.GL_QUADRATIC_ATTENUATION, 0.0)

        model = gl.glGetDoublev(gl.GL_MODELVIEW_MATRIX)
        projection = gl.glGetDoublev(gl.GL_PROJECTION_MATRIX)
        viewport = gl.glGetIntegerv(gl.GL_VIEWPORT)
        labels = []
        for row, y in enumerate(Y_POSITIONS):
            for column, x in enumerate(X_POSITIONS):
                material = self.material_for(row, column)
                for name, enum in (("ambient", gl.GL_AMBIENT), ("diffuse", gl.GL_DIFFUSE),
                                   ("specular", gl.GL_SPECULAR), ("emission", gl.GL_EMISSION)):
                    gl.glMaterialfv(gl.GL_FRONT_AND_BACK, enum, material[name])
                gl.glMaterialf(gl.GL_FRONT_AND_BACK, gl.GL_SHININESS, material["shininess"])
                gl.glPushMatrix()
                gl.glTranslatef(x, y, 0)
                gl.glCallList(self.sphere_list)
                gl.glPopMatrix()
                sx, sy, depth = gluProject(x, y - 1.26, 0, model, projection, viewport)
                if 0 < depth < 1:
                    labels.append((sx / ratio, self.height() - sy / ratio,
                                   f"{row + 1}-{column + 1}  {SHORT_COL_NAMES[column]}\n{ROW_NAMES[row]}"))

        # 小点只标记光源位置，不参与其他球体的材质设置。
        gl.glDisable(gl.GL_LIGHTING)
        gl.glColor3f(*self.light_rgb)
        gl.glPushMatrix()
        gl.glTranslatef(*self.light_position)
        gl.glScalef(0.13, 0.13, 0.13)
        gl.glCallList(self.sphere_list)
        gl.glPopMatrix()
        self.label_overlay.labels = labels
        self.label_overlay.update()

    def set_parameter(self, name, value, index=None):
        if index is None:
            setattr(self, name, float(value))
        else:
            getattr(self, name)[index] = float(value)
        self.changed.emit()
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        movement = {
            Qt.Key_Left: (0, -0.4), Qt.Key_A: (0, -0.4),
            Qt.Key_Right: (0, 0.4), Qt.Key_D: (0, 0.4),
            Qt.Key_Up: (1, 0.4), Qt.Key_W: (1, 0.4),
            Qt.Key_Down: (1, -0.4), Qt.Key_S: (1, -0.4),
            Qt.Key_Q: (2, 0.4), Qt.Key_E: (2, -0.4),
        }
        if key in movement:
            index, delta = movement[key]
            self.light_position[index] = max(-100, min(100, self.light_position[index] + delta))
        elif key in (Qt.Key_R, Qt.Key_G, Qt.Key_B):
            index = {Qt.Key_R: 0, Qt.Key_G: 1, Qt.Key_B: 2}[key]
            delta = -0.05 if event.modifiers() & Qt.ShiftModifier else 0.05
            self.light_rgb[index] = max(0, min(1, round(self.light_rgb[index] + delta, 4)))
        elif key == Qt.Key_Home:
            self.reset_parameters()
            return
        elif key == Qt.Key_Space:
            self.reset_camera()
            return
        else:
            super().keyPressEvent(event)
            return
        self.changed.emit()
        self.update()

    def mousePressEvent(self, event):
        self.setFocus()
        self.last_mouse = event.pos()

    def mouseMoveEvent(self, event):
        if self.last_mouse is not None:
            delta = event.pos() - self.last_mouse
            if event.buttons() & Qt.LeftButton:
                self.yaw = (self.yaw + delta.x() * 0.4) % 360
                self.pitch = max(-80, min(80, self.pitch + delta.y() * 0.4))
            elif event.buttons() & Qt.RightButton:
                self.distance = max(6, min(60, self.distance * math.exp(delta.y() * 0.01)))
            self.changed.emit()
            self.update()
        self.last_mouse = event.pos()

    def mouseReleaseEvent(self, event):
        self.last_mouse = None

    def wheelEvent(self, event):
        self.distance = max(6, min(60, self.distance * math.exp(-event.angleDelta().y() / 1200)))
        self.changed.emit()
        self.update()
        event.accept()

    def cleanup(self):
        if self.sphere_list and self.context() and self.context().isValid():
            self.makeCurrent()
            gl.glDeleteLists(self.sphere_list, 1)
            self.sphere_list = None
            self.doneCurrent()


class LightingWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("光照与材质 · 编程任务1 · 十二球体比较")
        self.resize(1360, 860)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        title = QLabel("光照与材质：十二球体对照实验")
        title.setStyleSheet("font-size: 20px; font-weight: bold; padding: 4px;")
        layout.addWidget(title)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self.view = LightingView()
        body.addWidget(self.view, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(300)
        panel = QWidget()
        sidebar = QVBoxLayout(panel)
        scroll.setWidget(panel)
        body.addWidget(scroll)
        self.controls = {}
        self.add_controls(sidebar, "点光源（世界坐标）", (
            ("X 左右", "light_position", -100, 100, 0.4, 0),
            ("Y 上下", "light_position", -100, 100, 0.4, 1),
            ("Z 前后", "light_position", -100, 100, 0.4, 2),
            ("红 R", "light_rgb", 0, 1, 0.05, 0),
            ("绿 G", "light_rgb", 0, 1, 0.05, 1),
            ("蓝 B", "light_rgb", 0, 1, 0.05, 2),
            ("环境光强度", "light_ambient", 0, 1, 0.05, None),
        ))
        self.add_controls(sidebar, "材质参数", (
            ("漫反射系数", "diffuse_strength", 0, 1, 0.05, None),
            ("环境反射系数", "ambient_strength", 0, 1, 0.05, None),
            ("镜面反射强度", "specular_strength", 0, 1, 0.05, None),
            ("低高光指数", "low_shininess", 0, 128, 1, None),
            ("强高光指数", "high_shininess", 0, 128, 1, None),
            ("自发光强度", "emission_strength", 0, 1, 0.05, None),
        ))
        self.color_button = QPushButton("选择球体漫反射颜色")
        self.color_button.clicked.connect(self.choose_color)
        sidebar.addWidget(self.color_button)
        self.emission_button = QPushButton("选择自发光颜色")
        self.emission_button.clicked.connect(lambda: self.choose_color("emission_color"))
        sidebar.addWidget(self.emission_button)
        note = QLabel("环境反射系数仅影响第二、三行。\n镜面反射仅影响第二、三列。\n自发光仅影响第四列。\n\nshininess 越大，高光越集中；\n镜面反射强度决定高光亮度。\n自发光只让自身变亮，不照亮邻球。")
        note.setWordWrap(True)
        sidebar.addWidget(note)
        reset_camera = QPushButton("重置视角（空格）")
        reset_camera.clicked.connect(self.view.reset_camera)
        sidebar.addWidget(reset_camera)
        reset_all = QPushButton("恢复全部默认值（Home）")
        reset_all.clicked.connect(self.view.reset_parameters)
        sidebar.addWidget(reset_all)
        sidebar.addStretch()
        self.status = QLabel()
        layout.addWidget(self.status)
        help_text = QLabel("先点击画面：方向键 / WASD 移灯光左右上下，Q/E 移灯光前后；R/G/B 增加对应颜色，Shift+R/G/B 减少。\n"
                           "鼠标左键拖动旋转视角；滚轮或右键上下拖动拉近拉远；空格重置视角；Home 重置全部。")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.view.changed.connect(self.sync_controls)
        self.view.failed.connect(self.show_error)
        self.sync_controls()

    def add_controls(self, sidebar, title, entries):
        group = QGroupBox(title)
        form = QFormLayout(group)
        for label, name, minimum, maximum, step, index in entries:
            box = QDoubleSpinBox()
            box.setRange(minimum, maximum)
            box.setSingleStep(step)
            box.setDecimals(2)
            box.setMinimumWidth(75)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(lambda value, n=name, i=index: self.view.set_parameter(n, value, i))
            self.controls[name, index] = box
            form.addRow(label, box)
        sidebar.addWidget(group)

    def sync_controls(self):
        for (name, index), box in self.controls.items():
            value = getattr(self.view, name)
            if index is not None:
                value = value[index]
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        for button, name in ((self.color_button, "diffuse_color"), (self.emission_button, "emission_color")):
            color = QColor.fromRgbF(*getattr(self.view, name))
            button.setStyleSheet(f"border: 2px solid {color.name()}; padding: 5px;")
        position = ", ".join(f"{v:.1f}" for v in self.view.light_position)
        rgb = ", ".join(f"{v:.2f}" for v in self.view.light_rgb)
        if not self.view.error:
            self.status.setText(f"灯光位置 ({position})　 RGB ({rgb})　 视距 {self.view.distance:.1f}")

    def choose_color(self, name="diffuse_color"):
        # clicked(bool) 的布尔参数不作为颜色属性名。
        if not isinstance(name, str):
            name = "diffuse_color"
        color = QColorDialog.getColor(QColor.fromRgbF(*getattr(self.view, name)), self, "选择材质颜色")
        if color.isValid():
            setattr(self.view, name, [color.redF(), color.greenF(), color.blueF()])
            self.view.changed.emit()
            self.view.update()

    def show_error(self, message):
        self.status.setText("OpenGL 初始化失败：" + message)

    def closeEvent(self, event):
        self.view.cleanup()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshot", type=Path, help="保存整个窗口截图后退出")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setFont(QFont("Microsoft YaHei", 9))
    window = LightingWindow()
    window.show()
    window.view.setFocus()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            framebuffer = window.view.grabFramebuffer()
            ok = not window.view.error and not framebuffer.isNull()
            ok = ok and window.grab().save(str(args.screenshot))
            if window.view.error:
                print(window.view.error, file=sys.stderr)
            window.close()
            app.exit(0 if ok else 1)
        QTimer.singleShot(1000, capture)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
