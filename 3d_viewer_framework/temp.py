from PyQt5.QtWidgets import QWidget

class Base3DPlugin:
    """3D查看器插件基类，所有功能插件实现该接口"""
    # 约定：子类必须重写该值，作为json配置里的唯一标识
    plugin_cls_name = ""
    plugin_name = "base_plugin"
    plugin_desc = "基础插件模板"

    def __init__(self, viewer_ctx):
        self.ctx = viewer_ctx
        self.plugin_panel = None

    def create_ui(self):
        raise NotImplementedError("插件必须实现create_ui")

    def on_model_loaded(self, obj_path, actor, polydata):
        pass

    def on_render_update(self):
        pass

    def on_window_resize(self):
        pass

    def on_destroy(self):
        pass