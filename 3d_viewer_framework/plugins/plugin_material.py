"""当前物体的材质参数和预设；普通纹理仍由原插件手动选择。"""
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QLabel, QPushButton

from plugins.base_plugin import Base3DPlugin
from plugins.base_material import PRESETS, material_store
from plugins.base_texture_ui import CollapsibleSection, ensure_model_settings_scroll


class MaterialPlugin(Base3DPlugin):
    plugin_cls_name = 'material_control'
    plugin_name = 'material_control'
    plugin_desc = '当前物体的材质参数与金属、木材、塑料预设'

    def __init__(self, viewer_ctx):
        super().__init__(viewer_ctx)
        self.store = material_store(self.ctx)
        self.controls = {}
        self.colors = {}

    def create_ui(self):
        ensure_model_settings_scroll(self.ctx)
        self.plugin_panel = CollapsibleSection('材质设置 · 当前物体')
        layout = self.plugin_panel.body_layout
        self.selection_label = QLabel('未选中物体')
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([*PRESETS, '自定义'])
        self.preset_combo.currentTextChanged.connect(self.choose_preset)
        layout.addWidget(self.preset_combo)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        entries = [('ambient', '环境光强度', 0, 1, 0.05),
                   ('diffuse', '漫反射强度', 0, 1, 0.05),
                   ('specular', '镜面反射强度', 0, 1, 0.05),
                   ('shininess', '高光指数', 1, 128, 1),
                   ('emission', '自发光强度', 0, 3, 0.05)]
        for key, title, minimum, maximum, step in entries:
            if key in ('ambient', 'diffuse', 'specular', 'emission'):
                button = QPushButton('选择颜色')
                color_key = key + '_color'
                button.clicked.connect(lambda _checked, k=color_key: self.choose_color(k))
                self.colors[color_key] = button
                form.addRow(title.replace('强度', '颜色'), button)
            box = QDoubleSpinBox()
            box.setRange(minimum, maximum)
            box.setDecimals(3)
            box.setSingleStep(step)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(lambda value, k=key: self.edit_value(k, value))
            self.controls[key] = box
            form.addRow(title, box)
        layout.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.reset_button = QPushButton('重置当前物体材质')
        self.reset_button.clicked.connect(lambda: self.choose_preset('默认'))
        layout.addWidget(self.reset_button)
        self.store.changed.connect(self.refresh)
        self.refresh()
        return self.plugin_panel

    def edit_value(self, key, value):
        actor = self.ctx.current_actor
        if actor is not None:
            self.store.edit(actor, **{key: value})
            self.store.render()

    def choose_color(self, key):
        actor = self.ctx.current_actor
        if actor is None:
            return
        color = QColorDialog.getColor(QColor.fromRgbF(*getattr(self.store.ensure(actor), key)),
                                      self.ctx.main_window, '选择材质颜色')
        if color.isValid():
            self.store.edit(actor, **{key: (color.redF(), color.greenF(), color.blueF())})
            self.store.render()

    def choose_preset(self, name):
        actor = self.ctx.current_actor
        if actor is None or name not in PRESETS:
            return
        self.store.preset(actor, name)
        self.store.render()

    def refresh(self, _actor=None):
        actor = self.ctx.current_actor
        state = self.store.ensure(actor) if actor is not None else None
        model = self.ctx.current_model
        self.selection_label.setText(model.name if model else '先在场景中选中一个物体')
        self.selection_label.setToolTip(model.path if model else '')
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentText(state.preset if state else '默认')
        self.preset_combo.setEnabled(state is not None)
        self.preset_combo.blockSignals(False)
        for key, box in self.controls.items():
            box.blockSignals(True)
            if state is not None:
                box.setValue(getattr(state, key))
            box.setEnabled(state is not None)
            box.blockSignals(False)
        for key, button in self.colors.items():
            button.setEnabled(state is not None)
            if state is not None:
                color = QColor.fromRgbF(*getattr(state, key))
                foreground = '#111' if color.lightnessF() > 0.55 else '#fff'
                button.setText(color.name().upper())
                button.setStyleSheet(f'background:{color.name()};color:{foreground};padding:4px;')
        self.reset_button.setEnabled(state is not None)
        if state and state.preset == '木材':
            text = '木材使用暖棕色主体、同色暗部与很弱的反光；木纹请在下方“普通纹理”中手动选择。'
        elif state and state.preset == '金属':
            text = '金属采用亮银灰色与宽而明亮的冷白高光，表现抛光银色表面。'
        elif state and state.preset == '塑料':
            text = '塑料采用饱和红色主体和独立的白色高光，暗部保持红色。'
        else:
            text = '高光指数越大，高光越集中。自发光只让物体自身变亮，不照亮其他物体。'
        if state and not self.store.enabled:
            text += '\n场景光照已关闭；材质数值保留，自发光仍显示。'
        self.note.setText(text)

    def on_model_loaded(self, obj_path, actor, polydata):
        self.store.prune()
        self.store.apply(actor)

    def on_selection_changed(self, obj_path, actor, polydata):
        self.refresh()
