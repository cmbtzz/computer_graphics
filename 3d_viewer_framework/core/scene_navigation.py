"""场景相机控制：右键自由观察、右键 + WASD 飞行、F 聚焦。"""

import math

from PyQt5.QtCore import QElapsedTimer, QObject, Qt, QTimer


class SceneNavigation(QObject):
    MOVE_KEYS = {Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D}

    def __init__(self, ctx):
        super().__init__(ctx.vtk_widget)
        self.ctx = ctx
        self.looking = False
        self.last_position = None
        self.pressed = set()
        self.speed = 1.0
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.advance)

    @property
    def camera(self):
        return self.ctx.vtk_renderer.GetActiveCamera()

    def begin(self, point):
        self.stop()
        self.looking = True
        self.last_position = point
        self.speed = max(self.camera.GetDistance() * 0.6, 0.001)
        self.ctx.vtk_widget.grabMouse()
        self.ctx.vtk_widget.setCursor(Qt.ClosedHandCursor)
        self.clock.start()
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self.looking = False
        self.pressed.clear()
        self.last_position = None
        view = self.ctx.vtk_widget
        if view.mouseGrabber() is view:
            view.releaseMouse()
        view.unsetCursor()

    def look(self, point):
        if not self.looking or self.last_position is None:
            return
        delta = point - self.last_position
        self.last_position = point
        if delta.isNull():
            return
        camera = self.camera
        forward = camera.GetDirectionOfProjection()
        yaw = math.atan2(forward[0], -forward[2]) + math.radians(delta.x() * 0.2)
        pitch = math.asin(max(-1, min(1, forward[1]))) - math.radians(delta.y() * 0.2)
        pitch = max(math.radians(-89), min(math.radians(89), pitch))
        forward = (math.sin(yaw)*math.cos(pitch), math.sin(pitch), -math.cos(yaw)*math.cos(pitch))
        position = camera.GetPosition()
        distance = max(camera.GetDistance(), 0.001)
        camera.SetFocalPoint(*(position[i] + forward[i]*distance for i in range(3)))
        camera.SetViewUp(0, 1, 0)
        camera.OrthogonalizeViewUp()
        self.render()

    def key_press(self, event):
        key = event.key()
        if key == Qt.Key_F and not event.isAutoRepeat():
            self.focus_selected()
        elif self.looking and (key in self.MOVE_KEYS or key == Qt.Key_Shift):
            self.pressed.add(key)

    def key_release(self, event):
        if not event.isAutoRepeat():
            self.pressed.discard(event.key())

    def advance(self):
        dt = min(self.clock.restart() / 1000, 0.05)
        if self.looking:
            self.move(dt)

    def move(self, dt):
        forward_amount = int(Qt.Key_W in self.pressed) - int(Qt.Key_S in self.pressed)
        side_amount = int(Qt.Key_D in self.pressed) - int(Qt.Key_A in self.pressed)
        if not forward_amount and not side_amount:
            return
        forward = self.camera.GetDirectionOfProjection()
        # forward × world_up，保证水平转向时 A/D 始终向左右平移。
        right = (-forward[2], 0.0, forward[0])
        length = math.hypot(right[0], right[2])
        right = tuple(v/max(length, 1e-9) for v in right)
        direction = tuple(forward[i]*forward_amount + right[i]*side_amount for i in range(3))
        length = math.sqrt(sum(v*v for v in direction))
        speed = self.speed * (3 if Qt.Key_Shift in self.pressed else 1)
        self.translate(tuple(v/length*speed*dt for v in direction))

    def translate(self, delta):
        camera = self.camera
        position, focal = camera.GetPosition(), camera.GetFocalPoint()
        camera.SetPosition(*(position[i]+delta[i] for i in range(3)))
        camera.SetFocalPoint(*(focal[i]+delta[i] for i in range(3)))
        self.render()

    def wheel(self, steps):
        if self.looking:
            self.speed = max(0.0001, min(1e12, self.speed * math.exp(steps*0.15)))
        elif self.camera.GetParallelProjection():
            self.camera.SetParallelScale(max(1e-9, self.camera.GetParallelScale()*math.exp(-steps*0.15)))
            self.render()
        else:
            distance = max(self.camera.GetDistance(), 0.001)
            self.translate(tuple(v*distance*0.12*steps for v in self.camera.GetDirectionOfProjection()))

    def focus_selected(self):
        actor = self.ctx.current_actor
        if actor is None:
            self.ctx.main_window.statusBar().showMessage('先左键选中物体，再按 F 聚焦。', 2500)
            return
        bounds = actor.GetBounds()
        center = tuple((bounds[2*i]+bounds[2*i+1])/2 for i in range(3))
        radius = max(math.sqrt(sum((bounds[2*i+1]-bounds[2*i])**2 for i in range(3)))/2, 0.001)
        camera = self.camera
        aspect = max(self.ctx.vtk_renderer.GetTiledAspectRatio(), 0.001)
        half_angle = math.radians(camera.GetViewAngle())/2
        if camera.GetUseHorizontalViewAngle():
            half_angle = min(half_angle, math.atan(math.tan(half_angle)/aspect))
        else:
            half_angle = min(half_angle, math.atan(math.tan(half_angle)*aspect))
        distance = radius/max(math.sin(half_angle), 0.001)*1.15
        forward = camera.GetDirectionOfProjection()
        camera.SetFocalPoint(*center)
        camera.SetPosition(*(center[i]-forward[i]*distance for i in range(3)))
        if camera.GetParallelProjection():
            camera.SetParallelScale(radius*max(1, 1/aspect)*1.15)
        self.speed = max(radius*2, 0.001)
        self.render()

    def render(self):
        renderer = self.ctx.vtk_renderer
        renderer.ResetCameraClippingRange()
        renderer.UpdateLightsGeometryToFollowCamera()
        self.ctx.vtk_widget.GetRenderWindow().Render()
