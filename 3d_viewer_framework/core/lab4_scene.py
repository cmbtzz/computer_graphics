"""实验四场景快照与三角网格 BVH。此模块不创建 OpenGL 上下文。"""
from dataclasses import dataclass, field

import numpy as np
import vtk
from PyQt5.QtGui import QImage
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy


@dataclass
class LabMaterial:
    preset: str = '陶瓷'
    mirror: float = .08
    transmission: float = 0.
    ior: float = 1.5
    bump: bool = False
    strength: float = .02  # 相对于物体包围盒最长边的高度
    tiling: tuple = (5., 4.)
    pattern: int = 0
    height: object = None
    height_name: str = '雕刻花纹'
    emission: tuple = (0., 0., 0.)


def height_pattern(index, size=256):
    v, u = np.mgrid[0:size, 0:size].astype(np.float32) / size
    if index == 0:
        h = .5 + .30*np.cos(2*np.pi*u)*np.cos(2*np.pi*v) + .12*np.cos(4*np.pi*u)*np.cos(4*np.pi*v)
    elif index == 1:
        x, y = (u + np.floor(v*2)*.5) % 1, (v*2) % 1
        a = np.clip((np.minimum(np.minimum(x,1-x),np.minimum(y,1-y))-.025)/.1,0,1)
        h = .15 + .7*a*a*(3-2*a)
    elif index == 2:
        h = .5 + .38*np.sin(2*np.pi*(u+.2*np.sin(2*np.pi*v)))
    else:
        h = .5 + .18*np.sin(2*np.pi*(7*u+3*v))*np.cos(2*np.pi*(2*u-5*v))
        h += .12*np.cos(2*np.pi*(13*u+11*v))
    return np.ascontiguousarray(np.clip(h,0,1),np.float32)


def read_height(path):
    image = QImage(str(path))
    if image.isNull():
        raise ValueError('无法读取高度图：' + str(path))
    image = image.scaled(1024,1024,1,1).convertToFormat(QImage.Format_Grayscale8)
    ptr = image.bits(); ptr.setsize(image.byteCount())
    data = np.frombuffer(ptr,np.uint8).reshape(image.height(),image.bytesPerLine())
    return np.ascontiguousarray(data[::-1,:image.width()].astype(np.float32)/255)


def vtk_texture(pixels):
    data = np.asarray(pixels,np.float32)
    if data.ndim == 2:
        data = data[...,None]
    image = vtk.vtkImageData()
    image.SetDimensions(data.shape[1],data.shape[0],1)
    image.GetPointData().SetScalars(numpy_to_vtk(data.reshape(-1,data.shape[-1]),deep=True))
    texture = vtk.vtkTexture()
    texture.SetInputData(image)
    texture.SetColorModeToDirectScalars()
    texture.InterpolateOn(); texture.RepeatOn()
    return texture


def texture_pixels(texture):
    if texture is None:
        return None
    texture.Update()
    image = texture.GetInput()
    if image is None or image.GetPointData().GetScalars() is None:
        return None
    w,h,_ = image.GetDimensions()
    scalars = vtk_to_numpy(image.GetPointData().GetScalars())
    channels = image.GetNumberOfScalarComponents()
    data = scalars.reshape(h,w,channels).astype(np.float32)
    if np.issubdtype(scalars.dtype,np.integer):
        data /= np.iinfo(scalars.dtype).max
    if channels < 3:
        data = np.repeat(data[...,:1],3,axis=-1)
    return np.ascontiguousarray(data[...,:3])


def resize_layer(data, size=256):
    """规则重采样；所有层统一大小以便 OpenGL 3.3 texture array 使用。"""
    y = np.minimum((np.arange(size)+.5)*data.shape[0]/size,data.shape[0]-1)
    x = np.minimum((np.arange(size)+.5)*data.shape[1]/size,data.shape[1]-1)
    return np.ascontiguousarray(data[y.astype(int)[:,None],x.astype(int)[None,:]],np.float32)


