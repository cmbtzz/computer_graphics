"""真实 Qt/VTK 检查：事件突发合并、隐藏页停绘及最终尺寸/标记正确性。"""
from collections import Counter
from pathlib import Path
import sys

import yaml
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QSplitter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '3d_viewer_framework'))
from main import VTKViewerCore, auto_scan_plugins


def run():
    app = QApplication.instance() or QApplication([])
    viewer = VTKViewerCore()
    classes = auto_scan_plugins()
    config = yaml.safe_load(
        (ROOT / '3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8')
    )
    observers = []
    try:
        for key in config['active_plugins']:
            viewer.register_plugin(classes[key])
        experiment = next(p for p in viewer.ctx.plugins
                          if p.plugin_cls_name == 'experiment1_color')
        model, cube = viewer.ctx.vtk_widget, experiment.cube_widget
        splitter = experiment.center_stack.parentWidget()
        assert isinstance(splitter, QSplitter)
        viewer.show()
        QTest.qWait(200)
        frames = Counter()
        for name, view in (('model', model), ('cube', cube)):
            window = view.GetRenderWindow()
            observer = window.AddObserver(
                'StartEvent', lambda _o, _e, key=name: frames.update([key])
            )
            observers.append((window, observer))

        # 使用真实鼠标点击页签；事件处理期间不应同步执行昂贵的 Render。
        for index in [1, 0] * 20:
            QTest.mouseClick(experiment.tabs.tabBar(), Qt.LeftButton,
                             pos=experiment.tabs.tabBar().tabRect(index).center())
        assert not frames, frames
        QTest.qWait(250)
        assert experiment.tabs.currentIndex() == 0
        assert frames['model'] == 0, frames
        # 工具栏/缩略图布局稳定时可能再产生少量重绘，不能逐次点击都绘制。
        assert 1 <= frames['cube'] <= 4, frames

        for index, name, view, hidden in ((0, 'cube', cube, 'model'),
                                          (1, 'model', model, 'cube')):
            experiment.tabs.setCurrentIndex(index)
            QTest.qWait(250)
            frames.clear()
            for _ in range(40):
                view.request_render()
            assert not frames, frames
            QTest.qWait(100)
            assert frames[name] == 1 and frames[hidden] == 0, frames

            # 模拟快速拖动窗口和分栏，最终只采用最后的尺寸。
            frames.clear()
            for step in range(30):
                viewer.resize(1500 + step * 3, 800 + step)
                splitter.setSizes([300, 700 + step * 4, 450 - step * 4])
            assert not frames, frames
            QTest.qWait(200)
            assert 1 <= frames[name] <= 3 and frames[hidden] == 0, frames
            scale = view._getPixelRatio()
            assert view.GetRenderWindow().GetSize() == (
                round(view.width() * scale), round(view.height() * scale)
            )
            if index == 0:
                # 缩放后标记必须使用新投影位置，不能停留在旧像素坐标。
                renderer = experiment.cube_renderer
                renderer.SetWorldPoint(*(c / 255 for c in experiment.rgb), 1)
                renderer.WorldToDisplay()
                expected = renderer.GetDisplayPoint()[:2]
                assert all(abs(actual - target) < 0.01
                           for marker in experiment.marker_actors
                           for actual, target in zip(marker.GetPosition(), expected))
        # 带有未执行的重绘任务关闭窗口也应安全。
        model.request_render()
    finally:
        for window, observer in observers:
            window.RemoveObserver(observer)
        viewer.close()
        QTest.qWait(50)
    print('PASS: rapid tab clicks, coalesced paint/resize, hidden views, final buffer size and RGB marker',
          flush=True)


if __name__ == '__main__':
    run()
