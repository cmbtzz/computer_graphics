"""将同一张全景图用于模型的镜面环境映射和天空背景。"""

import math
from pathlib import Path

import vtk
from PyQt5.QtWidgets import QCheckBox, QFileDialog, QLabel, QPushButton

from plugins.base_plugin import Base3DPlugin
from plugins.base_texture_ui import CollapsibleSection, ensure_model_settings_scroll


DEFAULT_PANORAMA = Path(__file__).resolve().parents[2] / "实验2" / "meadow_2_4k.exr"

# 环境坐标统一为 Y-up，XZ 为地面。背景和镜面反射共用此方向约定。
PANORAMA_GLSL = """
vec2 worldToPanoramaUV(vec3 worldDirection) {
    vec3 d = normalize(worldDirection);
    const float PI = 3.141592653589793;
    return vec2(atan(d.z, d.x)/(2.0*PI)+0.5,
                asin(clamp(d.y, -1.0, 1.0))/PI+0.5);
}
"""

SKY_VERTEX = """
//VTK::System::Dec
in vec4 vertexMC;
out vec2 screenPosition;
void main() {
    screenPosition = vertexMC.xy;
    gl_Position = vec4(vertexMC.xy, 0.999999, 1.0);
}
"""
SKY_FRAGMENT = """
//VTK::System::Dec
//VTK::Output::Dec
in vec2 screenPosition;
uniform sampler2D actortexture;
uniform vec3 skyForward, skyRight, skyUp;
uniform vec2 skyHalfSpan;
""" + PANORAMA_GLSL + """
void main() {
    vec3 ray = skyForward + screenPosition.x*skyHalfSpan.x*skyRight
                          + screenPosition.y*skyHalfSpan.y*skyUp;
    vec3 color = textureLod(actortexture, worldToPanoramaUV(ray), 0.0).rgb;
    gl_FragData[0] = vec4(pow(max(color,vec3(0.0)),vec3(1.0/2.2)),1.0);
}
"""


def unit(vector):
    length = math.sqrt(sum(value * value for value in vector))
    return tuple(value / length for value in vector)


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def read_environment(path):
    """直接读取 EXR，统一色调映射后生成背景和反射共用的线性浮点纹理。"""
    import numpy as np
    import OpenEXR
    from vtkmodules.util.numpy_support import numpy_to_vtk

    with OpenEXR.File(str(path)) as file:
        channels = file.channels()
        if "RGB" in channels:
            pixels = channels["RGB"].pixels
        elif "RGBA" in channels:
            pixels = channels["RGBA"].pixels[..., :3]
        else:
            pixels = np.stack([channels[channel].pixels for channel in "RGB"], axis=-1)
        pixels = np.array(pixels, dtype=np.float32, copy=True)
    pixels = np.clip(np.nan_to_num(pixels, nan=0., posinf=65504., neginf=0.), 0, 65504)
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("需要 RGB 格式的 EXR 全景图")
    pixels = np.clip((pixels * (2.51 * pixels + .03)) /
                     (pixels * (2.43 * pixels + .59) + .14), 0, 1)
    height, width = pixels.shape[:2]
    array = numpy_to_vtk(np.ascontiguousarray(pixels[::-1].reshape(-1, 3)), deep=True)
    image = vtk.vtkImageData()
    image.SetDimensions(width, height, 1)
    image.GetPointData().SetScalars(array)
    texture = vtk.vtkTexture()
    texture.SetInputData(image)
    texture.SetColorModeToDirectScalars()
    texture.InterpolateOn()
    texture.MipmapOn()
    texture.RepeatOn()
    return texture


