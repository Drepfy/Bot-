using System.IO.Compression;
using System.Text;
using CleanerPro.Core;
using CleanerPro.Core.Safety;

namespace CleanerPro.TestSupport;

/// <summary>An isolated temporary directory that is removed after the test.</summary>
public sealed class TempDirectory : IDisposable
{
    public TempDirectory()
    {
        Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "cleanerpro-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path);
        Path = PathKey.NormalizeFullPath(Path);
    }

    public string Path { get; }

    public string Combine(params string[] parts) => System.IO.Path.Combine([Path, .. parts]);

    public string CreateDirectory(params string[] parts)
    {
        var path = Combine(parts);
        Directory.CreateDirectory(path);
        return path;
    }

    public string WriteText(string relative, string content)
    {
        var path = Combine(relative.Split('/'));
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
        File.WriteAllText(path, content);
        return path;
    }

    public string WriteBytes(string relative, byte[] content)
    {
        var path = Combine(relative.Split('/'));
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, content);
        return path;
    }

    public void Dispose()
    {
        try
        {
            foreach (var file in Directory.EnumerateFiles(Path, "*", SearchOption.AllDirectories))
            {
                File.SetAttributes(file, FileAttributes.Normal);
            }

            Directory.Delete(Path, recursive: true);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}

/// <summary>Builds harmless ZIP/JAR fixtures in memory. Class entries are empty or synthetic; nothing is runnable.</summary>
public sealed class JarBuilder
{
    private readonly List<(string Name, byte[] Data)> _entries = [];

    public JarBuilder Text(string name, string content) => Bytes(name, Encoding.UTF8.GetBytes(content));

    public JarBuilder Bytes(string name, byte[] data)
    {
        _entries.Add((name, data));
        return this;
    }

    public JarBuilder EmptyClasses(params string[] names)
    {
        foreach (var name in names)
        {
            Bytes(name, []);
        }

        return this;
    }

    public JarBuilder FabricMod(string id, string? name = null) =>
        Text("fabric.mod.json", $$"""{ "schemaVersion": 1, "id": "{{id}}", "name": "{{name ?? id}}", "version": "1.0.0" }""");

    public JarBuilder Nested(string name, JarBuilder nested) => Bytes(name, nested.Build());

    public byte[] Build()
    {
        using var memory = new MemoryStream();
        using (var archive = new ZipArchive(memory, ZipArchiveMode.Create, leaveOpen: true))
        {
            foreach (var (name, data) in _entries)
            {
                var entry = archive.CreateEntry(name, CompressionLevel.Optimal);
                using var stream = entry.Open();
                stream.Write(data);
            }
        }

        return memory.ToArray();
    }

    public string WriteTo(string path)
    {
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, Build());
        return path;
    }
}

/// <summary>
/// Writes minimal Java class files with chosen instruction sequences, used to exercise the bytecode
/// signature matcher. The generated methods are not valid, runnable Java code.
/// </summary>
public sealed class ClassFileBuilder
{
    private readonly List<byte[]> _constants = [];
    private readonly Dictionary<string, int> _cache = new(StringComparer.Ordinal);
    private readonly List<(int Name, int Descriptor, byte[] Code)> _methods = [];
    private readonly int _this;
    private readonly int _super;

    public ClassFileBuilder(string className = "test/Fixture")
    {
        _this = Class(className);
        _super = Class("java/lang/Object");
    }

