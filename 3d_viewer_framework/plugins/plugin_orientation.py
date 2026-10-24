"""角落方向指示器与模型局部坐标轴，缩放时保持可读大小。"""

import math
import vtk
from PyQt5.QtCore import QElapsedTimer, QTimer

from plugins.base_plugin import Base3DPlugin


def normalized(vector):
    length = math.sqrt(sum(value * value for value in vector))
    return tuple(value / length for value in vector)


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def camera_rotation(back, up):
    """相机局部坐标到世界坐标的旋转，供球面插值使用。"""
    right = normalized(cross(up, back))
    up = cross(back, right)
    quaternion = vtk.vtkQuaterniond()
    quaternion.FromMatrix3x3(tuple((right[i], up[i], back[i]) for i in range(3)))
    return quaternion




class OrientationPlugin(Base3DPlugin):
    plugin_cls_name = "view_orientation"
    plugin_name = "view_orientation"
    plugin_desc = "XYZ 方向指示器与自适应局部坐标轴"

    # 使用屏幕逻辑像素，而非模型单位；不随相机距离或模型尺寸改变。
    SIZE = 112
    PADDING = 12
    LOCAL_SIZE = 76
    LABEL_GAP = 11
    AXIS_COLORS = ((1., .18, .12), (.12, .85, .2), (.2, .45, 1.))

    def __init__(self, viewer_ctx):
        super().__init__(viewer_ctx)
        self.widget = None
        self.local_axes = None
        self.local_renderer = None
        self.local_center = None
        self.local_labels = []
        self.local_length = 0.
        self.render_observer = None
        self.navigation_animation = None
        self.navigation_clock = QElapsedTimer()
        self.navigation_timer = QTimer()
        self.navigation_timer.setInterval(16)
        self.navigation_timer.timeout.connect(self.advance_navigation)
        self.resize_timer = QTimer()
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.update_size)

    def create_ui(self):
        self.create_local_axes()
        self.widget = vtk.vtkCameraOrientationWidget()
        self.widget.SetParentRenderer(self.ctx.vtk_renderer)
        self.widget.SetAnimatorTotalFrames(12)
        # 禁用原生鼠标处理，避免与场景视口的统一输入规则冲突。
        self.widget.ProcessEventsOff()
        rep = self.widget.GetRepresentation()
        rep.AnchorToUpperRight()
        rep.SetXPlusLabelText("X")
        rep.SetYPlusLabelText("Y")
        rep.SetZPlusLabelText("Z")
        self.update_size()
        self.widget.On()
        # 指示器只显示方向；左键选择与右键自由观察统一由场景视口处理。
        self.resize_timer.start(0)
        return None

    def navigation_position(self, point):
        view = self.ctx.vtk_widget
        width, height = view.GetRenderWindow().GetSize()
        return (round(point.x() * width / max(1, view.width())),
                height - 1 - round(point.y() * height / max(1, view.height())))


    def snap_to_axis(self, axis, sign):
        """点击 +轴从正侧看向焦点，再次点击当前侧则翻到负侧。"""
        self.stop_navigation_animation()
        camera = self.ctx.vtk_renderer.GetActiveCamera()
        camera.OrthogonalizeViewUp()
        focal = camera.GetFocalPoint()
        distance = camera.GetDistance()
        back = normalized(tuple(camera.GetPosition()[i] - focal[i] for i in range(3)))
        target_back = tuple(float(i == axis) * sign for i in range(3))
        if sum(back[i] * target_back[i] for i in range(3)) > .9999:
            sign = -sign
            target_back = tuple(float(i == axis) * sign for i in range(3))
        # 侧视图始终 Y 朝上；从 +Y 俯视时 -Z 朝上，从 -Y 仰视时 +Z 朝上。
        target_up = (0., 0., -float(sign)) if axis == 1 else (0., 1., 0.)
        self.navigation_animation = {
            "focal": focal, "distance": distance,
            "start": camera_rotation(back, camera.GetViewUp()),
            "target": camera_rotation(target_back, target_up),
            "back": target_back, "up": target_up,
        }
        if self.widget.GetAnimate():
            self.navigation_clock.start()
            self.navigation_timer.start()
        else:
            self.apply_navigation(1.)
            self.stop_navigation_animation()

    def advance_navigation(self):
        duration = max(1, self.widget.GetAnimatorTotalFrames()) * 16
        fraction = min(1., self.navigation_clock.elapsed() / duration)
        self.apply_navigation(fraction)
        if fraction >= 1.:
            self.stop_navigation_animation()

    def apply_navigation(self, fraction):
        state = self.navigation_animation
        if state is None:
            return
        if fraction >= 1.:
            back, up = state["back"], state["up"]
        else:
            t = fraction * fraction * (3 - 2 * fraction)
            rotation = state["start"].Slerp(t, state["target"])
            matrix = [[0.] * 3 for _ in range(3)]
            rotation.ToMatrix3x3(matrix)
            back = tuple(matrix[i][2] for i in range(3))
            up = tuple(matrix[i][1] for i in range(3))
        camera = self.ctx.vtk_renderer.GetActiveCamera()
        camera.SetFocalPoint(*state["focal"])
        camera.SetPosition(*(state["focal"][i] + state["distance"] * back[i] for i in range(3)))
        camera.SetViewUp(*up)
        camera.OrthogonalizeViewUp()
        self.render_navigation()

    def render_navigation(self):
        renderer = self.ctx.vtk_renderer
        renderer.ResetCameraClippingRange()
        renderer.UpdateLightsGeometryToFollowCamera()
        self.ctx.vtk_widget.GetRenderWindow().Render()

    def stop_navigation_animation(self):
        self.navigation_timer.stop()
        self.navigation_animation = None

    def update_size(self):
        if self.widget is None:
            return
        ratio = self.ctx.vtk_widget.devicePixelRatioF()
        rep = self.widget.GetRepresentation()
        size = round(self.SIZE * ratio)
        padding = round(self.PADDING * ratio)
        rep.SetSize(size, size)
        rep.SetPadding(padding, padding)
        for label in self.local_labels:
            label.GetTextProperty().SetFontSize(round(14 * ratio))

    def create_local_axes(self):
        self.local_axes = vtk.vtkAxesActor()
        self.local_axes.SetShaftTypeToCylinder()
        self.local_axes.SetCylinderRadius(.035)
        self.local_axes.SetConeRadius(.4)
        self.local_axes.SetCylinderResolution(32)
        self.local_axes.SetConeResolution(32)
        self.local_axes.SetNormalizedShaftLength(.76, .76, .76)
        self.local_axes.SetNormalizedTipLength(.24, .24, .24)
        # 轴的长度、半径都定义在单位几何中，再统一缩放，避免只有长度变化、
        # 半径仍是固定模型单位，导致轴越来越细。
        self.local_axes.SetTotalLength(1, 1, 1)
        self.local_axes.AxisLabelsOff()
        self.local_axes.UseBoundsOff()
        self.local_axes.PickableOff()
        self.local_axes.VisibilityOff()
        shafts = (self.local_axes.GetXAxisShaftProperty(), self.local_axes.GetYAxisShaftProperty(),
                  self.local_axes.GetZAxisShaftProperty())
        tips = (self.local_axes.GetXAxisTipProperty(), self.local_axes.GetYAxisTipProperty(),
                self.local_axes.GetZAxisTipProperty())
        for shaft, tip, color in zip(shafts, tips, self.AXIS_COLORS):
            for prop in (shaft, tip):
                prop.SetColor(*color)
                prop.LightingOff()
        # 独立覆盖层使位于模型内部的轴也可见；相机姿态与模型视口一致。
        # 先加入此层，再加入角落指示器，后者会绘制在局部轴之上。
        self.local_renderer = vtk.vtkRenderer()
        self.local_renderer.SetLayer(1)
        self.local_renderer.InteractiveOff()
        self.local_renderer.AddActor(self.local_axes)
        # 原生 caption 混用世界坐标附件和相对屏幕坐标，缩放时标签会漂移。
        # 改为独立屏幕文字，每帧直接投影轴端，位置不依赖 caption 的布局。
        for text, color in zip("XYZ", self.AXIS_COLORS):
            label = vtk.vtkTextActor()
            label.SetInput(text)
            label.SetTextScaleModeToNone()
            label.GetPositionCoordinate().SetCoordinateSystemToDisplay()
            label.PickableOff()
            label.VisibilityOff()
            prop = label.GetTextProperty()
            prop.SetColor(*color)
            prop.SetFontFamilyToArial()
            prop.SetFontSize(14)
            prop.BoldOn()
            prop.ShadowOn()
            prop.SetJustificationToCentered()
            prop.SetVerticalJustificationToCentered()
            self.local_renderer.AddViewProp(label)
            self.local_labels.append(label)
        self.ctx.vtk_widget.GetRenderWindow().AddRenderer(self.local_renderer)
        self.render_observer = self.local_renderer.AddObserver("StartEvent", self.update_local_axes)

    def set_local_visibility(self, visible):
        self.local_axes.SetVisibility(visible)
        for label in self.local_labels:
            label.SetVisibility(visible)

    def update_local_axes(self, _renderer=None, _event=None):
        actor = self.ctx.current_actor
        if actor is None or self.local_center is None:
            self.set_local_visibility(False)
            return
        renderer = self.ctx.vtk_renderer
        width, height = renderer.GetSize()
        if width <= 0 or height <= 0:
            return
        matrix = actor.GetMatrix()
        anchor = matrix.MultiplyPoint((*self.local_center, 1.))
        center = tuple(anchor[i] / anchor[3] for i in range(3))
        camera = renderer.GetActiveCamera()
        depth = sum((center[i] - camera.GetPosition()[i]) * camera.GetDirectionOfProjection()[i]
                    for i in range(3))
        if depth <= 0:
            self.set_local_visibility(False)
            return
        # 在锚点深度反投影相邻屏幕像素，得到当前相机下每像素的世界长度。
        # 透视、正交投影都适用，无需写死模型单位或按模型文件名调尺寸。
        renderer.SetWorldPoint(*center, 1.)
        renderer.WorldToDisplay()
        x, y, z = renderer.GetDisplayPoint()
        renderer.SetDisplayPoint(x + 1, y, z)
        renderer.DisplayToWorld()
        adjacent = renderer.GetWorldPoint()
        units_per_pixel = math.sqrt(sum((adjacent[i] / adjacent[3] - center[i]) ** 2
                                       for i in range(3)))
        length = units_per_pixel * self.LOCAL_SIZE * self.ctx.vtk_widget.devicePixelRatioF()
        if not math.isfinite(length) or length <= 0:
            return
        self.local_length = length
        # 局部方向随模型变换旋转，但去掉各轴缩放，保证三个方向等长。
        pose = vtk.vtkMatrix4x4()
        pose.Identity()
        for axis in range(3):
            scale = math.sqrt(sum(matrix.GetElement(i, axis) ** 2 for i in range(3)))
            for row in range(3):
                direction = matrix.GetElement(row, axis) / scale if scale else float(row == axis)
                pose.SetElement(row, axis, direction * length)
        for row in range(3):
            pose.SetElement(row, 3, center[row])
        self.local_axes.SetUserMatrix(pose)
        self.set_local_visibility(actor.GetVisibility())
        self.local_renderer.SetViewport(renderer.GetViewport())
        overlay_camera = self.local_renderer.GetActiveCamera()
        overlay_camera.DeepCopy(camera)
        # 只放宽覆盖层的裁剪距离，避免轴端被模型的近远裁剪面切掉。
        near, far = camera.GetClippingRange()
        overlay_camera.SetClippingRange(max(min(near, depth - 2 * length), depth * 1e-6),
                                       max(far, depth + 2 * length))
        # 轴端 + 固定屏幕间距；缩放时标签与箭头一起保持稳定的屏幕位置。
        ratio = self.ctx.vtk_widget.devicePixelRatioF()
        for axis, label in enumerate(self.local_labels):
            endpoint = tuple(center[i] + pose.GetElement(i, axis) for i in range(3))
            renderer.SetWorldPoint(*endpoint, 1.)
            renderer.WorldToDisplay()
            end_x, end_y, _ = renderer.GetDisplayPoint()
            dx, dy = end_x - x, end_y - y
            projected_length = math.hypot(dx, dy)
            if projected_length < 1e-6:
                dx, dy = ((1, 0), (0, 1), (-1, 0))[axis]
                projected_length = 1.
            gap = self.LABEL_GAP * ratio
            label.SetDisplayPosition(round(end_x + gap * dx / projected_length),
                                     round(end_y + gap * dy / projected_length))
            label.GetTextProperty().SetFontSize(round(14 * ratio))

    def on_model_loaded(self, obj_path, actor, polydata):
        self.stop_navigation_animation()
        renderer = self.ctx.vtk_renderer
        # 替换旧的固定 15 单位坐标轴，保留一套跟随当前模型的局部轴。
        for prop in list(renderer.GetViewProps()):
            if isinstance(prop, vtk.vtkAxesActor):
                renderer.RemoveViewProp(prop)
        self.local_center = polydata.GetCenter()
        # 原坐标轴也曾参与相机取景，移除后仅按模型的真实包围盒重新取景。
        renderer.ResetCamera()
        self.ctx.vtk_widget.GetRenderWindow().Render()

    def on_window_resize(self):
        self.resize_timer.start(0)

    def on_selection_changed(self, obj_path, actor, polydata):
        self.local_center = polydata.GetCenter() if polydata is not None else None
        self.set_local_visibility(actor is not None)

    def on_destroy(self):
        self.resize_timer.stop()
        self.stop_navigation_animation()
        if self.render_observer is not None:
            self.local_renderer.RemoveObserver(self.render_observer)
            self.render_observer = None
        if self.local_renderer is not None:
            self.ctx.vtk_widget.GetRenderWindow().RemoveRenderer(self.local_renderer)
            self.local_renderer = None
        if self.widget is not None:
            self.widget.Off()
            self.widget.SetParentRenderer(None)
            self.widget = None
