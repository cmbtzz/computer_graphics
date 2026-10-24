'''
框架内核：基础3D查看器底座，仅保留纯基础功能，所有扩展通过插件实现
作者：蔡洪斌
2026-06-24
'''
import sys
import os
from dataclasses import dataclass
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget,
                             QFileDialog, QPushButton, QTextEdit, QTreeView, QFileSystemModel, QSplitter,
                             QMenuBar, QMenu, QAction, QFrame, QAbstractItemView)
from PyQt5.QtCore import QDir, Qt, pyqtSignal
from core.scene_navigation import SceneNavigation
from core.model_normals import generate_normals


class SceneViewport(QVTKRenderWindowInteractor):
    files_dropped = pyqtSignal(list)
    scene_clicked = pyqtSignal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.press_position = None
        self.dragged = False
        self.navigation = None

    def obj_paths(self, event):
        return [url.toLocalFile() for url in event.mimeData().urls()
                if url.isLocalFile() and url.toLocalFile().lower().endswith('.obj')
                and os.path.isfile(url.toLocalFile())]

    def dragEnterEvent(self, event):
        if self.obj_paths(event):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = self.obj_paths(event)
        if paths:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.files_dropped.emit(paths)
        else:
            event.ignore()

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.RightButton:
            self.press_position = None
            if self.navigation:
                self.navigation.begin(event.pos())
            event.accept()
            return
        if self.navigation and self.navigation.looking:
            event.accept()
            return
        self.press_position = event.pos() if event.button() == Qt.LeftButton else None
        self.dragged = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.press_position is not None and (event.pos() - self.press_position).manhattanLength() > 4:
            self.dragged = True
        if self.navigation:
            self.navigation.look(event.pos())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            if self.navigation:
                self.navigation.stop()
            event.accept()
            return
        clicked = (event.button() == Qt.LeftButton and self.press_position is not None
                   and not self.dragged and (event.pos()-self.press_position).manhattanLength() <= 4)
        self.press_position = None
        if clicked:
            self.scene_clicked.emit(event.pos())
        event.accept()

    def keyPressEvent(self, event):
        if self.navigation:
            self.navigation.key_press(event)
        # 不再转发到 VTK，移除 W/S 线框、F fly-to、R 重置等默认快捷键。
        event.accept()

    def keyReleaseEvent(self, event):
        if self.navigation:
            self.navigation.key_release(event)
        event.accept()

    def wheelEvent(self, event):
        if self.navigation:
            self.navigation.wheel(event.angleDelta().y()/120)
        event.accept()

    def focusOutEvent(self, event):
        if self.navigation:
            self.navigation.stop()
        super().focusOutEvent(event)

    def hideEvent(self, event):
        if self.navigation:
            self.navigation.stop()
        super().hideEvent(event)


@dataclass
class SceneModel:
    name: str
    path: str
    actor: object
    polydata: object

class ViewerContext:
    """全局上下文，插件共享状态，避免各自重复存储变量"""
    def __init__(self):
        self.main_window = None
        self.vtk_renderer = None
        self.vtk_widget = None
        self.info_display = None
        self.right_extension_panel = None  # 插件面板挂载容器
        self.current_obj_path = None
        self.current_actor = None
        self.current_polydata = None
        self.current_model = None
        self.scene_models = []
        self.plugins = []  # 已加载插件实例列表

