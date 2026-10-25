"""实验四编程任务2：花瓶模型上的 GLSL 高度图凹凸映射。"""

import argparse
import ctypes
import math
from pathlib import Path
import sys
import time

import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImage, QSurfaceFormat
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QOpenGLWidget, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

SHADER_DIR = Path(__file__).resolve().parent / "shaders"
PATTERNS = ("雕刻花纹", "错缝砖纹", "流动波纹", "细密颗粒")


def make_height_map(pattern, size=512):
    """生成周期性浮点高度数据，避免 8 位量化被导数放大成条纹。"""
    v, u = np.mgrid[0:size, 0:size].astype(np.float64) / size
    if pattern == 0:
        h = .5 + .30*np.cos(2*np.pi*u)*np.cos(2*np.pi*v)
        h += .12*np.cos(4*np.pi*u)*np.cos(4*np.pi*v)
    elif pattern == 1:
        row = np.floor(v*2)
        x = (u + row*.5) % 1
        y = (v*2) % 1
        edge = np.minimum(np.minimum(x,1-x), np.minimum(y,1-y))
        blend = np.clip((edge-.025)/.10,0,1)
        h = .15 + .70*blend*blend*(3-2*blend)
    elif pattern == 2:
        h = .5 + .38*np.sin(2*np.pi*(u + .20*np.sin(2*np.pi*v)))
    else:
        h = .5 + .18*np.sin(2*np.pi*(7*u+3*v))*np.cos(2*np.pi*(2*u-5*v))
        h += .12*np.cos(2*np.pi*(13*u+11*v))
    return np.ascontiguousarray(np.clip(h,0,1),np.float32)


def load_height_map(path):
    """QImage 兼容中文路径；第一行翻转成 OpenGL 的 v=0。"""
    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"无法读取高度图：{path}")
    if image.width() > 4096 or image.height() > 4096:
        image = image.scaled(4096,4096,Qt.KeepAspectRatio,Qt.SmoothTransformation)
    image = image.convertToFormat(QImage.Format_Grayscale8)
    pointer = image.bits()
    pointer.setsize(image.byteCount())
    pixels = np.frombuffer(pointer,np.uint8).reshape(image.height(),image.bytesPerLine())
    return np.ascontiguousarray(pixels[::-1,:image.width()].astype(np.float32)/255)


