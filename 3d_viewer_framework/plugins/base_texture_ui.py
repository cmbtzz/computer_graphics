"""模型设置共用的纵向滚动区和可折叠分组，不修改查看器内核。"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QLayout, QScrollArea, QSizePolicy, QSplitter, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)

class ModelSettingsScroll(QScrollArea):
    resized = pyqtSignal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


def ensure_model_settings_scroll(ctx):
    """将原来的模型设置容器整体装入一个滚动区，后续插件继续向下添加。"""
    if getattr(ctx, "model_settings_scroll", None) is not None:
        return ctx.model_settings_scroll
    content = ctx.right_extension_panel
    parent = content.parentWidget()
    tabs = parent
    while tabs is not None and not isinstance(tabs, QTabWidget):
        tabs = tabs.parentWidget()
    scroll = ModelSettingsScroll()
    scroll.setObjectName("modelSettingsScroll")
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setMinimumWidth(300)
    if tabs is not None and tabs.indexOf(content) >= 0:
        index, active = tabs.indexOf(content), tabs.currentIndex()
        title = tabs.tabText(index)
        tabs.blockSignals(True)
        tabs.removeTab(index)
        scroll.setWidget(content)
        tabs.insertTab(index, scroll, title)
        tabs.setCurrentIndex(active)
        tabs.blockSignals(False)
    elif isinstance(parent, QSplitter):
        sizes = parent.sizes()
        parent.replaceWidget(parent.indexOf(content), scroll)
        scroll.setWidget(content)
        parent.setSizes(sizes)
        # replaceWidget 后需要显式显示；页签分支则由 QTabWidget 管理可见性。
        scroll.show()
    else:
        raise RuntimeError("未找到模型设置容器")
    ctx.right_extension_layout.setAlignment(Qt.AlignTop)
    ctx.right_extension_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
    ctx.right_extension_layout.setContentsMargins(8, 8, 8, 8)
    ctx.model_settings_scroll = scroll
    return scroll


class CollapsibleSection(QWidget):
    def __init__(self, title):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setArrowType(Qt.DownArrow)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setStyleSheet(
            "QToolButton { text-align:left; padding:8px; font-weight:bold; "
            "background:#e9edf2; border:1px solid #cbd2da; }"
        )
        layout.addWidget(self.header)
        self.body = QFrame()
        self.body.setFrameShape(QFrame.StyledPanel)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 10, 10, 10)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        self.header.toggled.connect(self.set_expanded)

    def set_expanded(self, expanded):
        self.body.setVisible(expanded)
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
