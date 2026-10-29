# -*- coding: utf-8 -*-
# 组装 ACC 车辆模型：PSK 部件定位 + PBR 贴图材质 + GLB 导出（示例：Ferrari 296 GT3）
import bpy, os, json, re, argparse
from mathutils import Vector, Matrix

ap = argparse.ArgumentParser(description="组装 ACC 车辆 PSK 部件并导出 GLB")
ap.add_argument("--export-dir", default=r"c:\Users\al208\Desktop\jidi.45.ACC\ACC\ferrari_296_gt3_export",
                help="AccExport 导出的车辆部件目录")
ap.add_argument("--tyre-dir", default=r"c:\Users\al208\Desktop\jidi.45.ACC\ACC\ferrari_296_gt3_tyres_export",
                help="AccExport 导出的轮胎目录（无则跳过轮胎）")
ap.add_argument("--out-dir", default=r"c:\Users\al208\Desktop\jidi.45.ACC\ACC\Ferrari_296_GT3",
                help="GLB/BLEND 输出目录")
# Blender 启动时 sys.argv 混有 blender 自身参数，用 parse_known_args 忽略；
# 传参示例: blender --background --python assemble.py -- --export-dir ./out
args, _unknown = ap.parse_known_args()
EXPORT = args.export_dir
TYRE_EXPORT = args.tyre_dir
OUT = args.out_dir
os.makedirs(OUT, exist_ok=True)

# ---------- 0. 插件与场景 ----------
bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.io_scene_psk_psa")
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
for img in list(bpy.data.images):
    if img.users == 0:
        bpy.data.images.remove(img)
for mat in list(bpy.data.materials):
    if mat.users == 0:
        bpy.data.materials.remove(mat)

with open(os.path.join(EXPORT, "materials.json"), encoding="utf-8") as f:
    MANIFEST = json.load(f)
MESH_MATS = {m["mesh"]: m["materials"] for m in MANIFEST["meshes"]}
try:
    with open(os.path.join(TYRE_EXPORT, "materials.json"), encoding="utf-8") as f:
        TMANIFEST = json.load(f)
    MESH_MATS.update({m["mesh"]: m["materials"] for m in TMANIFEST["meshes"]})
except FileNotFoundError:
    pass

# ---------- 1. 导入部件 ----------
PARTS = [
    "ferrari_296_gt3_exterior.pskx",
    "ferrari_296_gt3_interior.pskx",
    "ferrari_296_gt3_net.psk",
    "ferrari_296_gt3_belt_on.pskx",
    "ferrari_296_gt3_steer_hr.psk",
    "ferrari_296_gt3_rim_lf.pskx",
    "ferrari_296_gt3_rim_rf.pskx",
    "ferrari_296_gt3_rim_lr.pskx",
    "ferrari_296_gt3_rim_rr.pskx",
    "ferrari_296_gt3_numberplate_a.psk",
    "ferrari_296_gt3_numberplate_b.psk",
]
# 轮胎为全车共享静态网格（296 GT3：前 325/680R18，后 325/705R18，干地）
TYRE_PARTS = [
    "tyre_dry_325_680_18_L.pskx",
    "tyre_dry_325_680_18_R.pskx",
    "tyre_dry_325_705_18_L.pskx",
    "tyre_dry_325_705_18_R.pskx",
]
for p in PARTS:
    bpy.ops.psk.import_file(filepath=os.path.join(EXPORT, p))
for p in TYRE_PARTS:
    bpy.ops.psk.import_file(filepath=os.path.join(TYRE_EXPORT, p))

def mesh_of(key):
    """按部件名找 Blender 网格对象（armature 占用原名，网格带 .001）"""
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.name.startswith(key):
            return o
    return None

def arm_of(key):
    return bpy.data.objects.get(key)

meshes = {}
for p in PARTS + TYRE_PARTS:
    key = p.split(".")[0]
    m = mesh_of(key)
    meshes[key] = m
    if m is None:
        print("!! 缺少网格:", key)

# ---------- 2. 部件定位 ----------
# 注：PSK 原始绕序经逐图元体积验证基本正确（内饰/机械件均为正），不做全局翻转
ext_arm = arm_of("ferrari_296_gt3_exterior")
int_arm = arm_of("ferrari_296_gt3_interior")

