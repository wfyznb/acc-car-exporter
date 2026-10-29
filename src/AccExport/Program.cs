using System.Text;
using CUE4Parse.Compression;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Exports.Material;
using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Objects.UObject;
using CUE4Parse.UE4.Readers;
using CUE4Parse.UE4.Versions;
using CUE4Parse_Conversion;
using CUE4Parse_Conversion.Exporters;
using CUE4Parse_Conversion.Options;
using CUE4Parse_Conversion.Textures.BC;
using Newtonsoft.Json;
using Serilog;

namespace AccExport;

public static class Program
{
    private static string _gameDirectory = Environment.GetEnvironmentVariable("ACC_PAKS_DIR") ?? "";
    private static string _aesKey = Environment.GetEnvironmentVariable("ACC_AES_KEY") ?? "";
    private static string _oodleDll = Environment.GetEnvironmentVariable("ACC_OODLE_DLL") ?? "";
    private static string _detexDll = Environment.GetEnvironmentVariable("ACC_DETEX_DLL") ?? "";
    private static DefaultFileProvider _provider = null!;

    private static void PrintUsage()
    {
        Console.WriteLine(
            """
            AccExport - ACC (Assetto Corsa Competizione / AC2) 资源导出工具 (CUE4Parse)

            用法: AccExport <mode> [args]
              paths                        列出 pak 内全部资源路径到 acc_paths.txt
              find <keyword>               按关键字搜索资源路径
              tyres <pkgPath>              打印蓝图里 TyreMesh/RimMesh 引用的网格与相对变换
              info <pkgPath>               打印网格材质槽 / 材质贴图参数
              export <prefix|@list> <out>  批量导出网格(ActorX PSK)与关联贴图(PNG)

            选项（可被环境变量替代）:
              --gamedir <dir>   游戏 Paks 目录   (env ACC_PAKS_DIR)
              --aeskey <hex>    pak AES 密钥     (env ACC_AES_KEY)
              --oodle <dll>     oodle dll 路径   (env ACC_OODLE_DLL)
              --detex <dll>     Detex dll 路径   (env ACC_DETEX_DLL)

            示例:
              AccExport --gamedir "C:\\Steam\\...\\AC2\\Content\\Paks" --aeskey 0x... export AC2/Content/cars/ferrari_296_gt3 ./out
            """);
    }