def make_mesh(model=0, segments=128, rings=96):
    """顶点布局：位置3、法线3、UV2、dP/du3、dP/dv3，共14个 float。

    默认花瓶由外壁、内壁、上下底面及瓶口环构成；保留 UV 接缝的重复顶点。
    几何始终不受高度图影响，可直接比较轮廓和逐片元法线扰动。
    """
    vertices, indices = [], []

    def surface(p, n, tex, pu, pv, reverse=False):
        offset = sum(len(part) for part in vertices)
        rows, cols = p.shape[:2]
        vertices.append(np.concatenate((p,n,tex,pu,pv),axis=-1).reshape(-1,14))
        for j in range(rows-1):
            for i in range(cols-1):
                a = offset+j*cols+i
                faces = [(a,a+cols,a+1),(a+1,a+cols,a+cols+1)]
                indices.extend((c,b,a) if reverse else (a,b,c) for a,b,c in faces)

    v, u = np.meshgrid(np.linspace(0,1,rings+1),np.linspace(0,1,segments+1),indexing="ij")
    theta = u*2*np.pi
    tex = np.stack((u,v),axis=-1)
    if model == 1:
        phi = v*np.pi
        p = 1.65*np.stack((np.sin(phi)*np.cos(theta), np.cos(phi), np.sin(phi)*np.sin(theta)),axis=-1)
        pu = 1.65*2*np.pi*np.stack((-np.sin(phi)*np.sin(theta),0*u,np.sin(phi)*np.cos(theta)),axis=-1)
        pv = 1.65*np.pi*np.stack((np.cos(phi)*np.cos(theta),-np.sin(phi),np.cos(phi)*np.sin(theta)),axis=-1)
        surface(p,p/1.65,tex,pu,pv,True)
    else:
        def radius(y):
            return .43 + .68*np.exp(-((y+.50)/1.02)**2) + .16*np.exp(-((y-1.76)/.24)**2)

        for inner in (False,True):
            bottom = -1.64 if inner else -1.80
            span = 1.80-bottom
            y = bottom+v*span
            r = radius(y)-(.085 if inner else 0)
            slope = (radius(y+1e-4)-radius(y-1e-4))/2e-4
            p = np.stack((r*np.cos(theta),y,r*np.sin(theta)),axis=-1)
            pu = 2*np.pi*np.stack((-r*np.sin(theta),0*u,r*np.cos(theta)),axis=-1)
            pv = span*np.stack((slope*np.cos(theta),np.ones_like(u),slope*np.sin(theta)),axis=-1)
            n = np.stack((np.cos(theta),-slope,np.sin(theta)),axis=-1)
            n /= np.linalg.norm(n,axis=-1,keepdims=True)
            if inner:
                n = -n
            surface(p,n,tex,pu,pv,inner)

        # 圆盘用径向参数生成，但使用平面 UV 和与之匹配的解析切向导数。
        radial, tu = np.meshgrid(np.linspace(0,1,9),np.linspace(0,1,segments+1),indexing="ij")
        angle = tu*2*np.pi
        for y, inner in ((-1.80,False),(-1.64,True)):
            r = float(radius(y))-(.085 if inner else 0)
            x,z = radial*r*np.cos(angle),radial*r*np.sin(angle)
            p = np.stack((x,np.full_like(x,y),z),axis=-1)
            n = np.zeros_like(p); n[...,1] = 1 if inner else -1
            pu,pv = np.zeros_like(p),np.zeros_like(p)
            pu[...,0]=2*r; pv[...,2]=2*r
            surface(p,n,np.stack((x/(2*r)+.5,z/(2*r)+.5),axis=-1),pu,pv,inner)
        r_outer = float(radius(1.80))
        rr = r_outer-.085+radial*.085
        p = np.stack((rr*np.cos(angle),np.full_like(rr,1.80),rr*np.sin(angle)),axis=-1)
        n = np.zeros_like(p); n[...,1]=1
        # 瓶口采用平面 UV，避免把整张贴图挤进 0.085 单位的薄环。
        pu,pv = np.zeros_like(p),np.zeros_like(p)
        pu[...,0]=2*r_outer; pv[...,2]=2*r_outer
        lip_uv=np.stack((p[...,0]/(2*r_outer)+.5,p[...,2]/(2*r_outer)+.5),axis=-1)
        surface(p,n,lip_uv,pu,pv,True)
    return (np.ascontiguousarray(np.concatenate(vertices),np.float32),
            np.ascontiguousarray(indices,np.uint32).reshape(-1))


def perspective(fov, aspect, near=.1, far=100.):
    f = 1/math.tan(math.radians(fov)/2)
    return np.array([[f/aspect,0,0,0],[0,f,0,0],
                     [0,0,(far+near)/(near-far),2*far*near/(near-far)],
                     [0,0,-1,0]],np.float32)


def look_at(eye):
    forward = -eye/np.linalg.norm(eye)
    right = np.cross(forward,[0,1,0]); right /= np.linalg.norm(right)
    up = np.cross(right,forward)
    matrix = np.eye(4,dtype=np.float32)
    matrix[:3,:3] = np.stack((right,up,-forward))
    matrix[:3,3] = -matrix[:3,:3]@eye
    return matrix


