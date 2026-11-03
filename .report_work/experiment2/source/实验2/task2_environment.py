"""编程任务2：同一张 EXR 全景图的背景与球体、立方体环境反射。"""

import argparse
import math
from pathlib import Path
import sys

import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from OpenGL.GLU import gluLookAt, gluPerspective
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QSurfaceFormat
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
    QLabel, QMainWindow, QMenu, QOpenGLWidget, QPushButton, QVBoxLayout, QWidget,
)


DEFAULT_PANORAMA = Path(__file__).resolve().with_name("meadow_2_4k.exr")


def load_panorama(path):
    """直接读取 EXR 的线性 HDR 像素，保留原始动态范围。"""
    import OpenEXR
    with OpenEXR.File(str(path)) as file:
        channels = file.channels()
        if "RGB" in channels:
            pixels = channels["RGB"].pixels
        elif "RGBA" in channels:
            pixels = channels["RGBA"].pixels[..., :3]
        else:
            pixels = np.stack([channels[c].pixels for c in "RGB"], axis=-1)
        pixels = np.array(pixels, dtype=np.float32, copy=True)
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("全景图需要 RGB 三通道")
    pixels = np.nan_to_num(pixels, nan=0., posinf=65504., neginf=0.)
    # EXR 第一行是顶部，OpenGL 的 v=0 是底部；翻转一次统一坐标。
    return np.ascontiguousarray(np.clip(pixels[::-1], 0, 65504))


# 两个片元着色器共用完全相同的方向到全景 UV、曝光和色调映射。
ENVIRONMENT_GLSL = """
uniform sampler2D panorama;
uniform float exposure;
uniform float rotation;
const float PI = 3.141592653589793;
vec3 environment(vec3 direction) {
    vec3 d = normalize(direction);
    float c = cos(rotation), s = sin(rotation);
    d = vec3(c*d.x + s*d.z, d.y, -s*d.x + c*d.z);
    vec2 uv = vec2(atan(d.z, d.x)/(2.0*PI)+0.5,
                   asin(clamp(d.y, -1.0, 1.0))/PI+0.5);
    // 显式处理经度接缝的导数，避免 Mipmap 在 atan 跳变处出现模糊竖线。
    vec2 dx = dFdx(uv), dy = dFdy(uv);
    dx.x -= floor(dx.x+0.5);
    dy.x -= floor(dy.x+0.5);
    float footprint = max(length(dx*vec2(textureSize)), length(dy*vec2(textureSize)));
    float lod = max(0.0, log2(max(footprint, 0.0001)));
    vec3 color = texture2DLod(panorama, uv, lod).rgb * exp2(exposure);
    // ACES 近似曲线压缩 HDR，随后转为显示器的 sRGB。
    color = clamp((color*(2.51*color+0.03))/(color*(2.43*color+0.59)+0.14), 0.0, 1.0);
    return mix(12.92*color, 1.055*pow(color, vec3(1.0/2.4))-0.055,
               step(vec3(0.0031308), color));
}
"""

# texture2DLod 在片元阶段使用 GLSL 1.30；兼容上下文保留教学用的矩阵和顶点接口。
SHADER_HEADER = "#version 130\nuniform vec2 textureSize;\n"
SKY_VERTEX = """#version 130
varying vec2 screen;
void main() { screen = gl_Vertex.xy; gl_Position = gl_Vertex; }
"""
SKY_FRAGMENT = SHADER_HEADER + ENVIRONMENT_GLSL + """
varying vec2 screen;
uniform vec3 cameraRight, cameraUp, cameraForward;
uniform float aspect, halfFov;
void main() {
    vec3 ray = cameraForward + screen.x*aspect*halfFov*cameraRight
                             + screen.y*halfFov*cameraUp;
    gl_FragColor = vec4(environment(ray), 1.0);
}
"""
OBJECT_VERTEX = """#version 130
varying vec3 worldPosition, worldNormal;
void main() {
    // 模型坐标已经在 CPU 端变换到世界坐标，法线也按相同旋转变换。
    worldPosition = gl_Vertex.xyz;
    worldNormal = gl_Normal;
    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
}
"""
OBJECT_FRAGMENT = SHADER_HEADER + ENVIRONMENT_GLSL + """
varying vec3 worldPosition, worldNormal;
uniform vec3 cameraPosition;
void main() {
    vec3 incident = normalize(worldPosition - cameraPosition);
    vec3 reflected = reflect(incident, normalize(worldNormal));
    gl_FragColor = vec4(environment(reflected), 1.0);
}
"""


