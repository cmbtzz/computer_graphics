"""实验四：真实 Qt/VTK + GLSL 渲染、场景同步及 BVH 验证。"""
from pathlib import Path
import sys
import time

import numpy as np
import vtk
import yaml
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from vtkmodules.util.numpy_support import vtk_to_numpy

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'3d_viewer_framework'))
from main import VTKViewerCore,auto_scan_plugins
from core.lab4_scene import build_bvh,snapshot


def image_array(image):
    from PyQt5.QtGui import QImage
    image=image.convertToFormat(QImage.Format_RGBA8888)
    ptr=image.bits(); ptr.setsize(image.byteCount())
    return np.frombuffer(ptr,np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)[:,:image.width(),:3].copy()


def verify_bvh():
    random=np.random.default_rng(480)
    triangles=np.zeros((201,8,4),np.float32)
    triangles[:,0,:3]=random.uniform(-1,1,(201,3))
    triangles[:,1:3,:3]=random.uniform(-.4,.4,(201,2,3))
    nodes,ordered=build_bvh(triangles)
    def tri_hit(data,o,d):
        e1,e2=data[:,1,:3],data[:,2,:3]
        p=np.cross(d,e2); det=np.sum(e1*p,axis=1)
        safe=np.where(abs(det)>1e-9,det,1)
        t=o-data[:,0,:3]; u=np.sum(t*p,axis=1)/safe
        q=np.cross(t,e1); v=np.sum(d*q,axis=1)/safe
        distance=np.sum(e2*q,axis=1)/safe
        good=(abs(det)>1e-9)&(u>=0)&(v>=0)&(u+v<=1)&(distance>0)
        return float(np.min(np.where(good,distance,np.inf)))
    max_stack=0
    for _ in range(120):
        o=random.uniform(-2,2,3); d=random.normal(size=3); d/=np.linalg.norm(d)
        expected=tri_hit(triangles,o,d); found=np.inf; pending=[0]
        while pending:
            max_stack=max(max_stack,len(pending)); i=pending.pop(); low,high=nodes[i]
            a=(low[:3]-o)/d; b=(high[:3]-o)/d
            if max(np.minimum(a,b).max(),0)>min(np.maximum(a,b).min(),found): continue
            if high[3]>0:
                start,count=int(low[3]),int(high[3]); found=min(found,tri_hit(ordered[start:start+count],o,d))
            else: pending.extend([int(low[3]),int(-high[3])-1])
        assert (np.isinf(found) and np.isinf(expected)) or abs(found-expected)<1e-5,(found,expected)
    assert max_stack<64
    print('PASS BVH: 120 rays agree with exhaustive triangle intersection',flush=True)


