"""独立的 Transform 数值插件：位置、旋转、缩放，仅作用于当前选中模型。"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDoubleSpinBox, QGridLayout, QLabel, QPushButton, QSizePolicy

from plugins.base_plugin import Base3DPlugin
from plugins.base_texture_ui import CollapsibleSection, ensure_model_settings_scroll


class TransformPlugin(Base3DPlugin):
    plugin_cls_name = 'transform_control'
    plugin_name = 'transform_control'
    plugin_desc = '选中物体的位置、旋转、缩放数值面板'

    def __init__(self, viewer_ctx):
        super().__init__(viewer_ctx)
        self.controls = {}
        # 保存输入的欧拉角，避免 VTK 将 270° 等角度重写为等价表示。
        self.rotations = {}

    def create_ui(self):
        ensure_model_settings_scroll(self.ctx)
        self.plugin_panel = CollapsibleSection('Transform')
        self.selection_label = QLabel('未选中物体')
        self.selection_label.setWordWrap(True)
        self.plugin_panel.body_layout.addWidget(self.selection_label)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        for column, (axis, color) in enumerate(zip('XYZ', ('#c74336', '#238142', '#306ac2')), 1):
            label = QLabel(axis)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f'color:{color}; font-weight:bold;')
            grid.addWidget(label, 0, column)
            grid.setColumnStretch(column, 1)
        for row, (key, title, initial, step) in enumerate((
            ('position', '位置', 0, 0.1), ('rotation', '旋转°', 0, 1), ('scale', '缩放', 1, 0.1),
        ), 1):
            grid.addWidget(QLabel(title), row, 0)
            for axis in range(3):
                box = QDoubleSpinBox()
                box.setRange(-1e9, 1e9)
                box.setDecimals(4)
                box.setSingleStep(step)
                box.setValue(initial)
                box.setMinimumWidth(0)
                box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
                box.setKeyboardTracking(False)
                box.setObjectName(f'transform_{key}_{axis}')
                box.setToolTip(f'{title} {"XYZ"[axis]}；输入后回车生效')
                box.valueChanged.connect(lambda _value, group=key: self.apply_transform(group))
                self.controls[key, axis] = box
                grid.addWidget(box, row, axis+1)
        self.plugin_panel.body_layout.addLayout(grid)
        self.reset_button = QPushButton('重置 Transform')
        self.reset_button.clicked.connect(self.reset_transform)
        self.plugin_panel.body_layout.addWidget(self.reset_button)
        help_text = QLabel('左键选择物体，F 聚焦；按住右键转动视角，右键 + WASD 自由移动，Shift 加速。\n从左侧文件树或资源管理器拖入 OBJ；支持多选追加。位置为世界坐标，旋转单位为度，缩放为各轴倍数。')
        help_text.setWordWrap(True)
        self.plugin_panel.body_layout.addWidget(help_text)
        self.on_selection_changed(None, None, None)
        return self.plugin_panel

    def on_model_loaded(self, obj_path, actor, polydata):
        # 只保留仍在场景中的实例，避免单模型浏览时保留失效引用。
        actors = {model.actor for model in self.ctx.scene_models}
        self.rotations = {a: value for a, value in self.rotations.items() if a in actors}
        self.rotations[actor] = actor.GetOrientation()

    def on_selection_changed(self, obj_path, actor, polydata):
        model = self.ctx.current_model
        self.selection_label.setText(model.name if model else '未选中物体')
        self.selection_label.setToolTip(obj_path or '')
        values = (actor.GetPosition(), self.rotations.get(actor, actor.GetOrientation()), actor.GetScale()) if actor else ((0,)*3, (0,)*3, (1,)*3)
        for key, vector in zip(('position', 'rotation', 'scale'), values):
            for axis, value in enumerate(vector):
                box = self.controls[key, axis]
                box.blockSignals(True)
                box.setValue(value)
                box.setEnabled(actor is not None)
                box.blockSignals(False)
        self.reset_button.setEnabled(actor is not None)

    def apply_transform(self, group):
        actor = self.ctx.current_actor
        if actor is None:
            return
        values = tuple(self.controls[group, axis].value() for axis in range(3))
        if group == 'position':
            actor.SetPosition(*values)
        elif group == 'rotation':
            actor.SetOrientation(*values)
            self.rotations[actor] = values
        else:
            actor.SetScale(*values)
        self.ctx.main_window.refresh_selection()

    def reset_transform(self):
        actor = self.ctx.current_actor
        if actor is not None:
            actor.SetPosition(0, 0, 0)
            actor.SetOrientation(0, 0, 0)
            actor.SetScale(1, 1, 1)
            self.rotations[actor] = (0, 0, 0)
            self.on_selection_changed(self.ctx.current_obj_path, actor, self.ctx.current_polydata)
            self.ctx.main_window.refresh_selection()
