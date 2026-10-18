"""对当前模型的普通贴图设置六种真实的 OpenGL 缩小过滤方式。"""

import vtk
from PyQt5.QtWidgets import QComboBox, QLabel

from plugins.base_plugin import Base3DPlugin
from plugins.base_texture_ui import CollapsibleSection, ensure_model_settings_scroll


FILTERS = (
    ("GL_NEAREST", vtk.vtkTextureObject.Nearest, vtk.vtkTextureObject.Nearest,
     "原图最近邻：近处有像素块，远处容易走样和闪烁。"),
    ("GL_LINEAR", vtk.vtkTextureObject.Linear, vtk.vtkTextureObject.Linear,
     "原图双线性：单层内插值，远处仍可能走样。"),
    ("GL_NEAREST_MIPMAP_NEAREST", vtk.vtkTextureObject.NearestMipmapNearest,
     vtk.vtkTextureObject.Nearest, "最近 Mipmap 层，层内最近邻。"),
    ("GL_LINEAR_MIPMAP_NEAREST", vtk.vtkTextureObject.LinearMipmapNearest,
     vtk.vtkTextureObject.Linear, "最近 Mipmap 层，层内双线性；层间可能跳变。"),
    ("GL_NEAREST_MIPMAP_LINEAR", vtk.vtkTextureObject.NearestMipmapLinear,
     vtk.vtkTextureObject.Nearest, "相邻层线性插值，层内最近邻。"),
    ("GL_LINEAR_MIPMAP_LINEAR", vtk.vtkTextureObject.LinearMipmapLinear,
     vtk.vtkTextureObject.Linear, "三线性过滤：层内双线性、层间线性，减轻远处走样。"),
)


class MipmapPlugin(Base3DPlugin):
    plugin_cls_name = "mipmap_mapping"
    plugin_name = "mipmap_mapping"
    plugin_desc = "Mipmap 过滤设置"

    def __init__(self, viewer_ctx):
        super().__init__(viewer_ctx)
        self.filter_index = 5
        self.observer = None

    def create_ui(self):
        ensure_model_settings_scroll(self.ctx)
        self.plugin_panel = CollapsibleSection("Mipmap 设置")
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([item[0] for item in FILTERS])
        self.filter_combo.setCurrentIndex(self.filter_index)
        self.filter_combo.setMinimumContentsLength(12)
        self.filter_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.plugin_panel.body_layout.addWidget(self.filter_combo)
        self.description = QLabel(FILTERS[self.filter_index][3])
        self.description.setWordWrap(True)
        self.plugin_panel.body_layout.addWidget(self.description)
        help_label = QLabel("作用于上方选择的普通贴图；滚轮拉远模型，比较纹理细节与闪烁。")
        help_label.setWordWrap(True)
        self.plugin_panel.body_layout.addWidget(help_label)
        self.filter_combo.currentIndexChanged.connect(self.set_filter)
        window = self.ctx.vtk_widget.GetRenderWindow()
        self.observer = window.AddObserver("StartEvent", self.prepare_texture)
        return self.plugin_panel

    def set_filter(self, index):
        self.filter_index = index
        self.description.setText(FILTERS[index][3])
        self.ctx.vtk_widget.GetRenderWindow().Render()

    def prepare_texture(self, window, event):
        actor = self.ctx.current_actor
        texture = actor.GetTexture() if actor is not None else None
        if texture is None or texture.GetInput() is None:
            return
        # 上传完整 Mipmap 后设置底层纹理对象，完整支持六种组合。
        # 每帧检查也能覆盖窗口上下文重建；未修改的纹理不会重复上传。
        window.MakeCurrent()
        texture.InterpolateOn()
        texture.MipmapOn()
        texture.Load(self.ctx.vtk_renderer)
        obj = texture.GetTextureObject()
        if obj is not None:
            _, min_filter, mag_filter, _ = FILTERS[self.filter_index]
            obj.SetMinificationFilter(min_filter)
            obj.SetMagnificationFilter(mag_filter)
            obj.SendParameters()
        texture.PostRender(self.ctx.vtk_renderer)

    def on_destroy(self):
        if self.observer is not None:
            self.ctx.vtk_widget.GetRenderWindow().RemoveObserver(self.observer)
            self.observer = None
