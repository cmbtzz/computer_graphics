"""光线追踪：独立页签及中心视口的实时三角网格渲染。"""
from pathlib import Path

import numpy as np
import vtk
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QLabel, QPushButton, QSizePolicy, QScrollArea,
    QSpinBox, QSplitter, QStackedWidget, QTabWidget,
)
from core.lab4_scene import LabMaterial, height_pattern, prepare_polydata, read_height, snapshot, vtk_texture
from core.viewer_3d import SceneModel
from plugins.base_material import material_store
from plugins.base_plugin import Base3DPlugin
from plugins.base_texture_ui import CollapsibleSection, ensure_model_settings_scroll

SHADERS=Path(__file__).resolve().parents[1]/'shaders/lab4'
PATTERNS=('雕刻花纹','错缝砖纹','流动波纹','细密颗粒')
PRESETS={
    '陶瓷': ((.12,.48,.35),.08,0.,1.5,.65,90.),
    '金属': ((.73,.78,.86),.78,0.,1.5,.9,130.),
    '镜面': ((.96,.98,1.),.97,0.,1.5,1.,180.),
    '玻璃': ((.90,.97,.99),0.,.98,1.5,.9,180.),
}


class RayTracingPlugin(Base3DPlugin):
    plugin_cls_name='ray_tracing'
    plugin_name='光线追踪'
    plugin_desc='光线追踪：演示布景、凹凸映射与 OBJ 光追'

    def __init__(self,ctx):
        super().__init__(ctx)
        self.store=material_store(ctx)
        self.states={}; self.bindings={}; self.controls={}
        self.environment_actors=set()
        self.trace_view=None; self.syncing=False; self.light_size=.55
        self._scene_key=None; self._syncing_scene=False; self.scene_revision=0
        self.saved_background=None; self.emitter=None
        self.bump_vertex=(SHADERS/'bump.vert').read_text(encoding='utf-8')
        self.bump_fragment=(SHADERS/'bump.frag').read_text(encoding='utf-8')

    def ensure(self,actor):
        if actor not in self.states:
            self.states[actor]=LabMaterial(mirror=.65 if self.store.ensure(actor).preset=='金属' else .08)
        return self.states[actor]

    def create_ui(self):
        ensure_model_settings_scroll(self.ctx)
        from core.lab4_preview import MeshTraceView
        self.trace_view=MeshTraceView(plugin=self)
        self.plugin_panel=CollapsibleSection('光线追踪')
        layout=self.plugin_panel.body_layout
        help_text=QLabel('中心窗口持续实时渲染当前场景。\n右键观察 / 右键 + WASD 飞行 / 滚轮移动 / F 聚焦。')
        help_text.setWordWrap(True); layout.addWidget(help_text)
        self.fps_label=QLabel('FPS: -- · 等待加载模型'); layout.addWidget(self.fps_label)
        self.trace_view.fps_changed.connect(self.show_fps)
        self.trace_view.failed.connect(lambda error:self.status.setText('渲染失败：'+error[:350]))
        quality=QFormLayout(); layout.addLayout(quality)
        for key,title,low,high,value in (('depth','最大弹射深度',0,6,5),('shadow_samples','单帧阴影质量',1,8,1)):
            spin=QSpinBox(); spin.setRange(low,high); spin.setValue(value)
            spin.valueChanged.connect(lambda value,k=key:self.set_render_parameter(k,value)); quality.addRow(title,spin)
        for key,title,low,high,step,value in (
            ('render_scale','内部渲染比例',.25,1.,.25,.5),('environment_strength','环境亮度',0.,3.,.1,.65)):
            spin=QDoubleSpinBox(); spin.setRange(low,high); spin.setSingleStep(step); spin.setValue(value)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda value,k=key:self.set_render_parameter(k,value)); quality.addRow(title,spin)
        for key,title in (('reflection','镜面反射'),('refraction','玻璃折射'),('bump','光追凹凸映射'),('shadows','阴影遮挡')):
            checkbox=QCheckBox(title); checkbox.setChecked(True)
            checkbox.toggled.connect(lambda value,k=key:self.set_render_parameter(k,value)); layout.addWidget(checkbox)
        save=QPushButton('保存中心渲染图'); save.clicked.connect(self.save_render); layout.addWidget(save)
        self.selection=QLabel('先加载并选中 OBJ 模型'); self.selection.setWordWrap(True); layout.addWidget(self.selection)
        for title,callback in (('一键创建 / 更新演示场景',self.create_stage),('移除演示布景',self.remove_stage)):
            button=QPushButton(title); button.clicked.connect(callback); layout.addWidget(button)
        form=QFormLayout(); layout.addLayout(form)
        self.preset_combo=QComboBox(); self.preset_combo.addItems(PRESETS)
        self.preset_combo.activated[str].connect(self.apply_preset); form.addRow('实验材质',self.preset_combo)
        for key,title,low,high,step in (
            ('mirror','镜面反射比例',0,1,.05),('transmission','透明透射比例',0,1,.05),
            ('ior','折射率',1,2.5,.05),('strength','凹凸强度 / 尺寸',-.1,.1,.005),
            ('tile_u','U 方向重复',1,20,1),('tile_v','V 方向重复',1,20,1)):
            box=QDoubleSpinBox(); box.setRange(low,high); box.setDecimals(3); box.setSingleStep(step)
            box.setKeyboardTracking(False); box.setMinimumWidth(0)
            box.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
            box.valueChanged.connect(lambda v,k=key:self.edit(k,v)); self.controls[key]=box; form.addRow(title,box)
        self.bump_check=QCheckBox('启用凹凸映射')
        self.bump_check.setToolTip('仅作用于当前选中物体，独立保存其高度图和参数')
        self.bump_check.toggled.connect(lambda v:self.edit('bump',v)); layout.addWidget(self.bump_check)
        self.pattern_combo=QComboBox(); self.pattern_combo.addItems(PATTERNS)
        self.pattern_combo.setPlaceholderText('自定义高度图')
        for combo in (self.pattern_combo,self.preset_combo):
            combo.setMinimumWidth(0); combo.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed)
        self.pattern_combo.activated[int].connect(self.change_pattern); form.addRow('高度图',self.pattern_combo)
        load=QPushButton('加载选中模型的高度图…'); load.clicked.connect(self.load_height); layout.addWidget(load)
        color=QPushButton('修改选中模型颜色…'); color.clicked.connect(self.choose_color); layout.addWidget(color)
        self.height_label=QLabel(); self.height_label.setWordWrap(True); layout.addWidget(self.height_label)
        self.status=QLabel('加载模型后自动同步到中心光追视口，可创建演示布景观察倒影和阴影。')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.observer=self.ctx.vtk_renderer.AddObserver('StartEvent',self.prepare_render)
        self.store.changed.connect(self.material_changed)
        menu=self.ctx.main_window.menuBar().addMenu('光线追踪')
        for title,callback in (('显示光线追踪参数',self.focus_panel),('创建演示场景',self.create_stage),
                               ('切换到实时光线追踪',self.activate_raytracing),('移除演示布景',self.remove_stage)):
            menu.addAction(title,callback)
        self.mount_tab()
        self.on_selection_changed(None,None,None)
        return None

    def mount_tab(self):
        tabs=getattr(self.ctx,'plugin_tabs',None)
        stack=getattr(self.ctx,'center_stack',None)
        if tabs is None:
            model_scroll=self.ctx.model_settings_scroll
            splitter=model_scroll.parentWidget()
            if not isinstance(splitter,QSplitter): raise RuntimeError('未找到中心视口的三栏布局')
            sizes=splitter.sizes()
            center_index,right_index=splitter.indexOf(self.ctx.vtk_widget),splitter.indexOf(model_scroll)
            stack=QStackedWidget()
            model_view=splitter.replaceWidget(center_index,stack); stack.addWidget(model_view)
            tabs=QTabWidget(); model_page=splitter.replaceWidget(right_index,tabs)
            model_page._center_view=model_view; tabs.addTab(model_page,'模型查看')
            tabs.currentChanged.connect(lambda _:stack.setCurrentWidget(tabs.currentWidget()._center_view))
            self.ctx.plugin_tabs,self.ctx.center_stack=tabs,stack
            stack.show(); tabs.show(); splitter.setSizes(sizes)
        self.tab_page=QScrollArea()
        self.tab_page.setWidgetResizable(True); self.tab_page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tab_page.setMinimumWidth(300); self.tab_page.setWidget(self.plugin_panel)
        self.tab_page._center_view=self.trace_view
        stack.addWidget(self.trace_view)
        tabs.addTab(self.tab_page,'光线追踪')
        tabs.currentChanged.connect(self.on_tab_changed)
        light=self.light_plugin()
        if light is not None: self.trace_view.installEventFilter(light.key_filter)

    def on_tab_changed(self,*_):
        if self.ctx.plugin_tabs.currentWidget() is self.tab_page:
            self.ctx.center_stack.setCurrentWidget(self.trace_view)
            self.sync_live_scene(); self.trace_view.update()

    def set_render_parameter(self,key,value):
        setattr(self.trace_view,key,value); self.trace_view.update()

    def show_fps(self,fps):
        self.fps_label.setText(f'FPS: {fps:.1f} · {1000/max(fps,.001):.1f} ms · 实时渲染')

    def save_render(self):
        path,_=QFileDialog.getSaveFileName(self.ctx.main_window,'保存中心光追画面','raytracing.png','PNG 图片 (*.png)')
        if path and not self.trace_view.grabFramebuffer().save(path): self.status.setText('无法保存：'+path)

    def pick_in_view(self,point,width,height):
        """按光追视口实际宽高构造世界射线，避免隐藏 VTK 视口的尺寸影响拾取。"""
        camera=self.ctx.vtk_renderer.GetActiveCamera()
        origin=np.array(camera.GetPosition(),float)
        forward=np.array(camera.GetDirectionOfProjection(),float)
        right=np.cross(forward,camera.GetViewUp()); right/=np.linalg.norm(right)
        up=np.cross(right,forward)
        x=(2.*point.x()/max(width,1)-1.)*width/max(height,1)
        y=1.-2.*point.y()/max(height,1)
        offset=right*x+up*y
        if camera.GetParallelProjection():
            origin+=offset*camera.GetParallelScale(); direction=forward
        else:
            direction=forward+offset*np.tan(np.radians(camera.GetViewAngle())*.5)
            direction/=np.linalg.norm(direction)
        picker=vtk.vtkCellPicker(); picker.SetTolerance(.005); picker.PickFromListOn()
        for model in self.ctx.scene_models:
            if model.actor.GetVisibility(): picker.AddPickList(model.actor)
        end=origin+direction*max(camera.GetClippingRange()[1]*2.,1.)
        picker.Pick3DPoint(origin,end,self.ctx.vtk_renderer)
        self.ctx.main_window.select_actor(picker.GetActor())

    def focus_panel(self):
        self.ctx.plugin_tabs.setCurrentWidget(self.tab_page)
        self.plugin_panel.set_expanded(True)

    def activate_raytracing(self,*_):
        self.focus_panel(); self.sync_live_scene()

    def on_selection_changed(self,path,actor,polydata):
        self.syncing=True
        self.selection.setText('选中：'+self.ctx.current_model.name if actor else '先加载并选中 OBJ 模型')
        for widget in [*self.controls.values(),self.preset_combo,self.bump_check,self.pattern_combo]: widget.setEnabled(actor is not None)
        if actor is not None:
            state=self.ensure(actor)
            for key,widget in self.controls.items():
                widget.setValue(state.tiling[0 if key=='tile_u' else 1] if key.startswith('tile_') else getattr(state,key))
            self.bump_check.setChecked(state.bump)
            self.pattern_combo.setCurrentIndex(state.pattern)
            self.preset_combo.setCurrentText(state.preset if state.preset in PRESETS else '陶瓷')
            self.height_label.setText(state.height_name+'；强度以物体最长边为单位。')
        else: self.height_label.setText('设置保存在各个物体上。')
        self.syncing=False

    def material_changed(self,actor):
        if actor is self.ctx.current_actor or actor is None:
            self.on_selection_changed(self.ctx.current_obj_path,self.ctx.current_actor,self.ctx.current_polydata)

    def on_model_loaded(self,*_):
        self._scene_key=None
        self.prune()

    def on_environment_mode_changed(self,actor,enabled):
        if enabled:
            self.environment_actors.add(actor)
            self.unbind(actor)
        else:
            self.environment_actors.discard(actor)
            if actor in self.states and self.ensure(actor).bump and actor not in self.bindings:
                self.bind(actor)

    def prune(self):
        active={m.actor for m in self.ctx.scene_models}
        for actor in list(self.bindings):
            if actor not in active: self.unbind(actor)
        self.states={a:s for a,s in self.states.items() if a in active}
        self.environment_actors.intersection_update(active)
        if self.emitter not in active: self.emitter=None

    def edit(self,key,value):
        actor=self.ctx.current_actor
        if self.syncing or actor is None: return
        state=self.ensure(actor)
        if key.startswith('tile_'):
            values=list(state.tiling); values[0 if key=='tile_u' else 1]=value; state.tiling=tuple(values)
        else: setattr(state,key,value)
        self.render()

    def apply_preset(self,name):
        actor=self.ctx.current_actor
        if actor is None: return
        color,mirror,transmission,ior,specular,shininess=PRESETS[name]
        state=self.ensure(actor); state.preset=name
        state.mirror,state.transmission,state.ior=mirror,transmission,ior
        self.store.edit(actor,diffuse_color=color,ambient_color=color,specular=specular,shininess=shininess)
        self.on_selection_changed(self.ctx.current_obj_path,actor,self.ctx.current_polydata); self.render()

    def change_pattern(self,index):
        actor=self.ctx.current_actor
        if actor is None or index<0: return
        state=self.ensure(actor); state.pattern=index; state.height=None; state.height_name=PATTERNS[index]
        if actor in self.bindings: self.unbind(actor)
        self.on_selection_changed(None,actor,None); self.render()

    def load_height(self):
        actor=self.ctx.current_actor
        if actor is None: return
        path,_=QFileDialog.getOpenFileName(self.ctx.main_window,'选择灰度高度图','','图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)')
        if not path: return
        try:
            data=read_height(path); state=self.ensure(actor)
            state.height=data; state.height_name=Path(path).name; state.pattern=-1; state.bump=True
            if actor in self.bindings: self.unbind(actor)
            self.on_selection_changed(None,actor,None); self.render()
        except ValueError as exc: self.status.setText(str(exc))

    def choose_color(self):
        actor=self.ctx.current_actor
        if actor is None: return
        color=QColorDialog.getColor(QColor.fromRgbF(*self.store.ensure(actor).diffuse_color),self.ctx.main_window,'材质颜色')
        if color.isValid():
            rgb=(color.redF(),color.greenF(),color.blueF())
            self.store.edit(actor,diffuse_color=rgb,ambient_color=rgb); self.render()

    def render(self):
        if self.trace_view is not None and self.trace_view.isVisible():
            self.sync_live_scene(); self.trace_view.update()
        else: self.ctx.vtk_widget.GetRenderWindow().Render()

    def unbind(self,actor):
        binding=self.bindings.pop(actor,None)
        if binding is None: return
        shader=actor.GetShaderProperty()
        if shader.GetVertexShaderCode()==self.bump_vertex: shader.SetVertexShaderCode(binding['vertex'])
        if shader.GetFragmentShaderCode()==self.bump_fragment: shader.SetFragmentShaderCode(binding['fragment'])
        actor.GetProperty().RemoveTexture('lab4Height')
        binding['mapper'].RemoveObserver(binding['observer'])
        if binding['mapper'].GetInput() is binding['poly']:
            binding['mapper'].SetInputData(binding['original'])

    def bind(self,actor):
        self.unbind(actor)
        # 全景插件恢复的旧 shader 快照可能含有本插件此前的完整代码。
        # 先移除孤立代码，避免把自己的 shader 当成关闭后的恢复目标。
        shader=actor.GetShaderProperty()
        if shader.GetVertexShaderCode()==self.bump_vertex: shader.SetVertexShaderCode(None)
        if shader.GetFragmentShaderCode()==self.bump_fragment: shader.SetFragmentShaderCode(None)
        mapper=actor.GetMapper(); original=mapper.GetInput()
        poly=prepare_polydata(original)
        poly.GetPointData().GetTCoords().SetName('Lab4UV')
        mapper.SetInputData(poly)
        mapper.MapDataArrayToVertexAttribute('lab4UV','Lab4UV',vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS,-1)
        state=self.ensure(actor)
        data=state.height if state.height is not None else height_pattern(state.pattern)
        texture=vtk_texture(np.repeat(data[...,None],3,axis=-1))
        actor.GetProperty().RemoveTexture('lab4Height')
        actor.GetProperty().SetTexture('lab4Height',texture)
        shader=actor.GetShaderProperty()
        vertex,fragment=shader.GetVertexShaderCode(),shader.GetFragmentShaderCode()
        shader.SetVertexShaderCode(self.bump_vertex); shader.SetFragmentShaderCode(self.bump_fragment)
        callback=lambda mapper,event,program,a=actor:self.update_uniforms(a,program)
        callback=vtk.calldata_type(vtk.VTK_OBJECT)(callback)
        observer=mapper.AddObserver(vtk.vtkCommand.UpdateShaderEvent,callback)
        self.bindings[actor]=dict(mapper=mapper,original=original,poly=poly,texture=texture,
                                  vertex=vertex,fragment=fragment,observer=observer,callback=callback)

    def prepare_render(self,*_):
        self.prune()
        if self.emitter is not None:
            lamp=self.light_plugin()
            if lamp: self.emitter.SetPosition(*lamp.scene_light.GetPosition())
        for model in self.ctx.scene_models:
            actor=model.actor; state=self.ensure(actor)
            # 与上一实验的独立全景镜面着色模式互斥，关闭镜面后自动恢复凹凸。
            active=state.bump and actor not in self.environment_actors and actor.GetProperty().GetTexture('mirrorPanorama') is None
            if active:
                binding=self.bindings.get(actor)
                if binding is None or binding['mapper'] is not actor.GetMapper() or binding['poly'] is not actor.GetMapper().GetInput():
                    self.bind(actor)
            elif actor in self.bindings: self.unbind(actor)
            else:
                shader=actor.GetShaderProperty()
                if shader.GetVertexShaderCode()==self.bump_vertex: shader.SetVertexShaderCode(None)
                if shader.GetFragmentShaderCode()==self.bump_fragment:
                    shader.SetFragmentShaderCode(None); actor.GetProperty().RemoveTexture('lab4Height')

    def update_uniforms(self,actor,program):
        if actor.GetShaderProperty().GetFragmentShaderCode()!=self.bump_fragment: return
        state,base=self.ensure(actor),self.store.ensure(actor)
        lamp=self.light_plugin()
        position=lamp.scene_light.GetPosition() if lamp else self.ctx.vtk_renderer.GetActiveCamera().GetPosition()
        view=self.ctx.vtk_renderer.GetActiveCamera().GetViewTransformMatrix()
        position=view.MultiplyPoint((*position,1))[:3]
        bounds=actor.GetBounds(); span=max(bounds[1]-bounds[0],bounds[3]-bounds[2],bounds[5]-bounds[4],1e-9)
        active=self.store.enabled
        floats=dict(lab4Strength=state.strength*span,lab4Diffuse=base.diffuse if active and self.store.components['diffuse'] else 0.,
                    lab4Specular=base.specular if active and self.store.components['specular'] else 0.,lab4Shininess=base.shininess,
                    lab4Ambient=base.ambient*self.store.ambient_intensity*self.store.light_intensity if active and self.store.components['ambient'] else 0.,
                    lab4LightPower=self.store.light_intensity if active else 0.)
        for name,value in floats.items():
            if program.IsUniformUsed(name): program.SetUniformf(name,value)
        for name,value in dict(lab4Color=base.diffuse_color,lab4Emission=base.emission*np.array(base.emission_color)+np.array(state.emission),
                               lab4LightVC=position,lab4LightColor=self.store.light_rgb).items():
            if program.IsUniformUsed(name): program.SetUniform3f(name,value)
        if program.IsUniformUsed('lab4Tiling'): program.SetUniform2f('lab4Tiling',state.tiling)
        if program.IsUniformUsed('lab4HasAlbedo'): program.SetUniformi('lab4HasAlbedo',int(actor.GetTexture() is not None))

    def light_plugin(self):
        return next((p for p in self.ctx.plugins if p.plugin_cls_name=='light_control'),None)

    def imported_models(self):
        return [m for m in self.ctx.scene_models if not getattr(m,'lab4_stage',False)]

    def scene_span(self):
        models=self.imported_models()
        if not models: return 1.
        b=np.array([m.actor.GetBounds() for m in models])
        return max(float(np.max(b[:,1::2].max(axis=0)-b[:,::2].min(axis=0))),1e-6)

    def remove_stage(self,*_,restore=True):
        for model in list(self.ctx.scene_models):
            if getattr(model,'lab4_stage',False):
                self.unbind(model.actor); self.ctx.vtk_renderer.RemoveActor(model.actor); self.ctx.scene_models.remove(model)
        self.emitter=None; self.prune(); self.store.prune()
        if restore and self.saved_background is not None:
            a,b,gradient=self.saved_background; r=self.ctx.vtk_renderer
            r.SetBackground(*a); r.SetBackground2(*b); r.SetGradientBackground(gradient); self.saved_background=None
        if self.ctx.current_actor not in {m.actor for m in self.ctx.scene_models}:
            self.ctx.main_window.select_actor(self.ctx.scene_models[0].actor if self.ctx.scene_models else None)
        self.render()

    def add_stage(self,name,source,color,mirror=0.,emission=(0,0,0),texture=None):
        source.Update()
        poly=prepare_polydata(source.GetOutput())
        mapper=vtk.vtkPolyDataMapper(); mapper.SetInputData(poly); mapper.ScalarVisibilityOff()
        actor=vtk.vtkActor(); actor.SetMapper(mapper)
        model=SceneModel(name,'',actor,poly); model.lab4_stage=True
        self.ctx.scene_models.append(model); self.ctx.vtk_renderer.AddActor(actor)
        self.store.edit(actor,diffuse_color=color,ambient_color=color,specular=.15,shininess=80)
        state=self.ensure(actor); state.mirror=mirror; state.emission=emission
        if texture is not None: actor.SetTexture(texture)
        return actor

    def create_stage(self,*_):
        models=self.imported_models()
        if not models:
            self.status.setText('请先在文件树双击或拖入 OBJ，然后创建演示场景。'); return
        selected=self.ctx.current_actor if self.ctx.current_model in models else models[0].actor
        self.remove_stage(restore=False)
        b=np.array([m.actor.GetBounds() for m in models]); low,high=b[:,::2].min(axis=0),b[:,1::2].max(axis=0)
        center=(low+high)*.5; size=self.scene_span(); floor=low[1]-size*.015
        r=self.ctx.vtk_renderer
        if self.saved_background is None: self.saved_background=(r.GetBackground(),r.GetBackground2(),r.GetGradientBackground())
        r.SetBackground(.10,.14,.20); r.SetBackground2(.48,.60,.76); r.GradientBackgroundOn()
        plane=vtk.vtkPlaneSource()
        plane.SetOrigin(center[0]-3*size,floor,center[2]+3*size)
        plane.SetPoint1(center[0]+3*size,floor,center[2]+3*size)
        plane.SetPoint2(center[0]-3*size,floor,center[2]-3*size)
        y,x=np.mgrid[:256,:256]; checker=np.where(((x//16+y//16)%2)[...,None],.82,.28).astype(np.float32)
        self.add_stage('光线追踪 / 棋盘地面',plane,(.78,.77,.71),.18,texture=vtk_texture(np.repeat(checker,3,axis=-1)))
        for name,position,lengths,color in (
            ('浅色后墙',(center[0],floor+1.4*size,center[2]-2.6*size),(6*size,2.8*size,.04*size),(.67,.72,.79)),
            ('暖色侧墙',(center[0]-3*size,floor+1.4*size,center[2]),(.04*size,2.8*size,5.2*size),(.70,.34,.18)),
            ('蓝色参照箱',(center[0]+1.05*size,floor+.28*size,center[2]-.5*size),(.56*size,)*3,(.06,.24,.65))):
            cube=vtk.vtkCubeSource(); cube.SetCenter(*position)
            cube.SetXLength(lengths[0]); cube.SetYLength(lengths[1]); cube.SetZLength(lengths[2])
            self.add_stage('光线追踪 / '+name,cube,color)
        sphere=vtk.vtkSphereSource(); sphere.SetCenter(center[0]-1.05*size,floor+.28*size,center[2]+.5*size)
        sphere.SetRadius(.28*size); sphere.SetThetaResolution(32); sphere.SetPhiResolution(24)
        self.add_stage('光线追踪 / 金属参照球',sphere,(.90,.65,.25),.86)
        lamp=self.light_plugin()
        light_position=center+np.array([-1.1,2.,1.5])*size
        light_position[1]=floor+2.7*size
        if lamp:
            for key in 'rgb': lamp.controls[key].setValue(1.)
            for key in ('ambient','diffuse','specular'): getattr(lamp,'chk_'+key).setChecked(True)
            lamp.controls['ambient'].setValue(1.)
            for key,value in zip('xyz',light_position): lamp.controls[key].setValue(float(value))
            lamp.controls['intensity'].setValue(.85)
            lamp.chk_global.setChecked(True)
        emitter=vtk.vtkCubeSource(); emitter.SetXLength(self.light_size*size)
        emitter.SetYLength(.015*size); emitter.SetZLength(self.light_size*size)
        self.emitter=self.add_stage('光线追踪 / 面光源',emitter,(1.,.96,.86),emission=(5.,4.8,4.3))
        self.emitter.SetPosition(*light_position)
        camera=r.GetActiveCamera()
        camera.SetPosition(center[0]+1.7*size,floor+1.45*size,center[2]+3.25*size)
        camera.SetFocalPoint(center[0],floor+.50*size,center[2]); camera.SetViewUp(0,1,0)
        camera.SetViewAngle(45); camera.ParallelProjectionOff(); r.ResetCameraClippingRange()
        self.ctx.main_window.select_actor(selected)
        self.status.setText('已创建演示布景，导入模型保持原来的 Transform，中心光追画面自动更新。')
        self.render()

    def scene_key(self):
        result=[]
        for model in self.ctx.scene_models:
            actor=model.actor; mapper=actor.GetMapper(); poly=mapper.GetInput(); matrix=actor.GetMatrix()
            state=self.ensure(actor); texture=actor.GetTexture()
            result.append((actor.__this__,actor.GetVisibility(),mapper.__this__,poly.GetMTime(),
                tuple(matrix.GetElement(i,j) for i in range(4) for j in range(4)),
                repr(vars(self.store.ensure(actor))),state.mirror,state.transmission,state.ior,state.bump,
                state.strength,state.tiling,state.pattern,id(state.height),state.emission,
                texture.GetMTime() if texture is not None else None))
        env=next((p for p in self.ctx.plugins if p.plugin_cls_name=='environment_mapping'),None)
        if env: result.append((id(env.texture),env.background_check.isChecked(),env.reflection_check.isChecked()))
        return tuple(result)

    def sync_live_scene(self):
        if self._syncing_scene or self.trace_view is None: return
        if not self.ctx.scene_models:
            self.trace_view.scene=None; self._scene_key=None
            self.status.setText('从左侧文件树加载或拖入 OBJ，中心窗口将自动开始光追。')
            return
        self._syncing_scene=True
        try:
            self.prepare_render()
            key=self.scene_key()
            if key != self._scene_key:
                scene=snapshot(self)
                self.trace_view.set_scene(scene); self._scene_key=key; self.scene_revision+=1
                self.status.setText(f'实时场景：{len(scene.names)} 个物体 · {len(scene.triangles):,} 个三角形。\n场景变化自动同步；相机和灯光逐帧更新。')
        except Exception as exc:
            self.trace_view.scene=None
            self.status.setText('无法更新光追场景：'+str(exc))
            self._scene_key=key if 'key' in locals() else None
        finally: self._syncing_scene=False

    def on_destroy(self):
        self.ctx.vtk_renderer.RemoveObserver(self.observer)
        self.store.changed.disconnect(self.material_changed)
        if self.trace_view is not None:
            self.trace_view.timer.stop()
            if self.trace_view.navigation: self.trace_view.navigation.stop()
            self.trace_view.cleanup()
        for actor in list(self.bindings): self.unbind(actor)