    public static int Main(string[] args)
    {
        Log.Logger = new LoggerConfiguration()
            .MinimumLevel.Warning()
            .WriteTo.Console()
            .CreateLogger();
        CUE4Parse.CUE4ParseLog.UseLogger(Log.Logger);

        // 解析 --key value 形式的选项
        var rest = new List<string>();
        for (int i = 0; i < args.Length; i++)
        {
            var v = i + 1 < args.Length ? args[i + 1] : null;
            switch (args[i])
            {
                case "--gamedir": _gameDirectory = v ?? _gameDirectory; i++; break;
                case "--aeskey": _aesKey = v ?? _aesKey; i++; break;
                case "--oodle": _oodleDll = v ?? _oodleDll; i++; break;
                case "--detex": _detexDll = v ?? _detexDll; i++; break;
                default: rest.Add(args[i]); break;
            }
        }
        args = rest.ToArray();
        if (args.Length == 0 || args[0] == "-h" || args[0] == "--help" ||
            string.IsNullOrEmpty(_gameDirectory) || string.IsNullOrEmpty(_aesKey))
        {
            PrintUsage();
            return args.Length == 0 || args[0] == "-h" || args[0] == "--help" ? 0 : 1;
        }
        if (string.IsNullOrEmpty(_oodleDll) || string.IsNullOrEmpty(_detexDll))
        {
            Console.WriteLine("提示: 未指定 --oodle/--detex，尝试从 FModel 输出目录或当前目录加载...");
        }

        var versions = new VersionContainer(EGame.GAME_UE4_26);
        _provider = new DefaultFileProvider(_gameDirectory, SearchOption.AllDirectories, true, versions);
        _provider.Initialize();
        _provider.SubmitKey(new FGuid(), new FAesKey(_aesKey));
        _provider.PostMount();

        if (!string.IsNullOrEmpty(_oodleDll)) OodleHelper.Initialize(_oodleDll);
        if (!string.IsNullOrEmpty(_detexDll)) DetexHelper.Initialize(_detexDll);

        Log.Information($"Project: {_provider.ProjectName} | Files: x{_provider.Files.Count}");

        var mode = args.Length > 0 && !args[0].StartsWith("--") ? args[0] : "paths";
        switch (mode)
        {
            case "paths":
                File.WriteAllLines("acc_paths.txt", _provider.Files.Keys.OrderBy(x => x));
                Console.WriteLine($"wrote {_provider.Files.Count} paths to acc_paths.txt");
                return 0;
            case "find":
                if (args.Length < 2) { Console.WriteLine("usage: find <keyword>"); return 1; }
                foreach (var k in _provider.Files.Keys.Where(k => k.Contains(args[1], StringComparison.OrdinalIgnoreCase)))
                    Console.WriteLine(k);
                return 0;
            case "tyres":
                if (args.Length < 2) { Console.WriteLine("usage: tyres <pkgPath>"); return 1; }
                foreach (var ex in LoadExports(args[1]))
                {
                    if (ex.Name.StartsWith("TyreMesh") || ex.Name.StartsWith("RimMesh") || ex.Name.StartsWith("Wheel"))
                    {
                        var mref = ex.GetOrDefault<FPackageIndex?>("StaticMesh", null);
                        var path = mref != null ? PathOf(mref) : "";
                        var loc = ex.GetOrDefault<CUE4Parse.UE4.Objects.Core.Math.FVector>("RelativeLocation", new CUE4Parse.UE4.Objects.Core.Math.FVector());
                        var rot = ex.GetOrDefault<CUE4Parse.UE4.Objects.Core.Math.FRotator>("RelativeRotation", new CUE4Parse.UE4.Objects.Core.Math.FRotator());
                        Console.WriteLine($"{ex.Name}: mesh={Path.GetFileName(path)} rel=({loc.X:F1},{loc.Y:F1},{loc.Z:F1}) rot=({rot.Pitch:F1},{rot.Yaw:F1},{rot.Roll:F1})");
                    }
                }
                return 0;
            case "info":
                if (args.Length < 2) { Console.WriteLine("usage: info <pkgPath>"); return 1; }
                return Info(args[1]);
            case "export":
                if (args.Length < 3) { Console.WriteLine("usage: export <pathPrefix|@pkgList> <outDir>"); return 1; }
                return RunExport(args[1], args[2]).GetAwaiter().GetResult();
            default:
                Console.WriteLine($"未知模式 {mode}"); return 1;
        }
    }

    private static List<UObject> LoadExports(string packagePath)
    {
        var list = new List<UObject>();
        try
        {
            if (!_provider.TryLoadPackage(packagePath, out var package) || package is null) return list;
            list.AddRange(package.GetExports());
        }
        catch (Exception e) { Log.Warning($"包加载失败 {packagePath}: {e.Message}"); }
        return list;
    }

    private static UObject? Load(FPackageIndex? idx)
    {
        if (idx == null) return null;
        try { return idx.TryLoad(out UObject? o) ? o : null; } catch { return null; }
    }

    private static string PathOf(FPackageIndex? idx)
    {
        try { return idx?.ResolvedObject?.GetPathName() ?? ""; } catch { return ""; }
    }

    // 把 ResolvedObject.GetPathName()（形如 .../pkg.AssetName）归一化为包文件键（.../pkg.uasset）
    private static string FileKeyOf(string pathName)
    {
        if (string.IsNullOrEmpty(pathName)) return "";
        var slash = pathName.LastIndexOf('/');
        var dot = pathName.LastIndexOf('.');
        if (dot > slash) pathName = pathName.Substring(0, dot);
        return pathName.EndsWith(".uasset") ? pathName : pathName + ".uasset";
    }

