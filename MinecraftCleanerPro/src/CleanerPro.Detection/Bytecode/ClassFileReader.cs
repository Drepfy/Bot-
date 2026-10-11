using System.Buffers.Binary;
using System.Text;

namespace CleanerPro.Detection.Bytecode;

/// <summary>A decoded JVM instruction with the symbolic operands needed for signature matching.</summary>
public readonly record struct JvmInstruction(byte Opcode, int? IntOperand, string? TypeName, string? Owner, string? Name, string? Descriptor);

public sealed record JvmMethod(string Name, string Descriptor, IReadOnlyList<JvmInstruction> Instructions);

public sealed class ClassFormatException(string message) : Exception(message);

/// <summary>
/// Minimal, bounds-checked reader for Java class files. It decodes the constant pool and method
/// bytecode so documented malware signatures can be matched statically. Nothing is loaded or executed.
/// </summary>
public static class ClassFileReader
{
    private const uint Magic = 0xCAFEBABE;
    private const int MaxConstantPoolEntries = 65535;

    public static IReadOnlyList<JvmMethod> ReadMethods(ReadOnlySpan<byte> data)
    {
        var reader = new SpanReader(data);
        if (reader.U4() != Magic)
        {
            throw new ClassFormatException("Not a class file (bad magic number).");
        }

        reader.Skip(4); // minor, major version
        var pool = ReadConstantPool(ref reader);
        reader.Skip(6); // access flags, this_class, super_class
        var interfaces = reader.U2();
        reader.Skip(interfaces * 2);

        var fields = reader.U2();
        for (var i = 0; i < fields; i++)
        {
            reader.Skip(6);
            SkipAttributes(ref reader);
        }

        var methodCount = reader.U2();
        var methods = new List<JvmMethod>(methodCount);
        for (var i = 0; i < methodCount; i++)
        {
            reader.Skip(2); // access flags
            var name = pool.Utf8(reader.U2());
            var descriptor = pool.Utf8(reader.U2());
            var attributeCount = reader.U2();
            IReadOnlyList<JvmInstruction> instructions = [];
            for (var a = 0; a < attributeCount; a++)
            {
                var attributeName = pool.Utf8(reader.U2());
                var length = checked((int)reader.U4());
                var body = reader.Bytes(length);
                if (attributeName == "Code")
                {
                    instructions = DecodeCode(body, pool);
                }
            }

            methods.Add(new JvmMethod(name, descriptor, instructions));
        }

        return methods;
    }

    private static List<JvmInstruction> DecodeCode(ReadOnlySpan<byte> codeAttribute, ConstantPool pool)
    {
        var reader = new SpanReader(codeAttribute);
        reader.Skip(4); // max_stack, max_locals
        var codeLength = checked((int)reader.U4());
        var code = reader.Bytes(codeLength);
        var instructions = new List<JvmInstruction>();
        var pc = 0;
        while (pc < code.Length)
        {
            var opcode = code[pc];
            int length;
            switch (opcode)
            {
                case JvmOpcodes.Tableswitch:
                {
                    var p = Align(pc + 1);
                    Need(code, p, 12);
                    var low = BinaryPrimitives.ReadInt32BigEndian(code[(p + 4)..]);
                    var high = BinaryPrimitives.ReadInt32BigEndian(code[(p + 8)..]);
                    var count = (long)high - low + 1;
                    if (count < 0 || count > 65536)
                    {
                        throw new ClassFormatException("Invalid tableswitch range.");
                    }

                    length = p + 12 + (int)count * 4 - pc;
                    instructions.Add(new JvmInstruction(opcode, null, null, null, null, null));
                    break;
                }

                case JvmOpcodes.Lookupswitch:
                {
                    var p = Align(pc + 1);
                    Need(code, p, 8);
                    var pairs = BinaryPrimitives.ReadInt32BigEndian(code[(p + 4)..]);
                    if (pairs < 0 || pairs > 65536)
                    {
                        throw new ClassFormatException("Invalid lookupswitch size.");
                    }

                    length = p + 8 + pairs * 8 - pc;
                    instructions.Add(new JvmInstruction(opcode, null, null, null, null, null));
                    break;
                }

                case JvmOpcodes.Wide:
                {
                    Need(code, pc, 2);
                    length = code[pc + 1] == 0x84 ? 6 : 4; // wide iinc has an extra 16-bit constant
                    instructions.Add(new JvmInstruction(code[pc + 1], null, null, null, null, null));
                    break;
                }

                default:
                {
                    length = JvmOpcodes.FixedLength(opcode);
                    if (length <= 0)
                    {
                        throw new ClassFormatException($"Unknown opcode 0x{opcode:X2} at {pc}.");
                    }

                    Need(code, pc, length);
                    instructions.Add(Decode(opcode, code.Slice(pc, length), pool));
                    break;
                }
            }

            if (length <= 0)
            {
                throw new ClassFormatException("Invalid instruction length.");
            }

            Need(code, pc, length);
            pc += length;
        }

        return instructions;

        static int Align(int position) => (position + 3) & ~3;
    }

