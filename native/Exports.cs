using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using PdfPecker;

namespace PdfPecker.Native;

// The C ABI the Python and Node packages call. There is one entry point that takes an operation name, so a new operation does
// not change the ABI:
//
//   int  pdfpecker_invoke(const char* op, const uint8_t* input, int64_t input_len, const char* options_json,
//                         uint8_t** output, int64_t* output_len, char** error);
//   void pdfpecker_free(void* p);
//   const char* pdfpecker_version(void);         (static, never freed)
//   int  pdfpecker_abi_version(void);            (bumped when the calling convention changes)
//
// pdfpecker_invoke returns a Status. On success *output holds the result, on failure *error holds a UTF-8 message;
// both are allocated here and released with pdfpecker_free. Lists (several PDFs in, several images or pages out) are
// framed as a little-endian int32 count followed by an int64 length and the bytes of each item.
//
// No exception crosses the boundary: one that unwound into native code would end the process, so every call catches
// everything and reports it as a status.
public static unsafe class Exports
{
    const int AbiVersion = 1;
    static readonly byte* VersionString = Utf8(
        typeof(HtmlToPdf).Assembly.GetName().Version is { } v ? $"{v.Major}.{v.Minor}.{v.Build}" : "unknown");

    [UnmanagedCallersOnly(EntryPoint = "pdfpecker_version")]
    public static byte* Version() => VersionString;

    [UnmanagedCallersOnly(EntryPoint = "pdfpecker_abi_version")]
    public static int Abi() => AbiVersion;

    [UnmanagedCallersOnly(EntryPoint = "pdfpecker_free")]
    public static void Free(void* p) => NativeMemory.Free(p);

    [UnmanagedCallersOnly(EntryPoint = "pdfpecker_invoke")]
    public static int Invoke(byte* op, byte* input, long inputLength, byte* optionsJson, byte** output, long* outputLength, byte** error)
    {
        if (error != null) *error = null;
        if (output == null || outputLength == null || op == null || (input == null && inputLength != 0)
            || inputLength < 0 || inputLength > Array.MaxLength)
            return Fail(error, Status.BadArgument, "op, output and output_len must be set, and input_len must be a valid length");
        *output = null;
        *outputLength = 0;
        try
        {
            string name = Marshal.PtrToStringUTF8((nint)op)!;
            var data = new ReadOnlySpan<byte>(input, (int)inputLength);
            using var options = optionsJson == null
                ? JsonDocument.Parse("{}")
                : JsonDocument.Parse(MemoryMarshal.CreateReadOnlySpanFromNullTerminated(optionsJson).ToArray());
            var root = options.RootElement;
            if (root.ValueKind != JsonValueKind.Object) throw new ArgumentException("options must be a JSON object");
            byte[] result = Operations.Run(name, data, root);
            byte* buffer = (byte*)NativeMemory.Alloc((nuint)Math.Max(result.Length, 1));
            result.AsSpan().CopyTo(new Span<byte>(buffer, result.Length));
            *output = buffer;
            *outputLength = result.Length;
            return Status.Ok;
        }
        catch (Exception e)
        {
            return Fail(error, Status.Of(e), e.Message);
        }
    }

    static int Fail(byte** error, int status, string message)
    {
        if (error != null) *error = Utf8(message);
        return status;
    }

    static byte* Utf8(string s)
    {
        int length = Encoding.UTF8.GetByteCount(s);
        byte* p = (byte*)NativeMemory.Alloc((nuint)length + 1);
        Encoding.UTF8.GetBytes(s, new Span<byte>(p, length));
        p[length] = 0;
        return p;
    }
}

// The statuses pdfpecker_invoke returns; the Python package maps each to an exception class.
static class Status
{
    public const int Ok = 0;
    public const int BadArgument = 1;      // ArgumentException and its subclasses, bad options
    public const int Unreadable = 2;       // InvalidDataException: input that is not a readable PDF, image or font
    public const int Password = 3;         // PdfPasswordException
    public const int Limit = 4;            // PdfLimitException: a page, size or resource limit was reached
    public const int Timeout = 5;          // the timeout option ran out
    public const int Failed = 6;           // any other PdfPeckerException
    public const int Io = 7;               // IOException, a file that could not be read
    public const int Unexpected = 8;       // anything else: a bug

    public static int Of(Exception e) => e switch
    {
        ArgumentException or JsonException or FormatException => BadArgument,
        InvalidDataException => Unreadable,
        PdfPasswordException => Password,
        PdfLimitException => Limit,
        OperationCanceledException => Timeout,
        PdfPeckerException => Failed,
        IOException or UnauthorizedAccessException => Io,
        _ => Unexpected,
    };
}