# 轮毂：WHEEL_* 骨骼头部（骨骼矩阵为单位旋转，直接平移）
wheel_bone = {
    "ferrari_296_gt3_rim_lf": "WHEEL_LF",
    "ferrari_296_gt3_rim_rf": "WHEEL_RF",
    "ferrari_296_gt3_rim_lr": "WHEEL_LR",
    "ferrari_296_gt3_rim_rr": "WHEEL_RR",
    # 轮胎：蓝图组件相对轮毂偏移/旋转均为 0，原点即轮毂中心
    "tyre_dry_325_680_18_L": "WHEEL_LF",
    "tyre_dry_325_680_18_R": "WHEEL_RF",
    "tyre_dry_325_705_18_L": "WHEEL_LR",
    "tyre_dry_325_705_18_R": "WHEEL_RR",
}
for part, bn in wheel_bone.items():
    r = meshes.get(part)
    b = ext_arm.data.bones.get(bn) if ext_arm else None
    if r is None or b is None:
        print("!! 车轮定位失败:", part, bn); continue
    target = ext_arm.matrix_world @ b.matrix_local.to_translation()
    mw = r.matrix_world.copy()
    R = Matrix.Identity(4)
    if part.startswith("tyre_"):
        # 静态轮胎网格轴向未知：按包围盒最短轴（胎宽~32.5cm）对齐到车轴 X
        vs = [v.co for v in r.data.vertices]
        dims = (max(v.x for v in vs) - min(v.x for v in vs),
                max(v.y for v in vs) - min(v.y for v in vs),
                max(v.z for v in vs) - min(v.z for v in vs))
        wi = dims.index(min(dims))
        if wi == 1:
            R = Matrix.Rotation(1.5707963, 4, 'Z')   # +Y -> +X
        elif wi == 2:
            R = Matrix.Rotation(1.5707963, 4, 'Y')   # +Z -> +X
        print(f"[轮胎轴向] {part} 尺寸=({dims[0]:.1f},{dims[1]:.1f},{dims[2]:.1f}) 宽度轴={'XYZ'[wi]}->X")
    mw = Matrix.Translation(target) @ R @ Matrix.Diagonal(mw.to_scale().to_4d())
    r.parent = ext_arm
    r.parent_type = 'OBJECT'
    r.matrix_parent_inverse = ext_arm.matrix_world.inverted()
    r.matrix_world = mw
    print(f"[定位] {part} -> {bn} @ {tuple(round(v,1) for v in target)}")

# 方向盘：STEER_BASE 骨骼矩阵（带倾斜）
steer = meshes.get("ferrari_296_gt3_steer_hr")
sb = int_arm.data.bones.get("STEER_BASE") if int_arm else None
if steer is not None and sb is not None:
    mw = int_arm.matrix_world @ sb.matrix_local
    steer.parent = int_arm
    steer.parent_type = 'OBJECT'
    steer.matrix_parent_inverse = int_arm.matrix_world.inverted()
    steer.matrix_world = mw
    print(f"[定位] 方向盘 -> STEER_BASE @ {tuple(round(v,1) for v in mw.to_translation())}")
else:
    print("!! 方向盘定位失败")

# ---------- 3. 材质 ----------
def tex_file(path_name):
    base = path_name.rsplit("/", 1)[-1].split(".")[0]
    for d in (EXPORT, TYRE_EXPORT):
        fp = os.path.join(d, base + ".png")
        if os.path.exists(fp):
            return fp
    return None

def role_of(param):
    n = param.strip().lower()
    if "blur" in n:
        return None
    if "emissive" in n or "glow" in n:
        return "EMISSION"
    if n.endswith("_nm") or "nm_texture" in n or "normal" in n:
        return "NORMAL"
    if n == "ao" or "ao_texture" in n:
        return "AO"
    if n.endswith("map") or "map_texture" in n or "global map" in n or "globalmap" in n:
        if "damage" in n or "dirt" in n:
            return None
        return "ORM"
    if "albedo" in n or "colour" in n or "color" in n or "skin_texture" in n:
        return "BASE"
    return None

# 黑名单：叠层/细节/占位贴图，不进基础 PBR
BLACK = ("damage", "dirt", "scuffle", "sticker", "detail", "blur", "fiber", "mask", "carbon")

