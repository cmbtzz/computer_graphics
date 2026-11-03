"""嵌入查看器中心的 OpenGL 3.3 实时三角网格光追视口。"""
from collections import deque
from pathlib import Path
import time

import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from PyQt5.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QSurfaceFormat
from PyQt5.QtWidgets import QOpenGLWidget
from core.scene_navigation import SceneNavigation
from core.lab4_scene import sync_view_state

SHADERS = Path(__file__).resolve().parents[1]/'shaders/lab4'
VERTEX = '''#version 330 core
out vec2 uv;
void main() { vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);
uv=p; gl_Position=vec4(p*2.0-1.0,0,1); }
'''
DISPLAY = '''#version 330 core
in vec2 uv; out vec4 fragColor; uniform sampler2D image;
void main() { vec3 c=max(texture(image,uv).rgb,vec3(0));
c=clamp((c*(2.51*c+.03))/(c*(2.43*c+.59)+.14),0.0,1.0);
c=mix(c*12.92,1.055*pow(c,vec3(1.0/2.4))-.055,step(vec3(.0031308),c));
fragColor=vec4(c,1); }
'''


class TraceNavigation(SceneNavigation):
    def render(self):
        self.ctx.vtk_renderer.ResetCameraClippingRange()
        self.ctx.vtk_widget.update()


class NavigationContext:
    def __init__(self,ctx,view):
        self.source=ctx
        self.vtk_widget=view
        self.vtk_renderer=ctx.vtk_renderer
        self.main_window=ctx.main_window

    @property
    def current_actor(self):
        return self.source.current_actor