def run():
    verify_bvh()
    output=ROOT/'实验4/.verification'; output.mkdir(exist_ok=True)
    app=QApplication.instance() or QApplication([])
    window=VTKViewerCore(); classes=auto_scan_plugins()
    for key in yaml.safe_load((ROOT/'3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8'))['active_plugins']:
        window.register_plugin(classes[key])
    plugins={p.plugin_cls_name:p for p in window.ctx.plugins}
    window.show(); plugins['experiment1_color'].tabs.setCurrentIndex(1)
    plugins['view_orientation'].local_renderer.DrawOff()
    plugin=plugins['ray_tracing']
    error_log=vtk.vtkStringOutputWindow(); previous=vtk.vtkOutputWindow.GetInstance()
    vtk.vtkOutputWindow.SetInstance(error_log)

    def settle(): app.processEvents(); QTest.qWait(40)
    def vtk_frame():
        window.ctx.vtk_widget.GetRenderWindow().Render(); settle()
        cap=vtk.vtkWindowToImageFilter(); cap.SetInput(window.ctx.vtk_widget.GetRenderWindow())
        cap.ReadFrontBufferOff(); cap.Update(); image=cap.GetOutput()
        width,height,_=image.GetDimensions()
        return vtk_to_numpy(image.GetPointData().GetScalars()).reshape(height,width,3).astype(np.float32)
    def gpu_frame(scene=None,**changes):
        view=plugin.trace_view
        if scene is not None: view.set_scene(scene)
        for key,value in changes.items(): setattr(view,key,value)
        view.restart(); start=time.monotonic(); required=view.frame_index+3
        while view.frame_index<required:
            settle()
            assert not view.error,view.error
            assert time.monotonic()-start<60,'GPU render timeout'
        return image_array(view.grabFramebuffer()).astype(np.float32)
    def changed(a,b,title,minimum=.15):
        delta=float(np.mean(abs(a-b))); assert delta>minimum,(title,delta)
        print(f'PASS {title}: mean pixel difference {delta:.3f}',flush=True)
    try:
        settle()
        assert window.load_model(ROOT/'3d_viewer_framework/data/obj/bottle/bottle_0091.obj')
        actor=window.ctx.current_actor
        actor.RotateX(-90)  # 此示例数据为 Z-up；由 Transform 转为 Y-up。
        actor.SetScale(1.1,.85,1.2); actor.RotateY(17)
        before=np.array([[actor.GetMatrix().GetElement(i,j) for j in range(4)] for i in range(4)])
        plugin.create_stage(); assert len(window.ctx.scene_models)==7
        plugin.create_stage(); assert len(window.ctx.scene_models)==7,'重复布景产生了重复物体'
        after=np.array([[actor.GetMatrix().GetElement(i,j) for j in range(4)] for i in range(4)])
        assert np.array_equal(before,after),'布景改变了导入模型 Transform'
        plugin.apply_preset('陶瓷'); plugin.bump_check.setChecked(True)
        plugin.controls['strength'].setValue(0)
        flat=vtk_frame()
        plugin.controls['strength'].setValue(.025)
        relief=vtk_frame(); changed(flat,relief,'VTK height-map shading',.03)
        assert flat.max()>100 and flat.mean()>15
        plugin.bump_check.setChecked(False); assert actor not in plugin.bindings
        assert actor.GetShaderProperty().GetVertexShaderCode() is None
        plugin.bump_check.setChecked(True)
        # 兼容原有全景镜面模式及会替换 mapper 的普通纹理插件。
        env=plugins['environment_mapping']
        env.reflection_check.setChecked(True); vtk_frame()
        assert actor not in plugin.bindings
        env.reflection_check.setChecked(False); vtk_frame()
        assert actor in plugin.bindings
        plugin.bump_check.setChecked(False); vtk_frame()
        assert actor.GetShaderProperty().GetVertexShaderCode() is None
        plugin.bump_check.setChecked(True)
        plugins['texture_mapping'].apply_texture(str(ROOT/'3d_viewer_framework/data/texture/texture4.png'))
        vtk_frame(); assert plugin.bindings[actor]['mapper'] is actor.GetMapper()
        assert snapshot(plugin).materials[0,3,3]>=0
        actor.SetTexture(None)
        print('PASS environment-mode restoration and ordinary texture/mapper compatibility',flush=True)
        # 有作者 UV 的模型、缺 UV 的模型都能进入快照，世界矩阵在 CPU 正确应用。
        scene=snapshot(plugin); assert len(scene.triangles)>1320 and len(scene.names)==7
        rows=scene.triangles[scene.triangles[:,7,2]==0]
        actual=np.concatenate((rows[:,0,:3],rows[:,0,:3]+rows[:,1,:3],rows[:,0,:3]+rows[:,2,:3]))
        bounds=np.array([m.actor.GetBounds() for m in window.ctx.scene_models])
        origin=(bounds[:,::2].min(axis=0)+bounds[:,1::2].max(axis=0))*.5
        scale=10/np.max(bounds[:,1::2].max(axis=0)-bounds[:,::2].min(axis=0))
        raw=vtk_to_numpy(actor.GetMapper().GetInput().GetPoints().GetData())
        expected=(raw@before[:3,:3].T+before[:3,3]-origin)*scale
        assert np.allclose(actual.min(axis=0),expected.min(axis=0),atol=1e-5)
        assert np.allclose(actual.max(axis=0),expected.max(axis=0),atol=1e-5)
        print('PASS stage idempotence, nonuniform scale/rotation/world-space snapshot, generated UV',flush=True)
        # 选择切换保存各物体独立的光学设置。
        plugin.controls['mirror'].setValue(.73)
        other=window.ctx.scene_models[-2].actor
        window.select_actor(other); plugin.controls['mirror'].setValue(.41)
        window.select_actor(actor); assert plugin.controls['mirror'].value()==.73
        plugin.apply_preset('镜面'); plugin.activate_raytracing(); assert plugin.trace_view.scene is not None,plugin.status.text()
        view=plugin.trace_view; view.max_size=(360,260)
        base=gpu_frame()
        changed(base,gpu_frame(reflection=False),'mesh reflections')
        view.reflection=True
        changed(base,gpu_frame(bump=False),'bump changes traced reflections',.03)
        view.bump=True
        changed(base,gpu_frame(shadows=False),'shadow-ray occlusion',.03)
        view.shadows=True
        plugin.apply_preset('玻璃'); glass_scene=snapshot(plugin)
        glass=gpu_frame(glass_scene)
        changed(glass,gpu_frame(refraction=False),'mesh refraction',.03)
        view.refraction=True
        plugin.apply_preset('镜面'); actor.AddPosition(plugin.scene_span()*.25,0,0)
        camera=window.ctx.vtk_renderer.GetActiveCamera(); camera.Azimuth(8)
        updated=snapshot(plugin)
        moved=gpu_frame(updated); changed(base,moved,'model Transform and camera refresh')
        light=plugins['light_control']; light.controls['x'].setValue(light.controls['x'].value()+plugin.scene_span())
        changed(moved,gpu_frame(snapshot(plugin)),'shared light position',.03)
        # 自定义高度常量的两种取值均无梯度；高度绝对值不能伪造法线变化。
        state=plugin.ensure(actor); state.height=np.full((73,137),.2,np.float32)
        first=gpu_frame(snapshot(plugin))
        state.height=np.full((73,137),.8,np.float32)
        second=gpu_frame(snapshot(plugin)); assert np.max(abs(first-second))<=1
        print('PASS constant custom height and non-square texture layers',flush=True)
        state.height=None
        actor.SetPosition(0,0,0)
        plugin.create_stage(); plugin.apply_preset('镜面'); plugin.focus_panel()
        view.max_size=(960,700)
        gpu_frame(snapshot(plugin))
        assert view.grabFramebuffer().save(str(output/'advanced_raytracing.png'))
        assert window.grab().save(str(output/'advanced_raytracing_window.png'))
        vtk_frame()
        cap=vtk.vtkWindowToImageFilter(); cap.SetInput(window.ctx.vtk_widget.GetRenderWindow()); cap.ReadFrontBufferOff(); cap.Update()
        writer=vtk.vtkPNGWriter(); writer.SetFileName(str(output/'advanced_scene.png')); writer.SetInputConnection(cap.GetOutputPort()); writer.Write()
        plugin.remove_stage(); assert len(window.ctx.scene_models)==1
        assert actor in {m.actor for m in window.ctx.scene_models}
        assert window.load_model(ROOT/'3d_viewer_framework/data/obj/bottle/bottle_0402.obj')
        assert len(plugin.states)==1 and not plugin.bindings
        assert window.load_model(ROOT/'3d_viewer_framework/data/obj/airplane/airplane_0012.obj')
        large=snapshot(plugin)
        assert len(large.triangles)>50000
        view.max_size=(360,260)
        assert gpu_frame(large).std()>5
        print(f'PASS imported airplane: {len(large.triangles):,} triangles traced through BVH',flush=True)
        log=error_log.GetOutput()
        assert 'ERR|' not in log,log[-5000:]
        print('PASS removal, model replacement cleanup, no VTK shader errors',flush=True)
        print('All advanced lab4 checks passed.',flush=True)
    finally:
        window.close(); app.processEvents(); vtk.vtkOutputWindow.SetInstance(previous)


if __name__=='__main__': run()
