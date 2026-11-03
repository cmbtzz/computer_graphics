"""启动集成“光线追踪”插件的模型查看器。"""
import argparse
import importlib.util
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'3d_viewer_framework'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',help='启动时加载 OBJ 模型，保留原始 Transform')
    parser.add_argument('--demo',action='store_true',help='布置演示场景；无 --model 时加载并摆正示例瓶子')
    parser.add_argument('--preset',choices=('陶瓷','金属','镜面','玻璃'),default='陶瓷')
    parser.add_argument('--screenshot',metavar='PNG',help='保存中心实时光追图和主窗口截图并退出，默认使用演示场景')
    parser.add_argument('--self-test',action='store_true',help='运行真实 GPU 集成验证后退出')
    args=parser.parse_args()
    if args.self_test:
        path=ROOT/'3d_viewer_framework/tests/test_lab4_rendering.py'
        spec=importlib.util.spec_from_file_location('lab4_verification',path)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.run(); return 0
    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import QApplication
    import yaml
    from main import VTKViewerCore,auto_scan_plugins
    app=QApplication(sys.argv[:1]); app.setFont(QFont('Microsoft YaHei',9))
    window=VTKViewerCore(); classes=auto_scan_plugins()
    config=yaml.safe_load((ROOT/'3d_viewer_framework/plugin_config.yaml').read_text(encoding='utf-8'))
    for key in config['active_plugins']: window.register_plugin(classes[key])
    plugin=next((p for p in window.ctx.plugins if p.plugin_cls_name=='ray_tracing'),None)
    if plugin is None: parser.error('plugin_config.yaml 中未启用 ray_tracing')
    window.show(); plugin.focus_panel()
    obj_dir=ROOT/'3d_viewer_framework/data/obj'
    window.file_model.setRootPath(str(obj_dir)); window.tree_view.setRootIndex(window.file_model.index(str(obj_dir)))
    demo=args.demo or (args.screenshot is not None and not args.model)
    model=Path(args.model).resolve() if args.model else obj_dir/'bottle/bottle_0091.obj' if demo else None
    if model is not None:
        if not window.load_model(model):
            print('无法加载模型：'+str(model),file=sys.stderr); window.close(); return 1
        if demo and not args.model:
            # 内置 ModelNet 示例是 Z-up；仅示例模式显式调整朝向。
            window.ctx.current_actor.RotateX(-90)
        if demo: plugin.create_stage()
        plugin.apply_preset(args.preset); plugin.bump_check.setChecked(True); plugin.focus_panel()
    if args.screenshot:
        plugin.activate_raytracing()
        if plugin.trace_view.scene is None:
            print(plugin.status.text(),file=sys.stderr); window.close(); return 1
        view=plugin.trace_view
        capture_after=None
        deadline=time.monotonic()+120
        def finish():
            nonlocal capture_after
            if view.error or time.monotonic()>deadline:
                print(view.error or '光追截图超时',file=sys.stderr,flush=True)
                timer.stop(); window.close(); app.exit(1); return
            if view.frame_index<3: return
            if capture_after is None:
                capture_after=time.monotonic()+1.5
                return
            if time.monotonic()<capture_after: return
            path=Path(args.screenshot).resolve(); path.parent.mkdir(parents=True,exist_ok=True)
            success=view.grabFramebuffer().save(str(path))
            success=window.grab().save(str(path.with_name(path.stem+'_window.png'))) and success
            print(('Saved: ' if success else '保存失败：')+str(path),flush=True)
            timer.stop(); window.close(); app.exit(0 if success else 1)
        timer=QTimer(window); timer.timeout.connect(finish); timer.start(100)
    return app.exec_()


if __name__=='__main__': sys.exit(main())
