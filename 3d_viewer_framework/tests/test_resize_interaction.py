"""带事件循环等待的持续拖动检查，覆盖分栏拖动和 Windows 原生缩放。"""
from collections import Counter
from pathlib import Path
import sys

import yaml
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '3d_viewer_framework'))
from main import VTKViewerCore, auto_scan_plugins


def run():
    app = QApplication.instance() or QApplication([])
    viewer = VTKViewerCore()
    frames = Counter()
    observers = []
    try:
        classes = auto_scan_plugins()
        config = yaml.safe_load(
            (ROOT / '3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8')
        )
        for key in config['active_plugins']:
            viewer.register_plugin(classes[key])
        experiment = next(p for p in viewer.ctx.plugins
                          if p.plugin_cls_name == 'experiment1_color')
        views = {'cube': experiment.cube_widget, 'model': viewer.ctx.vtk_widget}
        splitter = experiment.center_stack.parentWidget()
        viewer.show()
        QTest.qWait(300)
        for name, view in views.items():
            window = view.GetRenderWindow()
            tag = window.AddObserver('StartEvent',
                                     lambda _o, _e, key=name: frames.update([key]))
            observers.append((window, tag))

        def buffer_size(view):
            size = [0, 0]
            view.GetRenderWindow().GetRenderFramebuffer().GetLastSize(size)
            return tuple(size)

        def check_size(view):
            scale = view._getPixelRatio()
            expected = (
                round(view.width() * scale), round(view.height() * scale)
            )
            assert view.GetRenderWindow().GetSize() == expected
            actual = buffer_size(view)
            assert actual == expected, (actual, expected, dict(frames))

        def native_resize(resizing):
            if sys.platform == 'win32':
                import ctypes
                from ctypes import wintypes
                message = wintypes.MSG()
                message.hwnd = int(viewer.winId())
                message.message = 0x0231 if resizing else 0x0232
                # 直接测试 Qt 原生消息入口，不向操作系统注入消息。
                viewer.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))
            else:
                for view in views.values():
                    view.set_interactive_resize(resizing)

        for index, name in enumerate(('cube', 'model')):
            experiment.tabs.setCurrentIndex(index)
            splitter.setSizes([250, 750, 500])
            QTest.qWait(300)
            view = views[name]
            handle = splitter.handle(2)
            origin = handle.rect().center()
            original_sizes = splitter.sizes()
            original_buffer = buffer_size(view)
            frames.clear()
            QTest.mousePress(handle, Qt.LeftButton, pos=origin)
            try:
                for delta in range(4, 85, 4):
                    point = origin + QPoint(delta, 0)
                    event = QMouseEvent(QMouseEvent.MouseMove, QPointF(point),
                                        QPointF(handle.mapToGlobal(point)), Qt.NoButton,
                                        Qt.LeftButton, Qt.NoModifier)
                    app.sendEvent(handle, event)
                    QTest.qWait(20)
                assert splitter.sizes() == original_sizes, '拖动中不应实时调整原生视口'
                assert buffer_size(view) == original_buffer
            finally:
                QTest.mouseRelease(handle, Qt.LeftButton, pos=origin + QPoint(84, 0))
            QTest.qWait(300)
            assert splitter.sizes() != original_sizes
            check_size(view)

            # 持续一秒且每次都让事件循环运行；不能只测不处理事件的 resize 突发。
            frames.clear()
            original_buffer = buffer_size(view)
            native_resize(True)
            try:
                for step in range(30):
                    viewer.resize(1500 + step * 4, 820 + step * 2)
                    QTest.qWait(20)
                assert not frames, frames
                assert buffer_size(view) == original_buffer
            finally:
                native_resize(False)
            QTest.qWait(300)
            assert frames[name] >= 1 and frames['cube' if name == 'model' else 'model'] == 0
            check_size(view)

            # 非原生/程序连续调整尺寸也应等尺寸稳定后再提交。
            frames.clear()
            for step in range(30):
                viewer.resize(1450 + step * 4, 800 + step * 2)
                QTest.qWait(20)
            assert not frames, frames
            QTest.qWait(300)
            assert frames[name] >= 1
            check_size(view)
    finally:
        for window, tag in observers:
            window.RemoveObserver(tag)
        viewer.close()
        app.processEvents()
    print('PASS: held splitter drag, Windows modal resize, continuous resize settling, both viewports',
          flush=True)


if __name__ == '__main__':
    run()
