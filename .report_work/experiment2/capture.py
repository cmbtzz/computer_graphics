import importlib.util
import json
from pathlib import Path
import platform
import sys
import importlib.metadata

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer, QT_VERSION_STR, PYQT_VERSION_STR, Qt, QPoint
from PyQt5.QtGui import QKeyEvent, QWheelEvent
from OpenGL import GL as gl

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source' / '实验2'

def load(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

app = QApplication([])
mipmap = load('task1_mipmap')
environment = load('task2_environment')
records = {'python': sys.version.split()[0], 'os': platform.platform(),
           'qt': QT_VERSION_STR, 'pyqt': PYQT_VERSION_STR,
           'packages': {p: importlib.metadata.version(p) for p in ['numpy', 'Pillow', 'PyOpenGL', 'OpenEXR', 'vtk']}}
windows = []

def save(window, name):
    if window.view.error:
        raise RuntimeError(window.view.error)
    window.view.makeCurrent()
    gl.glFinish()
    assert window.view.grabFramebuffer().save(str(ROOT / name))
    window.view.doneCurrent()

def first():
    w = windows[0]
    w.view.makeCurrent()
    records['gl'] = {k: gl.glGetString(v).decode() for k, v in
                     [('version', gl.GL_VERSION), ('vendor', gl.GL_VENDOR), ('renderer', gl.GL_RENDERER)]}
    w.view.doneCurrent()
    w.view.set_checker(True)
    for i in range(6):
        w.filters.setCurrentIndex(i)
        app.processEvents()
        save(w, f'filter-{i+1}.png')
    # 相同过滤器下记录前移后的画面。
    w.view.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_W, Qt.NoModifier))
    records['corridor_after_w'] = w.view.eye.tolist()
    w.view.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_R, Qt.NoModifier))
    records['corridor_after_r'] = w.view.eye.tolist()
    w.close()
    e = environment.EnvironmentWindow()
    windows.append(e)
    e.show()
    QTimer.singleShot(1600, second)

def second():
    e = windows[-1]
    records['panorama_size'] = list(e.view.texture_shape)
    records['environment_texture_id'] = e.view.texture
    e.cube.setChecked(False)
    app.processEvents()
    save(e, 'environment-no-cube.png')
    e.cube.setChecked(True)
    e.view.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Plus, Qt.NoModifier))
    records['environment_near_distance'] = e.view.distance
    app.processEvents()
    save(e, 'environment-near.png')
    e.set_parameter('rotation', 60.)
    app.processEvents()
    save(e, 'environment-rotate.png')
    e.view.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_R, Qt.NoModifier))
    records['environment_reset_distance'] = e.view.distance
    (ROOT / 'verification.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(records, ensure_ascii=False, indent=2))
    e.close()
    app.quit()

app.setQuitOnLastWindowClosed(False)
w = mipmap.MipmapWindow()
windows.append(w)
w.show()
QTimer.singleShot(1000, first)
sys.exit(app.exec_())
