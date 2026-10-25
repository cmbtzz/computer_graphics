"""实验一：HSV/RGB 转换、颜色三角形和可交互 RGB 立方体。"""

import colorsys

import vtk
from PyQt5.QtCore import QPoint, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPolygon
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from plugins.base_plugin import Base3DPlugin
from core.render_viewport import RenderViewport


def hsv_to_rgb(h, s, v):
    """将 H(0..359)、S/V(0..100) 转为 RGB(0..255)。"""
    return tuple(round(x * 255) for x in colorsys.hsv_to_rgb(h / 360, s / 100, v / 100))


def rgb_to_hsv(r, g, b):
    """将 RGB(0..255) 转为 H(0..359)、S/V(0..100)。"""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return round(h * 360) % 360, round(s * 100), round(v * 100)


class ColorTriangle(QWidget):
    """使用当前 RGB 颜色填充三角形。"""

    def __init__(self):
        super().__init__()
        self.color = QColor(255, 0, 0)
        self.setMinimumHeight(95)

    def set_color(self, rgb):
        self.color = QColor(*rgb)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        side = min(width - 24, int((height - 24) * 2 / 1.732))
        triangle_height = int(side * 0.866)
        left = (width - side) // 2
        top = (height - triangle_height) // 2
        painter.setPen(Qt.black)
        painter.setBrush(self.color)
        painter.drawPolygon(QPolygon([
            QPoint(width // 2, top),
            QPoint(left, top + triangle_height),
            QPoint(left + side, top + triangle_height),
        ]))


class Experiment1Plugin(Base3DPlugin):
    plugin_cls_name = "experiment1_color"
    plugin_name = "experiment1_color"
    plugin_desc = "实验一：颜色应用"

    def __init__(self, viewer_ctx):
        super().__init__(viewer_ctx)
        self.controls = {}
        self.updating = False
        self.rgb = (255, 0, 0)
        self.cube_widget = None
        self.cube_renderer = None
        self.cube_actor = None
        self.marker_3d = []
        self.marker_actors = []
        self.tabs = None
        self.center_stack = None
        self.marker_observer = None

    def create_ui(self):
        """右侧放两个选项卡，中央随选项卡切换实验预览和模型。"""
        display_area = QWidget()
        display_layout = QHBoxLayout(display_area)
        display_layout.setContentsMargins(6, 6, 6, 6)
        display_layout.setSpacing(8)

        triangle_panel = QFrame()
        triangle_panel.setFrameShape(QFrame.StyledPanel)
        triangle_layout = QVBoxLayout(triangle_panel)
        triangle_layout.addWidget(QLabel("HSV 显示区"))
        self.triangle = ColorTriangle()
        triangle_layout.addWidget(self.triangle, 1)
        display_layout.addWidget(triangle_panel, 1)

        cube_panel = QFrame()
        cube_panel.setFrameShape(QFrame.StyledPanel)
        cube_layout = QVBoxLayout(cube_panel)
        cube_layout.addWidget(QLabel("RGB 显示区"))
        self.cube_widget = RenderViewport(cube_panel)
        self.cube_widget.setMinimumSize(280, 280)
        cube_layout.addWidget(self.cube_widget, 1)
        display_layout.addWidget(cube_panel, 1)

        self.plugin_panel = QFrame()
        self.plugin_panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self.plugin_panel)
        layout.addWidget(QLabel("实验一 · 颜色参数"))

        grid = QGridLayout()
        channels = (
            ("H", 359, 0), ("S", 100, 100), ("V", 100, 100),
            ("R", 255, 255), ("G", 255, 0), ("B", 255, 0),
        )
        for row, (key, maximum, initial) in enumerate(channels):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, maximum)
            slider.setValue(initial)
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.setValue(initial)
            spin.setFixedWidth(62)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            spin.valueChanged.connect(
                lambda _value, channel=key: self.on_color_changed(channel)
            )
            grid.addWidget(QLabel(key), row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(spin, row, 2)
            self.controls[key] = (slider, spin)
        layout.addLayout(grid)
        self.hex_label = QLabel()
        layout.addWidget(self.hex_label)
        help_label = QLabel("拖动立方体旋转，滚轮缩放。R→X，G→Y，B→Z。")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        layout.addStretch(1)
        self.plugin_panel.setMinimumWidth(260)

        # 内核的文件树、中央 VTK 视图、右侧插件容器仍在原三栏布局中。
        splitter = self.ctx.right_extension_panel.parentWidget()
        if not isinstance(splitter, QSplitter):
            raise RuntimeError("实验插件需要内核的三栏 QSplitter 布局")
        column_sizes = splitter.sizes()
        center_index = splitter.indexOf(self.ctx.vtk_widget)
        right_index = splitter.indexOf(self.ctx.right_extension_panel)
        self.center_stack = QStackedWidget()
        model_view = splitter.replaceWidget(center_index, self.center_stack)
        self.center_stack.addWidget(display_area)
        self.center_stack.addWidget(model_view)

        self.tabs = QTabWidget()
        model_controls = splitter.replaceWidget(right_index, self.tabs)
        self.tabs.addTab(self.plugin_panel, "实验1")
        self.tabs.addTab(model_controls, "模型查看")
        self.center_stack.show()
        self.tabs.show()
        splitter.setSizes(column_sizes)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.setCurrentIndex(0)

        self.build_cube()
        self.update_color_display()
        QTimer.singleShot(0, self.initialize_cube)
        QTimer.singleShot(0, self.on_tab_changed)
        return None  # 两个右侧页面已各自挂载，避免内核重复添加控件。

    def on_tab_changed(self, _index=None):
        model_tab_active = self.tabs.currentIndex() == 1
        self.center_stack.setCurrentIndex(1 if model_tab_active else 0)
        for plugin in self.ctx.plugins:
            toolbar = getattr(plugin, "toolbar", None)
            if toolbar is not None:
                toolbar.setVisible(model_tab_active)
        if model_tab_active:
            self.ctx.vtk_widget.request_render()
        elif self.cube_widget is not None:
            self.cube_widget.request_render()

    def on_color_changed(self, channel):
        """根据用户修改的颜色空间，计算并更新另一个颜色空间。"""
        if self.updating:
            return
        self.updating = True
        try:
            if channel in "HSV":
                hsv = (self.controls[key][1].value() for key in "HSV")
                self.rgb = hsv_to_rgb(*hsv)
                target = dict(zip("RGB", self.rgb))
            else:
                self.rgb = tuple(self.controls[key][1].value() for key in "RGB")
                target = dict(zip("HSV", rgb_to_hsv(*self.rgb)))

            for key, value in target.items():
                slider, spin = self.controls[key]
                slider.blockSignals(True)
                spin.blockSignals(True)
                slider.setValue(value)
                spin.setValue(value)
                slider.blockSignals(False)
                spin.blockSignals(False)
        finally:
            self.updating = False
        self.update_color_display()

    def build_cube(self):
        """按 RGB 坐标给立方体顶点着色，面内颜色由 VTK 插值。"""
        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        self.cube_renderer = renderer
        self.cube_widget.GetRenderWindow().AddRenderer(renderer)
        interactor = self.cube_widget.GetRenderWindow().GetInteractor()
        interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())
        # 在实际绘制时按最终尺寸和相机位置投影标记，不额外触发第二帧。
        self.marker_observer = renderer.AddObserver("StartEvent", self.update_marker_position)

        cube = vtk.vtkCubeSource()
        cube.SetBounds(0, 1, 0, 1, 0, 1)
        cube.Update()
        polydata = cube.GetOutput()
        colors = vtk.vtkUnsignedCharArray()
        colors.SetName("RGB")
        colors.SetNumberOfComponents(3)
        for index in range(polydata.GetNumberOfPoints()):
            red, green, blue = polydata.GetPoint(index)
            colors.InsertNextTuple3(round(red * 255), round(green * 255), round(blue * 255))
        polydata.GetPointData().SetScalars(colors)

        cube_mapper = vtk.vtkPolyDataMapper()
        cube_mapper.SetInputData(polydata)
        cube_mapper.SetColorModeToDirectScalars()
        cube_mapper.SetScalarModeToUsePointData()
        cube_mapper.InterpolateScalarsBeforeMappingOn()
        cube_actor = vtk.vtkActor()
        cube_actor.SetMapper(cube_mapper)
        cube_actor.GetProperty().LightingOff()
        renderer.AddActor(cube_actor)
        self.cube_actor = cube_actor

        # 三维标记占据 RGB 坐标对应的真实空间位置。
        for radius, color in ((0.050, (0, 0, 0)), (0.039, (1, 1, 1)), (0.028, (1, 0, 0))):
            sphere = vtk.vtkSphereSource()
            sphere.SetRadius(radius)
            sphere.SetThetaResolution(24)
            sphere.SetPhiResolution(24)
            sphere_mapper = vtk.vtkPolyDataMapper()
            sphere_mapper.SetInputConnection(sphere.GetOutputPort())
            actor = vtk.vtkActor()
            actor.SetMapper(sphere_mapper)
            actor.GetProperty().SetColor(*color)
            actor.GetProperty().LightingOff()
            renderer.AddActor(actor)
            self.marker_3d.append(actor)

        # 空心轮廓保证内部位置可辨，同时不遮住真正的三维球体。
        for color, width in (((0, 0, 0), 4), ((1, 1, 1), 2)):
            circle = vtk.vtkRegularPolygonSource()
            circle.SetNumberOfSides(32)
            circle.SetRadius(7)
            circle.SetCenter(0, 0, 0)
            circle.GeneratePolygonOff()
            circle_mapper = vtk.vtkPolyDataMapper2D()
            circle_mapper.SetInputConnection(circle.GetOutputPort())
            marker = vtk.vtkActor2D()
            marker.SetMapper(circle_mapper)
            marker.GetProperty().SetColor(*color)
            marker.GetProperty().SetLineWidth(width)
            marker.GetPositionCoordinate().SetCoordinateSystemToDisplay()
            renderer.AddActor2D(marker)
            self.marker_actors.append(marker)

        camera = renderer.GetActiveCamera()
        camera.SetFocalPoint(0.5, 0.5, 0.5)
        camera.SetPosition(2.6, 2.6, 2.6)
        camera.SetViewUp(0, 0, 1)
        camera.ParallelProjectionOn()
        camera.SetParallelScale(0.95)
        renderer.ResetCameraClippingRange()

    def initialize_cube(self):
        if self.cube_widget is not None:
            self.cube_widget.Initialize()
            self.cube_widget.request_render()

    def update_color_display(self):
        self.triangle.set_color(self.rgb)
        self.hex_label.setText("当前颜色：#{:02X}{:02X}{:02X}".format(*self.rgb))

        point = tuple(component / 255 for component in self.rgb)
        for actor in self.marker_3d:
            actor.SetPosition(*point)
        self.marker_3d[-1].GetProperty().SetColor(*point)
        # 只有内部位置需要透出表面；边界颜色保留实体立方体外观。
        inside = all(0 < component < 255 for component in self.rgb)
        self.cube_actor.GetProperty().SetOpacity(0.55 if inside else 1.0)

        self.cube_widget.request_render()

    def update_marker_position(self, _interactor=None, _event=None):
        if self.cube_renderer is None:
            return
        point = tuple(component / 255 for component in self.rgb)
        self.cube_renderer.SetWorldPoint(*point, 1)
        self.cube_renderer.WorldToDisplay()
        x, y, _ = self.cube_renderer.GetDisplayPoint()
        for marker in self.marker_actors:
            marker.SetPosition(x, y)

    def on_destroy(self):
        if self.cube_widget is not None:
            self.cube_widget.stop_rendering()
            if self.marker_observer is not None:
                self.cube_renderer.RemoveObserver(self.marker_observer)
                self.marker_observer = None
            self.cube_widget.GetRenderWindow().Finalize()