class EnvironmentMappingPlugin(Base3DPlugin):
    plugin_cls_name = "environment_mapping"
    plugin_name = "environment_mapping"
    plugin_desc = "全景环境映射"

    def __init__(self, viewer_ctx):
        super().__init__(viewer_ctx)
        self.panorama_path = DEFAULT_PANORAMA
        self.texture = None
        self.actor_state = None
        self.saved_reflections = {}
        self.saved_view_angle = None
        self.mirror_observer = None
        self.background_state = None
        self.background_renderer = vtk.vtkRenderer()
        self.background_renderer.SetLayer(0)
        self.background_renderer.InteractiveOff()
        background_camera = self.background_renderer.GetActiveCamera()
        background_camera.ParallelProjectionOn()
        background_camera.SetParallelScale(1.)
        background_camera.SetPosition(0, 0, 1)
        background_camera.SetFocalPoint(0, 0, 0)
        background_camera.SetClippingRange(.01, 10)
        self.skybox = vtk.vtkActor()
        plane = vtk.vtkPlaneSource()
        plane.SetOrigin(-1, -1, 0)
        plane.SetPoint1(1, -1, 0)
        plane.SetPoint2(-1, 1, 0)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(plane.GetOutputPort())
        self.skybox.SetMapper(mapper)
        self.skybox.GetProperty().LightingOff()
        self.skybox.GetShaderProperty().SetVertexShaderCode(SKY_VERTEX)
        self.skybox.GetShaderProperty().SetFragmentShaderCode(SKY_FRAGMENT)
        self.sky_observer = mapper.AddObserver(vtk.vtkCommand.UpdateShaderEvent, self.update_sky_uniforms)
        self.skybox.PickableOff()
        self.skybox.UseBoundsOff()
        self.background_renderer.AddActor(self.skybox)

    def set_background_layer(self, enabled):
        window = self.ctx.vtk_widget.GetRenderWindow()
        renderer = self.ctx.vtk_renderer
        if enabled and self.background_state is None:
            self.background_state = (renderer.GetLayer(), renderer.GetPreserveColorBuffer(),
                                     window.GetNumberOfLayers())
            renderer.SetLayer(max(1, renderer.GetLayer()))
            renderer.PreserveColorBufferOn()
            window.SetNumberOfLayers(max(window.GetNumberOfLayers(), renderer.GetLayer()+1))
            window.AddRenderer(self.background_renderer)
        elif not enabled and self.background_state is not None:
            layer, preserve, layers = self.background_state
            window.RemoveRenderer(self.background_renderer)
            renderer.SetLayer(layer)
            renderer.SetPreserveColorBuffer(preserve)
            window.SetNumberOfLayers(max(layers, max(r.GetLayer()+1 for r in window.GetRenderers())))
            self.background_state = None

    def configure_texture_edges(self):
        obj = self.texture.GetTextureObject() if self.texture is not None else None
        if obj is not None:
            obj.SetWrapS(vtk.vtkTextureObject.Repeat)
            obj.SetWrapT(vtk.vtkTextureObject.ClampToEdge)
            obj.SendParameters()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def update_sky_uniforms(self, _mapper, _event, program):
        renderer = self.ctx.vtk_renderer
        camera = renderer.GetActiveCamera()
        forward = unit(camera.GetDirectionOfProjection())
        right = unit(cross(forward, camera.GetViewUp()))
        up = cross(right, forward)
        width, height = renderer.GetSize()
        half_fov = math.tan(math.radians(60) / 2)
        program.SetUniform3f("skyForward", forward)
        program.SetUniform3f("skyRight", right)
        program.SetUniform3f("skyUp", up)
        program.SetUniform2f("skyHalfSpan", (half_fov * width / max(1, height), half_fov))
        self.configure_texture_edges()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def update_mirror_uniforms(self, _mapper, _event, program):
        inverse = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(self.ctx.vtk_renderer.GetActiveCamera().GetViewTransformMatrix(), inverse)
        program.SetUniformMatrix("mirrorViewToWorld", inverse)
        self.configure_texture_edges()

    def set_background_view(self, enabled):
        camera = self.ctx.vtk_renderer.GetActiveCamera()
        if enabled:
            if self.saved_view_angle is not None:
                return
            self.saved_view_angle = camera.GetViewAngle()
            angle = 60.
        elif self.saved_view_angle is not None:
            angle = self.saved_view_angle
            self.saved_view_angle = None
        else:
            return
        # 放宽视野时调整相机距离，保留当前模型的大致屏幕大小。
        old_angle = camera.GetViewAngle()
        if not camera.GetParallelProjection():
            distance = camera.GetDistance() * math.tan(math.radians(old_angle)/2) / math.tan(math.radians(angle)/2)
            focal, forward = camera.GetFocalPoint(), camera.GetDirectionOfProjection()
            camera.SetPosition(*(focal[i]-distance*forward[i] for i in range(3)))
        camera.SetViewAngle(angle)
        self.ctx.vtk_renderer.ResetCameraClippingRange()

    def create_ui(self):
        ensure_model_settings_scroll(self.ctx)
        self.plugin_panel = CollapsibleSection("环境映射")
        self.path_label = QLabel(self.panorama_path.name)
        self.path_label.setWordWrap(True)
        self.path_label.setToolTip(str(self.panorama_path))
        self.plugin_panel.body_layout.addWidget(self.path_label)
        self.open_button = QPushButton("选择 EXR 全景图…")
        self.open_button.clicked.connect(self.choose_panorama)
        self.plugin_panel.body_layout.addWidget(self.open_button)
        self.reflection_check = QCheckBox("启用模型镜面反射")
        self.background_check = QCheckBox("显示全景背景")
        self.plugin_panel.body_layout.addWidget(self.reflection_check)
        self.plugin_panel.body_layout.addWidget(self.background_check)
        self.status_label = QLabel("默认使用 meadow_2_4k.exr；背景和模型反射共用同一张全景图。")
        self.status_label.setWordWrap(True)
        self.plugin_panel.body_layout.addWidget(self.status_label)
        self.reflection_check.toggled.connect(self.update_environment)
        self.background_check.toggled.connect(self.update_environment)
        return self.plugin_panel

    def render(self):
        self.ctx.vtk_widget.GetRenderWindow().Render()

    def ensure_texture(self):
        if self.texture is None:
            self.status_label.setText("正在读取 EXR 全景图…")
            self.texture = read_environment(self.panorama_path)
            self.skybox.SetTexture(self.texture)

    def choose_panorama(self):
        path, _ = QFileDialog.getOpenFileName(
            self.ctx.main_window, "选择环境全景图", str(self.panorama_path.parent), "OpenEXR (*.exr)"
        )
        if path:
            self.load_panorama(Path(path))

    def load_panorama(self, path):
        try:
            texture = read_environment(path)
        except Exception as exc:
            self.report_error(exc)
            return False
        self.texture = texture
        self.panorama_path = Path(path)
        self.skybox.SetTexture(texture)
        self.path_label.setText(self.panorama_path.name)
        self.path_label.setToolTip(str(self.panorama_path))
        self.update_environment()
        return True

    def report_error(self, exc):
        message = "全景图加载失败：" + str(exc)
        if isinstance(exc, ImportError):
            message += "；请安装 requirements.txt 中的 OpenEXR 和 numpy。"
        self.status_label.setText(message)
        self.ctx.info_display.append(message)

    def restore_actor(self, sync_lighting=True):
        if self.actor_state is not None:
            actor, prop, texture, mapper, shader = self.actor_state
            if self.mirror_observer is not None:
                actor.GetMapper().RemoveObserver(self.mirror_observer)
                self.mirror_observer = None
            actor.GetShaderProperty().DeepCopy(shader)
            actor.GetProperty().RemoveTexture("mirrorPanorama")
            actor.GetProperty().DeepCopy(prop)
            actor.SetTexture(texture)
            actor.SetMapper(mapper)
            self.actor_state = None
            # 反射开启期间也可能修改光照；恢复普通材质后以当前面板选项为准。
            if sync_lighting and actor is self.ctx.current_actor:
                for plugin in self.ctx.plugins:
                    if getattr(plugin, "plugin_cls_name", "") == "light_control":
                        plugin.update_material()

    def apply_reflection(self):
        actor = self.ctx.current_actor
        if actor is None:
            return
        self.bind_actor(actor)
        if self.actor_state is None:
            prop = vtk.vtkProperty()
            prop.DeepCopy(actor.GetProperty())
            shader = vtk.vtkShaderProperty()
            shader.DeepCopy(actor.GetShaderProperty())
            self.actor_state = (actor, prop, actor.GetTexture(), actor.GetMapper(), shader)
            normals = vtk.vtkPolyDataNormals()
            normals.SetInputData(actor.GetMapper().GetInput())
            normals.ComputePointNormalsOn()
            normals.SplittingOn()
            normals.SetFeatureAngle(45)
            normals.Update()
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(normals.GetOutput())
            mapper.ScalarVisibilityOff()
            actor.SetMapper(mapper)
            uniforms = actor.GetShaderProperty().GetFragmentCustomUniforms()
            uniforms.SetUniformMatrix4x4("mirrorViewToWorld", [1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0., 0.,0.,0.,1.])
            actor.GetShaderProperty().AddFragmentShaderReplacement(
                "//VTK::Light::Dec", True, "//VTK::Light::Dec\n" + PANORAMA_GLSL, False)
            actor.GetShaderProperty().AddFragmentShaderReplacement(
                "//VTK::Light::Impl", True,
                "vec3 incident = cameraParallel == 1 ? vec3(0.0,0.0,-1.0) : normalize(vertexVC.xyz);\n"
                "vec3 reflected = normalize(mat3(mirrorViewToWorld)*reflect(incident, normalize(normalVCVSOutput)));\n"
                "vec3 mirrorColor = textureLod(mirrorPanorama, worldToPanoramaUV(reflected), 0.0).rgb;\n"
                "fragOutput0 = vec4(pow(max(mirrorColor,vec3(0.0)),vec3(1.0/2.2)),1.0);\n", False)
            # 只按反射方向采样，不再将这张全景图按模型 UV 二次相乘。
            actor.GetShaderProperty().AddFragmentShaderReplacement("//VTK::TCoord::Impl", True, "", False)
            self.mirror_observer = mapper.AddObserver(vtk.vtkCommand.UpdateShaderEvent, self.update_mirror_uniforms)
        actor.SetTexture(None)
        prop = actor.GetProperty()
        prop.SetInterpolationToPhong()
        prop.SetColor(1, 1, 1)
        prop.SetTexture("mirrorPanorama", self.texture)

    def update_environment(self, checked=False):
        reflection = self.reflection_check.isChecked()
        background = self.background_check.isChecked()
        if reflection or background:
            try:
                self.ensure_texture()
            except Exception as exc:
                for control in (self.reflection_check, self.background_check):
                    control.blockSignals(True)
                    control.setChecked(False)
                    control.blockSignals(False)
                self.report_error(exc)
                return
        renderer = self.ctx.vtk_renderer
        renderer.SetEnvironmentTexture(self.texture if reflection else None, False)
        # 清晰镜面直接读取原始 4K 全景的第 0 层，避免额外的 cubemap 预过滤。
        renderer.UseImageBasedLightingOff()
        if reflection:
            self.apply_reflection()
        else:
            self.restore_actor()
        self.set_background_layer(background)
        self.set_background_view(background)
        if reflection and self.ctx.current_actor is None:
            message = "环境反射已开启；请在左侧选择模型。"
        elif reflection or background:
            width, height, _ = self.texture.GetInput().GetDimensions()
            message = f"{width} × {height} 原图镜面采样；+Y 为天空，XZ 为地面；背景视野 60°。"
        else:
            message = "环境映射已关闭，保留原模型的贴图和材质。"
        self.status_label.setText(message)
        self.render()

    def on_model_loaded(self, obj_path, actor, polydata):
        # 导入新物体时继承当前选项，但保留场景中其他物体原有的材质。
        self.bind_actor(actor)
        if self.reflection_check.isChecked() or self.background_check.isChecked():
            self.update_environment()

    def bind_actor(self, actor):
        if self.actor_state is not None and self.actor_state[0] is not actor:
            self.saved_reflections[self.actor_state[0]] = (self.actor_state, self.mirror_observer)
            self.actor_state, self.mirror_observer = None, None
        if self.actor_state is None and actor in self.saved_reflections:
            self.actor_state, self.mirror_observer = self.saved_reflections.pop(actor)
        active = {model.actor for model in self.ctx.scene_models}
        for previous in list(self.saved_reflections):
            if previous not in active:
                state, observer = self.saved_reflections.pop(previous)
                if observer is not None:
                    previous.GetMapper().RemoveObserver(observer)

    def on_selection_changed(self, obj_path, actor, polydata):
        self.bind_actor(actor)
        self.reflection_check.blockSignals(True)
        self.reflection_check.setChecked(self.actor_state is not None)
        self.reflection_check.blockSignals(False)

    def on_destroy(self):
        self.restore_actor(sync_lighting=False)
        for state, observer in self.saved_reflections.values():
            self.actor_state, self.mirror_observer = state, observer
            self.restore_actor(sync_lighting=False)
        self.saved_reflections.clear()
        self.skybox.GetMapper().RemoveObserver(self.sky_observer)
        self.set_background_view(False)
        self.set_background_layer(False)
        self.ctx.vtk_renderer.UseImageBasedLightingOff()
        self.ctx.vtk_renderer.SetEnvironmentTexture(None)
