"""场景灯光及全场景光照效果开关。"""
import vtk
from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QLabel, QPushButton, QSizePolicy
from plugins.base_plugin import Base3DPlugin
from plugins.base_material import material_store
from plugins.base_texture_ui import CollapsibleSection, ensure_model_settings_scroll


class LightKeys(QObject):
    def __init__(self, plugin):
        super().__init__(plugin.ctx.vtk_widget)
        self.plugin = plugin

    def eventFilter(self, watched, event):
        if event.type() != QEvent.KeyPress:
            return False
        navigation = getattr(watched, 'navigation', None)
        if navigation is not None and navigation.looking:
            return False
        return self.plugin.handle_key(event)


class LightPlugin(Base3DPlugin):
    plugin_cls_name = 'light_control'
    plugin_name = 'light_control'
    plugin_desc = '场景灯光与光照分量开关'

    def __init__(self, viewer_ctx):
        super().__init__(viewer_ctx)
        self.store = material_store(self.ctx)
        self.scene_light = None
        self.controls = {}
        self.light_global_enable = True

    def create_ui(self):
        ensure_model_settings_scroll(self.ctx)
        self.plugin_panel = CollapsibleSection('光照设置 · 整个场景')
        layout = self.plugin_panel.body_layout
        self.chk_global = QCheckBox('启用光照')
        self.chk_global.setChecked(True)
        layout.addWidget(self.chk_global)
        for name, title in (('ambient', '环境光'), ('diffuse', '漫反射'), ('specular', '镜面高光')):
            check = QCheckBox(title)
            check.setChecked(True)
            setattr(self, 'chk_' + name, check)
            check.toggled.connect(self.update_material)
            layout.addWidget(check)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        entries = [('x', '灯光 X', -100, -1e9, 1e9, 1),
                   ('y', '灯光 Y', 100, -1e9, 1e9, 1),
                   ('z', '灯光 Z', 120, -1e9, 1e9, 1),
                   ('r', '红 R', 1, 0, 1, 0.05), ('g', '绿 G', 1, 0, 1, 0.05),
                   ('b', '蓝 B', 1, 0, 1, 0.05), ('intensity', '灯光强度', 0.8, 0, 3, 0.05),
                   ('ambient', '环境光强度', 1, 0, 3, 0.05)]
        for key, title, value, minimum, maximum, step in entries:
            box = QDoubleSpinBox()
            box.setRange(minimum, maximum)
            box.setDecimals(3)
            box.setSingleStep(step)
            box.setKeyboardTracking(False)
            box.setMinimumWidth(75)
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            box.setValue(value)
            box.valueChanged.connect(self.update_light)
            self.controls[key] = box
            form.addRow(title, box)
        layout.addLayout(form)
        reset = QPushButton('重置场景灯光')
        reset.clicked.connect(self.reset_light)
        layout.addWidget(reset)
        help_text = QLabel('开关作用于全部模型，保留物体的材质数值。\n点击场景：方向键移动灯光 X/Y，PageUp/PageDown 移动 Z；R/G/B 增加颜色，Shift+R/G/B 减少。右键飞行时快捷键仍属于相机。')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.create_light()
        self.chk_global.toggled.connect(self.on_global_toggle)
        self.key_filter = LightKeys(self)
        self.ctx.vtk_widget.installEventFilter(self.key_filter)
        self.update_light()
        return self.plugin_panel

    def create_light(self):
        renderer = self.ctx.vtk_renderer
        renderer.AutomaticLightCreationOff()
        # 移除首次渲染自动创建的相机头灯，避免关闭光照后仍有额外照明。
        for light in list(renderer.GetLights()):
            if light.GetLightType() == 1:
                renderer.RemoveLight(light)
        self.scene_light = vtk.vtkLight()
        self.scene_light.SetLightTypeToSceneLight()
        self.scene_light.SetPositional(True)
        self.scene_light.SetConeAngle(180)
        self.scene_light.SetAttenuationValues(1, 0, 0)
        renderer.AddLight(self.scene_light)

    def update_light(self, *_):
        self.scene_light.SetPosition(*(self.controls[k].value() for k in 'xyz'))
        rgb = tuple(self.controls[k].value() for k in 'rgb')
        self.scene_light.SetColor(*rgb)
        self.scene_light.SetIntensity(self.controls['intensity'].value())
        self.store.light_rgb = rgb
        self.store.light_intensity = self.controls['intensity'].value()
        self.store.ambient_intensity = self.controls['ambient'].value()
        self.update_material()

    def on_global_toggle(self, checked):
        self.light_global_enable = bool(checked)
        self.scene_light.SetSwitch(checked)
        for name in ('ambient', 'diffuse', 'specular'):
            getattr(self, 'chk_' + name).setEnabled(checked)
        self.update_material()

    def update_material(self, *_):
        self.store.enabled = self.chk_global.isChecked()
        self.store.components = {name: getattr(self, 'chk_' + name).isChecked()
                                 for name in ('ambient', 'diffuse', 'specular')}
        self.store.apply_all()
        self.store.render()

    def reset_light(self):
        for key, value in dict(x=-100, y=100, z=120, r=1, g=1, b=1, intensity=0.8, ambient=1).items():
            self.controls[key].blockSignals(True)
            self.controls[key].setValue(value)
            self.controls[key].blockSignals(False)
        for control in (self.chk_global, self.chk_ambient, self.chk_diffuse, self.chk_specular):
            control.blockSignals(True)
            control.setChecked(True)
            control.setEnabled(True)
            control.blockSignals(False)
        self.light_global_enable = True
        self.scene_light.SwitchOn()
        self.update_light()

    def handle_key(self, event):
        movement = {Qt.Key_Left: ('x', -1), Qt.Key_Right: ('x', 1),
                    Qt.Key_Down: ('y', -1), Qt.Key_Up: ('y', 1),
                    Qt.Key_PageDown: ('z', -1), Qt.Key_PageUp: ('z', 1)}
        if event.key() in movement:
            key, sign = movement[event.key()]
            bounds = [model.actor.GetBounds() for model in self.ctx.scene_models]
            span = max((max(b[i+1]-b[i] for i in (0, 2, 4)) for b in bounds), default=20)
            self.controls[key].setValue(self.controls[key].value() + sign * max(span * 0.05, 0.001))
        elif event.key() in (Qt.Key_R, Qt.Key_G, Qt.Key_B):
            key = {Qt.Key_R: 'r', Qt.Key_G: 'g', Qt.Key_B: 'b'}[event.key()]
            delta = -0.05 if event.modifiers() & Qt.ShiftModifier else 0.05
            self.controls[key].setValue(self.controls[key].value() + delta)
        else:
            return False
        return True

    def on_model_loaded(self, obj_path, actor, polydata):
        self.store.prune()
        self.store.apply(actor)

    def on_destroy(self):
        self.ctx.vtk_widget.removeEventFilter(self.key_filter)
        self.ctx.vtk_renderer.RemoveLight(self.scene_light)