def camera_vectors(yaw, pitch, distance):
    yaw, pitch = math.radians(yaw), math.radians(pitch)
    eye = distance * np.array([math.sin(yaw)*math.cos(pitch), math.sin(pitch),
                               math.cos(yaw)*math.cos(pitch)])
    forward = -eye / np.linalg.norm(eye)
    right = np.cross(forward, [0, 1, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return eye, forward, right, up


class EnvironmentView(QOpenGLWidget):
    changed = pyqtSignal()
    status = pyqtSignal(str)

    def __init__(self, panorama_path=DEFAULT_PANORAMA):
        super().__init__()
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
        fmt.setOption(QSurfaceFormat.DeprecatedFunctions)
        fmt.setDepthBufferSize(24)
        self.setFormat(fmt)
        self.setMinimumSize(640, 440)
        self.setFocusPolicy(Qt.StrongFocus)
        self.panorama_path = Path(panorama_path)
        self.texture = 0
        self.programs = []
        self.geometry = 0
        self.texture_shape = (1, 1)
        self.show_cube = True
        self.exposure, self.rotation = 0., 0.
        self.error = ""
        self.last_mouse = None
        self.reset_camera()

    def reset_camera(self):
        self.yaw, self.pitch, self.distance = 0., 7., 7.8
        self.update()

    def initializeGL(self):
        try:
            gl.glClearColor(.03, .04, .06, 1)
            self.context().aboutToBeDestroyed.connect(self.cleanup)
            self.programs = [
                compileProgram(compileShader(SKY_VERTEX, gl.GL_VERTEX_SHADER),
                               compileShader(SKY_FRAGMENT, gl.GL_FRAGMENT_SHADER)),
                compileProgram(compileShader(OBJECT_VERTEX, gl.GL_VERTEX_SHADER),
                               compileShader(OBJECT_FRAGMENT, gl.GL_FRAGMENT_SHADER)),
            ]
            self.build_geometry()
            self.upload_panorama(self.panorama_path)
        except Exception as exc:
            self.error = str(exc)
            self.status.emit("初始化失败：" + self.error)

    def upload_panorama(self, path):
        # 先解码成功再替换已有纹理，读取失败时仍可继续使用上一张图。
        pixels = load_panorama(path)
        height, width = pixels.shape[:2]
        if max(width, height) > gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE):
            raise ValueError("全景图超过显卡支持的纹理尺寸")
        texture = int(gl.glGenTextures(1))
        try:
            gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB16F, width, height,
                            0, gl.GL_RGB, gl.GL_FLOAT, pixels)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        except Exception:
            gl.glDeleteTextures([texture])
            raise
        if self.texture:
            gl.glDeleteTextures([self.texture])
        self.texture = texture
        self.texture_shape = (width, height)
        self.panorama_path = Path(path)
        self.status.emit(f"{self.panorama_path.name}  |  {width} × {height}  |  背景、球体、立方体共用一张 HDR 纹理")

    def set_panorama(self, path):
        if not self.isValid() or len(self.programs) != 2:
            self.status.emit("OpenGL 尚未就绪，无法加载全景图")
            return
        self.makeCurrent()
        try:
            self.upload_panorama(path)
            self.error = ""
        except Exception as exc:
            self.status.emit("全景图加载失败：" + str(exc))
        finally:
            self.doneCurrent()
        self.update()

    def build_geometry(self):
        """球体使用光滑法线，立方体每个面保持独立的平面法线。"""
        self.geometry = gl.glGenLists(2)
        gl.glNewList(self.geometry, gl.GL_COMPILE)
        slices, stacks = 128, 80
        for j in range(stacks):
            gl.glBegin(gl.GL_QUAD_STRIP)
            for i in range(slices + 1):
                longitude = i / slices * 2 * math.pi
                for k in (j, j + 1):
                    latitude = -math.pi/2 + k / stacks * math.pi
                    normal = (math.cos(latitude)*math.cos(longitude), math.sin(latitude),
                              math.cos(latitude)*math.sin(longitude))
                    gl.glNormal3f(*normal)
                    gl.glVertex3f(normal[0]-1.25, normal[1], normal[2])
            gl.glEnd()
        gl.glEndList()

        gl.glNewList(self.geometry + 1, gl.GL_COMPILE)
        a, b = math.radians(-24), math.radians(12)
        ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0],
                       [-math.sin(a), 0, math.cos(a)]])
        rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)],
                       [0, math.sin(b), math.cos(b)]])
        rotate = ry @ rx
        faces = (
            ((1, 0, 0), ((1,-1,-1), (1,1,-1), (1,1,1), (1,-1,1))),
            ((-1, 0, 0), ((-1,-1,1), (-1,1,1), (-1,1,-1), (-1,-1,-1))),
            ((0, 1, 0), ((-1,1,-1), (-1,1,1), (1,1,1), (1,1,-1))),
            ((0, -1, 0), ((-1,-1,1), (-1,-1,-1), (1,-1,-1), (1,-1,1))),
            ((0, 0, 1), ((-1,-1,1), (1,-1,1), (1,1,1), (-1,1,1))),
            ((0, 0, -1), ((1,-1,-1), (-1,-1,-1), (-1,1,-1), (1,1,-1))),
        )
        gl.glBegin(gl.GL_QUADS)
        for normal, vertices in faces:
            gl.glNormal3f(*(rotate @ normal))
            for vertex in vertices:
                gl.glVertex3f(*(rotate @ (np.array(vertex)*.75) + [1.35, -.1, 0]))
        gl.glEnd()
        gl.glEndList()

    def use_environment(self, program):
        gl.glUseProgram(program)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glUniform1i(gl.glGetUniformLocation(program, "panorama"), 0)
        gl.glUniform1f(gl.glGetUniformLocation(program, "exposure"), self.exposure)
        gl.glUniform1f(gl.glGetUniformLocation(program, "rotation"), math.radians(self.rotation))
        gl.glUniform2f(gl.glGetUniformLocation(program, "textureSize"), *self.texture_shape)

    def paintGL(self):
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        if self.error or not self.texture or len(self.programs) != 2:
            return
        eye, forward, right, up = camera_vectors(self.yaw, self.pitch, self.distance)
        aspect = self.width() / max(1, self.height())
        # 背景只依赖相机朝向，不随相机平移，等价于无限远天空盒。
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_FALSE)
        sky = self.programs[0]
        self.use_environment(sky)
        for name, value in (("cameraForward", forward), ("cameraRight", right), ("cameraUp", up)):
            gl.glUniform3f(gl.glGetUniformLocation(sky, name), *value)
        gl.glUniform1f(gl.glGetUniformLocation(sky, "aspect"), aspect)
        gl.glUniform1f(gl.glGetUniformLocation(sky, "halfFov"), math.tan(math.radians(25)))
        gl.glBegin(gl.GL_QUADS)
        for x, y in ((-1,-1), (1,-1), (1,1), (-1,1)):
            gl.glVertex4f(x, y, 0, 1)
        gl.glEnd()
        gl.glDepthMask(gl.GL_TRUE)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glLoadIdentity()
        gluPerspective(50, aspect, .05, 100)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glLoadIdentity()
        gluLookAt(*eye, 0, 0, 0, *up)
        objects = self.programs[1]
        self.use_environment(objects)
        gl.glUniform3f(gl.glGetUniformLocation(objects, "cameraPosition"), *eye)
        gl.glCallList(self.geometry)
        if self.show_cube:
            gl.glCallList(self.geometry + 1)
        gl.glUseProgram(0)

    def set_cube(self, visible):
        self.show_cube = visible
        self.changed.emit()
        self.update()

    def wheelEvent(self, event):
        # 改变相机距离，真实改变物体大小；背景仍保持全景投影。
        self.distance = float(np.clip(self.distance * math.exp(-event.angleDelta().y()/120*.12), 4, 24))
        self.update()

    def mousePressEvent(self, event):
        self.setFocus()
        self.last_mouse = event.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.last_mouse is not None:
            delta = event.pos() - self.last_mouse
            self.yaw -= delta.x() * .3
            self.pitch = float(np.clip(self.pitch + delta.y() * .3, -85, 85))
            self.update()
        self.last_mouse = event.pos()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_C:
            self.set_cube(not self.show_cube)
        elif event.key() == Qt.Key_R:
            self.reset_camera()
        elif event.key() in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus):
            self.distance = float(np.clip(self.distance * (.88 if event.key() != Qt.Key_Minus else 1.12), 4, 24))
            self.update()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        action = menu.addAction("显示立方体 (C)")
        action.setCheckable(True)
        action.setChecked(self.show_cube)
        action.toggled.connect(self.set_cube)
        menu.addAction("重置视角 (R)", self.reset_camera)
        menu.exec_(event.globalPos())

    def cleanup(self):
        if self.texture or self.geometry or self.programs:
            self.makeCurrent()
            gl.glUseProgram(0)
            if self.texture:
                gl.glDeleteTextures([self.texture])
                self.texture = 0
            if self.geometry:
                gl.glDeleteLists(self.geometry, 2)
                self.geometry = 0
            for program in self.programs:
                gl.glDeleteProgram(program)
            self.programs = []
            self.doneCurrent()