class MeshTraceView(QOpenGLWidget):
    fps_changed = pyqtSignal(float)
    failed = pyqtSignal(str)

    def __init__(self,parent=None,plugin=None):
        super().__init__(parent)
        fmt=QSurfaceFormat(); fmt.setVersion(3,3); fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(0); fmt.setSamples(0)
        self.setFormat(fmt)
        self.setMinimumSize(480,360)
        self.setFocusPolicy(Qt.StrongFocus); self.setAcceptDrops(True)
        self.plugin=plugin
        self.navigation=TraceNavigation(NavigationContext(plugin.ctx,self)) if plugin else None
        self.press_position=None; self.dragged=False
        self.scene=None; self.dirty=True; self.frame_index=0
        self.shadow_samples=1; self.depth=5; self.render_scale=.5
        self.environment_strength=.65
        self.reflection=self.refraction=self.bump=self.shadows=True
        self.max_size=(1152,864)
        self.program=self.display=self.vao=0
        self.textures=[]; self.storage=[]; self.render_buffer=None; self.locations={}
        self.error=''
        self.fps=0.; self.frame_times=deque(maxlen=120); self.last_fps_update=0.; self.pending_frame=False
        self.timer=QTimer(self); self.timer.setInterval(16)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.next_frame); self.timer.start()
        self.frameSwapped.connect(self.record_frame)

    def next_frame(self):
        if not self.isVisible(): return
        if self.plugin is not None: self.plugin.sync_live_scene()
        if not self.error: self.update()

    def record_frame(self):
        if not self.pending_frame: return
        self.pending_frame=False
        now=time.perf_counter()
        if self.frame_times and now-self.frame_times[-1]>1.: self.frame_times.clear()
        self.frame_times.append(now)
        while len(self.frame_times)>2 and now-self.frame_times[0]>1.: self.frame_times.popleft()
        if len(self.frame_times)>1:
            self.fps=(len(self.frame_times)-1)/(now-self.frame_times[0])
            if now-self.last_fps_update>.25:
                self.last_fps_update=now; self.fps_changed.emit(self.fps)

    def set_scene(self,scene):
        self.scene=scene; self.dirty=True; self.error=''; self.restart()

    def restart(self):
        self.update()

    def initializeGL(self):
        try:
            print('Lab4 GPU:',gl.glGetString(gl.GL_VERSION).decode(),gl.glGetString(gl.GL_RENDERER).decode(),flush=True)
            self.program=compileProgram(compileShader(VERTEX,gl.GL_VERTEX_SHADER),
                                         compileShader((SHADERS/'mesh_trace.frag').read_text(encoding='utf-8'),gl.GL_FRAGMENT_SHADER),
                                         validate=False)  # 各类 sampler 在 upload 中分配独立纹理单元后才可验证。
            self.display=compileProgram(compileShader(VERTEX,gl.GL_VERTEX_SHADER),compileShader(DISPLAY,gl.GL_FRAGMENT_SHADER))
            self.vao=int(gl.glGenVertexArrays(1))
            self.context().aboutToBeDestroyed.connect(self.cleanup)
        except Exception as exc: self.fail(exc)

    def fail(self,exc):
        self.error=str(exc); self.failed.emit(self.error)
        print(self.error,file=__import__('sys').stderr,flush=True)

    def release_data(self):
        if self.textures: gl.glDeleteTextures(self.textures)
        if self.storage: gl.glDeleteBuffers(len(self.storage),self.storage)
        self.textures=[]; self.storage=[]

    def cleanup(self):
        if not self.context() or not self.context().isValid(): return
        self.makeCurrent(); self.render_buffer=None; self.release_data()
        for program in (self.program,self.display):
            if program: gl.glDeleteProgram(program)
        if self.vao: gl.glDeleteVertexArrays(1,[self.vao])
        self.program=self.display=self.vao=0; self.locations.clear(); self.dirty=True
        self.doneCurrent()

    def location(self,name,program=None):
        program=program or self.program
        key=(program,name)
        if key not in self.locations: self.locations[key]=gl.glGetUniformLocation(program,name)
        return self.locations[key]

    def uniform(self,name,value):
        loc=self.location(name)
        if name in ('shadowSamples','maxDepth','parallelCamera','useDiffuse','useSpecular','useEnvironment',
                     'useReflection','useRefraction','useBump','useShadows'):
            gl.glUniform1i(loc,int(value))
        elif isinstance(value,(np.ndarray,tuple,list)):
            {2:gl.glUniform2f,3:gl.glUniform3f}[len(value)](loc,*value)
        else: gl.glUniform1f(loc,float(value))

    def upload(self):
        self.release_data()
        scene=self.scene
        max_texels=int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_BUFFER_SIZE))
        for unit,(name,data) in enumerate((('triangles',scene.triangles),('nodes',scene.nodes),('materials',scene.materials))):
            if data.size//4>max_texels: raise RuntimeError(f'{name} 超出显卡纹理缓冲容量，请减少模型面数')
            texture=int(gl.glGenTextures(1)); buffer=int(gl.glGenBuffers(1))
            self.textures.append(texture); self.storage.append(buffer)
            gl.glBindBuffer(gl.GL_TEXTURE_BUFFER,buffer)
            gl.glBufferData(gl.GL_TEXTURE_BUFFER,data.nbytes,data,gl.GL_STATIC_DRAW)
            gl.glActiveTexture(gl.GL_TEXTURE0+unit); gl.glBindTexture(gl.GL_TEXTURE_BUFFER,texture)
            gl.glTexBuffer(gl.GL_TEXTURE_BUFFER,gl.GL_RGBA32F,buffer)
            gl.glUniform1i(self.location(name),unit)
        max_layers=int(gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS))
        for unit,name,data,internal,channels in (
            (3,'heights',scene.heights,gl.GL_R32F,gl.GL_RED),
            (4,'albedos',scene.albedos,gl.GL_RGB32F,gl.GL_RGB)):
            if data.shape[0]>max_layers: raise RuntimeError('纹理数量超过显卡的纹理数组层数')
            texture=int(gl.glGenTextures(1)); self.textures.append(texture)
            gl.glActiveTexture(gl.GL_TEXTURE0+unit); gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY,texture)
            gl.glTexImage3D(gl.GL_TEXTURE_2D_ARRAY,0,internal,256,256,len(data),0,channels,gl.GL_FLOAT,data)
            for p in (gl.GL_TEXTURE_MIN_FILTER,gl.GL_TEXTURE_MAG_FILTER): gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY,p,gl.GL_LINEAR)
            for p in (gl.GL_TEXTURE_WRAP_S,gl.GL_TEXTURE_WRAP_T): gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY,p,gl.GL_REPEAT)
            gl.glUniform1i(self.location(name),unit)
        texture=int(gl.glGenTextures(1)); self.textures.append(texture)
        env=scene.environment if scene.environment is not None else np.ones((1,1,3),np.float32)
        gl.glActiveTexture(gl.GL_TEXTURE5); gl.glBindTexture(gl.GL_TEXTURE_2D,texture)
        gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGB32F,env.shape[1],env.shape[0],0,gl.GL_RGB,gl.GL_FLOAT,env)
        for p in (gl.GL_TEXTURE_MIN_FILTER,gl.GL_TEXTURE_MAG_FILTER): gl.glTexParameteri(gl.GL_TEXTURE_2D,p,gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_WRAP_S,gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_WRAP_T,gl.GL_CLAMP_TO_EDGE)
        gl.glUniform1i(self.location('environmentMap'),5)
        self.dirty=False

    def paintGL(self):
        gl.glClearColor(.08,.10,.14,1); gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        if self.error or not self.program or self.scene is None: return
        try:
            pw,ph=round(self.width()*self.devicePixelRatioF()),round(self.height()*self.devicePixelRatioF())
            scale=min(self.render_scale,self.max_size[0]/pw,self.max_size[1]/ph)
            w,h=max(1,round(pw*scale)),max(1,round(ph*scale))
            if self.render_buffer is None or self.render_buffer.width()!=w or self.render_buffer.height()!=h:
                self.render_buffer=None
                fmt=QOpenGLFramebufferObjectFormat(); fmt.setInternalTextureFormat(gl.GL_RGBA16F)
                self.render_buffer=QOpenGLFramebufferObject(w,h,fmt)
                if not self.render_buffer.isValid(): raise RuntimeError('实时渲染缓冲创建失败')
            gl.glDisable(gl.GL_DEPTH_TEST); gl.glDisable(gl.GL_BLEND); gl.glDisable(gl.GL_FRAMEBUFFER_SRGB)
            gl.glBindVertexArray(self.vao); gl.glUseProgram(self.program)
            if self.dirty: self.upload()
            self.render_buffer.bind(); gl.glViewport(0,0,w,h)
            for unit,texture in enumerate(self.textures):
                target=gl.GL_TEXTURE_BUFFER if unit<3 else gl.GL_TEXTURE_2D_ARRAY if unit<5 else gl.GL_TEXTURE_2D
                gl.glActiveTexture(gl.GL_TEXTURE0+unit); gl.glBindTexture(target,texture)
            if self.plugin is not None: sync_view_state(self.plugin,self.scene)
            cam,light=self.scene.camera,self.scene.light
            values=dict(resolution=(w,h),shadowSamples=self.shadow_samples,maxDepth=self.depth,
                        eye=cam['eye'],target=cam['target'],cameraUp=cam['up'],fieldOfView=cam['fov'],
                        parallelCamera=cam['parallel'],parallelScale=cam['parallelScale'],
                        lightPosition=light['position'],lightColor=light['color'],lightPower=light['power'],
                        lightSize=light['size'],ambientLight=light['ambient'],useDiffuse=light['diffuse'],useSpecular=light['specular'],
                        environmentStrength=self.environment_strength,useEnvironment=self.scene.environment is not None,
                        useReflection=self.reflection,useRefraction=self.refraction,useBump=self.bump,useShadows=self.shadows)
            for name,value in values.items(): self.uniform(name,value)
            gl.glDrawArrays(gl.GL_TRIANGLES,0,3); self.frame_index+=1
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER,self.defaultFramebufferObject()); gl.glViewport(0,0,pw,ph)
            gl.glUseProgram(self.display); gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D,self.render_buffer.texture())
            gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_MIN_FILTER,gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_MAG_FILTER,gl.GL_LINEAR)
            gl.glUniform1i(self.location('image',self.display),0)
            gl.glDrawArrays(gl.GL_TRIANGLES,0,3)
            gl.glBindVertexArray(0); gl.glUseProgram(0)
            self.pending_frame=True
        except Exception as exc: self.fail(exc)


    def mousePressEvent(self,event):
        self.setFocus()
        if event.button()==Qt.RightButton and self.navigation:
            self.press_position=None; self.navigation.begin(event.pos())
        else:
            self.press_position=event.pos(); self.dragged=False
        event.accept()

    def mouseMoveEvent(self,event):
        if self.press_position is not None and (event.pos()-self.press_position).manhattanLength()>4:
            self.dragged=True
        if self.navigation: self.navigation.look(event.pos())
        event.accept()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.RightButton and self.navigation:
            self.navigation.stop()
        elif event.button()==Qt.LeftButton and self.press_position is not None and not self.dragged and self.plugin:
            self.plugin.pick_in_view(event.pos(),self.width(),self.height())
        self.press_position=None; event.accept()

    def keyPressEvent(self,event):
        if self.navigation: self.navigation.key_press(event)
        event.accept()

    def keyReleaseEvent(self,event):
        if self.navigation: self.navigation.key_release(event)
        event.accept()

    def wheelEvent(self,event):
        if self.navigation: self.navigation.wheel(event.angleDelta().y()/120)
        event.accept()

    def focusOutEvent(self,event):
        if self.navigation: self.navigation.stop()
        super().focusOutEvent(event)

    def hideEvent(self,event):
        if self.navigation: self.navigation.stop()
        super().hideEvent(event)

    def dragEnterEvent(self,event):
        if self.plugin and self.plugin.ctx.vtk_widget.obj_paths(event):
            event.setDropAction(Qt.CopyAction); event.accept()
        else: event.ignore()

    def dragMoveEvent(self,event):
        self.dragEnterEvent(event)

    def dropEvent(self,event):
        paths=self.plugin.ctx.vtk_widget.obj_paths(event) if self.plugin else []
        if paths:
            self.plugin.ctx.main_window.import_dropped_models(paths)
            self.plugin.focus_panel()
            event.setDropAction(Qt.CopyAction); event.accept()
        else: event.ignore()
