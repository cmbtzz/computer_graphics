"""本次光照与经典材质共用的物体状态；不是功能插件。"""
from dataclasses import dataclass, replace
from PyQt5.QtCore import QObject, pyqtSignal


@dataclass
class MaterialState:
    preset: str = '默认'
    ambient: float = 0.2
    ambient_color: tuple = (1.0, 1.0, 1.0)
    diffuse: float = 0.8
    diffuse_color: tuple = (0.8, 0.8, 0.8)
    specular: float = 0.4
    specular_color: tuple = (1.0, 1.0, 1.0)
    shininess: float = 30.0
    emission: float = 0.0
    emission_color: tuple = (1.0, 0.5, 0.1)


PRESETS = {
    '默认': MaterialState(),
    # 用同色系环境项保留暗部色调，避免木材/塑料的背光面变成中性灰。
    # 金属采用亮银灰主体与较宽的强高光，避免原来的黑球加小白点。
    '金属': MaterialState(preset='金属', ambient=0.3,
                       ambient_color=(0.58, 0.63, 0.7), diffuse=0.72,
                       diffuse_color=(0.62, 0.67, 0.75), specular=1.0,
                       specular_color=(0.9, 0.95, 1.0), shininess=38),
    '木材': MaterialState(preset='木材', ambient=0.35,
                       ambient_color=(0.42, 0.20, 0.065), diffuse=0.88,
                       diffuse_color=(0.63, 0.31, 0.10), specular=0.045,
                       specular_color=(0.75, 0.55, 0.30), shininess=12),
    '塑料': MaterialState(preset='塑料', ambient=0.25,
                       ambient_color=(0.75, 0.035, 0.025), diffuse=0.9,
                       diffuse_color=(0.85, 0.045, 0.025), specular=0.95,
                       specular_color=(1.0, 1.0, 1.0), shininess=64),
}


class MaterialStore(QObject):
    changed = pyqtSignal(object)

    def __init__(self, ctx):
        super().__init__(ctx.main_window)
        self.ctx = ctx
        self.states = {}
        self.enabled = True
        self.components = {'ambient': True, 'diffuse': True, 'specular': True}
        self.light_rgb = (1.0, 1.0, 1.0)
        self.light_intensity = 0.8
        self.ambient_intensity = 1.0

    def ensure(self, actor):
        if actor not in self.states:
            self.states[actor] = MaterialState()
        return self.states[actor]

    def prune(self):
        active = {model.actor for model in self.ctx.scene_models}
        self.states = {actor: state for actor, state in self.states.items() if actor in active}

    def edit(self, actor, **values):
        state = self.ensure(actor)
        for name, value in values.items():
            setattr(state, name, value)
        state.preset = '自定义'
        self.apply(actor)
        self.changed.emit(actor)

    def preset(self, actor, name):
        self.states[actor] = replace(PRESETS[name])
        self.apply(actor)
        self.changed.emit(actor)

    def apply(self, actor):
        state = self.ensure(actor)
        prop = actor.GetProperty()
        # 不覆盖上一实验正在使用的独立自定义着色模式。
        if prop.GetTexture('mirrorPanorama') is not None:
            return
        prop.LightingOn()
        prop.SetInterpolationToPhong()
        prop.SetAmbient(state.ambient if self.enabled and self.components['ambient'] else 0)
        prop.SetDiffuse(state.diffuse if self.enabled and self.components['diffuse'] else 0)
        prop.SetSpecular(state.specular if self.enabled and self.components['specular'] else 0)
        # VTK 经典材质的环境项不读取点光源颜色，显式加入场景光色与强度。
        prop.SetAmbientColor(*(state.ambient_color[i] * self.light_rgb[i]
                               * self.light_intensity * self.ambient_intensity for i in range(3)))
        prop.SetDiffuseColor(*state.diffuse_color)
        prop.SetSpecularColor(*state.specular_color)
        prop.SetSpecularPower(state.shininess)
        actor.GetMapper().ScalarVisibilityOff()  # 防止导入的白色顶点标量覆盖材质颜色。
        shader = actor.GetShaderProperty()
        uniforms = shader.GetFragmentCustomUniforms()
        uniforms.SetUniform3f('materialEmission', tuple(v * state.emission for v in state.emission_color))
        # 自发光在普通纹理采样之后加入，不受光照开关影响。
        code = '//VTK::TCoord::Impl\nfragOutput0.rgb += materialEmission;\n'
        shader.AddFragmentShaderReplacement('//VTK::TCoord::Impl', True, code, False)

    def apply_all(self):
        self.prune()
        for model in self.ctx.scene_models:
            self.apply(model.actor)
        self.changed.emit(None)

    def render(self):
        self.ctx.vtk_widget.GetRenderWindow().Render()


def material_store(ctx):
    if not hasattr(ctx, 'material_store'):
        ctx.material_store = MaterialStore(ctx)
    return ctx.material_store
