namespace CleanerPro.Detection.Bytecode;

/// <summary>JVM opcode table (JVMS chapter 6) used by the static class-file reader.</summary>
public static class JvmOpcodes
{
    public const byte Bipush = 0x10;
    public const byte Sipush = 0x11;
    public const byte Ldc = 0x12;
    public const byte Tableswitch = 0xAA;
    public const byte Lookupswitch = 0xAB;
    public const byte Getstatic = 0xB2;
    public const byte Invokevirtual = 0xB6;
    public const byte Invokespecial = 0xB7;
    public const byte Invokestatic = 0xB8;
    public const byte Invokeinterface = 0xB9;
    public const byte Invokedynamic = 0xBA;
    public const byte New = 0xBB;
    public const byte Anewarray = 0xBD;
    public const byte Checkcast = 0xC0;
    public const byte Instanceof = 0xC1;
    public const byte Wide = 0xC4;
    public const byte Multianewarray = 0xC5;

    private static readonly string[] Names = BuildNames();
    private static readonly Dictionary<string, byte> ByName = BuildLookup();

    /// <summary>Instruction length including the opcode byte, or -1 for variable-length / invalid opcodes.</summary>
    private static readonly sbyte[] Lengths = BuildLengths();

    public static string NameOf(byte opcode) => Names[opcode];

    public static bool TryParse(string mnemonic, out byte opcode) => ByName.TryGetValue(mnemonic.ToUpperInvariant(), out opcode);

    public static int FixedLength(byte opcode) => Lengths[opcode];

    private static string[] BuildNames()
    {
        var names = new string[256];
        for (var i = 0; i < names.Length; i++)
        {
            names[i] = $"OP_{i:X2}";
        }

        var list = new (int Code, string Name)[]
        {
            (0x00, "NOP"), (0x01, "ACONST_NULL"), (0x02, "ICONST_M1"), (0x03, "ICONST_0"), (0x04, "ICONST_1"), (0x05, "ICONST_2"),
            (0x06, "ICONST_3"), (0x07, "ICONST_4"), (0x08, "ICONST_5"), (0x09, "LCONST_0"), (0x0A, "LCONST_1"), (0x0B, "FCONST_0"),
            (0x0C, "FCONST_1"), (0x0D, "FCONST_2"), (0x0E, "DCONST_0"), (0x0F, "DCONST_1"), (0x10, "BIPUSH"), (0x11, "SIPUSH"),
            (0x12, "LDC"), (0x13, "LDC_W"), (0x14, "LDC2_W"), (0x15, "ILOAD"), (0x16, "LLOAD"), (0x17, "FLOAD"), (0x18, "DLOAD"),
            (0x19, "ALOAD"), (0x1A, "ILOAD_0"), (0x1B, "ILOAD_1"), (0x1C, "ILOAD_2"), (0x1D, "ILOAD_3"), (0x1E, "LLOAD_0"),
            (0x1F, "LLOAD_1"), (0x20, "LLOAD_2"), (0x21, "LLOAD_3"), (0x22, "FLOAD_0"), (0x23, "FLOAD_1"), (0x24, "FLOAD_2"),
            (0x25, "FLOAD_3"), (0x26, "DLOAD_0"), (0x27, "DLOAD_1"), (0x28, "DLOAD_2"), (0x29, "DLOAD_3"), (0x2A, "ALOAD_0"),
            (0x2B, "ALOAD_1"), (0x2C, "ALOAD_2"), (0x2D, "ALOAD_3"), (0x2E, "IALOAD"), (0x2F, "LALOAD"), (0x30, "FALOAD"),
            (0x31, "DALOAD"), (0x32, "AALOAD"), (0x33, "BALOAD"), (0x34, "CALOAD"), (0x35, "SALOAD"), (0x36, "ISTORE"),
            (0x37, "LSTORE"), (0x38, "FSTORE"), (0x39, "DSTORE"), (0x3A, "ASTORE"), (0x4F, "IASTORE"), (0x50, "LASTORE"),
            (0x51, "FASTORE"), (0x52, "DASTORE"), (0x53, "AASTORE"), (0x54, "BASTORE"), (0x55, "CASTORE"), (0x56, "SASTORE"),
            (0x57, "POP"), (0x58, "POP2"), (0x59, "DUP"), (0x5A, "DUP_X1"), (0x5B, "DUP_X2"), (0x5C, "DUP2"), (0x5D, "DUP2_X1"),
            (0x5E, "DUP2_X2"), (0x5F, "SWAP"), (0x60, "IADD"), (0x84, "IINC"), (0x99, "IFEQ"), (0xA7, "GOTO"), (0xA8, "JSR"),
            (0xA9, "RET"), (0xAA, "TABLESWITCH"), (0xAB, "LOOKUPSWITCH"), (0xAC, "IRETURN"), (0xAD, "LRETURN"), (0xAE, "FRETURN"),
            (0xAF, "DRETURN"), (0xB0, "ARETURN"), (0xB1, "RETURN"), (0xB2, "GETSTATIC"), (0xB3, "PUTSTATIC"), (0xB4, "GETFIELD"),
            (0xB5, "PUTFIELD"), (0xB6, "INVOKEVIRTUAL"), (0xB7, "INVOKESPECIAL"), (0xB8, "INVOKESTATIC"), (0xB9, "INVOKEINTERFACE"),
            (0xBA, "INVOKEDYNAMIC"), (0xBB, "NEW"), (0xBC, "NEWARRAY"), (0xBD, "ANEWARRAY"), (0xBE, "ARRAYLENGTH"), (0xBF, "ATHROW"),
            (0xC0, "CHECKCAST"), (0xC1, "INSTANCEOF"), (0xC2, "MONITORENTER"), (0xC3, "MONITOREXIT"), (0xC4, "WIDE"),
            (0xC5, "MULTIANEWARRAY"), (0xC6, "IFNULL"), (0xC7, "IFNONNULL"), (0xC8, "GOTO_W"), (0xC9, "JSR_W"),
        };
        foreach (var (code, name) in list)
        {
            names[code] = name;
        }

        return names;
    }

