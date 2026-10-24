"""本次经典光照与材质的 Qt/VTK 渲染检查；不依赖环境映射。"""
from pathlib import Path
import sys
import tempfile
from dataclasses import asdict

import numpy as np
import vtk
import yaml
from vtkmodules.util.numpy_support import vtk_to_numpy
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'3d_viewer_framework'))
from main import VTKViewerCore, auto_scan_plugins


def run():
    app = QApplication.instance() or QApplication([])
    window = VTKViewerCore()
    classes = auto_scan_plugins()
    config = yaml.safe_load((ROOT/'3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8'))
    for key in config['active_plugins']:
        window.register_plugin(classes[key])
    plugins = {p.plugin_cls_name: p for p in window.ctx.plugins}
    light, material, env = (plugins[k] for k in ('light_control', 'material_control', 'environment_mapping'))
    store = material.store
    window.show()
    plugins['experiment1_color'].tabs.setCurrentIndex(1)
    renderer = window.ctx.vtk_renderer
    view = window.ctx.vtk_widget
    # 像素检查排除覆盖在物体中心的彩色 XYZ 指示轴。
    plugins['view_orientation'].local_renderer.DrawOff()

    def settle():
        app.processEvents()
        QTest.qWait(70)

    def frame():
        view.GetRenderWindow().Render()
        settle()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(view.GetRenderWindow())
        capture.ReadFrontBufferOff()
        capture.Update()
        image = capture.GetOutput()
        w, h, _ = image.GetDimensions()
        return vtk_to_numpy(image.GetPointData().GetScalars()).reshape(h, w, 3).copy()

    def patch(image, actor):
        renderer.SetWorldPoint(*actor.GetCenter(), 1)
        renderer.WorldToDisplay()
        x, y, _ = renderer.GetDisplayPoint()
        x, y = round(x), round(y)
        return image[y-5:y+6, x-5:x+6].mean(axis=(0, 1))

    try:
        assert not material.preset_combo.isEnabled()
        with tempfile.TemporaryDirectory(prefix='lighting_material_') as folder:
            source = vtk.vtkSphereSource()
            source.SetThetaResolution(64)
            source.SetPhiResolution(48)
            source.Update()
            writer = vtk.vtkOBJWriter()
            writer.SetInputData(source.GetOutput())
            path = Path(folder)/'sphere.obj'
            writer.SetFileName(str(path))
            writer.Write()
            assert window.load_model(path)
            assert window.load_model(path, append=True)
            first, second = [m.actor for m in window.ctx.scene_models]
            for key, value in dict(x=0, y=3, z=4).items():
                light.controls[key].setValue(value)
            window.select_actor(first)
            material.preset_combo.setCurrentText('木材')
            first_state = asdict(store.ensure(first))
            assert store.ensure(second).preset == '默认'
            assert np.linalg.norm(patch(frame(), first)-patch(frame(), second)) > 20
            window.select_actor(second)
            material.controls['specular'].setValue(0.73)
            material.controls['shininess'].setValue(97)
            window.select_actor(first)
            assert material.preset_combo.currentText() == '木材'
            assert asdict(store.ensure(first)) == first_state

            light.chk_specular.setChecked(False)
            assert first.GetProperty().GetSpecular() == second.GetProperty().GetSpecular() == 0
            assert store.ensure(second).specular == 0.73
            light.chk_specular.setChecked(True)
            assert second.GetProperty().GetSpecular() == 0.73
            assert first.GetProperty().GetSpecular() == first_state['specular']

            before = frame()
            for key in 'rgb':
                light.controls[key].setValue(0)
            unlit = frame()
            assert patch(unlit, first).max() < 2 and patch(unlit, second).max() < 2
            store.edit(first, emission=0.6, emission_color=(1, 0.2, 0.1))
            emitted = patch(frame(), first)
            assert emitted[0] > 140 and emitted[1] > 20 and emitted[2] > 10
            light.chk_global.setChecked(False)
            assert np.max(np.abs(patch(frame(), first)-emitted)) < 2
            light.chk_global.setChecked(True)
            light.reset_light()
            store.edit(first, emission=0)

            view.setFocus()
            x = light.controls['x'].value()
            QTest.keyClick(view, Qt.Key_Right)
            assert light.controls['x'].value() > x
            for key, channel in ((Qt.Key_R,'r'), (Qt.Key_G,'g'), (Qt.Key_B,'b')):
                QTest.keyClick(view, key, Qt.ShiftModifier)
                assert light.controls[channel].value() == 0.95
            for key, value in dict(x=0, y=3, z=4, r=1, g=1, b=1).items():
                light.controls[key].setValue(value)

            texture = plugins['texture_mapping']
            texture_path = next(iter(texture.buttons))
            texture.on_texture_btn_click(texture.buttons[texture_path], texture_path)
            saved_texture = first.GetTexture()
            saved_mapper = first.GetMapper()
            material.choose_preset('金属')
            assert 'reflection' not in material.controls
            assert not env.reflection_check.isChecked() and env.texture is None
            assert first.GetTexture() is saved_texture and first.GetMapper() is saved_mapper
            assert first.GetProperty().GetTexture('mirrorPanorama') is None
            concentrated = frame()
            material.controls['shininess'].setValue(8)
            assert np.count_nonzero(frame() != concentrated) > 100
            material.controls['diffuse'].setValue(0.37)
            material.controls['shininess'].setValue(83)
            store.edit(first, emission=0.11, emission_color=(0.1, 0.2, 0.8))
            saved_state = asdict(store.ensure(first))
            window.select_actor(second)
            window.select_actor(first)
            assert first.GetTexture() is saved_texture and first.GetMapper() is saved_mapper
            assert first.GetProperty().GetDiffuse() == 0.37 and first.GetProperty().GetSpecularPower() == 83
            assert asdict(store.ensure(first)) == saved_state
            assert material.controls['emission'].value() == 0.11
            assert patch(frame(), first).max() > 10

            # 上一次实验仍可单独运行，材质预设不启用/关闭它，也不更换全景图。
            env.reflection_check.setChecked(True)
            material.choose_preset('木材')
            assert env.reflection_check.isChecked()
            env.background_check.setChecked(True)
            # 原纹理插件保持不动，普通贴图按钮仍能退出当前物体反射并保留材质参数。
            texture.on_texture_btn_click(texture.buttons[texture_path], texture_path)
            assert not env.reflection_check.isChecked() and first.GetTexture() is not None
            assert store.ensure(first).preset == '木材'
            assert view.GetRenderWindow().HasRenderer(env.background_renderer)
            env.background_check.setChecked(False)
            window.select_actor(None)
            assert not material.preset_combo.isEnabled()
            # 取消选择后，场景灯光仍可修改，影响所有模型。
            light.chk_diffuse.setChecked(False)
            assert first.GetProperty().GetDiffuse() == second.GetProperty().GetDiffuse() == 0
            light.chk_diffuse.setChecked(True)
            assert first.GetProperty().GetDiffuse() == store.ensure(first).diffuse
            window.resize(1100, 700)
            settle()
            assert window.ctx.model_settings_scroll.horizontalScrollBar().maximum() == 0, [
                (p.plugin_cls_name, p.plugin_panel.minimumSizeHint().width())
                for p in window.ctx.plugins if p.plugin_panel is not None]
            assert window.load_model(path)
            assert len(store.states) == 1
            assert not env.saved_reflections
        print('PASS: independent classic materials/presets, GPU colors/highlights/emission, no environment-map activation or blend control, global light switches, keyboard XYZ/RGB, unchanged texture workflow, prior experiment compatibility', flush=True)
    finally:
        window.close()
        app.processEvents()


if __name__ == '__main__':
    run()
