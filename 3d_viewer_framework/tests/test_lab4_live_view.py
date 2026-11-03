"""验证光追同级页签、中心视口、持续刷新和自动场景同步。"""
from pathlib import Path
import sys
import time

import numpy as np
import yaml
from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt5.QtGui import QDropEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'3d_viewer_framework'))
from main import VTKViewerCore,auto_scan_plugins


def run():
    app=QApplication.instance() or QApplication([])
    window=VTKViewerCore(); classes=auto_scan_plugins()
    for key in yaml.safe_load((ROOT/'3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8'))['active_plugins']:
        window.register_plugin(classes[key])
    plugin=next(p for p in window.ctx.plugins if p.plugin_cls_name=='ray_tracing')
    view=plugin.trace_view
    view.max_size=(400,300)
    window.resize(1320,820); window.show()

    def wait_for(condition,seconds=20):
        end=time.monotonic()+seconds
        while not condition():
            app.processEvents(); QTest.qWait(20)
            assert not view.error,view.error
            assert time.monotonic()<end,'等待实时视口超时：'+plugin.status.text()

    try:
        tabs,stack=window.ctx.plugin_tabs,window.ctx.center_stack
        assert [tabs.tabText(i) for i in range(tabs.count())]==['实验1','模型查看','光线追踪']
        assert tabs.indexOf(plugin.tab_page)==2
        assert window.load_model(ROOT/'3d_viewer_framework/data/obj/bottle/bottle_0091.obj')
        actor=window.ctx.current_actor; actor.RotateX(-90)
        plugin.create_stage(); plugin.focus_panel()
        wait_for(lambda:view.frame_index>5)
        assert stack.currentWidget() is view and view.isVisible()
        assert not window.ctx.vtk_widget.isVisible()
        assert not isinstance(view.window(),QDialog) and view.window() is window
        print('PASS peer raytracing tab, embedded central viewport, no preview dialog',flush=True)

        revision=plugin.scene_revision
        start=view.frame_index
        wait_for(lambda:view.frame_index>=start+70)
        assert plugin.scene_revision==revision,'静态场景每帧重建 BVH'
        assert view.fps>0 and 'FPS:' in plugin.fps_label.text()
        print(f'PASS continuous independent rendering: {view.frame_index} frames, {view.fps:.1f} FPS, static BVH reused',flush=True)

        camera=window.ctx.vtk_renderer.GetActiveCamera()
        original=np.array(view.scene.camera['eye'])
        camera.Azimuth(12); required=view.frame_index+2
        wait_for(lambda:view.frame_index>=required)
        assert not np.allclose(view.scene.camera['eye'],original)
        assert plugin.scene_revision==revision,'相机移动重建了几何 BVH'
        print('PASS shared camera synchronized without rebuilding geometry',flush=True)

        start=plugin.scene_revision
        actor.AddPosition(plugin.scene_span()*.1,0,0)
        wait_for(lambda:plugin.scene_revision>start)
        original=float(view.scene.materials[0,0,3])
        plugin.controls['mirror'].setValue(.83)
        wait_for(lambda:abs(float(view.scene.materials[0,0,3])-.83)<1e-5)
        assert original!=float(view.scene.materials[0,0,3])
        light=next(p for p in window.ctx.plugins if p.plugin_cls_name=='light_control')
        old=np.array(view.scene.light['position'])
        light.controls['x'].setValue(light.controls['x'].value()+plugin.scene_span()*.2)
        wait_for(lambda:not np.allclose(view.scene.light['position'],old))
        print('PASS Transform, material and light automatically reach the central renderer',flush=True)

        position=np.array(camera.GetPosition())
        view.navigation.wheel(1)
        required=view.frame_index+2; wait_for(lambda:view.frame_index>=required)
        assert not np.allclose(camera.GetPosition(),position)
        QTest.mousePress(view,Qt.RightButton,pos=QPoint(70,70))
        assert view.navigation.looking
        view.navigation.look(QPoint(90,78))
        QTest.mouseRelease(view,Qt.RightButton,pos=QPoint(90,78))
        assert not view.navigation.looking
        print('PASS navigation in the central raytracing viewport',flush=True)

        eye=np.array(camera.GetPosition()); forward=np.array(camera.GetDirectionOfProjection())
        right=np.cross(forward,camera.GetViewUp()); right/=np.linalg.norm(right)
        up=np.cross(right,forward); relative=np.array(actor.GetCenter())-eye
        distance=np.dot(relative,forward)*np.tan(np.radians(camera.GetViewAngle())*.5)
        x=np.dot(relative,right)/distance/(view.width()/view.height())
        y=np.dot(relative,up)/distance
        window.select_actor(None)
        QTest.mouseClick(view,Qt.LeftButton,pos=QPoint(round((x+1)*view.width()/2),round((1-y)*view.height()/2)))
        assert window.ctx.current_actor is actor,'光追视口点击未选中对应模型'
        print('PASS world-ray picking uses the central viewport dimensions',flush=True)

        mime=QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(ROOT/'3d_viewer_framework/data/obj/bottle/bottle_0091.obj'))])
        drop=QDropEvent(QPointF(100,100),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        count=len(window.ctx.scene_models)
        view.dropEvent(drop)
        assert drop.isAccepted() and len(window.ctx.scene_models)==count+1
        assert tabs.currentWidget() is plugin.tab_page and stack.currentWidget() is view
        wait_for(lambda:len(view.scene.names)==count+1)
        print('PASS OBJ drop updates the scene and stays in the raytracing tab',flush=True)

        for index in (1,0,2,1,2):
            tabs.setCurrentIndex(index); app.processEvents(); QTest.qWait(120)
            assert stack.currentIndex()==index
            assert view.isVisible()==(index==2)
            assert window.ctx.vtk_widget.isVisible()==(index==1)
        window.resize(1450,900); QTest.qWait(250)
        assert view.isVisible() and stack.currentWidget() is view
        print('PASS tab visibility, repeated switches and resize',flush=True)
        print('All central realtime raytracing checks passed.',flush=True)
    finally:
        window.close(); app.processEvents()


if __name__=='__main__': run()
