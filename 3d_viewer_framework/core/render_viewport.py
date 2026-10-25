"""将 Qt 的连续重绘和尺寸变化合并到下一帧，避免阻塞布局事件。"""

from PyQt5.QtCore import QElapsedTimer, QTimer
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkRenderingCore import vtkRenderWindow


class RenderViewport(QVTKRenderWindowInteractor):
    FRAME_INTERVAL_MS = 16
    RESIZE_SETTLE_MS = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self._size_dirty = True
        self._render_enabled = True
        self._interactive_resize = False
        self._frame_clock = QElapsedTimer()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        # 定时器只合并 update 请求，实际绘制仍在 Qt 的 paintEvent 内完成。
        self._render_timer.timeout.connect(self.update)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.request_render)

    def request_render(self):
        if (not self._render_enabled or not self.isVisible()
                or self._interactive_resize or self._resize_timer.isActive()
                or self._render_timer.isActive()):
            return
        delay = 0
        if self._frame_clock.isValid():
            delay = max(0, self.FRAME_INTERVAL_MS - self._frame_clock.elapsed())
        self._render_timer.start(delay)

    def paintEvent(self, event):
        self._render_timer.stop()
        self._render_pending()

    def resizeEvent(self, event):
        # 原实现每次 resize 都同步调整 VTK 缓冲区并追加一次 update。
        # 在真正绘制前只同步最终尺寸，省去拖动过程中的中间尺寸。
        self._size_dirty = True
        self._render_timer.stop()
        if self.isVisible() and not self._interactive_resize:
            self._resize_timer.start(self.RESIZE_SETTLE_MS)

    def showEvent(self, event):
        super().showEvent(event)
        self.request_render()

    def hideEvent(self, event):
        self._render_timer.stop()
        self._resize_timer.stop()
        super().hideEvent(event)

    def set_interactive_resize(self, resizing):
        """原生窗口拖动期间保留上一帧，松手后才同步 OpenGL 缓冲区。"""
        self._interactive_resize = resizing
        self._render_timer.stop()
        self._resize_timer.stop()
        if not resizing:
            self.request_render()

    def _render_pending(self):
        if (not self._render_enabled or not self.isVisible()
                or self._interactive_resize or self._resize_timer.isActive()):
            return
        if self._size_dirty:
            self._size_dirty = False
            scale = self._getPixelRatio()
            width = round(scale * self.width())
            height = round(scale * self.height())
            self._RenderWindow.SetDPI(round(72 * scale))
            vtkRenderWindow.SetSize(self._RenderWindow, width, height)
            self._Iren.SetSize(width, height)
            self._Iren.ConfigureEvent()
        self._frame_clock.start()
        self._Iren.Render()

    def stop_rendering(self):
        # 释放 renderer / OpenGL 上下文前，取消尚未执行的帧。
        self._render_enabled = False
        self._render_timer.stop()
        self._resize_timer.stop()

    def closeEvent(self, event):
        self.stop_rendering()
        super().closeEvent(event)
