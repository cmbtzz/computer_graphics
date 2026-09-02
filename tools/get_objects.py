'''
    准备obj三维模型，从modelnet40数据集的off文件中读取，转换为obj格式，并保存到指定目录。
'''
import os
import random
import numpy as np

def read_off(file_path):
    """读取OFF文件，返回顶点、面"""
    with open(file_path, 'r') as f:
        lines = [line.strip() for line in f if line.strip()]
    ptr = 0
    assert lines[ptr] == "OFF", f"无效OFF文件: {file_path}"
    ptr += 1
    n_vert, n_face, _ = map(int, lines[ptr].split())
    ptr += 1
    verts = []
    for _ in range(n_vert):
        x, y, z = map(float, lines[ptr].split())
        verts.append([x, y, z])
        ptr += 1
    faces = []
    for _ in range(n_face):
        parts = list(map(int, lines[ptr].split()))
        cnt = parts[0]
        idx = parts[1:1+cnt]
        faces.append([i + 1 for i in idx])
        ptr += 1
    return np.array(verts), faces

def save_obj(file_path, verts, faces):
    """保存为OBJ文件"""
    with open(file_path, 'w') as f:
        for v in verts:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for face in faces:
            face_str = " ".join(map(str, face))
            f.write(f"f {face_str}\n")

def process_category(category_name, root_modelnet, out_root, sample_num=10):
    cat_dir = os.path.join(root_modelnet, category_name)
    if not os.path.isdir(cat_dir):
        print(f"警告：分类目录不存在 {cat_dir}，跳过")
        return

    off_paths = []
    for split in ["train", "test"]:
        split_dir = os.path.join(cat_dir, split)
        if not os.path.isdir(split_dir):
            continue
        for fname in os.listdir(split_dir):
            if fname.lower().endswith(".off"):
                full_p = os.path.join(split_dir, fname)
                off_paths.append(full_p)

    if len(off_paths) == 0:
        print(f"分类 {category_name} 无off文件，跳过")
        return
    print(f"[{category_name}] 共找到 {len(off_paths)} 个OFF文件")

    sample_count = min(sample_num, len(off_paths))
    selected_off = random.sample(off_paths, sample_count)
    print(f"[{category_name}] 随机选取 {sample_count} 个样本转换")

    out_cat_dir = os.path.join(out_root, category_name)
    os.makedirs(out_cat_dir, exist_ok=True)

    for off_p in selected_off:
        base_name = os.path.splitext(os.path.basename(off_p))[0]
        obj_save_p = os.path.join(out_cat_dir, f"{base_name}.obj")
        try:
            verts, faces = read_off(off_p)
            save_obj(obj_save_p, verts, faces)
            print(f"  已转换: {os.path.basename(off_p)} -> {os.path.basename(obj_save_p)}")
        except Exception as e:
            print(f"  转换失败 {off_p}: {str(e)}")

def main():
    # ========== 关键修改：替换为绝对路径 ==========
    objects_txt_path = "./data/objects.txt"
    # 服务器真实数据集绝对路径
    modelnet40_root = "/home/caihb/public_data/modelnet40"
    output_root = "./data/modelnet"
    sample_per_class = 10

    if not os.path.exists(objects_txt_path):
        print(f"错误：{objects_txt_path} 文件不存在！")
        return
    with open(objects_txt_path, "r", encoding="utf-8") as f:
        categories = [line.strip() for line in f if line.strip()]
    print(f"从objects.txt读取到 {len(categories)} 个分类")

    for cat in categories:
        print("-" * 40)
        process_category(
            category_name=cat,
            root_modelnet=modelnet40_root,
            out_root=output_root,
            sample_num=sample_per_class
        )
    print("=" * 40)
    print("全部分类处理完成！")

if __name__ == "__main__":
    random.seed(42)
    main()