# acc-car-exporter

从 **Assetto Corsa Competizione**（UE4.26，内部代号 AC2）的加密 pak 中提取整车辆模型，
并自动组装为带 PBR 材质的 GLB / Blender 工程。

本项目只包含**工具代码与流程文档**，不含任何游戏资源。
提取到的模型/贴图版权归 Kunos Simulazioni 所有，仅供个人学习研究，请勿传播提取产物。

## 组成

| 路径 | 说明 |
|---|---|
| `src/AccExport/` | C# 命令行工具，基于 [CUE4Parse](https://github.com/4lex1v/FModel) 解密/解析 pak，导出网格(ActorX PSK)与贴图(PNG)，并生成材质映射清单 |
| `blender/assemble.py` | Blender 无头脚本：导入 PSK 部件 → 按骨骼定位 → bmesh 合并车轮 → 重建 PBR 材质 → 导出 GLB |

## 环境要求

- .NET 10 SDK（构建 AccExport）
- Blender 4.x/5.x + [io_scene_psk_psa](https://github.com/Befzz/blender3d_import_psk_psa) 插件（Blender 4.2+ 用扩展平台版）
- `oodle-data-shared.dll` 与 `Detex.dll`（贴图解码依赖）：随 FModel 发布，位于其输出目录 `.data/` 下
- pak 的 AES 密钥：ACC 的主密钥是社区公开信息，可在 FModel 的 `AesKeys` 数据或公开 key 列表中找到（`0x` 开头的 64 位十六进制串）

## 快速开始（以 Ferrari 296 GT3 为例）

```bash
# 1. 构建
dotnet build src/AccExport/AccExport.csproj -c Release

# 2. 设置环境变量（也可用 --gamedir/--aeskey 参数）
#    Linux/macOS:
export ACC_PAKS_DIR="~/Steam/steamapps/common/Assetto Corsa Competizione/AC2/Content/Paks"
export ACC_AES_KEY="0x...."
export ACC_OODLE_DLL="/path/to/oodle-data-shared.dll"
export ACC_DETEX_DLL="/path/to/Detex.dll"
EXE=src/AccExport/bin/Release/net10.0/AccExport

# 3. 浏览资源
$EXE find cars/ferrari_296_gt3

# 4. 查询车辆用的轮毂/轮胎网格（解析蓝图组件引用）
$EXE tyres AC2/Content/cars/ferrari_296_gt3/ferrari_296_gt3.uasset

# 5. 导出车身部件（网格 + 沿材质父链收集的贴图 + materials.json）
$EXE export AC2/Content/cars/ferrari_296_gt3 ./ferrari_export

# 6. 导出轮胎（全车共享资源，规格见 tyres 命令输出）
$EXE export AC2/Content/cars/common/assets/tyres/tyre_dry_325_680_18_L ./tyres_export
#    ... 其余三条同理，或用 @列表文件：
$EXE export @tyre_pkgs.txt ./tyres_export

# 7. Blender 组装导出 GLB
blender --background --python blender/assemble.py -- \
    --export-dir ./ferrari_export --tyre-dir ./tyres_export --out-dir ./car_out
```

## 解析过程逻辑

ACC 的车辆不是一个整体模型，而是一组 SkeletalMesh/StaticMesh 部件 + 蓝图装配。
完整还原一辆车的推理链路如下：

### 1. 车辆部件结构

车辆蓝图（`cars/<car>/<car>.uasset`）里能枚举出全部部件组件：

- `ExternalMesh` / `InternalMesh` / `SteeringWheelMesh` / `BeltSkeletalMesh` /
  `ProtectionNetMesh` / `NumberPlateMesh` — 车身/内饰/方向盘/安全带/挡网/车号牌（SkeletalMesh）
- `RimMesh_LF/RF/LR/RR` — 轮毂（StaticMesh，独立文件，因有动态模糊替身 `BlurredRimMesh_*`）
- `TyreMesh_LF/RF/LR/RR` — 轮胎（**全车共享**，在 `cars/common/assets/tyres/`）
- `Collider`、`AuxLight*` — 碰撞体、耐力赛灯排等可选件

每个 `*_GEN_VARIABLE` 组件的 `StaticMesh` 属性给出精确的资源引用；
`RelativeLocation/RelativeRotation` 全为 0 时，表示该网格原点即安装骨骼位置。

### 2. 定位部件（assemble.py 核心逻辑）

- **车身/内饰/挡网/安全带/车号牌**：PSK 导出时骨骼绑定姿态即世界位姿，直接使用。
- **轮毂**：放到 exterior 骨架 `WHEEL_LF/RF/LR/RR` 骨骼位置（ACC 车辆骨架中这四根
  骨骼旋转为单位阵，直接平移即可）。
- **轮胎**：蓝图组件相对轮毂偏移为 0 → 原点放在同一轮毂骨骼位置。静态网格轴向未知，
  按包围盒"最短轴 = 胎宽(≈33cm)"自动对齐到车轴 X。
- **方向盘**：interior 骨架 `STEER_BASE` 骨骼矩阵（含转向柱后倾角）。

### 3. 车轮合并进车身（单一网格输出）

用 bmesh 做数据级合并（避免 Blender 后台模式下 `join` 操作器的上下文问题）：

1. 源网格世界变换烘焙到车身体空间；
2. 材质槽追加 + 面材质索引偏移；
3. UV 层逐 loop 拷贝；
4. 整个部件权重 1 分配到对应 `WHEEL_*` 顶点组 → 静态显示正确，挂动画也能跟随车轮旋转。

### 4. 材质重建（PBR 近似）

ACC 使用多层母材质 + 材质实例，`AccExport` 沿材质实例的 **Parent 链**递归收集全部
`TextureParameterValues` 写入 `materials.json`。`assemble.py` 按参数名语义映射：

| 引擎参数（模式匹配） | PBR 通道 |
|---|---|
| `*Albedo*` / `*Colour*` / `CAR_SKIN_TEXTURE` | Base Color |
| `*_NM` / `NM_texture` | Normal |
| `*MAP*` / `map_texture`（R=金属 G=粗糙 B=AO） | Metallic / Roughness / AO |
| `*AO*` | AO 乘算进 Base Color |
| `*emissive*` | Emission（强度 2） |

特殊处理：`EXT_Windows*`/风挡为引擎内程序化雨滴玻璃逻辑，无独立贴图，手动给半透明玻璃材质；
栅格类（`*grid*`）走 alpha 裁切。

### 5. 已知的坑（踩过的）

- **贴图 alpha ≠ 透明度**：ACC 贴图普遍是 RGBA，但 alpha 是污渍/贴花遮罩。
  把 alpha 接进 Principled 透明度会让整车身变半透明。只有栅格类材质应启用 alpha。
- **PSK 绕序不要盲目翻转**：CUE4Parse 的 ActorX 导出绕序是正确的。判断方法：
  对封闭部件（刹车盘、安全带衬垫）按图元算**有符号体积**，正=朝外；开放壳体（车皮）
  体积趋近 0 无判别意义。
- **UE 法线贴图是 DirectX 习惯**（绿通道向下），导 GLB（OpenGL 习惯）严格说需翻转
  G 通道，ACC 法线在此近似下表现可接受。
- **Hub 重心即轮胎中心**：TyreMesh 组件 RelativeTransform 为 0 是通用规律，
  换其他车不需要重新推导轮胎定位。
- **轮胎是共享资源**：按 `tyre_<干/湿>_<宽>_<直径>_<轮辋>_<L/R>` 命名。具体规格
  必须查车辆蓝图（`tyres` 命令），296 GT3 为前 325/680R18、后 325/705R18。

## materials.json 结构

```jsonc
{
  "meshes": [{
    "mesh": "ferrari_296_gt3_exterior",
    "materials": [{
      "section": 0,                    // 材质槽序号
      "material": "EXT_Carpaint_Inst", // 实例名
      "parent": ".../M_Carpaint.Parent", // 母材质
      "textures": { "Albedo": "...", "NM_texture": "...", ... } // 沿父链收集的全部贴图
    }]
  }],
  "textures": { "贴图资产名": "pak 内路径" }
}
```

## 移植到其他车辆

1. `$EXE tyres cars/<新车>/<新车>.uasset` 拿到轮毂/轮胎规格；
2. 导出该车目录全部网格；
3. 按规格导出 4 条共享轮胎；
4. `assemble.py` 里把 `PARTS`/`TYRE_PARTS`/`wheel_bone` 的文件名换成新车
   （逻辑通用，仅文件名清单需要改）。

## 致谢

- [CUE4Parse](https://github.com/4lex1v/FModel) — UE4 pak 解析库
- [io_scene_psk_psa](https://github.com/Befzz/blender3d_import_psk_psa) — Blender PSK 导入插件

## License

MIT — 见 [LICENSE](LICENSE)。提取出的游戏资源不受本许可覆盖。