def prepare_polydata(source):
    """不改作者几何；无 UV 时生成 Y 轴柱面 UV，并拆开经度接缝。"""
    tri = vtk.vtkTriangleFilter(); tri.SetInputData(source)
    tri.PassLinesOff(); tri.PassVertsOff(); tri.Update()
    poly = vtk.vtkPolyData(); poly.DeepCopy(tri.GetOutput())
    if poly.GetPointData().GetNormals() is None:
        normals = vtk.vtkPolyDataNormals(); normals.SetInputData(poly)
        normals.SplittingOff(); normals.ConsistencyOn(); normals.Update()
        poly.DeepCopy(normals.GetOutput())
    if poly.GetPointData().GetTCoords() is None:
        p = vtk_to_numpy(poly.GetPoints().GetData()).astype(np.float64)
        faces = vtk_to_numpy(poly.GetPolys().GetConnectivityArray()).reshape(-1,3)
        center = (p.max(axis=0)+p.min(axis=0))*.5
        uv = np.column_stack((np.arctan2(p[:,2]-center[2],p[:,0]-center[0])/(2*np.pi)+.5,
                              (p[:,1]-p[:,1].min())/max(np.ptp(p[:,1]),1e-10)))
        # 逐面展开后，跨接缝的低 u 加 1；法线及几何保持不变。
        uv = uv[faces].copy()
        seam = np.ptp(uv[:,:,0],axis=1) > .5
        uv[:,:,0] += (seam[:,None] & (uv[:,:,0]<.5))
        normals = vtk_to_numpy(poly.GetPointData().GetNormals())[faces].reshape(-1,3)
        output = vtk.vtkPolyData()
        points = vtk.vtkPoints(); points.SetData(numpy_to_vtk(p[faces].reshape(-1,3),deep=True))
        output.SetPoints(points)
        cells = vtk.vtkCellArray()
        cells.SetData(numpy_to_vtk(np.arange(0,faces.size+1,3,dtype=np.int64),deep=True,array_type=vtk.VTK_ID_TYPE),
                      numpy_to_vtk(np.arange(faces.size,dtype=np.int64),deep=True,array_type=vtk.VTK_ID_TYPE))
        output.SetPolys(cells)
        normal_array = numpy_to_vtk(normals,deep=True); normal_array.SetName('Normals')
        output.GetPointData().SetNormals(normal_array)
        coords = numpy_to_vtk(uv.reshape(-1,2),deep=True); coords.SetName('Lab4UV')
        output.GetPointData().SetTCoords(coords)
        return output
    return poly


def build_bvh(triangles, leaf_size=8):
    """中位数划分，叶子三角形连续排列；平衡树深度受输入数量限制。"""
    low = np.minimum(np.minimum(triangles[:,0,:3],triangles[:,0,:3]+triangles[:,1,:3]),triangles[:,0,:3]+triangles[:,2,:3])
    high = np.maximum(np.maximum(triangles[:,0,:3],triangles[:,0,:3]+triangles[:,1,:3]),triangles[:,0,:3]+triangles[:,2,:3])
    centroid = (low+high)*.5
    nodes, order = [], []

    def split(ids):
        index = len(nodes)
        node = np.zeros((2,4),np.float32); nodes.append(node)
        node[0,:3] = low[ids].min(axis=0)-1e-6
        node[1,:3] = high[ids].max(axis=0)+1e-6
        if len(ids) <= leaf_size:
            node[0,3],node[1,3] = len(order),len(ids)
            order.extend(ids.tolist())
        else:
            axis = int(np.argmax(np.ptp(centroid[ids],axis=0)))
            middle = len(ids)//2
            ids = ids[np.argpartition(centroid[ids,axis],middle)]
            left,right = split(ids[:middle]),split(ids[middle:])
            node[0,3],node[1,3] = left,-right-1
        return index

    if not len(triangles):
        raise ValueError('场景没有可追踪的三角形')
    split(np.arange(len(triangles)))
    return np.ascontiguousarray(nodes),np.ascontiguousarray(triangles[order])


@dataclass
class SceneSnapshot:
    triangles: np.ndarray
    nodes: np.ndarray
    materials: np.ndarray
    heights: np.ndarray
    albedos: np.ndarray
    camera: dict
    light: dict
    environment: object = None
    names: list = field(default_factory=list)
    origin: np.ndarray = field(default_factory=lambda: np.zeros(3))
    scale: float = 1.


