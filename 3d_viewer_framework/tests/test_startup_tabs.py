"""检查首次启动、缩放和切换页签时，仅显示当前页面。"""
from pathlib import Path
import sys

import yaml
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

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
    try:
        for key in config['active_plugins']:
            viewer.register_plugin(classes[key])
        experiment = next(p for p in viewer.ctx.plugins
                          if p.plugin_cls_name == 'experiment1_color')
        tabs = experiment.tabs
        scroll = viewer.ctx.model_settings_scroll
        viewer.show()

        def check_page(index):
            app.processEvents()
            QTest.qWait(100)
            assert tabs.currentIndex() == index
            assert experiment.plugin_panel.isVisible() == (index == 0)
            assert scroll.isVisible() == (index == 1), '非当前模型设置页覆盖了实验页'
            assert experiment.center_stack.currentIndex() == index
            assert viewer.ctx.vtk_widget.isVisible() == (index == 1)
            assert experiment.cube_widget.isVisible() == (index == 0)
            for plugin in viewer.ctx.plugins:
                toolbar = getattr(plugin, 'toolbar', None)
                if toolbar is not None:
                    assert toolbar.isVisible() == (index == 1)

        # 首次进入时先检查，不能先切换页签掩盖初始化问题。
        check_page(0)
        viewer.resize(1800, 950)
        check_page(0)
        for index in (1, 0, 1, 0):
            tabs.setCurrentIndex(index)
            check_page(index)
        print('PASS: startup, resize and repeated tab switches show only the active page', flush=True)
    finally:
        viewer.close()
        app.processEvents()


if __name__ == '__main__':
    run()
