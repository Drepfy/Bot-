using System.Text;
using CleanerPro.Detection.Rules;

namespace CleanerPro.Detection.Bytecode;

public readonly record struct CompiledInstruction(byte Opcode, string? Type, string? Owner, string? Name, string? Descriptor, int? Operand);

/// <summary>A validated bytecode signature from the rule database.</summary>
public sealed class CompiledBytecodeSignature
{
    public CompiledBytecodeSignature(string key, BytecodeMatchMode mode, IReadOnlyList<CompiledInstruction> pattern)
    {
        Key = key;
        Mode = mode;
        Pattern = pattern;
        RequiredStrings = pattern
            .SelectMany(p => new[] { p.Type, p.Owner, p.Name })
            .Where(s => !string.IsNullOrEmpty(s))
            .Distinct(StringComparer.Ordinal)
            .Select(s => Encoding.UTF8.GetBytes(s!))
            .ToArray();
        RequiredRawBytes = mode == BytecodeMatchMode.Contiguous ? EncodeRaw(pattern) : null;
    }

    /// <summary>
    /// For contiguous signatures made only of operand-free or immediate-operand instructions, the exact
    /// byte sequence that must appear in the class file. Used as a cheap pre-filter before parsing.
    /// </summary>
    public byte[]? RequiredRawBytes { get; }

    private static byte[]? EncodeRaw(IReadOnlyList<CompiledInstruction> pattern)
    {
        var bytes = new List<byte>();
        foreach (var instruction in pattern)
        {
            if (instruction.Type is not null || instruction.Owner is not null || instruction.Name is not null || instruction.Descriptor is not null)
            {
                return null;
            }

            switch (instruction.Opcode)
            {
                case JvmOpcodes.Bipush when instruction.Operand is { } value and >= sbyte.MinValue and <= sbyte.MaxValue:
                    bytes.Add(instruction.Opcode);
                    bytes.Add(unchecked((byte)(sbyte)value));
                    break;
                case JvmOpcodes.Sipush when instruction.Operand is { } value and >= short.MinValue and <= short.MaxValue:
                    bytes.Add(instruction.Opcode);
                    bytes.Add((byte)((value >> 8) & 0xFF));
                    bytes.Add((byte)(value & 0xFF));
                    break;
                default:
                    if (JvmOpcodes.FixedLength(instruction.Opcode) != 1 || instruction.Operand is not null)
                    {
                        return null;
                    }

                    bytes.Add(instruction.Opcode);
                    break;
            }
        }

        return bytes.Count > 0 ? bytes.ToArray() : null;
    }

    /// <summary>"ruleId/indicatorId".</summary>
    public string Key { get; }

    public BytecodeMatchMode Mode { get; }

    public IReadOnlyList<CompiledInstruction> Pattern { get; }

    /// <summary>Constant-pool strings that must appear in the class for a match to be possible.</summary>
    public IReadOnlyList<byte[]> RequiredStrings { get; }
}

/// <summary>Matches documented instruction sequences inside class files without executing them.</summary>
public sealed class BytecodeSignatureMatcher
{
    private readonly IReadOnlyList<CompiledBytecodeSignature> _signatures;

    public BytecodeSignatureMatcher(IEnumerable<CompiledBytecodeSignature> signatures)
    {
        _signatures = signatures.ToList();
    }

    public bool HasSignatures => _signatures.Count > 0;

    /// <summary>Returns the keys of all signatures found in the class. Throws <see cref="ClassFormatException"/> for malformed input.</summary>
    public IReadOnlyList<string> Match(ReadOnlySpan<byte> classBytes)
    {
        if (_signatures.Count == 0)
        {
            return [];
        }

        var candidates = new List<CompiledBytecodeSignature>();
        foreach (var signature in _signatures)
        {
            if (IsPossibleMatch(classBytes, signature))
            {
                candidates.Add(signature);
            }
        }

        if (candidates.Count == 0)
        {
            return [];
        }

        var methods = ClassFileReader.ReadMethods(classBytes);
        var hits = new List<string>();
        foreach (var signature in candidates)
        {
            if (methods.Any(m => MatchesMethod(m.Instructions, signature)))
            {
                hits.Add(signature.Key);
            }
        }

        return hits;
    }

    private static bool IsPossibleMatch(ReadOnlySpan<byte> classBytes, CompiledBytecodeSignature signature)
    {
        if (signature.RequiredRawBytes is not null && classBytes.IndexOf(signature.RequiredRawBytes) < 0)
        {
            return false;
        }

        foreach (var required in signature.RequiredStrings)
        {
            if (classBytes.IndexOf(required) < 0)
            {
                return false;
            }
        }

        return true;
    }

    internal static bool MatchesMethod(IReadOnlyList<JvmInstruction> instructions, CompiledBytecodeSignature signature)
    {
        var pattern = signature.Pattern;
        if (pattern.Count == 0 || instructions.Count == 0)
        {
            return false;
        }

        return signature.Mode switch
        {
            BytecodeMatchMode.OrderedOpcodeFilter => OrderedFrom(instructions, pattern, 0),
            BytecodeMatchMode.OrderedOpcodeFilterAnyStart => AnyStart(instructions, pattern),
            BytecodeMatchMode.Contiguous => Contiguous(instructions, pattern),
            _ => false,
        };
    }

    private static bool OrderedFrom(IReadOnlyList<JvmInstruction> instructions, IReadOnlyList<CompiledInstruction> pattern, int start)
    {
        var j = 0;
        for (var i = start; i < instructions.Count && j < pattern.Count; i++)
        {
            var instruction = instructions[i];
            if (instruction.Opcode != pattern[j].Opcode)
            {
                continue;
            }

            // Once an instruction with the expected opcode differs, the sequence cannot match from this start.
            if (!Same(instruction, pattern[j]))
            {
                return false;
            }

            j++;
        }

        return j == pattern.Count;
    }

    private static bool AnyStart(IReadOnlyList<JvmInstruction> instructions, IReadOnlyList<CompiledInstruction> pattern)
    {
        // Starting at an instruction that does not match the first pattern element is equivalent to starting
        // at the next one that does, so only those positions need to be tried.
        for (var start = 0; start < instructions.Count; start++)
        {
            if (instructions[start].Opcode == pattern[0].Opcode && Same(instructions[start], pattern[0]) &&
                OrderedFrom(instructions, pattern, start))
            {
                return true;
            }
        }

        return false;
    }

    private static bool Contiguous(IReadOnlyList<JvmInstruction> instructions, IReadOnlyList<CompiledInstruction> pattern)
    {
        for (var start = 0; start + pattern.Count <= instructions.Count; start++)
        {
            var matched = true;
            for (var k = 0; k < pattern.Count; k++)
            {
                var instruction = instructions[start + k];
                if (instruction.Opcode != pattern[k].Opcode || !Same(instruction, pattern[k]))
                {
                    matched = false;
                    break;
                }
            }

            if (matched)
            {
                return true;
            }
        }

        return false;
    }

    private static bool Same(JvmInstruction instruction, CompiledInstruction pattern) =>
        (pattern.Type is null || string.Equals(instruction.TypeName, pattern.Type, StringComparison.Ordinal)) &&
        (pattern.Owner is null || string.Equals(instruction.Owner, pattern.Owner, StringComparison.Ordinal)) &&
        (pattern.Name is null || string.Equals(instruction.Name, pattern.Name, StringComparison.Ordinal)) &&
        (pattern.Descriptor is null || string.Equals(instruction.Descriptor, pattern.Descriptor, StringComparison.Ordinal)) &&
        (pattern.Operand is null || instruction.IntOperand == pattern.Operand);
}