    public int Utf8(string value) => Intern("U:" + value, () =>
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        return [1, (byte)(bytes.Length >> 8), (byte)bytes.Length, .. bytes];
    });

    public int Class(string name)
    {
        var utf = Utf8(name);
        return Intern("C:" + name, () => [7, (byte)(utf >> 8), (byte)utf]);
    }

    public int MethodRef(string owner, string name, string descriptor)
    {
        var cls = Class(owner);
        var n = Utf8(name);
        var d = Utf8(descriptor);
        var nat = Intern($"N:{name}:{descriptor}", () => [12, (byte)(n >> 8), (byte)n, (byte)(d >> 8), (byte)d]);
        return Intern($"M:{owner}.{name}{descriptor}", () => [10, (byte)(cls >> 8), (byte)cls, (byte)(nat >> 8), (byte)nat]);
    }

    public ClassFileBuilder Method(string name, Action<CodeWriter> code)
    {
        var writer = new CodeWriter(this);
        code(writer);
        _methods.Add((Utf8(name), Utf8("()V"), writer.ToArray()));
        return this;
    }

    public byte[] Build()
    {
        var code = Utf8("Code");
        var output = new List<byte> { 0xCA, 0xFE, 0xBA, 0xBE, 0, 0, 0, 52 };
        U2(output, _constants.Count + 1);
        foreach (var constant in _constants)
        {
            output.AddRange(constant);
        }

        U2(output, 0x21);
        U2(output, _this);
        U2(output, _super);
        U2(output, 0); // interfaces
        U2(output, 0); // fields
        U2(output, _methods.Count);
        foreach (var (name, descriptor, bytes) in _methods)
        {
            U2(output, 0x09);
            U2(output, name);
            U2(output, descriptor);
            U2(output, 1);
            U2(output, code);
            var length = 2 + 2 + 4 + bytes.Length + 2 + 2;
            U4(output, length);
            U2(output, 16); // max stack
            U2(output, 16); // max locals
            U4(output, bytes.Length);
            output.AddRange(bytes);
            U2(output, 0); // exception table
            U2(output, 0); // attributes
        }

        U2(output, 0); // class attributes
        return output.ToArray();
    }

    private int Intern(string key, Func<byte[]> create)
    {
        if (_cache.TryGetValue(key, out var index))
        {
            return index;
        }

        _constants.Add(create());
        index = _constants.Count;
        _cache[key] = index;
        return index;
    }

    private static void U2(List<byte> output, int value)
    {
        output.Add((byte)(value >> 8));
        output.Add((byte)value);
    }

    private static void U4(List<byte> output, int value)
    {
        output.Add((byte)(value >> 24));
        output.Add((byte)(value >> 16));
        output.Add((byte)(value >> 8));
        output.Add((byte)value);
    }

    public sealed class CodeWriter(ClassFileBuilder owner)
    {
        private readonly List<byte> _bytes = [];

        public CodeWriter Op(byte opcode)
        {
            _bytes.Add(opcode);
            return this;
        }

        public CodeWriter Bipush(int value)
        {
            _bytes.Add(0x10);
            _bytes.Add(unchecked((byte)(sbyte)value));
            return this;
        }

        public CodeWriter New(string type)
        {
            var index = owner.Class(type);
            _bytes.AddRange([0xBB, (byte)(index >> 8), (byte)index]);
            return this;
        }

        public CodeWriter Invoke(byte opcode, string ownerName, string name, string descriptor)
        {
            var index = owner.MethodRef(ownerName, name, descriptor);
            _bytes.AddRange([opcode, (byte)(index >> 8), (byte)index]);
            if (opcode == 0xB9)
            {
                _bytes.AddRange([1, 0]);
            }

            return this;
        }

        public CodeWriter Raw(params byte[] bytes)
        {
            _bytes.AddRange(bytes);
            return this;
        }

        public byte[] ToArray() => _bytes.ToArray();
    }
}

/// <summary>Synthetic instruction sequences matching the published fractureiser signatures (inert, never executed).</summary>
public static class FractureiserFixtures
{
    private const byte Invokevirtual = 0xB6;
    private const byte Invokespecial = 0xB7;
    private const byte Invokestatic = 0xB8;
    private const string S = "java/lang/String";

    public static void Sig1(ClassFileBuilder.CodeWriter c) => c
        .New(S).Invoke(Invokespecial, S, "<init>", "([B)V")
        .New(S).Invoke(Invokespecial, S, "<init>", "([B)V")
        .Invoke(Invokestatic, "java/lang/Class", "forName", "(Ljava/lang/String;)Ljava/lang/Class;")
        .Invoke(Invokevirtual, "java/lang/Class", "getConstructor", "([Ljava/lang/Class;)Ljava/lang/reflect/Constructor;")
        .New("java/net/URL")
        .New(S).Invoke(Invokespecial, S, "<init>", "([B)V")
        .New(S).Invoke(Invokespecial, S, "<init>", "([B)V")
        .New(S).Invoke(Invokespecial, S, "<init>", "([B)V")
        .Invoke(Invokespecial, "java/net/URL", "<init>", "(Ljava/lang/String;Ljava/lang/String;ILjava/lang/String;)V")
        .Invoke(Invokevirtual, "java/lang/reflect/Constructor", "newInstance", "([Ljava/lang/Object;)Ljava/lang/Object;")
        .Invoke(Invokestatic, "java/lang/Class", "forName", "(Ljava/lang/String;ZLjava/lang/ClassLoader;)Ljava/lang/Class;")
        .New(S).Invoke(Invokespecial, S, "<init>", "([B)V")
        .Invoke(Invokevirtual, "java/lang/Class", "getMethod", "(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;")
        .Invoke(Invokevirtual, "java/lang/reflect/Method", "invoke", "(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;")
        .Op(0xB1);

