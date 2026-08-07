'''
(1) 功能说明：使用树形目录结构，查看3D模型（单窗口），支持纹理贴图映射
(2) 开发单位：
(3) 作者：蔡洪斌
(4) 联系方式：QQ7849952
(5) 创建日期：2026-06-23
(6) 重要修改：增加纹理映射功能，点击纹理按钮自动将纹理贴到当前3D模型；选中按钮橙色粗边框高亮；缩略图改为可点击按钮；固定5行4列纹理网格，四周留白，自适应正方形尺寸
'''
import sys
import os
import vtk
from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QTextEdit,
                             QTreeView, QFileSystemModel, QSplitter, QMenuBar, QMenu, QAction, QScrollArea, QGridLayout, QLabel, QFrame, QPushButton)
from PyQt5.QtCore import QDir, Qt, QSize, QTimer
from PyQt5.QtGui import QPixmap, QIcon

class VTKViewer(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Model Viewer")
        self.setGeometry(100, 100, 1600, 800)  # 调整窗口大小
        self.selected_texture_path = None  # 记录当前选中的纹理图片路径
        self.selected_texture_btn = None  # 保存当前选中纹理按钮
        self.current_obj_path = None      # 记录当前加载的OBJ模型路径
        self.current_actor = None         # 保存当前模型Actor，用于更换纹理

        # 创建菜单栏
        self.create_menu()

        # ============ 整体布局重构：垂直总布局 ============
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_v_layout = QVBoxLayout(central_widget)
        main_v_layout.setSpacing(4)

        # 上层水平三分栏：文件树 | VTK窗口 | 纹理缩略图滚动区
        top_h_splitter = QSplitter(Qt.Horizontal)
        main_v_layout.addWidget(top_h_splitter, stretch=8)

        # 底部：信息文本显示区
        self.info_display = QTextEdit(self)
        self.info_display.setReadOnly(True)
        self.info_display.setMaximumHeight(160)
        main_v_layout.addWidget(self.info_display, stretch=1)

        # ---------------------- 左侧树形文件区 ----------------------
        self.tree_view = QTreeView()
        self.file_model = QFileSystemModel()
        self.file_model.setFilter(QDir.NoDotAndDotDot | QDir.AllDirs | QDir.Files)
        self.file_model.setNameFilters(["*.obj"])
        self.file_model.setNameFilterDisables(False)
        self.tree_view.setModel(self.file_model)
        self.tree_view.clicked.connect(self.on_tree_item_clicked)

        # 隐藏不需要的列，只显示文件名
        for column in range(1, self.file_model.columnCount()):
            self.tree_view.hideColumn(column)

        # 设置初始根路径为所有盘符
        self.file_model.setRootPath("")
        self.tree_view.setRootIndex(self.file_model.index(""))
        top_h_splitter.addWidget(self.tree_view)

        # ---------------------- 中间VTK渲染窗口 ----------------------
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_renderer = vtk.vtkRenderer()
        self.vtk_widget.GetRenderWindow().AddRenderer(self.vtk_renderer)
        top_h_splitter.addWidget(self.vtk_widget)

        # ---------------------- 右侧纹理缩略图区域 ----------------------
        # 滚动容器
        self.texture_scroll = QScrollArea()
        self.texture_scroll.setWidgetResizable(True)
        self.texture_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.texture_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 网格布局承载缩略图按钮
        self.texture_container = QWidget()
        self.texture_grid = QGridLayout(self.texture_container)
        self.texture_grid.setSpacing(6)   # 格子之间的间距
        # 新增：上下左右外层留白，单位像素，按需调整数值
        self.texture_grid.setContentsMargins(15, 15, 15, 15)     # 参数顺序：左、上、右、下
        self.texture_scroll.setWidget(self.texture_container)
        top_h_splitter.addWidget(self.texture_scroll)

        # 设置三分栏初始宽度比例：树30%，VTK50%，纹理20%
        top_h_splitter.setSizes([int(0.3 * self.width()), int(0.5 * self.width()), int(0.2 * self.width())])

        # 上层水平分割器高度分配：VTK区域占上层60%，纹理区域占上层40%
        top_h_splitter.setStretchFactor(1, 6)
        top_h_splitter.setStretchFactor(2, 4)

        # 初始化交互
        self.vtk_widget.Initialize()
        self.vtk_widget.Start()

        # 窗口显示完成后再加载纹理
        QTimer.singleShot(100, self.load_texture_images)

    def on_texture_btn_click(self, clicked_btn, texture_path):
        # 先把上一个选中按钮恢复默认样式
        if self.selected_texture_btn is not None:
            self.selected_texture_btn.setStyleSheet("")
        # 设置当前点击按钮高亮边框
        clicked_btn.setStyleSheet("border:3px solid #ff4400;")
        # 保存状态
        self.selected_texture_btn = clicked_btn
        self.selected_texture_path = texture_path
        self.info_display.append(f"\n选中纹理贴图：{texture_path}")

        # 关键新增：如果已加载三维模型，自动映射纹理
        if self.current_obj_path is not None and self.current_actor is not None:
            self.apply_texture_to_model(texture_path)

    def create_empty_thumb_widget(self, thumb_size):
        """创建空白正方形占位按钮（无纹理，不可点击）"""
        empty_btn = QPushButton()
        empty_btn.setFixedSize(thumb_size, thumb_size)
        empty_btn.setEnabled(False)
        empty_btn.setStyleSheet("background-color:#eeeeee; border:1px solid #cccccc;")
        return empty_btn

    def apply_texture_to_model(self, tex_file_path):
        """给当前模型Actor加载纹理贴图，自动生成UV坐标映射"""
        # 1. 读取纹理图片
        tex_reader = vtk.vtkPNGReader()
        if tex_file_path.lower().endswith(".jpg") or tex_file_path.lower().endswith(".jpeg"):
            tex_reader = vtk.vtkJPEGReader()
        tex_reader.SetFileName(tex_file_path)
        tex_reader.Update()

        # 2. 创建纹理对象
        texture = vtk.vtkTexture()
        texture.SetInputData(tex_reader.GetOutput())
        texture.RepeatOn()  # 纹理重复平铺
        texture.InterpolateOn()

        # 3. 自动生成柱状UV坐标（通用简单映射，适配任意OBJ模型）
        tex_coord_gen = vtk.vtkTextureMapToCylinder()
        tex_coord_gen.SetInputData(self.current_actor.GetMapper().GetInput())
        tex_coord_gen.Update()

        # 4. 更新Mapper输入并绑定纹理
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(tex_coord_gen.GetOutput())
        self.current_actor.SetMapper(mapper)
        self.current_actor.SetTexture(texture)

        # 刷新渲染窗口
        self.vtk_widget.GetRenderWindow().Render()
        self.info_display.append(f"纹理已成功映射到模型：{os.path.basename(self.current_obj_path)}")

    def load_texture_images(self):
        """读取./data/texture下所有jpg/png，固定5行4列=20个正方形缩略图按钮
        1. 纹理区域高度占上层40%，VTK占60%
        2. 网格固定5行4列共20个位置
        3. 图片不足20则空白占位按钮，超过20启用垂直滚动
        4. 缩略图正方形尺寸自动适配纹理区域宽度均分，不显示文件名，图片以按钮图标展示，支持点击选中并自动贴纹理到模型
        """
        # 新增：重置选中按钮记录
        self.selected_texture_btn = None
        self.selected_texture_path = None

        texture_dir = "./data/texture"
        max_rows = 5
        max_cols = 4
        total_slots = max_rows * max_cols

        # 清空旧按钮控件
        while self.texture_grid.count():
            item = self.texture_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # 让4列自动均分宽度
        for col in range(max_cols):
            self.texture_grid.setColumnStretch(col, 1)

        # 安全获取可视宽度，避免0宽度计算错误
        viewport = self.texture_scroll.viewport()

        scroll_w = viewport.width()
        if scroll_w <= 10:
            scroll_w = 200
        spacing = self.texture_grid.spacing()
        # 取出网格左右外边距
        left_margin = self.texture_grid.contentsMargins().left()
        right_margin = self.texture_grid.contentsMargins().right()
        # 总可用宽度 = 视口宽度 - 左留白 - 右留白 - 列之间所有间距
        available_w = scroll_w - left_margin - right_margin - (max_cols - 1) * spacing
        thumb_size = int(available_w / max_cols)
        thumb_size = max(64, thumb_size)

        if not os.path.exists(texture_dir):
            img_paths = []
        else:
            img_ext = (".jpg", ".jpeg", ".png")
            img_paths = []
            for fname in sorted(os.listdir(texture_dir)):
                if fname.lower().endswith(img_ext):
                    full_path = os.path.join(texture_dir, fname)
                    img_paths.append(full_path)

        # 填充全部20个网格位置
        slot_idx = 0
        for r in range(max_rows):
            for c in range(max_cols):
                if slot_idx < len(img_paths):
                    # 有纹理图片，创建带图片图标的按钮
                    img_path = img_paths[slot_idx]
                    pix = QPixmap(img_path)
                    pix = pix.scaled(thumb_size, thumb_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

                    # 创建按钮，设置图标为纹理缩略图
                    tex_btn = QPushButton()
                    tex_btn.setFixedSize(thumb_size, thumb_size)
                    tex_btn.setIcon(QIcon(pix))
                    tex_btn.setIconSize(QSize(thumb_size - 8, thumb_size - 8))
                    # 绑定点击信号，传递当前纹理路径
                    tex_btn.clicked.connect(lambda checked, btn=tex_btn, path=img_path: self.on_texture_btn_click(btn, path))
                    self.texture_grid.addWidget(tex_btn, r, c)
                else:
                    # 空白占位按钮
                    empty_btn = self.create_empty_thumb_widget(thumb_size)
                    self.texture_grid.addWidget(empty_btn, r, c)
                slot_idx += 1

    def resizeEvent(self, event):
        """窗口大小变化时重新计算缩略图尺寸并重绘纹理按钮"""
        super().resizeEvent(event)
        # 移除实时刷新，改为延迟刷新，避免拖拽时反复计算
        QTimer.singleShot(50, self.load_texture_images)

    def create_menu(self):
        menubar = self.menuBar()

        # 文件菜单
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
        if os.path.isfile(file_path) and file_path.endswith(".obj"):
            self.load_model(file_path)

    def load_model(self, file_name):
        # 记录当前加载模型路径
        self.current_obj_path = file_name
        vtk.vtkObject.GlobalWarningDisplayOff()

        reader = vtk.vtkOBJReader()
        reader.SetFileName(file_name)
        reader.Update()

        polydata = reader.GetOutput()
        points = polydata.GetPoints()
        num_points = points.GetNumberOfPoints()
        num_faces = polydata.GetNumberOfCells()

        # 统一纯白色顶点
        color_array = vtk.vtkUnsignedCharArray()
        color_array.SetNumberOfComponents(3)
        color_array.SetName("VertexColors")
        for i in range(num_points):
            color_array.InsertNextTuple3(255, 255, 255)
        polydata.GetPointData().SetScalars(color_array)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        self.current_actor = actor  # 保存模型Actor用于后续贴纹理

        self.vtk_renderer.RemoveAllViewProps()
        self.vtk_renderer.AddActor(actor)

        # 添加坐标轴到模型质心上方
        self.add_axes(polydata)

        # 重置相机位置
        self.vtk_renderer.ResetCamera()

        # 更新渲染窗口
        self.vtk_widget.GetRenderWindow().Render()

        self.update_info_display(file_name, num_points, num_faces)

        # 如果已经提前选中了纹理，自动给新模型贴纹理
        if self.selected_texture_path is not None:
            self.apply_texture_to_model(self.selected_texture_path)

        return True

    def add_axes(self, polydata):
        """ 在模型的质心上方显示坐标轴 """
        centroid = polydata.GetCenter()

        axes_actor = vtk.vtkAxesActor()
        axes_actor.SetTotalLength(15, 15, 15)  # 设置XYZ轴长度

        # 获取 XYZ 轴的文本属性
        x_caption = axes_actor.GetXAxisCaptionActor2D()
        y_caption = axes_actor.GetYAxisCaptionActor2D()
        z_caption = axes_actor.GetZAxisCaptionActor2D()

        # 设置文本颜色
        x_caption.GetCaptionTextProperty().SetColor(1, 0, 0)  # X轴红色
        y_caption.GetCaptionTextProperty().SetColor(0, 1, 0)  # Y轴绿色
        z_caption.GetCaptionTextProperty().SetColor(0, 0, 1)  # Z轴蓝色

        # 调整字体大小（有bug，字号未变）
        x_caption.GetCaptionTextProperty().SetFontSize(10)
        y_caption.GetCaptionTextProperty().SetFontSize(10)
        z_caption.GetCaptionTextProperty().SetFontSize(10)

        # 使用 SetAttachmentPoint 设置 3D 位置
        text_offset = 24
        x_caption.SetAttachmentPoint(centroid[0] + text_offset, centroid[1], centroid[2])
        y_caption.SetAttachmentPoint(centroid[0], centroid[1] + text_offset, centroid[2])
        z_caption.SetAttachmentPoint(centroid[0], centroid[1], centroid[2] + text_offset)

        # 把坐标轴放在模型质心上方
        z_offset = 10
        transform = vtk.vtkTransform()
        transform.Translate(centroid[0], centroid[1], centroid[2] + z_offset)
        axes_actor.SetUserTransform(transform)

        self.vtk_renderer.AddActor(axes_actor)

    def update_info_display(self, obj_file, num_points, num_faces):
        info_text = (
            f"OBJ File: {obj_file}\n"
            f"Number of Vertices: {num_points}\n"
            f"Number of Faces: {num_faces}\n"
        )
        self.info_display.setPlainText(info_text)
        if self.selected_texture_path is not None:
            self.info_display.append(f"\n当前选中纹理：{self.selected_texture_path}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = VTKViewer()
    viewer.show()
    sys.exit(app.exec_())