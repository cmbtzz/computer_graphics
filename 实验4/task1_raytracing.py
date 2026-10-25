"""实验四编程任务1：使用 GLSL 片元着色器完成交互式光线追踪。

Python 只负责窗口、参数和全屏三角形；求交、遮挡、反射、折射全部在 GPU 上计算。
运行：..\.venv\Scripts\python.exe task1_raytracing.py（也可双击 run_task1.cmd）。
"""

import argparse
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
import sys
import time

from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QSurfaceFormat
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QOpenGLWidget, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

SHADER_DIR = Path(__file__).resolve().parent / "shaders"


@dataclass
class SceneObject:
    name: str
    shape: int
    position: list
    extent: tuple
    color: list
    mirror: float = 0.0
    transmission: float = 0.0
    ior: float = 1.5
    shininess: float = 70.0
    pattern: int = 0


def default_scene():
    """封闭物体使用解析几何；extent 是半尺寸，球只读取第一个分量。"""
    return [
        SceneObject("棋盘地面", 1, [0, -.08, .5], (4, .08, 4.5), [.72, .65, .51], mirror=.12, pattern=1),
        SceneObject("红色左墙", 1, [-4.08, 2.5, .5], (.08, 2.5, 4.5), [.62, .065, .045]),
        SceneObject("绿色右墙", 1, [4.08, 2.5, .5], (.08, 2.5, 4.5), [.065, .43, .20]),
        SceneObject("浅色后墙", 1, [0, 2.5, -4.08], (4, 2.5, .08), [.64, .68, .73]),
        SceneObject("天花板", 1, [0, 5.08, .5], (4, .08, 4.5), [.66, .68, .71]),
        SceneObject("矩形面光源", 1, [-1.5, 4.91, .3], (.9, .015, .9), [1, 1, 1]),
        SceneObject("镜面球", 0, [-1.9, 1.05, .2], (1.05, 1.05, 1.05), [.90, .95, 1.0], mirror=.94, shininess=180),
        SceneObject("玻璃球", 0, [.45, .90, 1.25], (.9, .9, .9), [.87, .96, .99], transmission=.98, ior=1.5, shininess=180),
        SceneObject("木纹立方体", 1, [2.15, .85, -.55], (.85, .85, .85), [.58, .30, .11], mirror=.04, pattern=2),
        SceneObject("蓝色圆柱", 2, [-.25, .72, -1.85], (.60, .72, .60), [.065, .24, .65], mirror=.18, shininess=100),
        SceneObject("金属小球", 0, [2.65, .48, 2.15], (.48, .48, .48), [.95, .63, .19], mirror=.78, shininess=160),
    ]