class VTKViewerCore(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Model Viewer Framework")
        self.setGeometry(100, 100, 1600, 800)

        # 全局上下文
        self.ctx = ViewerContext()
        self.ctx.main_window = self

        # 插件管理器
        self.plugin_instances = []

        self.create_menu()
        self.build_base_layout()
        self.init_vtk()

    def register_plugin(self, plugin_cls):
        """外部注册插件，入口main.py调用"""
        plugin = plugin_cls(self.ctx)
        self.plugin_instances.append(plugin)
        self.ctx.plugins.append(plugin)
        # 创建插件UI并挂载到右侧扩展面板
        panel = plugin.create_ui()
        if panel:
            self.ctx.right_extension_layout.addWidget(panel)

    def build_base_layout(self):
        """基础布局：文件树 | VTK窗口 | 右侧插件垂直容器"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_v_layout = QVBoxLayout(central_widget)
        main_v_layout.setSpacing(4)

        top_h_splitter = QSplitter(Qt.Horizontal)
        main_v_layout.addWidget(top_h_splitter, stretch=8)

        # 底部信息栏
        self.ctx.info_display = QTextEdit()
        self.ctx.info_display.setReadOnly(True)
        self.ctx.info_display.setMaximumHeight(160)
        main_v_layout.addWidget(self.ctx.info_display, stretch=1)

        # 左侧文件树
        self.tree_view = QTreeView()
        self.file_model = QFileSystemModel()
        self.file_model.setFilter(QDir.NoDotAndDotDot | QDir.AllDirs | QDir.Files)
        self.file_model.setNameFilters(["*.obj"])
        self.file_model.setNameFilterDisables(False)
        self.tree_view.setModel(self.file_model)
        # 单击只选择文件，避免拖拽之前触发旧的单模型替换逻辑。
        self.tree_view.setDragEnabled(True)
        self.tree_view.setDragDropMode(QAbstractItemView.DragOnly)
        self.tree_view.setDefaultDropAction(Qt.CopyAction)
        self.tree_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree_view.doubleClicked.connect(self.on_tree_item_clicked)
        for col in range(1, self.file_model.columnCount()):
            self.tree_view.hideColumn(col)
        self.file_model.setRootPath("")
        self.tree_view.setRootIndex(self.file_model.index(""))
        top_h_splitter.addWidget(self.tree_view)

        # 中间VTK窗口
        self.ctx.vtk_widget = SceneViewport(self)
        self.ctx.vtk_renderer = vtk.vtkRenderer()
        self.ctx.vtk_widget.GetRenderWindow().AddRenderer(self.ctx.vtk_renderer)
        self.ctx.vtk_widget.files_dropped.connect(self.import_dropped_models)
        self.ctx.vtk_widget.scene_clicked.connect(self.pick_model)
        self.selection_outline = vtk.vtkOutlineFilter()
        outline_mapper = vtk.vtkPolyDataMapper()
        outline_mapper.SetInputConnection(self.selection_outline.GetOutputPort())
        self.selection_actor = vtk.vtkActor()
        self.selection_actor.SetMapper(outline_mapper)
        self.selection_actor.GetProperty().SetColor(1.0, 0.55, 0.1)
        self.selection_actor.GetProperty().SetLineWidth(2)
        self.selection_actor.GetProperty().LightingOff()
        self.selection_actor.PickableOff()
        self.selection_actor.UseBoundsOff()
        self.selection_actor.VisibilityOff()
        self.ctx.vtk_renderer.AddActor(self.selection_actor)
        top_h_splitter.addWidget(self.ctx.vtk_widget)

        # 右侧：插件统一挂载容器
        right_container = QWidget()
        self.ctx.right_extension_layout = QVBoxLayout(right_container)
        self.ctx.right_extension_layout.setSpacing(8)
        self.ctx.right_extension_layout.setContentsMargins(0,0,0,0)
        self.ctx.right_extension_panel = right_container
        top_h_splitter.addWidget(right_container)

        top_h_splitter.setSizes([int(0.3*self.width()), int(0.5*self.width()), int(0.2*self.width())])
        top_h_splitter.setStretchFactor(1, 6)
        top_h_splitter.setStretchFactor(2, 4)

    def init_vtk(self):
        self.ctx.vtk_widget.navigation = SceneNavigation(self.ctx)
        self.ctx.vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(vtk.vtkInteractorStyleUser())
        self.ctx.vtk_widget.Initialize()
        self.ctx.vtk_widget.Start()

    def create_menu(self):
        menubar = self.menuBar()
        file_menu = QMenu("File", self)
        open_folder_action = QAction("Open Folder", self)
        open_folder_action.triggered.connect(self.open_folder)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(open_folder_action)
        file_menu.addAction(exit_action)
        menubar.addMenu(file_menu)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Folder", "")
        if folder:
            self.file_model.setRootPath(folder)
            self.tree_view.setRootIndex(self.file_model.index(folder))

    def on_tree_item_clicked(self, index):
        file_path = self.file_model.filePath(index)
        if os.path.isfile(file_path) and file_path.lower().endswith(".obj"):
            self.load_model(file_path)

    def load_model(self, file_name, append=False):
        """文件树保留单模型浏览；拖拽使用 append=True 追加独立实例。"""
        file_name = os.path.abspath(os.fspath(file_name))
        if not os.path.isfile(file_name) or not file_name.lower().endswith('.obj'):
            self.ctx.info_display.append('无法加载 OBJ：' + file_name)
            return False
        reader = vtk.vtkOBJReader()
        errors = []
        reader.AddObserver('ErrorEvent', lambda *_: errors.append(True))
        reader.SetFileName(file_name)
        reader.Update()
        polydata = reader.GetOutput()
        num_points = polydata.GetNumberOfPoints()
        num_faces = polydata.GetNumberOfCells()
        if errors or not num_points or not num_faces:
            self.ctx.info_display.append('OBJ 没有可显示的几何，已保留当前场景：' + file_name)
            return False

        polydata = generate_normals(polydata)
        num_points = polydata.GetNumberOfPoints()

        # 纯白顶点色
        color_array = vtk.vtkUnsignedCharArray()
        color_array.SetNumberOfComponents(3)
        color_array.SetName("VertexColors")
        for i in range(num_points):
            color_array.InsertNextTuple3(255,255,255)
        polydata.GetPointData().SetScalars(color_array)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetInterpolationToPhong()

        if not append:
            for model in self.ctx.scene_models:
                self.ctx.vtk_renderer.RemoveActor(model.actor)
            self.ctx.scene_models.clear()
        elif self.ctx.scene_models:
            # 保留源模型尺寸；新实例排在场景右侧，并对齐底部与 Z 中心。
            bounds = [model.actor.GetBounds() for model in self.ctx.scene_models]
            source = polydata.GetBounds()
            right = max(b[1] for b in bounds)
            bottom = min(b[2] for b in bounds)
            z_mid = (min(b[4] for b in bounds) + max(b[5] for b in bounds)) / 2
            size = max(source[1]-source[0], source[3]-source[2], source[5]-source[4], 0.001)
            scene_size = max(max(b[1]-b[0], b[3]-b[2], b[5]-b[4]) for b in bounds)
            actor.SetPosition(right + max(size, scene_size) * 0.15 - source[0],
                              bottom-source[2], z_mid-(source[4]+source[5])/2)
        base_name = os.path.basename(file_name)
        name = base_name
        number = 2
        while any(model.name == name for model in self.ctx.scene_models):
            name = f'{base_name} ({number})'
            number += 1
        model = SceneModel(name, file_name, actor, polydata)
        self.ctx.scene_models.append(model)

        # 更新全局上下文
        self.ctx.current_obj_path = file_name
        self.ctx.current_actor = actor
        self.ctx.current_polydata = polydata
        self.ctx.current_model = model

        self.ctx.vtk_renderer.AddActor(actor)
        self.add_axes(polydata)
        self.ctx.vtk_renderer.ResetCamera()
        self.ctx.vtk_widget.GetRenderWindow().Render()

        self.update_info(file_name, num_points, num_faces)

        # 分发插件钩子：模型加载完成
        for plugin in self.plugin_instances:
            plugin.on_model_loaded(file_name, actor, polydata)
        self.select_actor(actor)
        return True

    def import_dropped_models(self, paths):
        loaded = sum(self.load_model(path, append=True) for path in paths)
        if loaded:
            self.ctx.vtk_renderer.ResetCamera()
            self.ctx.vtk_widget.GetRenderWindow().Render()
            # 自动切换到已有的模型查看选项卡。
            for plugin in self.plugin_instances:
                if getattr(plugin, 'plugin_cls_name', '') == 'experiment1_color':
                    plugin.tabs.setCurrentIndex(1)
        self.ctx.info_display.append(f'拖拽导入 {loaded} 个模型；场景共 {len(self.ctx.scene_models)} 个。')

    def pick_model(self, point):
        widget = self.ctx.vtk_widget
        width, height = widget.GetRenderWindow().GetSize()
        x = round(point.x() * width / max(1, widget.width()))
        y = height - 1 - round(point.y() * height / max(1, widget.height()))
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.005)
        picker.PickFromListOn()
        for model in self.ctx.scene_models:
            picker.AddPickList(model.actor)
        picker.Pick(x, y, 0, self.ctx.vtk_renderer)
        self.select_actor(picker.GetActor())

    def select_actor(self, actor):
        model = next((m for m in self.ctx.scene_models if m.actor is actor), None)
        self.ctx.current_model = model
        self.ctx.current_actor = model.actor if model else None
        self.ctx.current_obj_path = model.path if model else None
        self.ctx.current_polydata = model.polydata if model else None
        if model:
            self.update_info(model.path, model.polydata.GetNumberOfPoints(), model.polydata.GetNumberOfCells())
            self.ctx.info_display.append(f'当前选中：{model.name}；场景共 {len(self.ctx.scene_models)} 个模型。')
        else:
            self.ctx.info_display.setPlainText(f'未选中物体；场景共 {len(self.ctx.scene_models)} 个模型。')
        for plugin in self.plugin_instances:
            plugin.on_selection_changed(self.ctx.current_obj_path, self.ctx.current_actor, self.ctx.current_polydata)
        self.refresh_selection()

    def refresh_selection(self):
        actor = self.ctx.current_actor
        self.selection_actor.SetVisibility(actor is not None)
        if actor is not None:
            self.selection_outline.SetInputData(self.ctx.current_polydata)
            self.selection_actor.SetUserMatrix(actor.GetMatrix())
        self.ctx.vtk_renderer.ResetCameraClippingRange()
        self.ctx.vtk_widget.GetRenderWindow().Render()

    def add_axes(self, polydata):
        """基础坐标轴，全局统一"""
        for prop in list(self.ctx.vtk_renderer.GetViewProps()):
            if isinstance(prop, vtk.vtkAxesActor):
                self.ctx.vtk_renderer.RemoveViewProp(prop)
        centroid = polydata.GetCenter()
        axes_actor = vtk.vtkAxesActor()
        axes_actor.SetTotalLength(15,15,15)
        x_c = axes_actor.GetXAxisCaptionActor2D()
        y_c = axes_actor.GetYAxisCaptionActor2D()
        z_c = axes_actor.GetZAxisCaptionActor2D()
        x_c.GetCaptionTextProperty().SetColor(1,0,0)
        y_c.GetCaptionTextProperty().SetColor(0,1,0)
        z_c.GetCaptionTextProperty().SetColor(0,0,1)
        x_c.GetCaptionTextProperty().SetFontSize(10)
        y_c.GetCaptionTextProperty().SetFontSize(10)
        z_c.GetCaptionTextProperty().SetFontSize(10)
        offset = 24
        x_c.SetAttachmentPoint(centroid[0]+offset, centroid[1], centroid[2])
        y_c.SetAttachmentPoint(centroid[0], centroid[1]+offset, centroid[2])
        z_c.SetAttachmentPoint(centroid[0], centroid[1], centroid[2]+offset)
        trans = vtk.vtkTransform()
        trans.Translate(centroid[0], centroid[1], centroid[2]+10)
        axes_actor.SetUserTransform(trans)
        self.ctx.vtk_renderer.AddActor(axes_actor)

    def update_info(self, obj_file, pts, faces):
        text = f"OBJ File: {obj_file}\nVertices: {pts}\nFaces: {faces}\n"
        self.ctx.info_display.setPlainText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 窗口缩放分发插件钩子
        for plugin in self.plugin_instances:
            plugin.on_window_resize()

    def closeEvent(self, event):
        self.ctx.vtk_widget.navigation.stop()
        # 程序关闭释放插件资源
        for plugin in self.plugin_instances:
            plugin.on_destroy()
        event.accept()
