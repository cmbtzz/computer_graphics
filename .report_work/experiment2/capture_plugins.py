import sys
from pathlib import Path
import json
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
import vtk
ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'source' / '3d_viewer_framework'
sys.path.insert(0, str(SRC))
from core.viewer_3d import VTKViewerCore
from plugins.plugin_mipmap import MipmapPlugin, FILTERS
from plugins.plugin_environment import EnvironmentMappingPlugin

app = QApplication([])
viewer = VTKViewerCore()
viewer.register_plugin(MipmapPlugin)
viewer.register_plugin(EnvironmentMappingPlugin)
viewer.resize(1400, 900)
viewer.show()
record = {}

def capture():
    viewer.load_model(str(SRC / 'data/obj/bottle/bottle_0043.obj'))
    m, e = viewer.plugin_instances
    # 用现有模型附加确定性的棋盘纹理，检查六种底层过滤参数。
    tcoord = vtk.vtkTextureMapToSphere()
    tcoord.SetInputData(viewer.ctx.current_actor.GetMapper().GetInput())
    tcoord.PreventSeamOn()
    tcoord.Update()
    viewer.ctx.current_actor.GetMapper().SetInputData(tcoord.GetOutput())
    reader = vtk.vtkPNGReader()
    reader.SetFileName(str(SRC / 'data/texture/texture1.png'))
    texture = vtk.vtkTexture()
    texture.SetInputConnection(reader.GetOutputPort())
    viewer.ctx.current_actor.SetTexture(texture)
    values = []
    for i in range(6):
        m.filter_combo.setCurrentIndex(i)
        viewer.ctx.vtk_widget.GetRenderWindow().Render()
        obj = texture.GetTextureObject()
        values.append([int(obj.GetMinificationFilter()), int(obj.GetMagnificationFilter())])
        assert values[-1] == [int(FILTERS[i][1]), int(FILTERS[i][2])]
    record['filter_parameters'] = values
    actor = viewer.ctx.current_actor
    for prop in list(viewer.ctx.vtk_renderer.GetViewProps()):
        if prop is not actor:
            viewer.ctx.vtk_renderer.RemoveViewProp(prop)
    viewer.ctx.vtk_renderer.ResetCamera(actor.GetBounds())
    e.background_check.setChecked(True)
    e.reflection_check.setChecked(True)
    QTimer.singleShot(2000, finish)

def finish():
    m, e = viewer.plugin_instances
    window = viewer.ctx.vtk_widget.GetRenderWindow()
    window.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(window)
    grab.ReadFrontBufferOff()
    grab.Update()
    png = vtk.vtkPNGWriter()
    png.SetFileName(str(ROOT / 'plugin-environment.png'))
    png.SetInputConnection(grab.GetOutputPort())
    png.Write()
    actor = viewer.ctx.current_actor
    record['shared_texture'] = bool(e.skybox.GetTexture() is e.texture and actor.GetProperty().GetTexture('mirrorPanorama') is e.texture)
    e.reflection_check.setChecked(False)
    record['ordinary_texture_restored'] = actor.GetTexture() is not None
    assert record['shared_texture'] and record['ordinary_texture_restored']
    (ROOT / 'plugin-verification.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record, indent=2))
    viewer.close()
    app.quit()

QTimer.singleShot(800, capture)
sys.exit(app.exec_())
