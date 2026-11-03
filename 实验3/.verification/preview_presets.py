from pathlib import Path
import sys
from types import SimpleNamespace
import vtk
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'3d_viewer_framework'))
from plugins.base_material import MaterialStore,PRESETS
renderer=vtk.vtkRenderer();renderer.SetBackground(.045,.055,.075);renderer.AutomaticLightCreationOff()
window=vtk.vtkRenderWindow();window.SetOffScreenRendering(True);window.SetSize(1200,440);window.AddRenderer(renderer)
ctx=SimpleNamespace(main_window=None,scene_models=[],vtk_renderer=renderer)
store=MaterialStore(ctx)
for x,name in zip((-2.7,0,2.7),('金属','木材','塑料')):
 source=vtk.vtkSphereSource();source.SetRadius(1);source.SetThetaResolution(128);source.SetPhiResolution(96)
 mapper=vtk.vtkPolyDataMapper();mapper.SetInputConnection(source.GetOutputPort());mapper.Update()
 actor=vtk.vtkActor();actor.SetMapper(mapper);actor.SetPosition(x,0,0);renderer.AddActor(actor);ctx.scene_models.append(SimpleNamespace(actor=actor))
 store.preset(actor,name)
light=vtk.vtkLight();light.SetLightTypeToSceneLight();light.SetPositional(True);light.SetConeAngle(180);light.SetPosition(-3,4,7);light.SetIntensity(.8);renderer.AddLight(light)
renderer.ResetCamera();camera=renderer.GetActiveCamera();camera.SetPosition(0,0,8);camera.SetFocalPoint(0,0,0);camera.SetViewUp(0,1,0);renderer.ResetCameraClippingRange()
for x,name in zip((324,600,876),('METAL','WOOD','PLASTIC')):
 label=vtk.vtkTextActor();label.SetInput(name);label.SetDisplayPosition(x,25);label.GetTextProperty().SetFontSize(22);label.GetTextProperty().SetJustificationToCentered();renderer.AddViewProp(label)
window.Render();capture=vtk.vtkWindowToImageFilter();capture.SetInput(window);capture.ReadFrontBufferOff();capture.Update()
writer=vtk.vtkPNGWriter();writer.SetInputConnection(capture.GetOutputPort());writer.SetFileName(str(Path(__file__).parent/sys.argv[1]));writer.Write();window.Finalize()
