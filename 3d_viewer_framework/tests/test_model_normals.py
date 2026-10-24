"""检查独立三角形的平滑法线、硬边、UV 接缝和作者法线。"""
from pathlib import Path
import sys
import numpy as np
import vtk
from vtkmodules.util.numpy_support import vtk_to_numpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.model_normals import generate_normals, has_valid_normals


def run():
    sphere = vtk.vtkSphereSource()
    sphere.SetThetaResolution(24)
    sphere.SetPhiResolution(18)
    sphere.Update()
    source = sphere.GetOutput()
    # 模拟 OBJ：每个面都用独立的顶点和 UV；几何相同但顶点不共享。
    exploded = vtk.vtkPolyData()
    points, polygons = vtk.vtkPoints(), vtk.vtkCellArray()
    uv = vtk.vtkFloatArray()
    uv.SetNumberOfComponents(2)
    uv.SetName('UV')
    for cell_id in range(source.GetNumberOfCells()):
        cell = source.GetCell(cell_id)
        ids = vtk.vtkIdList()
        for corner in range(cell.GetNumberOfPoints()):
            ids.InsertNextId(points.InsertNextPoint(source.GetPoint(cell.GetPointId(corner))))
            uv.InsertNextTuple2(cell_id/1000, corner/3)
        polygons.InsertNextCell(ids)
    exploded.SetPoints(points)
    exploded.SetPolys(polygons)
    exploded.GetPointData().SetTCoords(uv)
    smooth = generate_normals(exploded)
    assert exploded.GetPointData().GetNormals() is None  # 输入未被辅助焊接操作修改。
    assert has_valid_normals(smooth)
    assert smooth.GetNumberOfCells() == exploded.GetNumberOfCells()
    by_position = {}
    varied_faces = 0
    for cell_id in range(smooth.GetNumberOfCells()):
        old, new = exploded.GetCell(cell_id), smooth.GetCell(cell_id)
        face_normals = []
        for corner in range(new.GetNumberOfPoints()):
            a, b = old.GetPointId(corner), new.GetPointId(corner)
            position = smooth.GetPoint(b)
            assert position == exploded.GetPoint(a)
            assert smooth.GetPointData().GetTCoords().GetTuple2(b) == uv.GetTuple2(a)
            normal = np.array(smooth.GetPointData().GetNormals().GetTuple3(b))
            radial = np.array(position)/np.linalg.norm(position)
            assert np.dot(normal, radial) > 0.98
            if position in by_position:
                assert np.linalg.norm(normal-by_position[position]) < 1e-5
            by_position[position] = normal
            face_normals.append(normal)
        varied_faces += np.linalg.norm(face_normals[0]-face_normals[1]) > 0.01
    assert varied_faces > smooth.GetNumberOfCells()*0.8  # 每面角点法线不同，确实不是 flat。

    cube = vtk.vtkCubeSource()
    cube.Update()
    cube.GetOutput().GetPointData().SetNormals(None)
    hard = generate_normals(cube.GetOutput())
    normals = vtk_to_numpy(hard.GetPointData().GetNormals())
    assert np.all(np.sum(np.abs(normals) > 1e-5, axis=1) == 1)
    assert hard.GetNumberOfCells() == 6  # 90° 边不被磨成圆角。

    authored = source.GetPointData().GetNormals()
    assert authored is not None and generate_normals(source) is source
    assert source.GetPointData().GetNormals() is authored
    print('PASS: smooth corner normals across disconnected triangles and UV seams, unchanged UV/geometry, sharp cube edges and preserved authored normals', flush=True)


if __name__ == '__main__':
    run()
