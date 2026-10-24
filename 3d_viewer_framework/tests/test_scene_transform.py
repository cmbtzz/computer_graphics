"""真实 Qt/VTK 集成检查；在仓库根目录用 .venv/Scripts/python.exe 运行本文件。"""
from pathlib import Path
import sys
import tempfile

import vtk
import yaml
from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QAbstractItemView

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '3d_viewer_framework'))
from main import VTKViewerCore, auto_scan_plugins


def run():
    app = QApplication.instance() or QApplication([])
    viewer = VTKViewerCore()
    classes = auto_scan_plugins()
    config = yaml.safe_load((ROOT/'3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8'))
    for key in config['active_plugins']:
        viewer.register_plugin(classes[key])
    viewer.show()
    plugins = {p.plugin_cls_name: p for p in viewer.ctx.plugins}
    plugins['experiment1_color'].tabs.setCurrentIndex(1)
    transform = plugins['transform_control']
    widget = viewer.ctx.vtk_widget

    def settle():
        app.processEvents()
        QTest.qWait(100)

    def drop(paths):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        return drop_mime(mime)

    def drop_mime(mime):
        enter = QDragEnterEvent(QPoint(60, 60), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(widget, enter)
        event = QDropEvent(QPointF(60, 60), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(widget, event)
        settle()
        return enter.isAccepted(), event.isAccepted()

    def click(actor):
        renderer = viewer.ctx.vtk_renderer
        renderer.SetWorldPoint(*actor.GetCenter(), 1)
        renderer.WorldToDisplay()
        x, y, _ = renderer.GetDisplayPoint()
        width, height = widget.GetRenderWindow().GetSize()
        point = QPoint(round(x*widget.width()/width), round((height-1-y)*widget.height()/height))
        QTest.mouseClick(widget, Qt.LeftButton, pos=point)
        settle()
        assert viewer.ctx.current_actor is actor

    try:
        settle()
        assert not transform.reset_button.isEnabled()
        with tempfile.TemporaryDirectory(prefix='scene_transform_') as directory:
            folder = Path(directory)
            cube = vtk.vtkCubeSource()
            cube.Update()
            writer = vtk.vtkOBJWriter()
            writer.SetInputData(cube.GetOutput())
            path = folder/'模型.OBJ'
            writer.SetFileName(str(path))
            writer.Write()
            assert drop([path, path]) == (True, True)
            assert len(viewer.ctx.scene_models) == 2
            first, second = viewer.ctx.scene_models
            assert first.actor is not second.actor and first.name != second.name
            assert first.actor.GetBounds()[1] < second.actor.GetBounds()[0]
            assert viewer.ctx.current_actor is second.actor
            camera = viewer.ctx.vtk_renderer.GetActiveCamera()
            pose = (camera.GetPosition(), camera.GetFocalPoint(), camera.GetViewUp())
            click(first.actor)
            assert pose == (camera.GetPosition(), camera.GetFocalPoint(), camera.GetViewUp())

            second_matrix = vtk.vtkMatrix4x4()
            second_matrix.DeepCopy(second.actor.GetMatrix())
            transform.controls['position', 1].setValue(0.5)
            transform.controls['rotation', 2].setValue(270)
            transform.controls['scale', 0].setValue(1.3)
            assert first.actor.GetPosition()[1] == 0.5
            assert first.actor.GetScale()[0] == 1.3
            assert all(second.actor.GetMatrix().GetElement(i,j) == second_matrix.GetElement(i,j)
                       for i in range(4) for j in range(4))
            assert viewer.selection_actor.GetUserMatrix() is first.actor.GetMatrix()
            click(second.actor)
            click(first.actor)
            assert transform.controls['rotation', 2].value() == 270
            assert plugins['view_orientation'].local_center == first.polydata.GetCenter()

            # 切换选中和变换不能把其他物体的贴图、光照或环境反射覆盖掉。
            texture = plugins['texture_mapping']
            texture_path = next(iter(texture.buttons))
            texture.on_texture_btn_click(texture.buttons[texture_path], texture_path)
            saved_texture = first.actor.GetTexture()
            click(second.actor)
            assert second.actor.GetTexture() is None
            plugins['light_control'].chk_specular.setChecked(False)
            click(first.actor)
            assert first.actor.GetTexture() is saved_texture
            assert not plugins['light_control'].chk_specular.isChecked()  # 光照分量现在是全场景开关。
            assert first.actor.GetProperty().GetSpecular() == 0
            assert second.actor.GetProperty().GetSpecular() == 0

            environment = plugins['environment_mapping']
            environment.reflection_check.setChecked(True)
            assert first.actor.GetProperty().GetTexture('mirrorPanorama') is environment.texture
            click(second.actor)
            assert not environment.reflection_check.isChecked()
            assert first.actor.GetProperty().GetTexture('mirrorPanorama') is environment.texture
            environment.reflection_check.setChecked(True)
            click(first.actor)
            assert environment.reflection_check.isChecked()
            environment.reflection_check.setChecked(False)
            assert first.actor.GetTexture() is saved_texture
            assert second.actor.GetProperty().GetTexture('mirrorPanorama') is environment.texture

            current = viewer.ctx.current_actor
            start = QPointF(widget.rect().center())
            app.sendEvent(widget, QMouseEvent(QMouseEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
            app.sendEvent(widget, QMouseEvent(QMouseEvent.MouseMove, start+QPointF(20,15), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
            app.sendEvent(widget, QMouseEvent(QMouseEvent.MouseButtonRelease, start+QPointF(20,15), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
            settle()
            assert viewer.ctx.current_actor is current
            QTest.mouseClick(widget, Qt.LeftButton, pos=QPoint(4, widget.height()-4))
            settle()
            assert viewer.ctx.current_actor is None and not transform.reset_button.isEnabled()
            assert not viewer.selection_actor.GetVisibility()
            viewer.select_actor(first.actor)
            transform.reset_transform()
            assert first.actor.GetPosition() == (0,0,0) and first.actor.GetScale() == (1,1,1)
            assert transform.controls['rotation', 2].value() == 0

            invalid = folder/'empty.obj'
            invalid.write_text('# no geometry\n')
            assert not viewer.load_model(invalid, append=True)
            assert not viewer.load_model(invalid)
            assert len(viewer.ctx.scene_models) == 2
            unsupported = folder/'text.txt'
            unsupported.write_text('test')
            assert drop([unsupported]) == (False, False)
            assert len(viewer.ctx.scene_models) == 2
            assert viewer.load_model(path)  # 原文件树单模型浏览仍可用。
            assert len(viewer.ctx.scene_models) == 1
            assert len(transform.rotations) == 1
            assert not environment.saved_reflections

            # 使用左侧文件树实际产生的 MIME 数据，覆盖此前遗漏的拖拽来源。
            second_path = folder/'第二个.obj'
            writer.SetFileName(str(second_path))
            writer.Write()
            tree = viewer.tree_view
            model = viewer.file_model
            model.setRootPath(str(folder))
            tree.setRootIndex(model.index(str(folder)))
            settle()
            assert tree.dragEnabled() and tree.dragDropMode() == QAbstractItemView.DragOnly
            first_index = model.index(str(path))
            second_index = model.index(str(second_path))
            assert first_index.isValid() and second_index.isValid()
            assert model.flags(first_index) & Qt.ItemIsDragEnabled
            current = viewer.ctx.current_actor
            QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=tree.visualRect(first_index).center())
            assert viewer.ctx.current_actor is current and len(viewer.ctx.scene_models) == 1
            QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.ControlModifier,
                             pos=tree.visualRect(second_index).center())
            selected = tree.selectionModel().selectedRows(0)
            assert len(selected) == 2
            mime = model.mimeData(selected)
            assert {Path(u.toLocalFile()) for u in mime.urls()} == {path, second_path}
            assert drop_mime(mime) == (True, True)
            assert len(viewer.ctx.scene_models) == 3 and path.exists() and second_path.exists()
        print('PASS: file-tree drag/multiselect MIME and non-destructive click, external OBJ drop, multiple instances, click/drag picking, independent TRS, materials/reflections, failed imports', flush=True)
    finally:
        viewer.close()
        app.processEvents()


if __name__ == '__main__':
    run()
