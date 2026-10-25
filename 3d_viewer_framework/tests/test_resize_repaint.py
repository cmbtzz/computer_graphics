"""验证原生视口真正处理 paint，以及分栏松手后无需点击就清除旧像素。"""
from pathlib import Path
import sys

import yaml
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QPaintEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '3d_viewer_framework'))
from main import VTKViewerCore, auto_scan_plugins


def run():
    app = QApplication.instance() or QApplication([])
    viewer = VTKViewerCore()
    observer = None
    try:
        classes = auto_scan_plugins()
        config = yaml.safe_load(
            (ROOT / '3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8')
        )
        for key in config['active_plugins']:
            viewer.register_plugin(classes[key])
        experiment = next(p for p in viewer.ctx.plugins
                          if p.plugin_cls_name == 'experiment1_color')
        experiment.tabs.setCurrentIndex(1)
        viewer.showMaximized()
        QTest.qWait(400)
        view = viewer.ctx.vtk_widget
        window = view.GetRenderWindow()
        frames = []
        observer = window.AddObserver('StartEvent', lambda *_: frames.append(True))

        # WA_OpaquePaintEvent + WA_PaintOnScreen 的 paint 不能不画就返回。
        app.sendEvent(view, QPaintEvent(view.rect()))
        assert len(frames) == 1, 'paintEvent 返回前没有实际绘制原生视口'

        splitter = experiment.center_stack.parentWidget()
        splitter.setSizes([280, 900, 500])
        QTest.qWait(400)
        for delta in (-180, 220, -120, 180):
            handle = splitter.handle(2)
            origin = handle.rect().center()
            QTest.mousePress(handle, Qt.LeftButton, pos=origin)
            point = origin + QPoint(delta, 0)
            event = QMouseEvent(QMouseEvent.MouseMove, QPointF(point),
                                QPointF(handle.mapToGlobal(point)), Qt.NoButton,
                                Qt.LeftButton, Qt.NoModifier)
            app.sendEvent(handle, event)
            QTest.mouseRelease(handle, Qt.LeftButton, pos=point)
            QTest.qWait(400)

            # 抓取已呈现的窗口像素；QWidget.grab() 会主动重画，从而掩盖残留。
            image = viewer.screen().grabWindow(int(viewer.winId())).toImage()
            scale_x = image.width() / viewer.width()
            scale_y = image.height() / viewer.height()
            origin = view.mapTo(viewer, QPoint(0, 0))
            # 空场景应为黑色；排除右上角方向指示器和边缘。
            for x_fraction in (0.2, 0.4, 0.6, 0.8):
                for y_fraction in (0.3, 0.5, 0.7):
                    x = round((origin.x() + view.width() * x_fraction) * scale_x)
                    y = round((origin.y() + view.height() * y_fraction) * scale_y)
                    color = image.pixelColor(x, y)
                    assert max(color.red(), color.green(), color.blue()) < 5, (
                        '视口内存在旧面板像素', delta, x, y, color.name()
                    )
    finally:
        if observer is not None:
            window.RemoveObserver(observer)
        viewer.close()
        app.processEvents()
    print('PASS: synchronous native paint and presented pixels after bidirectional splitter drags',
          flush=True)


if __name__ == '__main__':
    run()