class RayTracingView(QOpenGLWidget):
    fps_changed = pyqtSignal(float)
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 420)
        self.setFocusPolicy(Qt.StrongFocus)
        self.trace_program = self.display_program = self.vao = 0
        self.render_buffer = None
        self.locations = {}
        self.error = ""
        self.frame_index = 0
        self.fps = 0.0
        self.frame_times = deque(maxlen=120)
        self.last_fps_update = 0.0
        self.pending_render_frame = False
        self.shadow_samples = 4
        self.render_scale = .75
        self.last_mouse = None
        self.reset_parameters()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.next_frame)
        self.frameSwapped.connect(self.record_frame_rate)
        self.timer.start()

    def reset_parameters(self):
        self.objects = default_scene()
        self.max_depth = 5
        self.epsilon = .001
        self.reflection = self.refraction = self.shadows = self.soft_shadows = True
        self.light_power = 7.0
        self.light_size = 1.8
        self.light_color = [1.0, .94, .84]
        self.ambient = .055
        self.exposure = 0.0
        self.reset_camera()

    def reset_camera(self):
        self.yaw, self.pitch, self.distance = 0.0, 5.0, 11.8
        self.target = [0.0, 2.0, -.35]
        self.fov = 43.0
        self.restart()

    def restart(self):
        """请求绘制当前场景；各帧完全独立，不保留历史颜色。"""
        self.update()

    def next_frame(self):
        if self.isVisible() and not self.error:
            self.update()

    def record_frame_rate(self):
        """统计实际提交显示的完整渲染帧。"""
        if not self.pending_render_frame:
            return
        self.pending_render_frame = False
        now = time.perf_counter()
        if self.frame_times and now - self.frame_times[-1] > 1.0:
            self.frame_times.clear()
            self.fps = 0.0
            self.fps_changed.emit(self.fps)
        self.frame_times.append(now)
        while len(self.frame_times) > 2 and now - self.frame_times[0] > 1.0:
            self.frame_times.popleft()
        if len(self.frame_times) >= 2:
            self.fps = (len(self.frame_times) - 1) / (now - self.frame_times[0])
            if now - self.last_fps_update >= .25:
                self.last_fps_update = now
                self.fps_changed.emit(self.fps)

    def initializeGL(self):
        try:
            version = gl.glGetString(gl.GL_VERSION).decode()
            renderer = gl.glGetString(gl.GL_RENDERER).decode()
            print(f"OpenGL {version}; {renderer}", flush=True)
            vertex = (SHADER_DIR / "fullscreen.vert").read_text(encoding="utf-8")
            for attribute, filename in (("trace_program", "raytrace.frag"), ("display_program", "display.frag")):
                # 着色器编译/链接失败会显示完整日志，不用近似图替代渲染结果。
                program = compileProgram(
                    compileShader(vertex, gl.GL_VERTEX_SHADER),
                    compileShader((SHADER_DIR / filename).read_text(encoding="utf-8"), gl.GL_FRAGMENT_SHADER),
                )
                setattr(self, attribute, program)
            self.vao = int(gl.glGenVertexArrays(1))
            self.context().aboutToBeDestroyed.connect(self.cleanup)
        except Exception as exc:
            self.error = str(exc)
            self.failed.emit(self.error)

    def cleanup(self):
        if not self.context() or not self.context().isValid():
            return
        self.makeCurrent()
        self.render_buffer = None
        for program in (self.trace_program, self.display_program):
            if program:
                gl.glDeleteProgram(program)
        if self.vao:
            gl.glDeleteVertexArrays(1, [self.vao])
        self.trace_program = self.display_program = self.vao = 0
        self.locations.clear()
        self.doneCurrent()

    def location(self, program, name):
        key = (program, name)
        if key not in self.locations:
            self.locations[key] = gl.glGetUniformLocation(program, name)
        return self.locations[key]

    def uniform(self, name, value):
        loc = self.location(self.trace_program, name)
        if isinstance(value, (bool, int)):
            gl.glUniform1i(loc, int(value))
        elif isinstance(value, (list, tuple)):
            {2: gl.glUniform2f, 3: gl.glUniform3f, 4: gl.glUniform4f}[len(value)](loc, *value)
        else:
            gl.glUniform1f(loc, value)

    def upload_scene(self, width, height):
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        eye = [
            self.target[0] + self.distance * math.cos(pitch) * math.sin(yaw),
            self.target[1] + self.distance * math.sin(pitch),
            self.target[2] + self.distance * math.cos(pitch) * math.cos(yaw),
        ]
        parameters = {
            "resolution": (width, height), "shadowSamples": self.shadow_samples,
            "eye": eye, "target": self.target, "fieldOfView": self.fov,
            "objectCount": len(self.objects), "maxDepth": self.max_depth,
            "rayEpsilon": self.epsilon, "useReflection": self.reflection,
            "useRefraction": self.refraction, "useShadows": self.shadows,
            "softShadows": self.soft_shadows, "ambientLight": self.ambient,
            "lightPosition": self.objects[5].position, "lightColor": self.light_color,
            "lightPower": self.light_power, "lightSize": self.light_size,
        }
        for name, value in parameters.items():
            # resolution 是浮点 vec2；避免整数元组被识别成 ivec2。
            self.uniform(name, value)
        for index, obj in enumerate(self.objects):
            half_size = (self.light_size / 2, .015, self.light_size / 2) if index == 5 else obj.extent
            for name, value in {
                "shape": obj.shape, "center": obj.position, "extent": half_size,
                "baseColor": obj.color, "pattern": obj.pattern,
                "material": (obj.mirror, obj.transmission, obj.ior, obj.shininess),
            }.items():
                self.uniform(f"{name}[{index}]", value)

    def paintGL(self):
        if self.error or not self.trace_program:
            gl.glClearColor(.08, .09, .12, 1)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            return
        try:
            physical_w = max(1, round(self.width() * self.devicePixelRatioF()))
            physical_h = max(1, round(self.height() * self.devicePixelRatioF()))
            width, height = max(1, round(physical_w * self.render_scale)), max(1, round(physical_h * self.render_scale))
            if self.render_buffer is None or self.render_buffer.width() != width or self.render_buffer.height() != height:
                self.render_buffer = None
                fmt = QOpenGLFramebufferObjectFormat()
                fmt.setInternalTextureFormat(gl.GL_RGBA16F)
                self.render_buffer = QOpenGLFramebufferObject(width, height, fmt)
                if not self.render_buffer.isValid():
                    raise RuntimeError("不能创建实时渲染缓冲区")
            gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_BLEND)
            gl.glDisable(gl.GL_FRAMEBUFFER_SRGB)
            gl.glBindVertexArray(self.vao)
            # 每一帧重新追踪整个场景，不读取上一帧，也没有达到样本数后停止的分支。
            self.render_buffer.bind()
            gl.glViewport(0, 0, width, height)
            gl.glUseProgram(self.trace_program)
            self.upload_scene(width, height)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            gl.glViewport(0, 0, physical_w, physical_h)
            gl.glUseProgram(self.display_program)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.render_buffer.texture())
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glUniform1i(self.location(self.display_program, "image"), 0)
            gl.glUniform1f(self.location(self.display_program, "exposure"), self.exposure)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
            gl.glBindVertexArray(0)
            gl.glUseProgram(0)
            self.frame_index += 1
            self.pending_render_frame = True
        except Exception as exc:
            self.error = str(exc)
            self.failed.emit(self.error)

    def mousePressEvent(self, event):
        self.setFocus()
        self.last_mouse = event.pos()

    def mouseMoveEvent(self, event):
        if self.last_mouse is None:
            return
        delta = event.pos() - self.last_mouse
        self.last_mouse = event.pos()
        if event.buttons() & Qt.LeftButton:
            self.yaw = max(-75.0, min(75.0, self.yaw + delta.x() * .25))
            self.pitch = max(-30.0, min(70.0, self.pitch + delta.y() * .25))
        elif event.buttons() & Qt.RightButton:
            self.distance = max(2.0, min(24.0, self.distance + delta.y() * .04))
        else:
            return
        self.restart()

    def wheelEvent(self, event):
        self.distance = max(2.0, min(24.0, self.distance * math.exp(-event.angleDelta().y() / 1200)))
        self.restart()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Home):
            self.reset_camera()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实验四 · 编程任务1 · 实时 GPU 光线追踪")
        self.resize(1340, 880)
        self.view = RayTracingView()
        self.updating_controls = False
        self.controls = {}
        self.status = QLabel("正在编译 GLSL 着色器…")
        self.status.setWordWrap(True)
        self.fps_label = QLabel("FPS: --（正在启动实时渲染）")
        self.statusBar().addPermanentWidget(self.fps_label)
        self.view.fps_changed.connect(self.update_fps)
        self.view.failed.connect(self.show_error)
        panel = QWidget()
        self.panel_layout = QVBoxLayout(panel)
        title = QLabel("光线追踪实验")
        title.setStyleSheet("font-size: 22px; font-weight: 600; padding: 8px 0;")
        self.panel_layout.addWidget(title)
        hint = QLabel("球体 · 立方体 · 封闭圆柱\n镜面反射 · Fresnel 折射 · 面光源软阴影\n左键旋转 / 滚轮缩放 / 空格复位视角")
        hint.setWordWrap(True)
        self.panel_layout.addWidget(hint)
        self.make_algorithm_controls()
        self.make_light_controls()
        self.make_object_controls()
        buttons = QHBoxLayout()
        reset = QPushButton("重置全部")
        reset.clicked.connect(self.reset_all)
        save = QPushButton("保存渲染图")
        save.clicked.connect(self.save_render)
        buttons.addWidget(reset)
        buttons.addWidget(save)
        self.panel_layout.addLayout(buttons)
        self.panel_layout.addWidget(self.status)
        self.panel_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(320)
        scroll.setMaximumWidth(370)
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(8, 8, 8, 8)
        row.addWidget(self.view, 1)
        row.addWidget(scroll)
        self.setCentralWidget(root)
        self.setStyleSheet("QGroupBox { font-weight: 600; margin-top: 10px; padding-top: 12px; }"
                           "QDoubleSpinBox, QSpinBox, QComboBox { min-height: 23px; }"
                           "QPushButton { min-height: 28px; } QLabel { line-height: 1.3; }")
        self.sync_controls()

    def update_fps(self, fps):
        value = f"{fps:.1f}" if fps > 0 else "--"
        duration = f"{1000.0 / fps:.1f} ms" if fps > 0 else "-- ms"
        self.fps_label.setText(f"FPS: {value} · {duration} · 实时渲染")
        if not self.view.error:
            self.status.setText(f"实时 GPU 光线追踪 · 已绘制 {self.view.frame_index} 帧\n每帧独立计算，持续刷新")

    def group(self, title):
        box = QGroupBox(title)
        form = QFormLayout(box)
        self.panel_layout.addWidget(box)
        return form

    def spin(self, form, key, label, low, high, step, integer=False, callback=None):
        widget = QSpinBox() if integer else QDoubleSpinBox()
        if not integer:
            widget.setDecimals(4 if key == "epsilon" else 2)
        widget.setRange(low, high)
        widget.setSingleStep(step)
        widget.setKeyboardTracking(False)
        widget.valueChanged.connect(callback or (lambda value, k=key: self.set_parameter(k, value)))
        self.controls[key] = widget
        form.addRow(label, widget)
        return widget

    def make_algorithm_controls(self):
        form = self.group("追踪与画质")
        self.spin(form, "max_depth", "最大弹射深度", 0, 6, 1, True)
        self.spin(form, "shadow_samples", "单帧软阴影质量", 1, 16, 1, True)
        self.spin(form, "epsilon", "求交偏移 ε", .0001, .02, .0005)
        self.spin(form, "render_scale", "内部渲染比例", .25, 1.0, .25)
        self.spin(form, "exposure", "曝光 EV", -3.0, 3.0, .25)
        for key, label in (("reflection", "镜面反射"), ("refraction", "玻璃折射"),
                           ("shadows", "阴影遮挡"), ("soft_shadows", "软阴影（关闭后为硬阴影）")):
            box = QCheckBox(label)
            box.toggled.connect(lambda value, k=key: self.set_parameter(k, value))
            self.controls[key] = box
            form.addRow(box)

    def make_light_controls(self):
        form = self.group("光源")
        for axis, label in enumerate(("X", "Y", "Z")):
            self.spin(form, f"light_{axis}", f"光源 {label}", -3.7 if axis != 1 else .2,
                      3.7 if axis != 1 else 4.94, .1,
                      callback=lambda value, a=axis: self.set_light_position(a, value))
        self.spin(form, "light_power", "光源亮度", 0.0, 20.0, .5)
        self.spin(form, "light_size", "面光源边长", .1, 3.0, .1)
        self.spin(form, "ambient", "近似环境光", 0.0, .3, .01)
        self.light_color_button = QPushButton("选择光源颜色")
        self.light_color_button.clicked.connect(lambda: self.choose_color(True))
        form.addRow(self.light_color_button)

    def make_object_controls(self):
        form = self.group("物体与材质")
        self.object_combo = QComboBox()
        self.editable_ids = [6, 7, 8, 9, 10, 0, 1, 2, 3]
        for index in self.editable_ids:
            self.object_combo.addItem(self.view.objects[index].name, index)
        self.object_combo.currentIndexChanged.connect(self.sync_object_controls)
        form.addRow("编辑物体", self.object_combo)
        for axis, label in enumerate(("X", "Y", "Z")):
            self.spin(form, f"object_{axis}", f"位置 {label}", -8.0, 8.0, .1,
                      callback=lambda value, a=axis: self.set_object_position(a, value))
        for key, label, low, high, step in (
            ("mirror", "镜面反射比例", 0., 1., .05),
            ("transmission", "透明透射比例", 0., 1., .05),
            ("ior", "折射率", 1., 2.5, .05),
            ("shininess", "高光指数", 2., 256., 4.),
        ):
            self.spin(form, key, label, low, high, step,
                      callback=lambda value, k=key: self.set_material(k, value))
        self.color_button = QPushButton("选择材质颜色")
        self.color_button.clicked.connect(lambda: self.choose_color(False))
        form.addRow(self.color_button)
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems(["纯色", "棋盘", "木纹"])
        self.pattern_combo.currentIndexChanged.connect(lambda value: self.set_material("pattern", value))
        form.addRow("颜色纹理", self.pattern_combo)

    def selected_object(self):
        return self.view.objects[self.object_combo.currentData()]

    def set_parameter(self, key, value):
        if self.updating_controls:
            return
        setattr(self.view, key, value)
        self.view.restart()

    def set_light_position(self, axis, value):
        if not self.updating_controls:
            self.view.objects[5].position[axis] = value
            self.view.restart()

    def set_object_position(self, axis, value):
        if not self.updating_controls:
            self.selected_object().position[axis] = value
            self.view.restart()

    def set_material(self, key, value):
        if not self.updating_controls:
            setattr(self.selected_object(), key, value)
            self.view.restart()

    @staticmethod
    def button_color(button, color, text):
        qcolor = QColor.fromRgbF(*color)
        button.setText(f"{text}  {qcolor.name()}")
        button.setStyleSheet(f"border: 2px solid {qcolor.name()};")

    def choose_color(self, light):
        current = self.view.light_color if light else self.selected_object().color
        color = QColorDialog.getColor(QColor.fromRgbF(*current), self, "选择光源颜色" if light else "选择材质颜色")
        if color.isValid():
            values = [color.redF(), color.greenF(), color.blueF()]
            if light:
                self.view.light_color = values
            else:
                self.selected_object().color = values
            self.sync_controls()
            self.view.restart()

    def sync_controls(self):
        self.updating_controls = True
        for key, widget in self.controls.items():
            if hasattr(self.view, key):
                value = getattr(self.view, key)
                widget.setChecked(value) if isinstance(widget, QCheckBox) else widget.setValue(value)
        for axis, value in enumerate(self.view.objects[5].position):
            self.controls[f"light_{axis}"].setValue(value)
        self.button_color(self.light_color_button, self.view.light_color, "光源颜色")
        self.updating_controls = False
        self.sync_object_controls()

    def sync_object_controls(self, *_):
        self.updating_controls = True
        obj = self.selected_object()
        for axis, value in enumerate(obj.position):
            self.controls[f"object_{axis}"].setValue(value)
        for key in ("mirror", "transmission", "ior", "shininess"):
            self.controls[key].setValue(getattr(obj, key))
        self.pattern_combo.setCurrentIndex(obj.pattern)
        self.button_color(self.color_button, obj.color, "材质颜色")
        self.updating_controls = False

    def reset_all(self):
        self.view.shadow_samples = 4
        self.view.render_scale = .75
        self.view.reset_parameters()
        self.sync_controls()

    def save_render(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存当前渲染图", "raytracing.png", "PNG 图片 (*.png)")
        if path and not self.view.grabFramebuffer().save(path):
            QMessageBox.warning(self, "保存失败", f"无法写入：{path}")

    def show_error(self, message):
        self.status.setText("OpenGL 渲染失败，请检查显卡驱动与 OpenGL 3.3 支持。\n" + message)
        print(message, file=sys.stderr, flush=True)

    def closeEvent(self, event):
        self.view.timer.stop()
        self.view.cleanup()
        super().closeEvent(event)


def image_bytes(image):
    image = image.convertToFormat(QImage.Format_RGB888)
    data = image.bits()
    data.setsize(image.byteCount())
    return bytes(data), image.width(), image.height()


class RenderVerification:
    """通过真实 GPU 渲染比较参数变化，不把着色器文本检查当作渲染验证。"""

    def __init__(self, window, app, screenshot, self_test):
        self.window, self.app = window, app
        self.screenshot, self.self_test = screenshot, self_test
        self.start_time = time.monotonic()
        self.capture_after = self.start_time + 1.2
        self.baseline = None
        self.stage = 0
        self.phase = "baseline"
        self.required_frame = window.view.frame_index + 3
        self.original_scene = deepcopy(window.view.objects)
        self.checks = [
            ("reflection", lambda v: setattr(v, "reflection", False)),
            ("refraction", lambda v: setattr(v, "refraction", False)),
            ("shadows", lambda v: setattr(v, "shadows", False)),
            ("depth", lambda v: setattr(v, "max_depth", 0)),
            ("material", lambda v: setattr(v.objects[6], "color", [.9, .05, .03])),
            ("position", lambda v: v.objects[8].position.__setitem__(0, 1.0)),
            ("light", lambda v: setattr(v, "light_power", 2.0)),
        ]
        self.timer = QTimer(window)
        self.timer.timeout.connect(self.poll)
        self.timer.start(80)

    def poll(self):
        view = self.window.view
        try:
            if view.error:
                raise RuntimeError(view.error)
            if time.monotonic() - self.start_time > 180:
                raise RuntimeError("180 秒内未完成 GPU 渲染")
            if view.frame_index < self.required_frame:
                return
            if not view.isValid():
                raise RuntimeError("OpenGL 上下文无效")
            if self.self_test and self.phase != "finished":
                pixels, width, height = image_bytes(view.grabFramebuffer())
                if self.phase == "baseline":
                    self.baseline = pixels
                    if max(pixels) - min(pixels) < 80 or sum(pixels) / len(pixels) < 15:
                        raise AssertionError("基准图像为空白或无有效场景")
                    print(f"PASS baseline: {width}x{height}", flush=True)
                    # 超过旧版 64 帧的停止点，确认静止场景仍在真正执行光追。
                    self.required_frame = view.frame_index + 70
                    self.phase = "continuous"
                    return
                if self.phase == "continuous":
                    if pixels != self.baseline:
                        raise AssertionError("静止场景的独立帧发生变化，存在闪烁或历史颜色影响")
                    if view.fps <= 0 or "实时渲染" not in self.window.fps_label.text():
                        raise AssertionError("持续刷新时未显示有效 FPS")
                    print(f"PASS continuous rendering: {view.frame_index} frames, {view.fps:.1f} FPS; stable independent frames", flush=True)
                    self.phase = "changes"
                elif self.phase == "changes":
                    difference = sum(abs(a-b) for a, b in zip(pixels, self.baseline)) / len(pixels)
                    if difference < .08:
                        raise AssertionError(f"{self.checks[self.stage-1][0]} 未改变渲染结果：{difference}")
                    print(f"PASS {self.checks[self.stage-1][0]}: mean pixel difference {difference:.3f}", flush=True)
                view.reset_parameters()
                view.objects = deepcopy(self.original_scene)
                if self.stage < len(self.checks):
                    self.checks[self.stage][1](view)
                else:
                    self.phase = "finished"
                    # 像素回读与 Python 比较会暂停事件循环；截图前让 FPS 恢复正常统计。
                    self.capture_after = time.monotonic() + 1.2
                self.stage += 1
                self.window.sync_controls()
                view.restart()
                self.required_frame = view.frame_index + 1
                return
            if time.monotonic() < self.capture_after:
                return
            if self.screenshot:
                path = Path(self.screenshot).resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                if not view.grabFramebuffer().save(str(path)):
                    raise RuntimeError(f"不能保存渲染图：{path}")
                # 同时保留包含控制面板的窗口图，便于复现实验参数。
                window_path = path.with_name(path.stem + "_window.png")
                if not self.window.grab().save(str(window_path)):
                    raise RuntimeError(f"不能保存窗口截图：{window_path}")
                print(f"Saved: {path}", flush=True)
            if self.self_test:
                print("All GPU rendering checks passed.", flush=True)
            self.timer.stop()
            self.window.close()
            self.app.exit(0)
        except Exception as exc:
            print(f"Verification failed: {exc}", file=sys.stderr, flush=True)
            self.timer.stop()
            self.window.close()
            self.app.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshot", metavar="PNG", help="绘制实时帧后保存渲染图和窗口截图并退出")
    parser.add_argument("--shadow-samples", type=int, default=4, choices=range(1, 17), metavar="1..16",
                        help="单帧内的软阴影质量，默认 4，不跨帧累积")
    parser.add_argument("--render-scale", type=float, default=.75, help="内部渲染比例 0.25..1.0，默认 0.75")
    parser.add_argument("--size", default="1340x880", help="窗口大小，例如 1340x880")
    parser.add_argument("--self-test", action="store_true", help="在实际 GPU 上验证反射、折射、阴影和参数修改")
    args = parser.parse_args()
    if not .25 <= args.render_scale <= 1.0:
        parser.error("--render-scale 需要在 0.25 与 1.0 之间")
    try:
        width, height = map(int, args.size.lower().split("x"))
        if width < 900 or height < 600:
            raise ValueError
    except ValueError:
        parser.error("--size 需要至少 900x600 的宽x高")
    QApplication.setAttribute(Qt.AA_UseDesktopOpenGL)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("实验四 光线追踪")
    window = MainWindow()
    window.resize(width, height)
    window.view.shadow_samples = args.shadow_samples
    window.view.render_scale = args.render_scale
    window.sync_controls()
    window.show()
    if args.screenshot or args.self_test:
        window.verification = RenderVerification(window, app, args.screenshot, args.self_test)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