    private static Dictionary<string, byte> BuildLookup()
    {
        var map = new Dictionary<string, byte>(StringComparer.Ordinal);
        for (var i = 0; i < Names.Length; i++)
        {
            if (!Names[i].StartsWith("OP_", StringComparison.Ordinal))
            {
                map[Names[i]] = (byte)i;
            }
        }

        return map;
    }

    private static sbyte[] BuildLengths()
    {
        var lengths = new sbyte[256];
        Array.Fill(lengths, (sbyte)-1);

        // 1-byte instructions.
        for (var i = 0x00; i <= 0x0F; i++)
        {
            lengths[i] = 1;
        }

        for (var i = 0x1A; i <= 0x35; i++)
        {
            lengths[i] = 1;
        }

        for (var i = 0x3B; i <= 0x83; i++)
        {
            lengths[i] = 1;
        }

        for (var i = 0x85; i <= 0x98; i++)
        {
            lengths[i] = 1;
        }

        for (var i = 0xAC; i <= 0xB1; i++)
        {
            lengths[i] = 1;
        }

        lengths[0xBE] = 1; // arraylength
        lengths[0xBF] = 1; // athrow
        lengths[0xC2] = 1; // monitorenter
        lengths[0xC3] = 1; // monitorexit

        // Instructions with operands.
        lengths[0x10] = 2; // bipush
        lengths[0x11] = 3; // sipush
        lengths[0x12] = 2; // ldc
        lengths[0x13] = 3; // ldc_w
        lengths[0x14] = 3; // ldc2_w
        for (var i = 0x15; i <= 0x19; i++)
        {
            lengths[i] = 2; // xload index
        }

        for (var i = 0x36; i <= 0x3A; i++)
        {
            lengths[i] = 2; // xstore index
        }

        lengths[0x84] = 3; // iinc
        for (var i = 0x99; i <= 0xA8; i++)
        {
            lengths[i] = 3; // if* / goto / jsr
        }

        lengths[0xA9] = 2; // ret
        for (var i = 0xB2; i <= 0xB8; i++)
        {
            lengths[i] = 3; // field access, invokevirtual/special/static
        }

        lengths[0xB9] = 5; // invokeinterface
        lengths[0xBA] = 5; // invokedynamic
        lengths[0xBB] = 3; // new
        lengths[0xBC] = 2; // newarray
        lengths[0xBD] = 3; // anewarray
        lengths[0xC0] = 3; // checkcast
        lengths[0xC1] = 3; // instanceof
        lengths[0xC5] = 4; // multianewarray
        lengths[0xC6] = 3; // ifnull
        lengths[0xC7] = 3; // ifnonnull
        lengths[0xC8] = 5; // goto_w
        lengths[0xC9] = 5; // jsr_w
        return lengths;
    }
}