    private static JvmInstruction Decode(byte opcode, ReadOnlySpan<byte> bytes, ConstantPool pool)
    {
        switch (opcode)
        {
            case JvmOpcodes.Bipush:
                return new JvmInstruction(opcode, unchecked((sbyte)bytes[1]), null, null, null, null);
            case JvmOpcodes.Sipush:
                return new JvmInstruction(opcode, BinaryPrimitives.ReadInt16BigEndian(bytes[1..]), null, null, null, null);
            case JvmOpcodes.New:
            case JvmOpcodes.Anewarray:
            case JvmOpcodes.Checkcast:
            case JvmOpcodes.Instanceof:
            case JvmOpcodes.Multianewarray:
                return new JvmInstruction(opcode, null, pool.ClassName(BinaryPrimitives.ReadUInt16BigEndian(bytes[1..])), null, null, null);
            case JvmOpcodes.Invokevirtual:
            case JvmOpcodes.Invokespecial:
            case JvmOpcodes.Invokestatic:
            case JvmOpcodes.Invokeinterface:
            {
                var (owner, name, descriptor) = pool.MemberRef(BinaryPrimitives.ReadUInt16BigEndian(bytes[1..]));
                return new JvmInstruction(opcode, null, null, owner, name, descriptor);
            }

            default:
                return new JvmInstruction(opcode, null, null, null, null, null);
        }
    }

    private static void Need(ReadOnlySpan<byte> code, int offset, int count)
    {
        if (offset < 0 || count < 0 || offset + count > code.Length)
        {
            throw new ClassFormatException("Instruction extends past the end of the code array.");
        }
    }

    private static ConstantPool ReadConstantPool(ref SpanReader reader)
    {
        var count = reader.U2();
        if (count == 0 || count > MaxConstantPoolEntries)
        {
            throw new ClassFormatException("Invalid constant pool size.");
        }

        var pool = new ConstantPool(count);
        for (var index = 1; index < count; index++)
        {
            var tag = reader.U1();
            switch (tag)
            {
                case 1: // Utf8
                {
                    var length = reader.U2();
                    pool.SetUtf8(index, DecodeModifiedUtf8(reader.Bytes(length)));
                    break;
                }

                case 3: // Integer
                case 4: // Float
                    reader.Skip(4);
                    break;
                case 5: // Long
                case 6: // Double
                    reader.Skip(8);
                    index++; // takes two slots
                    break;
                case 7: // Class
                case 8: // String
                case 16: // MethodType
                case 19: // Module
                case 20: // Package
                    pool.SetRef(index, tag, reader.U2(), 0);
                    break;
                case 9: // Fieldref
                case 10: // Methodref
                case 11: // InterfaceMethodref
                case 12: // NameAndType
                case 17: // Dynamic
                case 18: // InvokeDynamic
                    pool.SetRef(index, tag, reader.U2(), reader.U2());
                    break;
                case 15: // MethodHandle
                    reader.Skip(3);
                    break;
                default:
                    throw new ClassFormatException($"Unknown constant pool tag {tag}.");
            }
        }

        return pool;
    }

    private static void SkipAttributes(ref SpanReader reader)
    {
        var count = reader.U2();
        for (var i = 0; i < count; i++)
        {
            reader.Skip(2);
            reader.Skip(checked((int)reader.U4()));
        }
    }

    private static string DecodeModifiedUtf8(ReadOnlySpan<byte> bytes)
    {
        // Class names in the signatures are ASCII; standard UTF-8 decoding is sufficient for comparison.
        return Encoding.UTF8.GetString(bytes);
    }

    private sealed class ConstantPool(int count)
    {
        private readonly string?[] _utf8 = new string?[count];
        private readonly byte[] _tags = new byte[count];
        private readonly int[] _ref1 = new int[count];
        private readonly int[] _ref2 = new int[count];

        public void SetUtf8(int index, string value)
        {
            _tags[index] = 1;
            _utf8[index] = value;
        }

        public void SetRef(int index, byte tag, int first, int second)
        {
            _tags[index] = tag;
            _ref1[index] = first;
            _ref2[index] = second;
        }

        public string Utf8(int index)
        {
            if (index <= 0 || index >= _tags.Length || _tags[index] != 1)
            {
                throw new ClassFormatException($"Constant {index} is not a UTF-8 entry.");
            }

            return _utf8[index]!;
        }

        public string ClassName(int index)
        {
            Check(index, 7);
            return Utf8(_ref1[index]);
        }

        public (string Owner, string Name, string Descriptor) MemberRef(int index)
        {
            if (index <= 0 || index >= _tags.Length || _tags[index] is not (9 or 10 or 11))
            {
                throw new ClassFormatException($"Constant {index} is not a member reference.");
            }

            var owner = ClassName(_ref1[index]);
            var nameAndType = _ref2[index];
            Check(nameAndType, 12);
            return (owner, Utf8(_ref1[nameAndType]), Utf8(_ref2[nameAndType]));
        }

        private void Check(int index, byte tag)
        {
            if (index <= 0 || index >= _tags.Length || _tags[index] != tag)
            {
                throw new ClassFormatException($"Constant {index} has an unexpected type.");
            }
        }
    }

    private ref struct SpanReader(ReadOnlySpan<byte> data)
    {
        private readonly ReadOnlySpan<byte> _data = data;
        private int _position;

        public byte U1()
        {
            Ensure(1);
            return _data[_position++];
        }

        public ushort U2()
        {
            Ensure(2);
            var value = BinaryPrimitives.ReadUInt16BigEndian(_data[_position..]);
            _position += 2;
            return value;
        }

        public uint U4()
        {
            Ensure(4);
            var value = BinaryPrimitives.ReadUInt32BigEndian(_data[_position..]);
            _position += 4;
            return value;
        }

        public ReadOnlySpan<byte> Bytes(int count)
        {
            Ensure(count);
            var slice = _data.Slice(_position, count);
            _position += count;
            return slice;
        }

        public void Skip(int count)
        {
            Ensure(count);
            _position += count;
        }

        private readonly void Ensure(int count)
        {
            if (count < 0 || _position + count > _data.Length)
            {
                throw new ClassFormatException("Unexpected end of class file.");
            }
        }
    }
}
