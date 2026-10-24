"""真实 Qt 输入下检查场景相机操作和旧快捷键冲突。"""
from pathlib import Path
import math
import sys
import tempfile

import vtk
import yaml
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QFocusEvent, QMouseEvent
from PyQt5.QtCore import QEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'3d_viewer_framework'))
from main import VTKViewerCore, auto_scan_plugins


def close(a, b):
    return all(math.isclose(x, y, abs_tol=1e-8) for x, y in zip(a, b))


def run():
    app = QApplication.instance() or QApplication([])
    viewer = VTKViewerCore()
    classes = auto_scan_plugins()
    for key in yaml.safe_load((ROOT/'3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8'))['active_plugins']:
        viewer.register_plugin(classes[key])
    viewer.show()
    plugins = {p.plugin_cls_name: p for p in viewer.ctx.plugins}
    plugins['experiment1_color'].tabs.setCurrentIndex(1)
    view = viewer.ctx.vtk_widget
    nav = view.navigation
    renderer = viewer.ctx.vtk_renderer
    camera = renderer.GetActiveCamera()

    def settle(ms=60):
        app.processEvents()
        QTest.qWait(ms)

    def pose():
        return camera.GetPosition(), camera.GetFocalPoint(), camera.GetViewUp(), camera.GetViewAngle()

    def drag(button):
        start = QPointF(view.rect().center())
        app.sendEvent(view, QMouseEvent(QEvent.MouseButtonPress, start, button, button, Qt.NoModifier))
        app.sendEvent(view, QMouseEvent(QEvent.MouseMove, start+QPointF(80, -35), Qt.NoButton, button, Qt.NoModifier))
        app.sendEvent(view, QMouseEvent(QEvent.MouseButtonRelease, start+QPointF(80, -35), button, Qt.NoButton, Qt.NoModifier))
        settle()

    try:
        settle()
        with tempfile.TemporaryDirectory(prefix='scene_navigation_') as directory:
            cube = vtk.vtkCubeSource()
            cube.Update()
            path = Path(directory)/'cube.obj'
            writer = vtk.vtkOBJWriter()
            writer.SetFileName(str(path))
            writer.SetInputData(cube.GetOutput())
            writer.Write()
            viewer.import_dropped_models([path, path])
            first, second = viewer.ctx.scene_models
            second.actor.SetPosition(25, 0, 0)
            renderer.ResetCamera()
            viewer.select_actor(first.actor)
            view.setFocus()
            settle()

            before = pose()
            drag(Qt.LeftButton)
            assert pose() == before, 'left drag must not move the camera'
            assert viewer.ctx.current_actor is first.actor
            drag(Qt.MiddleButton)
            assert pose() == before, 'old middle-button behavior must not leak through'

            # VTK 的 W/S/R/P 等快捷键全部停止接收场景按键。
            for key in (Qt.Key_W, Qt.Key_S, Qt.Key_A, Qt.Key_D, Qt.Key_R, Qt.Key_P):
                QTest.keyClick(view, key)
            settle()
            assert pose() == before
            assert all(m.actor.GetProperty().GetRepresentation() == vtk.VTK_SURFACE for m in viewer.ctx.scene_models)

            # F 只取选中物体的世界包围盒，而不是整个场景；保持方向。
            direction = camera.GetDirectionOfProjection()
            distance = camera.GetDistance()
            QTest.keyClick(view, Qt.Key_F)
            settle()
            assert close(camera.GetFocalPoint(), first.actor.GetCenter())
            assert close(camera.GetDirectionOfProjection(), direction)
            assert camera.GetDistance() < distance/3
            renderer.SetWorldPoint(*first.actor.GetCenter(), 1)
            renderer.WorldToDisplay()
            x, y, _ = renderer.GetDisplayPoint()
            width, height = view.GetRenderWindow().GetSize()
            assert abs(x-width/2) < 1 and abs(y-height/2) < 1

            # 右键原地转向，不绕选中物体公转或执行旧的 dolly 缩放。
            position = camera.GetPosition()
            direction = camera.GetDirectionOfProjection()
            distance = camera.GetDistance()
            drag(Qt.RightButton)
            assert close(camera.GetPosition(), position)
            assert not close(camera.GetDirectionOfProjection(), direction)
            assert math.isclose(camera.GetDistance(), distance, abs_tol=1e-8)
            assert viewer.ctx.current_actor is first.actor
            assert not nav.looking and not nav.timer.isActive()

            # 连续移动：W 沿俯仰后的视线飞行，A/D/S 也可持续按住。
            for key, sign in ((Qt.Key_W, 1), (Qt.Key_S, -1), (Qt.Key_D, 1), (Qt.Key_A, -1)):
                QTest.mousePress(view, Qt.RightButton, pos=view.rect().center())
                position, focal = camera.GetPosition(), camera.GetFocalPoint()
                forward = camera.GetDirectionOfProjection()
                axis = forward if key in (Qt.Key_W, Qt.Key_S) else (-forward[2], 0, forward[0])
                QTest.keyPress(view, key)
                settle(130)
                QTest.keyRelease(view, key)
                delta = tuple(camera.GetPosition()[i]-position[i] for i in range(3))
                assert sum(delta[i]*axis[i] for i in range(3))*sign > 0
                assert close(tuple(camera.GetFocalPoint()[i]-focal[i] for i in range(3)), delta)
                QTest.mouseRelease(view, Qt.RightButton, pos=view.rect().center())
                stopped = pose()
                settle(100)
                assert pose() == stopped and not nav.pressed
                assert first.actor.GetProperty().GetRepresentation() == vtk.VTK_SURFACE

            QTest.mousePress(view, Qt.RightButton, pos=view.rect().center())
            QTest.keyPress(view, Qt.Key_W)
            app.sendEvent(view, QFocusEvent(QEvent.FocusOut))
            stopped = pose()
            settle(100)
            assert not nav.looking and not nav.pressed and not nav.timer.isActive()
            assert pose() == stopped and view.mouseGrabber() is not view

            # 角落指示器不再拦截左键转动视角。
            view.setFocus()
            before = pose()
            QTest.mouseClick(view, Qt.LeftButton, pos=QPoint(view.width()-60, 60))
            settle(250)
            assert pose() == before
            viewer.select_actor(None)
            QTest.keyClick(view, Qt.Key_F)
            assert pose() == before

            # 正交视图也能聚焦；数值框编辑不触发场景的 F/W/S 行为。
            viewer.select_actor(second.actor)
            camera.ParallelProjectionOn()
            QTest.keyClick(view, Qt.Key_F)
            assert close(camera.GetFocalPoint(), second.actor.GetCenter())
            assert camera.GetParallelScale() > 0
            box = plugins['transform_control'].controls['position', 0]
            box.setFocus()
            before = pose()
            QTest.keyClick(box, Qt.Key_F)
            assert pose() == before
        print('PASS: left selection only, F selection framing, in-place right look, held WASD flight, release/focus-loss stop, no VTK key conflicts, display-only corner, orthographic framing and input isolation', flush=True)
    finally:
        viewer.close()
        app.processEvents()


if __name__ == '__main__':
    run()