    public static void Sig2(ClassFileBuilder.CodeWriter c) => c
        .Op(0x03) // unrelated leading instruction
        .Invoke(Invokestatic, "java/lang/Runtime", "getRuntime", "()Ljava/lang/Runtime;")
        .Invoke(Invokestatic, "java/util/Base64", "getDecoder", "()Ljava/util/Base64$Decoder;")
        .Invoke(Invokevirtual, S, "concat", "(Ljava/lang/String;)Ljava/lang/String;")
        .Invoke(Invokevirtual, "java/util/Base64$Decoder", "decode", "(Ljava/lang/String;)[B")
        .Invoke(Invokespecial, S, "<init>", "([B)V")
        .Invoke(Invokevirtual, "java/io/File", "getPath", "()Ljava/lang/String;")
        .Invoke(Invokevirtual, "java/lang/Runtime", "exec", "([Ljava/lang/String;)Ljava/lang/Process;")
        .Op(0xB1);

    /// <summary>Byte array construction spelling the documented stage 0 address, as nekodetector's third signature describes.</summary>
    public static void Sig3(ClassFileBuilder.CodeWriter c)
    {
        const string ip = "85.217.144.130";
        c.Bipush(ip.Length).Raw(0xBC, 8); // newarray byte
        for (var i = 0; i < ip.Length; i++)
        {
            c.Op(0x59); // dup
            if (i <= 5)
            {
                c.Op((byte)(0x03 + i)); // iconst_i
            }
            else
            {
                c.Bipush(i);
            }

            c.Bipush(ip[i]).Op(0x54); // bastore
        }

        c.Op(0x57).Op(0xB1);
    }

    public static byte[] Sig1Class() => new ClassFileBuilder("net/example/InfectedMain").Method("_d1385bd3c36f464882460aa4f0484c53", Sig1).Build();

    public static byte[] HarmlessClass() => new ClassFileBuilder("net/example/Harmless").Method("run", c => c
        .New("java/lang/StringBuilder").Invoke(0xB7, "java/lang/StringBuilder", "<init>", "()V").Op(0x57).Op(0xB1)).Build();
}

/// <summary>A controllable clock for expiry tests.</summary>
public sealed class ManualTimeProvider(DateTimeOffset start) : TimeProvider
{
    private DateTimeOffset _now = start;

    public override DateTimeOffset GetUtcNow() => _now;

    public void Advance(TimeSpan by) => _now += by;
}

public static class TestPolicies
{
    /// <summary>A path policy with the given protected roots, using the current platform's path rules.</summary>
    public static PathSafetyPolicy Create(params string[] protectedRoots) =>
        new(protectedRoots, [], OperatingSystem.IsWindows(), PathKey.IsCaseInsensitivePlatform);
}

public sealed class WindowsFactAttribute : FactAttribute
{
    public WindowsFactAttribute()
    {
        if (!OperatingSystem.IsWindows())
        {
            Skip = "Requires Windows.";
        }
    }
}

public static class SymlinkSupport
{
    /// <summary>Creates a directory symlink if the OS/user allows it; returns false otherwise (Windows without Developer Mode).</summary>
    public static bool TryCreateDirectoryLink(string link, string target)
    {
        try
        {
            Directory.CreateSymbolicLink(link, target);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or PlatformNotSupportedException)
        {
            return false;
        }
    }

    public static bool TryCreateFileLink(string link, string target)
    {
        try
        {
            File.CreateSymbolicLink(link, target);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or PlatformNotSupportedException)
        {
            return false;
        }
    }
}