class EnvironmentWindow(QMainWindow):
    def __init__(self, panorama_path=DEFAULT_PANORAMA):
        super().__init__()
        self.setWindowTitle("编程任务2 · 全景环境映射")
        self.resize(1200, 780)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        row = QHBoxLayout()
        self.cube = QCheckBox("显示立方体")
        self.cube.setChecked(True)
        row.addWidget(self.cube)
        row.addWidget(QLabel("曝光 EV："))
        exposure = QDoubleSpinBox()
        exposure.setRange(-5, 5)
        exposure.setSingleStep(.25)
        row.addWidget(exposure)
        row.addWidget(QLabel("环境旋转："))
        rotation = QDoubleSpinBox()
        rotation.setRange(-180, 180)
        rotation.setSuffix("°")
        rotation.setSingleStep(10)
        row.addWidget(rotation)
        row.addStretch()
        load = QPushButton("打开 EXR 全景图")
        reset = QPushButton("重置视角")
        row.addWidget(load)
        row.addWidget(reset)
        layout.addLayout(row)
        self.view = EnvironmentView(panorama_path)
        layout.addWidget(self.view, 1)
        self.info = QLabel("正在加载全景图…")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        layout.addWidget(QLabel("左键拖动：环绕观察　|　鼠标滚轮 / +/-：拉近、拉远　|　右键菜单 / C：显示或隐藏立方体　|　R：重置\n"
                                "球体与立方体均为镜面环境反射；曝光和环境旋转同时作用于背景及两个物体。"))
        self.cube.toggled.connect(self.view.set_cube)
        self.view.changed.connect(self.sync_cube)
        self.view.status.connect(self.info.setText)
        exposure.valueChanged.connect(lambda value: self.set_parameter("exposure", value))
        rotation.valueChanged.connect(lambda value: self.set_parameter("rotation", value))
        reset.clicked.connect(self.view.reset_camera)
        load.clicked.connect(self.open_panorama)

    def sync_cube(self):
        self.cube.blockSignals(True)
        self.cube.setChecked(self.view.show_cube)
        self.cube.blockSignals(False)

    def set_parameter(self, name, value):
        setattr(self.view, name, value)
        self.view.update()

    def open_panorama(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择全景图", str(self.view.panorama_path.parent), "OpenEXR (*.exr)")
        if path:
            self.view.set_panorama(path)

    def closeEvent(self, event):
        self.view.cleanup()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panorama", type=Path, default=DEFAULT_PANORAMA)
    parser.add_argument("--no-cube", action="store_true")
    parser.add_argument("--screenshot", type=Path, help="保存渲染区截图后退出")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    window = EnvironmentWindow(args.panorama)
    window.cube.setChecked(not args.no_cube)
    window.show()
    window.view.setFocus()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            ok = not window.view.error and window.view.grabFramebuffer().save(str(args.screenshot))
            if window.view.error:
                print(window.view.error, file=sys.stderr)
            window.close()
            app.exit(0 if ok else 1)
        QTimer.singleShot(1200, capture)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