def prio(param, role):
    n = param.strip().lower()
    if role == "BASE":
        return 0 if ("albedo_texture" in n or "skin_texture" in n or n == "generic_color") else 1
    if role == "NORMAL":
        if "nm_texture" in n: return 0
        if n.endswith("_nm") or "normal_map" in n: return 1
        return 2
    if role == "ORM":
        return 0 if ("map_texture" in n or "global map" in n or "globalmap" in n) else 1
    if role == "AO":
        return 0
    if role == "EMISSION":
        return 0
    return 9

def load_img(fp, non_color):
    img = bpy.data.images.load(fp, check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img

def make_material(name, texs, report):
    # 每个角色只保留一个最优贴图；引擎默认贴图跳过
    chosen = {}
    for param, path in texs.items():
        role = role_of(param)
        if role is None: continue
        p = param.strip().lower()
        if any(b in p for b in BLACK) and role not in ("ORM", "EMISSION"):
            report.append(f"    [忽略] {param}")
            continue
        base = path.rsplit("/", 1)[-1].split(".")[0]
        if base.lower().startswith("default"):
            report.append(f"    [引擎默认跳过] {param} <- {base}")
            continue
        if role in ("ORM", "EMISSION") and any(b in p for b in BLACK):
            report.append(f"    [忽略] {param}")
            continue
        sc = prio(param, role)
        if role not in chosen or sc < chosen[role][0]:
            chosen[role] = (sc, param, path)
    for role, (sc, param, path) in chosen.items():
        if role != "ORM":  # 占位，实际加载在下面
            pass
    report.extend(f"    [忽略] {p}" for p in texs if role_of(p) is None)
    texs = {param: path for role, (sc, param, path) in chosen.items()}
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if out is None:
            out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    for n in list(nt.nodes):
        if n != bsdf and n.type != 'OUTPUT_MATERIAL':
            nt.nodes.remove(n)
    bsdf.location = (0, 0)
    has_alpha_img = None
    ao_img = None
    y = 300
    for param, path in sorted(texs.items()):
        role = role_of(param)
        if role is None:
            report.append(f"    [忽略] {param}")
            continue
        fp = tex_file(path)
        if fp is None:
            report.append(f"    [缺PNG] {param} -> {path}")
            continue
        if role == "BASE":
            img = load_img(fp, False)
            t = next((n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image == img), None)
            if t is None:
                t = nt.nodes.new("ShaderNodeTexImage"); t.image = img; t.location = (-400, y)
            nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
            # 仅栅格类镂空材质启用 alpha 裁切；其余（车漆/贴花/内饰等）一律不透明，
            # ACC 贴图普遍带 alpha 通道（污渍/贴花遮罩），接进透明度会导致车身半透明
            if "grid" in name.lower():
                nt.links.new(t.outputs["Alpha"], bsdf.inputs["Alpha"])
                try:
                    mat.blend_method = 'CLIP'
                    mat.alpha_threshold = 0.5
                except Exception:
                    pass
            report.append(f"    [BASE] {param} <- {os.path.basename(fp)}")
        elif role == "ORM":
            img = load_img(fp, True)
            t = nt.nodes.new("ShaderNodeTexImage"); t.image = img; t.location = (-400, y)
            sep = nt.nodes.new("ShaderNodeSeparateColor"); sep.location = (-150, y)
            nt.links.new(t.outputs["Color"], sep.inputs["Color"])
            nt.links.new(sep.outputs["Red"], bsdf.inputs["Metallic"])
            nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
            mix = nt.nodes.new("ShaderNodeMixRGB"); mix.blend_type = 'MULTIPLY'; mix.inputs["Fac"].default_value = 1.0
            mix.location = (-150, -200)
            nt.links.new(t.outputs["Color"], mix.inputs["Color2"])
            # 接到 Base Color（若无 BASE 时直接接；有 BASE 时后面补乘）
            mix.label = "ORM_AO"
            mix["__is_ao_mix"] = True
            report.append(f"    [ORM] {param} <- {os.path.basename(fp)} (R金属 G粗糙 B环境光遮蔽)")
        elif role == "NORMAL":
            img = load_img(fp, True)
            t = nt.nodes.new("ShaderNodeTexImage"); t.image = img; t.location = (-400, y)
            nm = nt.nodes.new("ShaderNodeNormalMap"); nm.location = (-150, y)
            nt.links.new(t.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
            report.append(f"    [法线] {param} <- {os.path.basename(fp)}")
        elif role == "EMISSION":
            img = load_img(fp, False)
            t = nt.nodes.new("ShaderNodeTexImage"); t.image = img; t.location = (-400, y)
            nt.links.new(t.outputs["Color"], bsdf.inputs["Emission Color"])
            bsdf.inputs["Emission Strength"].default_value = 2.0
            report.append(f"    [自发光] {param} <- {os.path.basename(fp)}")
        elif role == "AO":
            img = load_img(fp, True)
            t = nt.nodes.new("ShaderNodeTexImage"); t.image = img; t.location = (-400, y)
            mix = nt.nodes.new("ShaderNodeMixRGB"); mix.blend_type = 'MULTIPLY'; mix.inputs["Fac"].default_value = 1.0
            mix.location = (-150, -300); mix.label = "AO"
            nt.links.new(t.outputs["Color"], mix.inputs["Color2"])
            mix["__is_ao_mix"] = True
            ao_img = fp
            report.append(f"    [环境光遮蔽] {param} <- {os.path.basename(fp)}")
        y -= 220
    # 把所有 AO 乘法链串到 Base Color
    ao_mixes = [n for n in nt.nodes if n.get("__is_ao_mix")]
    if ao_mixes:
        base_sock = None
        for l in list(nt.links):
            if l.to_node == bsdf and l.to_socket.name == "Base Color":
                base_sock = l.from_socket
                nt.links.remove(l)
                break
        chain_in = base_sock
        for m in ao_mixes:
            if chain_in is not None:
                nt.links.new(chain_in, m.inputs["Color1"])
            chain_in = m.outputs["Color"]
        if chain_in is not None:
            nt.links.new(chain_in, bsdf.inputs["Base Color"])
        elif not any(l.to_node == bsdf and l.to_socket.name == "Base Color" for l in nt.links):
            bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1.0)
    return mat

report_lines = []

def make_glass(name, alpha=0.22, tint=(0.05, 0.05, 0.06, 1.0)):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Base Color"].default_value = tint
    bsdf.inputs["Roughness"].default_value = 0.03
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Alpha"].default_value = alpha
    try: mat.blend_method = 'BLEND'
    except Exception: pass
    return mat

for key, m in meshes.items():
    if m is None: continue
    refs = MESH_MATS.get(key, [])
    by_name = {r["material"]: r for r in refs}
    for slot in m.material_slots:
        mat_name = slot.material.name if slot.material else "?"
        r = by_name.get(mat_name)
        if r is None:  # 索引兜底
            idx = list(m.material_slots).index(slot)
            r = next((x for x in refs if x["section"] == idx), None)
        low = mat_name.lower()
        if r is None or not r["textures"]:
            # 无清单/无贴图：玻璃与后视镜手动处理
            if "window" in low or "glass" in low or "windshield" in low:
                slot.material = make_glass(f"{key.rsplit('_',1)[-1].upper()}_{mat_name}_GLASS")
                report_lines.append(f"{key} [{mat_name}]: 玻璃材质(手动)")
            elif "mirror" in low:
                g = make_glass(f"{key.rsplit('_',1)[-1].upper()}_{mat_name}_MIRROR", alpha=1.0, tint=(0.9, 0.9, 0.9, 1.0))
                nt = g.node_tree
                bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
                bsdf.inputs["Metallic"].default_value = 1.0
                slot.material = g
                report_lines.append(f"{key} [{mat_name}]: 镜面材质(手动)")
            else:
                report_lines.append(f"{key} [{mat_name}]: 无材质清单(默认灰)")
            continue
        rep = [f"{key} slot '{mat_name}' (parent={r['parent'].rsplit('/',1)[-1] if r['parent'] else '-'})"]
        new_mat = make_material(f"{key.rsplit('_',1)[-1].upper()}_{mat_name}", r["textures"], rep)
        slot.material = new_mat
        report_lines.extend(rep)

print("\n".join(report_lines))

# ---------- 3.5 车轮并入车身网格（bmesh 数据级合并：轮毂+轮胎） ----------
ext_mesh = meshes.get("ferrari_296_gt3_exterior")
if ext_mesh is not None:
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ext_mesh.data)
    base_mats = len(ext_mesh.data.materials)
    dlayer = bm.verts.layers.deform.verify()
    for part, bn in wheel_bone.items():
        r = meshes.get(part)
        if r is None:
            continue
        # 材质并入槽位
        mat_ofs = base_mats
        for ms in r.material_slots:
            ext_mesh.data.materials.append(ms.material)
            base_mats += 1
        # 世界变换烘焙到车身体空间
        M = ext_mesh.matrix_world.inverted() @ r.matrix_world
        tmp = bmesh.new()
        tmp.from_mesh(r.data)
        tmp.transform(M)
        src_uv = tmp.loops.layers.uv[0] if len(tmp.loops.layers.uv) else None
        dst_uv = bm.loops.layers.uv[0] if len(bm.loops.layers.uv) else None
        vmap = {}
        new_verts = []
        for v in tmp.verts:
            nv = bm.verts.new(v.co)
            vmap[v] = nv
            new_verts.append(nv)
        for f in tmp.faces:
            try:
                nf = bm.faces.new([vmap[v] for v in f.verts])
                nf.smooth = f.smooth
                nf.material_index = f.material_index + mat_ofs
                if src_uv and dst_uv:
                    for ls, ld in zip(f.loops, nf.loops):
                        ld[dst_uv].uv = ls[src_uv].uv
            except ValueError:
                pass
        tmp.free()
        # 顶点组：整轮权重 1 挂到 WHEEL_* 骨骼
        vg_idx = ext_mesh.vertex_groups[bn].index if bn in ext_mesh.vertex_groups else ext_mesh.vertex_groups.new(name=bn).index
        for nv in new_verts:
            nv[dlayer][vg_idx] = 1.0
        print(f"[合并] {part} -> 车身 ({bn}, {len(new_verts)} 顶点)")
        meshes.pop(part, None)
    bm.to_mesh(ext_mesh.data)
    bm.free()
    ext_mesh.data.update()
    # 删除车轮原对象与空骨架
    for o in list(bpy.data.objects):
        if o.name.startswith('ferrari_296_gt3_rim') or o.name.startswith('tyre_dry'):
            bpy.data.objects.remove(o, do_unlink=True)