    // 打印网格的材质槽与材质贴图参数（用于组装前的分析）
    private static int Info(string pkgPath)
    {
        foreach (var ex in LoadExports(pkgPath))
        {
            Console.WriteLine($"=== {ex.Name} ({ex.Class?.Name}) ===");
            if (ex is USkeletalMesh sm)
            {
                foreach (var (m, i) in sm.SkeletalMaterials.Select((m, i) => (m, i)))
                {
                    var mat = Load(m.MaterialInterface);
                    Console.WriteLine($"  [{i}] {mat?.Name ?? m.MaterialSlotName.Text}  <-  {PathOf(m.MaterialInterface)}");
                }
            }
            else if (ex is UStaticMesh stm)
            {
                foreach (var (mi, i) in stm.Materials.Select((m, i) => (m, i)))
                {
                    var mat = Load(mi);
                    Console.WriteLine($"  [{i}] {mat?.Name ?? "?"}  <-  {PathOf(mi)}");
                }
            }
            else if (ex is UMaterialInstanceConstant mic)
            {
                Console.WriteLine($"  Parent: {PathOf(mic.Parent)}");
                foreach (var p in mic.TextureParameterValues)
                    Console.WriteLine($"  tex  {p.Name} = {p.ParameterValue?.ResolvedObject?.Name.Text}  <-  {PathOf(p.ParameterValue)}");
                foreach (var p in mic.ScalarParameterValues)
                    Console.WriteLine($"  scal {p.Name} = {p.ParameterValue}");
            }
        }
        return 0;
    }

    private sealed record MatRef(int Section, string MatName, string MatPath, string? ParentPath, Dictionary<string, string> Textures);

    // 递归收集一个材质（含父链）的全部贴图参数
    private static Dictionary<string, string> CollectTextures(UObject mat, Dictionary<string, string> acc, HashSet<string> visited)
    {
        if (!visited.Add(mat.Name)) return acc;
        if (mat is UMaterialInstanceConstant mic)
        {
            foreach (var p in mic.TextureParameterValues)
            {
                var tex = Load(p.ParameterValue);
                var path = PathOf(p.ParameterValue);
                if (tex is UTexture2D && !string.IsNullOrEmpty(path) && !acc.ContainsKey(p.Name))
                    acc[p.Name] = path;
            }
            var parentIdx = (mat as UMaterialInstance)?.Parent;
            if (Load(parentIdx) is UObject parent)
                CollectTextures(parent, acc, visited);
        }
        return acc;
    }

    private static async Task<int> RunExport(string pathPrefix, string outDir)
    {
        Directory.CreateDirectory(outDir);
        var stagingMesh = Path.Combine(outDir, "_staging_mesh");
        var stagingTex = Path.Combine(outDir, "_staging_tex");
        if (Directory.Exists(stagingMesh)) Directory.Delete(stagingMesh, true);
        if (Directory.Exists(stagingTex)) Directory.Delete(stagingTex, true);

        // 输入可以是路径前缀，也可以是 @文件列表
        List<string> pkgs;
        if (pathPrefix.StartsWith('@'))
        {
            pkgs = File.ReadAllLines(pathPrefix[1..])
                .Select(l => l.Trim()).Where(l => l.Length > 0).ToList();
        }
        else
        {
            pkgs = _provider.Files.Keys
                .Where(k => k.StartsWith(pathPrefix, StringComparison.OrdinalIgnoreCase) && k.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase))
                .OrderBy(k => k, StringComparer.Ordinal).ToList();
        }
        Console.WriteLine($"[export] {pkgs.Count} 个包");

