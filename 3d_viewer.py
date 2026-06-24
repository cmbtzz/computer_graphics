'''
(1) 功能说明：使用树形目录结构，查看3D模型（单窗口）
(2) 开发单位：
(3) 作者：蔡洪斌
(4) 联系方式：QQ7849952
(5) 创建日期：2026-06-23
(6) 重要修改：删除所有JSON标注、按label着色、FDI文字标签相关代码，仅纯白加载OBJ模型
'''
import sys
import os
import vtk
from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QPushButton, QTextEdit, QTreeView, QFileSystemModel, QSplitter, QMenuBar, QMenu, QAction)
from PyQt5.QtCore import QDir

class VTKViewer(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Model Viewer")
        self.setGeometry(100, 100, 1600, 800)  # 调整窗口大小

        # 创建菜单栏
        self.create_menu()

        # 设置主布局
        main_layout = QHBoxLayout()
        self.setCentralWidget(QWidget(self))
        self.centralWidget().setLayout(main_layout)

        # 创建树形文件显示区
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

        # 创建VTK渲染窗口
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_renderer = vtk.vtkRenderer()
        self.vtk_widget.GetRenderWindow().AddRenderer(self.vtk_renderer)

        # 创建信息显示区域
        self.info_display = QTextEdit(self)
        self.info_display.setReadOnly(True)

        # 创建分割布局
        splitter = QSplitter()
        splitter.addWidget(self.tree_view)
        splitter.addWidget(self.vtk_widget)
        splitter.addWidget(self.info_display)
        # 设置每个控件的初始比例
        splitter.setSizes([int(0.3 * self.width()), int(0.5 * self.width()), int(0.2 * self.width())])

        main_layout.addWidget(splitter)

        # 初始化交互
        self.vtk_widget.Initialize()
        self.vtk_widget.Start()

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
        # 直接纯白渲染模型
        self.render_model(file_name)

    def render_model(self, file_name):
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

        self.vtk_renderer.RemoveAllViewProps()
        self.vtk_renderer.AddActor(actor)

        # 添加坐标轴到模型质心上方
        self.add_axes(polydata)

        # 重置相机位置
        self.vtk_renderer.ResetCamera()

        # 更新渲染窗口
        self.vtk_widget.GetRenderWindow().Render()

        self.update_info_display(file_name, num_points, num_faces)

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = VTKViewer()
    viewer.show()
    sys.exit(app.exec_())