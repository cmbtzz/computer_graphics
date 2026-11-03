import importlib.util
import json
from pathlib import Path
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from OpenGL import GL as gl
ROOT = Path(__file__).resolve().parent
path = ROOT.parents[1] / '实验2/task1_mipmap.py'
spec = importlib.util.spec_from_file_location('corridor_with_end',path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app=QApplication([])
w=module.MipmapWindow()
w.show()

def save(name):
    app.processEvents()
    if w.view.error: raise RuntimeError(w.view.error)
    assert w.view.grabFramebuffer().save(str(ROOT/name))

def capture():
    w.view.makeCurrent()
    assert len(w.view.textures)==5
    gl.glBindTexture(gl.GL_TEXTURE_2D,w.view.textures[4])
    width=int(gl.glGetTexLevelParameteriv(gl.GL_TEXTURE_2D,0,gl.GL_TEXTURE_WIDTH))
    height=int(gl.glGetTexLevelParameteriv(gl.GL_TEXTURE_2D,0,gl.GL_TEXTURE_HEIGHT))
    assert width*2==height*3,(width,height)
    levels=[]
    for i in range(20):
        a=int(gl.glGetTexLevelParameteriv(gl.GL_TEXTURE_2D,i,gl.GL_TEXTURE_WIDTH))
        b=int(gl.glGetTexLevelParameteriv(gl.GL_TEXTURE_2D,i,gl.GL_TEXTURE_HEIGHT))
        if not a or not b:break
        levels.append([a,b])
        if (a,b)==(1,1):break
    assert levels[-1]==[1,1]
    w.view.doneCurrent()
    save('corridor.png')
    w.view.eye[2]=-94
    w.view.update()
    save('corridor-end-near.png')
    w.view.set_checker(True)
    save('corridor-end-near-checker.png')
    w.view.reset_camera()
    for i in range(6):
        w.filters.setCurrentIndex(i)
        save(f'filter-{i+1}.png')
    report={'texture_count':len(w.view.textures),'end_image_size':[width,height],
            'end_mipmap_levels':levels,'gl_error':int(gl.glGetError()),'near_camera_z':-94}
    assert report['gl_error']==0,report
    (ROOT/'corridor-end-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    w.close()
    app.quit()
QTimer.singleShot(1200,capture)
sys.exit(app.exec_())
