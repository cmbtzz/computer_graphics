"""为缺失法线的 OBJ 补齐曲面顶点法线，同时保留硬边和原有 UV 接缝。"""
import numpy as np
import vtk
from vtkmodules.util.numpy_support import vtk_to_numpy


def has_valid_normals(polydata):
    normals = polydata.GetPointData().GetNormals()
    if normals is None or normals.GetNumberOfTuples() != polydata.GetNumberOfPoints():
        return False
    values = vtk_to_numpy(normals)
    return (values.ndim == 2 and values.shape[1] == 3 and np.isfinite(values).all()
            and np.all(np.linalg.norm(values, axis=1) > 1e-8))


def generate_normals(polydata, feature_angle=60):
    """保留有效的作者法线；仅为缺失/无效法线的数据生成新法线。

    OBJ 经常把每个三角形的顶点独立存储。只调用 vtkPolyDataNormals
    无法在这些顶点之间平滑；直接 Clean 又会破坏 UV 接缝。因此在无
    纹理属性的辅助网格上焊接、分硬边、计算法线，再按面角还原源属性。
    """
    if has_valid_normals(polydata) or not polydata.GetNumberOfPolys():
        return polydata
    auxiliary = vtk.vtkPolyData()
    auxiliary.ShallowCopy(polydata)
    auxiliary.GetPointData().Initialize()
    auxiliary.GetCellData().Initialize()
    original_ids = vtk.vtkIdTypeArray()
    original_ids.SetName('source_face_id')
    for index in range(polydata.GetNumberOfCells()):
        original_ids.InsertNextValue(index)
    auxiliary.GetCellData().AddArray(original_ids)

    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(auxiliary)
    clean.PointMergingOn()
    clean.ToleranceIsAbsoluteOn()
    clean.SetAbsoluteTolerance(0)  # 只焊接完全重合的坐标，不改变几何位置。
    clean.ConvertPolysToLinesOff()
    clean.ConvertLinesToPointsOff()
    clean.ConvertStripsToPolysOff()
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputConnection(clean.GetOutputPort())
    normals.ComputePointNormalsOn()
    normals.ComputeCellNormalsOff()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOff()
    normals.SplittingOn()
    normals.SetFeatureAngle(feature_angle)
    normals.NonManifoldTraversalOff()
    normals.Update()
    smooth = normals.GetOutput()
    generated = smooth.GetPointData().GetNormals()
    ids = smooth.GetCellData().GetArray('source_face_id')
    if generated is None or ids is None:
        return polydata

    # 每个源面分别查找其角点法线，因而立方体同一位置可保留三种硬边法线。
    face_normals = {}
    for cell_id in range(smooth.GetNumberOfCells()):
        cell = smooth.GetCell(cell_id)
        corners = {}
        for corner in range(cell.GetNumberOfPoints()):
            point_id = cell.GetPointId(corner)
            corners[smooth.GetPoint(point_id)] = point_id
        face_normals[int(ids.GetTuple1(cell_id))] = corners

    result = vtk.vtkPolyData()
    points = vtk.vtkPoints()
    points.SetDataType(polydata.GetPoints().GetDataType())
    result.GetPointData().CopyAllocate(polydata.GetPointData())
    output_normals = vtk.vtkFloatArray()
    output_normals.SetName('Normals')
    output_normals.SetNumberOfComponents(3)
    remap = {}
    arrays = {kind: vtk.vtkCellArray() for kind in ('verts', 'lines', 'polys', 'strips')}
    limits = (polydata.GetNumberOfVerts(), polydata.GetNumberOfLines(),
              polydata.GetNumberOfPolys(), polydata.GetNumberOfStrips())
    cell_id = 0
    for kind, count in zip(arrays, limits):
        for _ in range(count):
            cell = polydata.GetCell(cell_id)
            smooth_corners = face_normals.get(cell_id, {})
            output_ids = vtk.vtkIdList()
            for corner in range(cell.GetNumberOfPoints()):
                source_id = cell.GetPointId(corner)
                coordinate = polydata.GetPoint(source_id)
                smooth_id = smooth_corners.get(coordinate)
                # 源顶点 ID 保留 UV/颜色接缝；辅助点 ID 保留硬边分组。
                key = (source_id, smooth_id)
                if key not in remap:
                    new_id = points.InsertNextPoint(coordinate)
                    result.GetPointData().CopyData(polydata.GetPointData(), source_id, new_id)
                    value = generated.GetTuple3(smooth_id) if smooth_id is not None else (0, 0, 1)
                    output_normals.InsertNextTuple3(*value)
                    remap[key] = new_id
                output_ids.InsertNextId(remap[key])
            arrays[kind].InsertNextCell(output_ids)
            cell_id += 1
    result.SetPoints(points)
    result.SetVerts(arrays['verts'])
    result.SetLines(arrays['lines'])
    result.SetPolys(arrays['polys'])
    result.SetStrips(arrays['strips'])
    result.GetPointData().SetNormals(output_normals)
    result.GetCellData().DeepCopy(polydata.GetCellData())
    result.GetFieldData().DeepCopy(polydata.GetFieldData())
    return result
