"""普通贴图选择，作为模型设置中第一个纵向分组。"""

import os

import vtk
from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QGridLayout, QLabel, QPushButton, QWidget

from plugins.base_plugin import Base3DPlugin
from plugins.base_texture_ui import CollapsibleSection, ensure_model_settings_scroll


class TextureGrid(QWidget):
    resized = pyqtSignal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class TexturePlugin(Base3DPlugin):
    plugin_cls_name = "texture_mapping"
    plugin_name = "texture_mapping"
    plugin_desc = "普通纹理贴图"

    def __init__(self, viewer_ctx):
        super().__init__(viewer_ctx)
        self.selected_texture_path = None
        self.selected_texture_btn = None
        self.texture = None
        self.buttons = {}
        self.actor_paths = {}
        self.texture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/texture"))
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.resize_thumbnails)

    def create_ui(self):
        scroll = ensure_model_settings_scroll(self.ctx)
        scroll.resized.connect(lambda: self.timer.start(80))
        self.plugin_panel = CollapsibleSection("普通纹理")
        self.container = TextureGrid()
        self.texture_grid = QGridLayout(self.container)
        self.texture_grid.setContentsMargins(0, 0, 0, 0)
        self.texture_grid.setSpacing(6)
        self.texture_grid.setAlignment(Qt.AlignTop)
        self.container.resized.connect(lambda: self.timer.start(80))
        self.plugin_panel.body_layout.addWidget(self.container)
        self.help_label = QLabel("先在左侧加载模型，再点击纹理；过滤方式在下方 Mipmap 设置中选择。")
        self.help_label.setWordWrap(True)
        self.plugin_panel.body_layout.addWidget(self.help_label)
        self.load_texture_images()
        QTimer.singleShot(0, self.resize_thumbnails)
        return self.plugin_panel

    def load_texture_images(self):
        if not os.path.isdir(self.texture_dir):
            self.help_label.setText("纹理目录不存在：" + self.texture_dir)
            return
        for path in sorted(os.listdir(self.texture_dir)):
            if not path.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            path = os.path.join(self.texture_dir, path)
            button = QPushButton()
            button.setIcon(QIcon(QPixmap(path)))
            button.setToolTip(os.path.basename(path))
            button.clicked.connect(lambda checked, b=button, p=path: self.on_texture_btn_click(b, p))
            index = len(self.buttons)
            self.buttons[path] = button
            self.texture_grid.addWidget(button, index // 4, index % 4)

    def resize_thumbnails(self):
        # 使用可视区宽度，避免旧按钮的最小宽度撑大内容后无法缩回。
        width = self.ctx.model_settings_scroll.viewport().width()
        size = max(50, min(100, (width - 58) // 4))
        for button in self.buttons.values():
            button.setFixedSize(size, size)
            button.setIconSize(QSize(size - 8, size - 8))

    def on_window_resize(self):
        self.timer.start(80)

    def on_texture_btn_click(self, button, path):
        if self.selected_texture_btn is not None:
            self.selected_texture_btn.setStyleSheet("")
        self.selected_texture_btn = button
        self.selected_texture_path = path
        button.setStyleSheet("border:3px solid #ff4400;")
        # 选择普通贴图时切回普通材质；加载新模型时保留环境映射模式。
        for plugin in self.ctx.plugins:
            if getattr(plugin, "plugin_cls_name", "") == "environment_mapping":
                plugin.reflection_check.setChecked(False)
        self.ctx.info_display.append("选中纹理：" + os.path.basename(path))
        if self.ctx.current_actor is not None:
            self.apply_texture(path)

    def on_model_loaded(self, obj_path, actor, polydata):
        if self.selected_texture_path:
            self.apply_texture(self.selected_texture_path)

    def on_selection_changed(self, obj_path, actor, polydata):
        if self.selected_texture_btn is not None:
            self.selected_texture_btn.setStyleSheet('')
        self.selected_texture_path = self.actor_paths.get(actor)
        self.selected_texture_btn = self.buttons.get(self.selected_texture_path)
        if self.selected_texture_btn is not None:
            self.selected_texture_btn.setStyleSheet('border:3px solid #ff4400;')
        active = {model.actor for model in self.ctx.scene_models}
        self.actor_paths = {a: path for a, path in self.actor_paths.items() if a in active}

    def apply_texture(self, path):
        reader = vtk.vtkJPEGReader() if path.lower().endswith((".jpg", ".jpeg")) else vtk.vtkPNGReader()
        reader.SetFileName(path)
        reader.Update()
        if reader.GetOutput().GetNumberOfPoints() == 0:
            self.ctx.info_display.append("纹理读取失败：" + path)
            return
        texture = vtk.vtkTexture()
        texture.SetInputData(reader.GetOutput())
        texture.RepeatOn()
        texture.InterpolateOn()
        texture.MipmapOn()
        texture.SetMaximumAnisotropicFiltering(1)
        # 每次从原始数据生成，避免映射过滤器叠加；保留模型自带 UV。
        source = self.ctx.current_polydata
        coords = source.GetPointData().GetTCoords()
        if coords is None:
            tex_gen = vtk.vtkTextureMapToCylinder()
            tex_gen.SetInputData(source)
            tex_gen.Update()
            source = tex_gen.GetOutput()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(source)
        mapper.ScalarVisibilityOff()
        self.ctx.current_actor.SetMapper(mapper)
        self.ctx.current_actor.SetTexture(texture)
        self.actor_paths[self.ctx.current_actor] = path
        self.texture = texture
        self.ctx.vtk_widget.GetRenderWindow().Render()

    def on_destroy(self):
        self.timer.stop()