def snapshot(plugin):
    """在主线程复制当前 mapper 数据与 actor 世界矩阵；包含布景但排除坐标轴和选择框。"""
    ctx = plugin.ctx
    models = [m for m in ctx.scene_models if m.actor.GetVisibility()]
    if not models:
        raise ValueError('请先加载 OBJ 模型')
    if len(models) > 128:
        raise ValueError('教学预览最多支持 128 个物体')
    bounds = np.array([m.actor.GetBounds() for m in models])
    lower,upper = bounds[:,::2].min(axis=0),bounds[:,1::2].max(axis=0)
    origin = (lower+upper)*.5
    scale = 10/max(float(np.max(upper-lower)),1e-9)
    triangle_parts,materials,heights,albedos = [],[],[],[]
    total = 0
    for material_id,model in enumerate(models):
        actor = model.actor
        poly = prepare_polydata(actor.GetMapper().GetInput())
        vertices = vtk_to_numpy(poly.GetPoints().GetData()).astype(np.float64)
        faces = vtk_to_numpy(poly.GetPolys().GetConnectivityArray()).reshape(-1,3)
        total += len(faces)
        if total > 1000000:
            raise ValueError('教学预览上限为 100 万三角形，请减少场景模型数量')
        matrix = np.array([[actor.GetMatrix().GetElement(i,j) for j in range(4)] for i in range(4)])
        if abs(np.linalg.det(matrix[:3,:3])) < 1e-18:
            raise ValueError(f'{model.name} 的缩放退化为零，无法追踪')
        world = vertices @ matrix[:3,:3].T + matrix[:3,3]
        world = (world-origin)*scale
        normals = vtk_to_numpy(poly.GetPointData().GetNormals()).astype(np.float64) @ np.linalg.inv(matrix[:3,:3])
        normals /= np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
        uv = vtk_to_numpy(poly.GetPointData().GetTCoords())[:,:2]
        tri = np.zeros((len(faces),8,4),np.float32)
        p = world[faces]
        tri[:,0,:3] = p[:,0]; tri[:,1,:3] = p[:,1]-p[:,0]; tri[:,2,:3] = p[:,2]-p[:,0]
        tri[:,3:6,:3] = normals[faces]
        tex = uv[faces]
        tri[:,6,:2],tri[:,6,2:] = tex[:,0],tex[:,1]
        tri[:,7,:2],tri[:,7,2] = tex[:,2],material_id
        valid = np.linalg.norm(np.cross(tri[:,1,:3],tri[:,2,:3]),axis=1)>1e-12
        triangle_parts.append(tri[valid])
        state,base = plugin.ensure(actor),plugin.store.ensure(actor)
        material = np.zeros((5,4),np.float32)
        material[0] = (*base.diffuse_color,state.mirror)
        material[1] = (state.transmission,state.ior,base.shininess,base.specular)
        b = actor.GetBounds(); span = max(b[1]-b[0],b[3]-b[2],b[5]-b[4],1e-9)
        layer = -1
        if state.bump:
            layer = len(heights)
            heights.append(resize_layer(state.height if state.height is not None else height_pattern(state.pattern)))
        material[2] = (state.strength*span*scale,*state.tiling,layer)
        albedo = texture_pixels(actor.GetTexture())
        color_layer = -1
        if albedo is not None:
            color_layer = len(albedos); albedos.append(resize_layer(albedo))
        material[3] = (*(np.array(state.emission)+base.emission*np.array(base.emission_color)),color_layer)
        material[4] = (base.diffuse,base.ambient,0,0)
        materials.append(material)
    triangles = np.concatenate(triangle_parts)
    nodes,triangles = build_bvh(triangles)
    scene = SceneSnapshot(triangles,nodes,np.ascontiguousarray(materials),
                         np.ascontiguousarray(heights if heights else [np.zeros((256,256),np.float32)]),
                         np.ascontiguousarray(albedos if albedos else [np.ones((256,256,3),np.float32)]),
                         {},{},names=[m.name for m in models],origin=origin,scale=scale)
    sync_view_state(plugin,scene)
    environment = None
    env = next((p for p in ctx.plugins if p.plugin_cls_name=='environment_mapping'),None)
    if env and env.texture is not None and (env.background_check.isChecked() or env.reflection_check.isChecked()):
        environment = texture_pixels(env.texture)
        if environment is not None:
            step = max(1,environment.shape[1]//1024)
            environment = np.ascontiguousarray(environment[::step,::step])
    scene.environment = environment
    return scene


def sync_view_state(plugin,scene):
    """相机和灯光每帧更新，复用静态几何及 BVH，避免移动相机时重建网格。"""
    ctx=plugin.ctx
    camera=ctx.vtk_renderer.GetActiveCamera()
    def point(p): return (np.asarray(p)-scene.origin)*scene.scale
    scene.camera = dict(eye=point(camera.GetPosition()),target=point(camera.GetFocalPoint()),
                        up=np.asarray(camera.GetViewUp(),np.float32),fov=float(camera.GetViewAngle()),
                        parallel=int(camera.GetParallelProjection()),parallelScale=float(camera.GetParallelScale()*scene.scale))
    light_plugin = next((p for p in ctx.plugins if p.plugin_cls_name=='light_control'),None)
    lamp = light_plugin.scene_light if light_plugin else next(iter(ctx.vtk_renderer.GetLights()),None)
    active = bool(plugin.store.enabled and (lamp is None or lamp.GetSwitch()))
    scene.light = dict(position=point(lamp.GetPosition() if lamp else camera.GetPosition()),
                 color=np.array(lamp.GetDiffuseColor() if lamp else (1,1,1)),
                 power=float((lamp.GetIntensity()*8 if lamp else 6.4) if active else 0.),
                 size=float(plugin.light_size*plugin.scene_span()*scene.scale),
                 ambient=float(.08*plugin.store.ambient_intensity if active and plugin.store.components['ambient'] else 0.),
                 diffuse=int(plugin.store.components['diffuse']),specular=int(plugin.store.components['specular']))