# ---------- 4. 归组 & 缩放 ----------
root = bpy.data.objects.new("Ferrari_296_GT3", None)
bpy.context.scene.collection.objects.link(root)
root.empty_display_size = 10
root.scale = (0.01, 0.01, 0.01)  # UE cm -> m
for key, m in meshes.items():
    if m is None: continue
    top = m.parent if (m.parent and m.parent.type == 'ARMATURE') else m
    # 部件自带的 armature 是顶层；轮毂/方向盘已挂到 exterior/interior 的 armature 下
    if top.parent is None and top != root:
        mw = top.matrix_world.copy()
        top.parent = root
        top.matrix_parent_inverse = Matrix.Identity(4)
        top.matrix_world = mw

# 尺寸报告
mins = Vector((1e9, 1e9, 1e9)); maxs = Vector((-1e9, -1e9, -1e9))
for o in bpy.data.objects:
    if o.type != 'MESH': continue
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        mins = Vector(map(min, mins, w)); maxs = Vector(map(max, maxs, w))
print("整车包围盒(cm): min=%s max=%s 尺寸=%s" % (
    tuple(round(v,1) for v in mins), tuple(round(v,1) for v in maxs),
    tuple(round(v,1) for v in (maxs - mins))))

# ---------- 5. 保存与导出 ----------
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "ferrari_296_gt3.blend"))
bpy.ops.export_scene.gltf(
    filepath=os.path.join(OUT, "ferrari_296_gt3.glb"),
    export_format='GLB',
    export_apply=True,
    export_animations=False,
    export_yup=True,
)
print("=== 组装完成 ===")
print("GLB:", os.path.join(OUT, "ferrari_296_gt3.glb"))
print("BLEND:", os.path.join(OUT, "ferrari_296_gt3.blend"))
