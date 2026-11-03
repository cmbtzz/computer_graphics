import json
from pathlib import Path
import sys
import math
from PyQt5.QtWidgets import QApplication, QSplitter
from PyQt5.QtCore import QTimer, QPoint
import vtk

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'source/3d_viewer_framework'
sys.path.insert(0,str(SRC))
from core.viewer_3d import VTKViewerCore
from plugins.plugin_texture import TexturePlugin
from plugins.plugin_mipmap import MipmapPlugin
from plugins.plugin_environment import EnvironmentMappingPlugin

app=QApplication([])
v=VTKViewerCore()
for cls in (TexturePlugin,MipmapPlugin,EnvironmentMappingPlugin):v.register_plugin(cls)
t,m,e=v.plugin_instances
v.setGeometry(30,30,1420,820)
v.ctx.info_display.setMaximumHeight(80)
v.show()
record={}

def screenshot(name):
    v.raise_();v.activateWindow();app.processEvents()
    v.ctx.vtk_widget.GetRenderWindow().Render()
    pos=v.mapToGlobal(QPoint(0,0))
    shot=app.primaryScreen().grabWindow(0,pos.x(),pos.y(),v.width(),v.height())
    assert shot.save(str(ROOT/name))

def start():
    model=SRC/'data/obj/bottle/bottle_0043.obj'
    folder=SRC/'data/obj'
    v.file_model.setRootPath(str(folder))
    v.tree_view.setRootIndex(v.file_model.index(str(folder)))
    v.tree_view.expand(v.file_model.index(str(model.parent)))
    v.tree_view.setCurrentIndex(v.file_model.index(str(model)))
    v.load_model(str(model))
    actor=v.ctx.current_actor
    # 将数据集中Z轴朝上的瓶子转为查看器的Y-up展示方向。
    actor.RotateX(-90)
    for prop in list(v.ctx.vtk_renderer.GetViewProps()):
        if prop is not actor:v.ctx.vtk_renderer.RemoveViewProp(prop)
    camera=v.ctx.vtk_renderer.GetActiveCamera()
    center=actor.GetCenter()
    camera.SetFocalPoint(*center)
    camera.SetPosition(center[0]+18,center[1]+7,center[2]+28)
    camera.SetViewUp(0,1,0)
    v.ctx.vtk_renderer.ResetCameraClippingRange()
    splitter=v.findChild(QSplitter)
    splitter.setSizes([230,820,370])
    path=str(SRC/'data/texture/texture4.png')
    t.on_texture_btn_click(t.buttons[path],path)
    m.filter_combo.setCurrentIndex(5)
    e.plugin_panel.header.setChecked(False)
    t.plugin_panel.header.setChecked(True)
    record['model']='bottle_0043.obj'
    record['filter']=m.filter_combo.currentText()
    QTimer.singleShot(800,normal)

def normal():
    screenshot('advanced-mipmap-ui.png')
    t.plugin_panel.header.setChecked(False)
    e.plugin_panel.header.setChecked(True)
    e.background_check.setChecked(True)
    e.reflection_check.setChecked(True)
    QTimer.singleShot(1500,environment)

def environment():
    screenshot('advanced-environment-ui.png')
    actor=v.ctx.current_actor
    record['shared_environment_texture']=bool(actor.GetProperty().GetTexture('mirrorPanorama') is e.texture and e.skybox.GetTexture() is e.texture)
    assert record['shared_environment_texture']
    e.reflection_check.setChecked(False)
    record['ordinary_texture_restored']=actor.GetTexture() is not None
    assert record['ordinary_texture_restored']
    (ROOT/'advanced-figure-verification.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record))
    v.close();app.quit()

QTimer.singleShot(700,start)
sys.exit(app.exec_())