        var meshSession = new ExportSession { MaxDegreeOfParallelism = 2 };
        var texSession = new ExportSession { MaxDegreeOfParallelism = 2 };
        var meshesIn = new List<UObject>();
        int textures = 0;
        var meshMaterials = new Dictionary<string, List<MatRef>>();
        var texNameToPath = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase); // 贴图资产名(大写) -> 游戏包路径

        foreach (var p in pkgs)
        {
            foreach (var ex in LoadExports(p))
            {
                if (ex is UStaticMesh or USkeletalMesh)
                {
                    try { meshSession.Add(ex); meshesIn.Add(ex); }
                    catch (Exception e) { Console.WriteLine($"[mesh跳过] {ex.Name}: {e.Message}"); }
                }
            }
        }

        // 解析网格材质 → 收集贴图
        foreach (var mesh in meshesIn)
        {
            var refs = new List<MatRef>();
            if (mesh is USkeletalMesh sm)
            {
                foreach (var (m, i) in sm.SkeletalMaterials.Select((m, i) => (m, i)))
                {
                    var mat = Load(m.MaterialInterface);
                    if (mat == null) continue;
                    var tex = CollectTextures(mat, new Dictionary<string, string>(), new HashSet<string>());
                    refs.Add(new MatRef(i, mat.Name, PathOf(m.MaterialInterface), PathOf((mat as UMaterialInstance)?.Parent), tex));
                    foreach (var t in tex.Values)
                        texNameToPath.TryAdd(Path.GetFileNameWithoutExtension(FileKeyOf(t)).ToUpperInvariant(), FileKeyOf(t));
                }
            }
            else if (mesh is UStaticMesh stm)
            {
                foreach (var (mi, i) in stm.Materials.Select((m, i) => (m, i)))
                {
                    var mat = Load(mi);
                    if (mat == null) continue;
                    var tex = CollectTextures(mat, new Dictionary<string, string>(), new HashSet<string>());
                    refs.Add(new MatRef(i, mat.Name, PathOf(mi), PathOf((mat as UMaterialInstance)?.Parent), tex));
                    foreach (var t in tex.Values)
                        texNameToPath.TryAdd(Path.GetFileNameWithoutExtension(FileKeyOf(t)).ToUpperInvariant(), FileKeyOf(t));
                }
            }
            meshMaterials[mesh.Name] = refs;
        }

        // 加载收集到的贴图
        foreach (var t in texNameToPath.Values.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            foreach (var ex in LoadExports(t))
                if (ex is UTexture2D) { try { texSession.Add(ex); textures++; } catch (Exception e) { Console.WriteLine($"[tex跳过] {ex.Name}: {e.Message}"); } }
        }

        Console.WriteLine($"[export] 网格 {meshesIn.Count}, 关联贴图 {textures}");

        if (meshSession.HasQueuedItems)
            await meshSession.RunAsync(stagingMesh, new ExportOptions(EMeshFormat.ActorX, exportMaterials: false, exportMorphTargets: false));
        if (texSession.HasQueuedItems)
            await texSession.RunAsync(stagingTex, new ExportOptions(EMeshFormat.Gltf2, exportMaterials: true, exportMorphTargets: false));

        // 归位：staging 中的文件平铺到 outDir
        foreach (var src in new[] { stagingMesh, stagingTex })
        {
            if (!Directory.Exists(src)) continue;
            foreach (var f in Directory.EnumerateFiles(src, "*", SearchOption.AllDirectories))
            {
                var dest = Path.Combine(outDir, Path.GetFileName(f));
                if (File.Exists(dest)) continue;
                File.Move(f, dest);
            }
        }
        try { if (Directory.Exists(stagingMesh)) Directory.Delete(stagingMesh, true); } catch { }
        try { if (Directory.Exists(stagingTex)) Directory.Delete(stagingTex, true); } catch { }

        // 材质清单
        var manifest = new
        {
            meshes = meshMaterials.Select(kv => new
            {
                mesh = kv.Key,
                materials = kv.Value.Select(r => new
                {
                    section = r.Section,
                    material = r.MatName,
                    materialPath = r.MatPath,
                    parent = r.ParentPath,
                    textures = r.Textures
                })
            }),
            textures = texNameToPath
        };
        File.WriteAllText(Path.Combine(outDir, "materials.json"), JsonConvert.SerializeObject(manifest, Formatting.Indented), new UTF8Encoding(false));

        Console.WriteLine($"=== 导出完成: 网格 {meshesIn.Count}, 贴图 {textures} → {outDir} ===");
        return 0;
    }
}