class BumpView(QOpenGLWidget):
    failed = pyqtSignal(str)
    rendered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560,440)
        self.setFocusPolicy(Qt.StrongFocus)
        self.program = self.vao = self.vbo = self.ebo = self.texture = 0
        self.mesh_dirty = self.texture_dirty = True
        self.locations = {}
        self.error = ""
        self.frame_serial = 0
        self.last_mouse = None
        self.reset_parameters()
        self.left_label = QLabel(self)
        self.right_label = QLabel(self)
        for label in (self.left_label,self.right_label):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color:#e5edf9; background:rgba(15,23,38,190); padding:8px; border-radius:6px;")
        self.update_labels()

    def reset_parameters(self):
        self.model = 0
        self.pattern = 0
        self.height_pixels = make_height_map(0)
        self.height_name = PATTERNS[0]
        self.mesh_dirty = self.texture_dirty = True
        self.strength = .10
        self.tiling = [6.,4.]
        self.bump_enabled = True
        self.compare = True
        self.tint = False
        self.mode = 0
        self.color = [.10,.48,.35]
        self.shininess = 90.
        self.specular = .65
        self.light = [-3.0,3.5,4.0]
        self.light_power = 1.4
        self.reset_camera()

    def reset_camera(self):
        self.yaw,self.pitch,self.distance = 24.,22.,7.2
        self.update()

    def update_labels(self):
        self.left_label.setVisible(self.compare)
        self.left_label.setText("原始法线 · 关闭凹凸映射")
        self.right_label.setText("高度图扰动法线 · 凹凸映射" if self.bump_enabled else "关闭凹凸映射")
        width = self.width()
        if self.compare:
            self.left_label.setGeometry(12,14,max(1,width//2-24),38)
            self.right_label.setGeometry(width//2+12,14,max(1,width//2-24),38)
        else:
            self.right_label.setGeometry(12,14,max(1,width-24),38)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.update_labels()

    def initializeGL(self):
        try:
            print(f"OpenGL {gl.glGetString(gl.GL_VERSION).decode()}; {gl.glGetString(gl.GL_RENDERER).decode()}",flush=True)
            self.program = compileProgram(
                compileShader((SHADER_DIR/"bump.vert").read_text(encoding="utf-8"),gl.GL_VERTEX_SHADER),
                compileShader((SHADER_DIR/"bump.frag").read_text(encoding="utf-8"),gl.GL_FRAGMENT_SHADER))
            self.vao = int(gl.glGenVertexArrays(1))
            self.vbo,self.ebo = map(int,gl.glGenBuffers(2))
            self.texture = int(gl.glGenTextures(1))
            self.context().aboutToBeDestroyed.connect(self.cleanup)
        except Exception as exc:
            self.report_error(exc)

    def report_error(self,exc):
        self.error = str(exc)
        self.failed.emit(self.error)
        print(self.error,file=sys.stderr,flush=True)

    def cleanup(self):
        if not self.context() or not self.context().isValid():
            return
        self.makeCurrent()
        if self.program: gl.glDeleteProgram(self.program)
        if self.vao: gl.glDeleteVertexArrays(1,[self.vao])
        if self.vbo: gl.glDeleteBuffers(2,[self.vbo,self.ebo])
        if self.texture: gl.glDeleteTextures([self.texture])
        self.program=self.vao=self.vbo=self.ebo=self.texture=0
        self.mesh_dirty=self.texture_dirty=True
        self.locations.clear()
        self.doneCurrent()

    def uniform(self,name,value):
        if name not in self.locations:
            self.locations[name] = gl.glGetUniformLocation(self.program,name)
        location = self.locations[name]
        if isinstance(value,np.ndarray) and value.shape == (4,4):
            gl.glUniformMatrix4fv(location,1,gl.GL_TRUE,np.ascontiguousarray(value))
        elif name in ("heightMap","tintByHeight","displayMode","enableBump"):
            gl.glUniform1i(location,int(value))
        elif isinstance(value,(list,tuple,np.ndarray)):
            {2:gl.glUniform2f,3:gl.glUniform3f}[len(value)](location,*value)
        else:
            gl.glUniform1f(location,value)

    def upload_mesh(self):
        vertices,indices = make_mesh(self.model)
        self.index_count = len(indices)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER,vertices.nbytes,vertices,gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER,self.ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER,indices.nbytes,indices,gl.GL_STATIC_DRAW)
        for location,size,offset in ((0,3,0),(1,3,3),(2,2,6),(3,3,8),(4,3,11)):
            gl.glEnableVertexAttribArray(location)
            gl.glVertexAttribPointer(location,size,gl.GL_FLOAT,False,14*4,ctypes.c_void_p(offset*4))
        self.mesh_dirty = False

    def upload_texture(self):
        height,width = self.height_pixels.shape
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D,self.texture)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT,1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_R32F,width,height,0,gl.GL_RED,gl.GL_FLOAT,self.height_pixels)
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_WRAP_S,gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_WRAP_T,gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_MIN_FILTER,gl.GL_LINEAR_MIPMAP_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_MAG_FILTER,gl.GL_LINEAR)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT,4)
        self.texture_dirty = False

    def paintGL(self):
        gl.glClearColor(.055,.078,.12,1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT|gl.GL_DEPTH_BUFFER_BIT)
        if self.error or not self.program:
            return
        try:
            if self.mesh_dirty: self.upload_mesh()
            if self.texture_dirty: self.upload_texture()
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_CULL_FACE)
            gl.glDisable(gl.GL_BLEND)
            gl.glDisable(gl.GL_FRAMEBUFFER_SRGB)
            gl.glUseProgram(self.program)
            gl.glBindVertexArray(self.vao)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D,self.texture)
            yaw,pitch = math.radians(self.yaw),math.radians(self.pitch)
            eye = self.distance*np.array([math.cos(pitch)*math.sin(yaw),math.sin(pitch),math.cos(pitch)*math.cos(yaw)],np.float32)
            for name,value in {
                "heightMap":0,"tiling":self.tiling,"bumpStrength":self.strength,
                "shininess":self.shininess,"specularStrength":self.specular,
                "tintByHeight":self.tint,"displayMode":self.mode,"eye":eye,
                "lightPosition":self.light,"materialColor":self.color,"lightPower":self.light_power,
            }.items(): self.uniform(name,value)
            width,height = round(self.width()*self.devicePixelRatioF()),round(self.height()*self.devicePixelRatioF())
            pane = width//2 if self.compare else width
            self.uniform("viewProjection",perspective(42.,pane/height)@look_at(eye))
            for x,enabled in ([(0,False),(width-pane,self.bump_enabled)] if self.compare else [(0,self.bump_enabled)]):
                gl.glViewport(x,0,pane,height)
                self.uniform("enableBump",enabled)
                gl.glDrawElements(gl.GL_TRIANGLES,self.index_count,gl.GL_UNSIGNED_INT,None)
            gl.glBindVertexArray(0)
            gl.glUseProgram(0)
            self.frame_serial += 1
            self.rendered.emit()
        except Exception as exc:
            self.report_error(exc)

    def mousePressEvent(self,event):
        self.setFocus()
        self.last_mouse = event.pos()

    def mouseMoveEvent(self,event):
        if self.last_mouse is None: return
        delta = event.pos()-self.last_mouse
        self.last_mouse=event.pos()
        if event.buttons() & Qt.LeftButton:
            self.yaw += delta.x()*.4
            self.pitch = max(-75.,min(75.,self.pitch+delta.y()*.35))
        elif event.buttons() & Qt.RightButton:
            self.distance=max(3.,min(16.,self.distance+delta.y()*.03))
        self.update()

    def wheelEvent(self,event):
        self.distance=max(3.,min(16.,self.distance*math.exp(-event.angleDelta().y()/1200)))
        self.update()

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Space,Qt.Key_Home): self.reset_camera()
        else: super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实验四 · 编程任务2 · 花瓶凹凸映射")
        self.resize(1360,900)
        self.view=BumpView()
        self.controls={}
        self.syncing=False
        panel=QWidget()
        self.panel=QVBoxLayout(panel)
        title=QLabel("高度图凹凸映射")
        title.setStyleSheet("font-size:21px; font-weight:600; padding:8px 0;")
        self.panel.addWidget(title)
        hint=QLabel("左：原始表面　右：扰动法线\n同一模型、光源和颜色，比较光照差异。\n左键旋转 / 滚轮缩放 / 空格复位视角")
        hint.setWordWrap(True)
        self.panel.addWidget(hint)
        form=self.group("模型与高度图")
        self.model_combo=QComboBox()
        self.model_combo.addItems(["花瓶（含内壁与瓶口）","球体"])
        self.model_combo.currentIndexChanged.connect(self.change_model)
        form.addRow("三维模型",self.model_combo)
        self.pattern_combo=QComboBox()
        self.pattern_combo.addItems(PATTERNS)
        self.pattern_combo.setPlaceholderText("自定义高度图")
        self.pattern_combo.currentIndexChanged.connect(self.change_pattern)
        form.addRow("内置高度图",self.pattern_combo)
        load=QPushButton("加载自定义高度图…")
        load.clicked.connect(self.open_height)
        form.addRow(load)
        self.texture_info=QLabel()
        self.texture_info.setWordWrap(True)
        form.addRow(self.texture_info)
        self.preview=QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        form.addRow(self.preview)
        form=self.group("映射与显示")
        self.spin(form,"strength","凹凸强度",-.20,.20,.01,3)
        self.spin(form,"tiling_0","U 方向重复",1.,20.,1.)
        self.spin(form,"tiling_1","V 方向重复",1.,20.,1.)
        for key,label in (("bump_enabled","开启凹凸映射"),("compare","左右并排对照"),("tint","附加高度颜色（默认关闭）")):
            checkbox=QCheckBox(label)
            checkbox.toggled.connect(lambda value,k=key:self.change(k,value))
            self.controls[key]=checkbox
            form.addRow(checkbox)
        self.mode_combo=QComboBox()
        self.mode_combo.addItems(["正常光照","法线可视化","高度图可视化"])
        self.mode_combo.currentIndexChanged.connect(lambda value:self.change("mode",value))
        form.addRow("显示模式",self.mode_combo)
        form=self.group("材质与光源")
        self.spin(form,"shininess","高光指数",2.,256.,4.)
        self.spin(form,"specular","高光强度",0.,2.,.05)
        self.color_button=QPushButton("选择材质颜色")
        self.color_button.clicked.connect(self.choose_color)
        form.addRow(self.color_button)
        for axis,label in enumerate(("X","Y","Z")):
            self.spin(form,f"light_{axis}",f"光源 {label}",-8.,8.,.25)
        self.spin(form,"light_power","光源亮度",0.,5.,.1)
        buttons=QHBoxLayout()
        reset=QPushButton("重置全部"); reset.clicked.connect(self.reset_all)
        save=QPushButton("保存渲染图"); save.clicked.connect(self.save_render)
        buttons.addWidget(reset); buttons.addWidget(save)
        self.panel.addLayout(buttons)
        self.status=QLabel()
        self.status.setWordWrap(True)
        self.panel.addWidget(self.status)
        self.panel.addStretch()
        scroll=QScrollArea()
        scroll.setWidgetResizable(True); scroll.setWidget(panel)
        scroll.setMinimumWidth(320); scroll.setMaximumWidth(370)
        root=QWidget(); row=QHBoxLayout(root)
        row.setContentsMargins(8,8,8,8)
        row.addWidget(self.view,1); row.addWidget(scroll)
        self.setCentralWidget(root)
        self.setStyleSheet("QGroupBox {font-weight:600; margin-top:10px; padding-top:12px;}"
                           "QDoubleSpinBox,QComboBox {min-height:23px;} QPushButton {min-height:28px;}")
        self.view.failed.connect(self.status.setText)
        self.sync_controls()

    def group(self,title):
        group=QGroupBox(title); form=QFormLayout(group)
        self.panel.addWidget(group)
        return form

    def spin(self,form,key,label,low,high,step,decimals=2):
        widget=QDoubleSpinBox()
        widget.setDecimals(decimals); widget.setRange(low,high); widget.setSingleStep(step)
        widget.setKeyboardTracking(False)
        widget.valueChanged.connect(lambda value,k=key:self.change(k,value))
        self.controls[key]=widget; form.addRow(label,widget)

    def change(self,key,value):
        if self.syncing: return
        if key.startswith("tiling_"): self.view.tiling[int(key[-1])]=value
        elif key.startswith("light_") and key[-1].isdigit(): self.view.light[int(key[-1])]=value
        else: setattr(self.view,key,value)
        self.view.update_labels(); self.view.update()

    def change_model(self,index):
        if not self.syncing:
            self.view.model=index; self.view.mesh_dirty=True; self.view.update()
            self.update_status()

    def change_pattern(self,index):
        if not self.syncing and 0 <= index < len(PATTERNS):
            self.view.pattern=index
            self.view.height_pixels=make_height_map(index)
            self.view.height_name=PATTERNS[index]
            self.view.texture_dirty=True; self.view.update()
            self.refresh_preview()

    def refresh_preview(self):
        from PyQt5.QtGui import QPixmap
        pixels=self.view.height_pixels
        h,w=pixels.shape
        # copy 使 QImage 拥有自己的数据，避免临时 bytes 被释放。
        image=QImage((np.clip(pixels,0,1)*255).astype(np.uint8).tobytes(),w,h,w,QImage.Format_Grayscale8).copy().mirrored(False,True)
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(200,92,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.texture_info.setText(f"{self.view.height_name}\n{w} × {h} · 灰度高度数据")

    def update_status(self):
        self.status.setText("GLSL 3.30 · 高度图中心差分\n仅扰动逐片元法线，模型几何与轮廓不变。")

    def sync_controls(self):
        self.syncing=True
        for key,widget in self.controls.items():
            if key.startswith("tiling_"): value=self.view.tiling[int(key[-1])]
            elif key.startswith("light_") and key[-1].isdigit(): value=self.view.light[int(key[-1])]
            else: value=getattr(self.view,key)
            widget.setChecked(value) if isinstance(widget,QCheckBox) else widget.setValue(value)
        self.model_combo.setCurrentIndex(self.view.model)
        self.pattern_combo.setCurrentIndex(self.view.pattern)
        self.mode_combo.setCurrentIndex(self.view.mode)
        color=QColor.fromRgbF(*self.view.color).name()
        self.color_button.setText(f"材质颜色  {color}")
        self.color_button.setStyleSheet(f"border:2px solid {color};")
        self.syncing=False
        self.refresh_preview(); self.update_status(); self.view.update_labels()

    def open_height(self):
        path,_=QFileDialog.getOpenFileName(self,"选择灰度高度图","","图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;所有文件 (*)")
        if not path: return
        try:
            self.view.height_pixels=load_height_map(path)
            self.view.height_name=Path(path).name
            self.view.pattern=-1
            self.view.texture_dirty=True; self.view.update(); self.sync_controls()
        except ValueError as exc: QMessageBox.warning(self,"加载失败",str(exc))

    def choose_color(self):
        color=QColorDialog.getColor(QColor.fromRgbF(*self.view.color),self,"选择材质颜色")
        if color.isValid():
            self.view.color=[color.redF(),color.greenF(),color.blueF()]
            self.sync_controls(); self.view.update()

    def reset_all(self):
        self.view.reset_parameters(); self.sync_controls()

    def save_render(self):
        path,_=QFileDialog.getSaveFileName(self,"保存凹凸映射对照图","bump_mapping.png","PNG 图片 (*.png)")
        if path and not self.view.grabFramebuffer().save(path):
            QMessageBox.warning(self,"保存失败",f"无法写入：{path}")

    def closeEvent(self,event):
        self.view.cleanup()
        super().closeEvent(event)


def pixels(image):
    image=image.convertToFormat(QImage.Format_RGBA8888)
    ptr=image.bits(); ptr.setsize(image.byteCount())
    return np.frombuffer(ptr,np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)[:,:image.width(),:3].copy()


class Verification:
    def __init__(self,window,app,args):
        self.window,self.app,self.args=window,app,args
        self.started=time.monotonic(); self.stage=0; self.baseline=None
        self.required_serial=window.view.frame_serial+1
        self.timer=QTimer(window); self.timer.timeout.connect(self.poll); self.timer.start(100)
        window.view.update()

    def poll(self):
        view=self.window.view
        try:
            if view.error: raise RuntimeError(view.error)
            if time.monotonic()-self.started>60: raise RuntimeError("60 秒内未完成 OpenGL 渲染")
            if view.frame_serial<self.required_serial: return
            image=view.grabFramebuffer()
            rgb=pixels(image).astype(np.float32)
            half=rgb.shape[1]//2
            difference=float(np.mean(np.abs(rgb[:,:half]-rgb[:,-half:])))
            if self.args.self_test and self.stage<9:
                if self.stage==0:
                    if difference<1.0: raise AssertionError(f"开启凹凸映射未产生可见差异：{difference}")
                    self.baseline=rgb
                    print(f"PASS bump enabled: pane difference {difference:.3f}",flush=True)
                    view.strength=0
                elif self.stage==1:
                    if difference>.01: raise AssertionError(f"零强度与原表面不一致：{difference}")
                    print("PASS zero strength: identical geometry and shading",flush=True)
                    view.strength=.10; view.bump_enabled=False
                elif self.stage==2:
                    if difference>.01: raise AssertionError("关闭映射后左右不一致")
                    print("PASS disabled: identical panes",flush=True)
                    view.bump_enabled=True; view.height_pixels=np.full((64,64),.5,np.float32); view.texture_dirty=True
                elif self.stage==3:
                    if difference>.01: raise AssertionError("常量高度图产生了虚假的凹凸")
                    print("PASS constant height: zero normal perturbation",flush=True)
                    view.height_pixels=make_height_map(0); view.texture_dirty=True; view.strength=-.10
                elif self.stage==4:
                    delta=float(np.mean(np.abs(rgb-self.baseline)))
                    if delta<.2: raise AssertionError("负强度未改变凹凸方向")
                    print(f"PASS inverted relief: difference {delta:.3f}",flush=True)
                    view.strength=.10; view.mode=1
                elif self.stage==5:
                    if difference<1.: raise AssertionError("法线可视化未显示扰动")
                    print(f"PASS normal visualization: pane difference {difference:.3f}",flush=True)
                    view.mode=0; view.light=[3.,-1.,2.]
                elif self.stage==6:
                    delta=float(np.mean(np.abs(rgb-self.baseline)))
                    if delta<1.: raise AssertionError("移动光源未改变照明")
                    print(f"PASS light position: difference {delta:.3f}",flush=True)
                    view.light=[-3.,3.5,4.]; view.height_pixels=make_height_map(1); view.texture_dirty=True
                elif self.stage==7:
                    delta=float(np.mean(np.abs(rgb-self.baseline)))
                    if delta<.2: raise AssertionError("更换高度图未改变渲染")
                    print(f"PASS height texture: difference {delta:.3f}",flush=True)
                    view.model=1; view.mesh_dirty=True
                else:
                    if difference<1.: raise AssertionError("球体凹凸映射无效")
                    print(f"PASS second model: pane difference {difference:.3f}",flush=True)
                    view.reset_parameters()
                self.stage+=1; self.window.sync_controls()
                self.required_serial=view.frame_serial+1; view.update()
                return
            if self.args.screenshot:
                path=Path(self.args.screenshot).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
                if not image.save(str(path)): raise RuntimeError(f"无法保存：{path}")
                if not self.window.grab().save(str(path.with_name(path.stem+"_window.png"))):
                    raise RuntimeError("无法保存窗口截图")
                print(f"Saved: {path}",flush=True)
            if self.args.self_test: print("All bump mapping GPU checks passed.",flush=True)
            self.timer.stop(); self.window.close(); self.app.exit(0)
        except Exception as exc:
            print(f"Verification failed: {exc}",file=sys.stderr,flush=True)
            self.timer.stop(); self.window.close(); self.app.exit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshot",metavar="PNG",help="保存渲染图与窗口图并退出")
    parser.add_argument("--self-test",action="store_true",help="执行真实 GPU 渲染对照检查")
    parser.add_argument("--height-map",metavar="IMAGE",help="启动时加载自定义高度图")
    parser.add_argument("--size",default="1360x900",help="窗口大小，默认 1360x900")
    args=parser.parse_args()
    try:
        width,height=map(int,args.size.lower().split("x"))
        if width<1000 or height<640: raise ValueError
    except ValueError: parser.error("--size 需要至少 1000x640 的宽x高")
    if args.self_test and args.height_map: parser.error("自检使用内置标准高度图，请单独运行 --height-map")
    QApplication.setAttribute(Qt.AA_UseDesktopOpenGL)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    fmt=QSurfaceFormat(); fmt.setVersion(3,3); fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24); fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    app=QApplication(sys.argv[:1]); app.setFont(QFont("Microsoft YaHei",9))
    window=MainWindow(); window.resize(width,height)
    if args.height_map:
        try:
            window.view.height_pixels=load_height_map(args.height_map)
            window.view.height_name=Path(args.height_map).name
            window.view.pattern=-1
            window.sync_controls()
        except ValueError as exc: parser.error(str(exc))
    window.show()
    if args.screenshot or args.self_test: window.verification=Verification(window,app,args)
    return app.exec_()


if __name__=="__main__":
    sys.exit(main())
