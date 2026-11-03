# 实验二 纹理映射

两个独立的 Python / OpenGL 桌面程序，无需启动 3D 查看器，也不依赖插件框架。

当前项目环境已经具备依赖，可直接双击 `run_task1.cmd` 或 `run_task2.cmd` 启动。启动脚本优先使用仓库的 `.venv`，不存在时使用系统 Python。

## 运行

在仓库根目录打开 PowerShell，使用已有的虚拟环境：

```powershell
.venv\Scripts\python.exe -m pip install -r 实验2\requirements.txt
.venv\Scripts\python.exe 实验2\task1_mipmap.py
.venv\Scripts\python.exe 实验2\task2_environment.py
```

也可以在安装依赖的 Python 环境中直接运行这两个文件。任务2默认从脚本所在目录读取 `meadow_2_4k.exr`，不依赖当前工作目录。需要支持桌面 OpenGL 3.3 兼容模式的显卡驱动。

## 编程任务1

场景由左右砖墙、木地板和灰泥天花板构成。纹理由程序生成，不需要额外图片。每张纹理都上传从 512×512 到 1×1 的完整 Mipmap 链；每级使用面积平均缩小。

右键弹出菜单、顶部下拉框或数字键 1–6 可切换六种缩小过滤方式：

| 按键 | 过滤方式 | 层内 / 层间处理 |
| --- | --- | --- |
| 1 | GL_NEAREST | 原始图最近邻 |
| 2 | GL_LINEAR | 原始图双线性 |
| 3 | GL_NEAREST_MIPMAP_NEAREST | 最近层、层内最近邻 |
| 4 | GL_LINEAR_MIPMAP_NEAREST | 最近层、层内双线性 |
| 5 | GL_NEAREST_MIPMAP_LINEAR | 相邻层线性、层内最近邻 |
| 6 | GL_LINEAR_MIPMAP_LINEAR | 相邻层线性、层内双线性，即三线性 |

W/S 或上下键前后移动，A/D 或左右键横移，Q/E 升降，左键拖动环顾，滚轮前后移动，R 重置。按键移动前先点击渲染区域。

观察建议：勾选“高频棋盘纹理”，在相同位置分别切换 1、2、6，然后缓慢前后移动。无 Mipmap 时远处纹理易闪烁和走样；三线性过滤通常更稳定。Mipmap 会让远处细节变软，不能消除所有斜视角走样。

## 编程任务2

背景、球体和立方体严格共用同一个 GPU 纹理对象，来源为提供的 EXR。程序直接读取 HDR 浮点数据，上传 RGB16F 纹理，建立 Mipmap。所有对象使用相同曝光、ACES 近似色调映射和 sRGB 转换。

背景根据相机朝向生成观察射线；物体逐片元根据世界坐标法线和观察向量计算 `reflect(I, N)`，再将反射方向转换为等距柱状全景 UV。球体使用光滑法线，立方体使用独立面法线。此处实现的是镜面环境映射，物体间不会互相反射。

左键拖动环绕观察，滚轮或 +/- 拉近拉远，右键菜单或 C 隐藏/显示立方体，R 重置视角。顶部可以同步调节背景及反射的曝光、环境旋转，也可以重新选择 EXR。默认使用原始的 `meadow_2_4k.exr`。

## 截图

两个程序支持保存渲染区截图后自动退出：

```powershell
.venv\Scripts\python.exe 实验2\task1_mipmap.py --filter 6 --screenshot 实验2\task1.png
.venv\Scripts\python.exe 实验2\task2_environment.py --screenshot 实验2\task2.png
```

任务1可追加 `--checker`，任务2可追加 `--no-cube`；任务2也支持 `--panorama 全景图路径`。
