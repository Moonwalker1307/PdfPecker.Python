using System.Buffers.Binary;
using System.Globalization;
using System.Text;
using System.Text.Json;
using PdfPecker;

namespace PdfPecker.Native;

// The operations behind pdfpecker_invoke. Option names are the Python keyword arguments, so the Python side passes
// them through unchanged; an option that an operation does not know is an error, so a typo never passes silently.
static class Operations
{
    public static byte[] Run(string op, ReadOnlySpan<byte> input, JsonElement options)
    {
        var o = new OptionReader(options);
        using var timeout = o.Timeout();
        var token = timeout?.Token ?? CancellationToken.None;
        byte[] result = op switch
        {
            "html_to_pdf" => HtmlToPdf.Convert(Encoding.UTF8.GetString(input), PdfOptionsOf(o), token),
            "markdown_to_pdf" => MarkdownToPdf.Convert(Encoding.UTF8.GetString(input), PdfOptionsOf(o), null, token),
            "pdf_page_count" => Encoding.UTF8.GetBytes(PdfRenderer.Open(input.ToArray(), o.String("password")).PageCount
                .ToString(CultureInfo.InvariantCulture)),
            "pdf_to_images" => PdfToImages(input.ToArray(), o, token),
            "pdf_to_text" => PdfToText(input.ToArray(), o, token),
            "merge_pdfs" => Merge(Frames.Read(input), o, token),
            "pdf_to_markdown" => Encoding.UTF8.GetBytes(PdfToMarkdownOf(input.ToArray(), o, token)),
            "pdf_to_pdfa" => ToPdfA(input.ToArray(), o, token),
            "redact_pdf" => Redact(input.ToArray(), o, token),
            "read_barcodes" => ReadBarcodes(input.ToArray(), o, token),
            _ => throw new ArgumentException("unknown operation: " + op),
        };
        o.ThrowOnUnused();
        return result;
    }

    static PdfOptions PdfOptionsOf(OptionReader o)
    {
        try { return PdfOptionsOfUnchecked(o); }
        catch (InvalidOperationException e) { throw new ArgumentException("an option has the wrong type: " + e.Message); }
    }

    static PdfOptions PdfOptionsOfUnchecked(OptionReader o)
    {
        var options = new PdfOptions();
        if (o.String("base_dir") is { } baseDir) options.BaseDirectory = baseDir;
        options.AllowFileAccess = o.Bool("allow_file_access") ?? false;
        if (o.Parse("page_size", static size => size.ValueKind == JsonValueKind.Array
                ? PageSize.FromMillimeters(size[0].GetSingle(), size[1].GetSingle())
                : (size.GetString() ?? "").ToUpperInvariant() switch
                {
                    "A3" => PageSize.A3,
                    "A4" => PageSize.A4,
                    "A5" => PageSize.A5,
                    "LETTER" => PageSize.Letter,
                    "LEGAL" => PageSize.Legal,
                    _ => throw new ArgumentException("page_size must be A3, A4, A5, Letter, Legal or (width_mm, height_mm), not " + size),
                }) is { } pageSize)
            options.PageSize = pageSize;
        if (o.Bool("landscape") == true) options.PageSize = options.PageSize.Landscape;
        if (o.Parse("margin", static margin => margin.ValueKind == JsonValueKind.Array
                ? new PageMargins(margin[0].GetSingle(), margin[1].GetSingle(), margin[2].GetSingle(), margin[3].GetSingle())
                : new PageMargins(margin.GetSingle())) is { } margins)
            options.Margins = margins;
        if (o.Float("scale") is { } scale) options.Scale = scale;
        if (o.Bool("shrink_to_fit") is { } shrink) options.ShrinkToFit = shrink;
        options.Title = o.String("title");
        options.Author = o.String("author");
        options.Subject = o.String("subject");
        options.Keywords = o.String("keywords");
        options.Language = o.String("language");
        options.HeaderText = o.String("header_text");
        options.FooterText = o.String("footer_text");
        options.UserStyleSheet = o.String("user_style_sheet");
        if (o.Bool("compress") is { } compress) options.Compress = compress;
        if (o.Bool("bookmarks") is { } bookmarks) options.Bookmarks = bookmarks;
        if (o.Int("max_pages") is { } maxPages) options.MaxPages = maxPages;
        if (o.Long("creation_date") is { } seconds) options.CreationDate = DateTimeOffset.FromUnixTimeSeconds(seconds);
        if (o.String("conformance") is { } conformance)
            options.Conformance = conformance.ToLowerInvariant() switch
            {
                "pdf/a-2b" or "pdfa-2b" => PdfConformance.PdfA2b,
                "pdf/a-3b" or "pdfa-3b" => PdfConformance.PdfA3b,
                "pdf/a-2u" or "pdfa-2u" => PdfConformance.PdfA2u,
                "pdf/a-3u" or "pdfa-3u" => PdfConformance.PdfA3u,
                "pdf/a-2a" or "pdfa-2a" => PdfConformance.PdfA2a,
                "pdf/a-3a" or "pdfa-3a" => PdfConformance.PdfA3a,
                "pdf/a-4" or "pdfa-4" => PdfConformance.PdfA4,
                "pdf/a-4f" or "pdfa-4f" => PdfConformance.PdfA4f,
                _ => throw new ArgumentException("conformance must be PDF/A-2b, -3b, -2u, -3u, -2a, -3a, -4 or -4f, not " + conformance),
            };
        if (o.String("accessibility") is { } accessibility)
            options.Accessibility = accessibility.ToLowerInvariant() switch
            {
                "tagged" => PdfAccessibility.Tagged,
                "pdf/ua-1" or "pdfua-1" => PdfAccessibility.PdfUA1,
                "pdf/ua-2" or "pdfua-2" => PdfAccessibility.PdfUA2,
                _ => throw new ArgumentException("accessibility must be tagged, PDF/UA-1 or PDF/UA-2, not " + accessibility),
            };
        if (o.Bool("use_system_fonts") is { } systemFonts) options.UseSystemFonts = systemFonts;
        if (o.Element("fonts") is { } fonts)
            foreach (var font in fonts.EnumerateArray())
            {
                string path = font.GetString() ?? throw new ArgumentException("fonts must be a list of paths");
                if (Directory.Exists(path)) options.Fonts.AddDirectory(path);
                else options.Fonts.AddFile(path);
            }
        return options;
    }

    static byte[] PdfToImages(byte[] pdf, OptionReader o, CancellationToken token)
    {
        var options = new ImageOptions { Password = o.String("password") };
        if (o.Float("dpi") is { } dpi) options.Dpi = dpi;
        options.Width = o.Int("width");
        options.Height = o.Int("height");
        if (o.Bool("transparent") is { } transparent) options.Transparent = transparent;
        if (o.String("format") is { } format)
            options.Format = format.ToLowerInvariant() switch
            {
                "png" => PdfImageFormat.Png,
                "jpeg" or "jpg" => PdfImageFormat.Jpeg,
                "webp" => PdfImageFormat.WebP,
                _ => throw new ArgumentException("format must be png, jpeg or webp, not " + format),
            };
        if (o.Int("quality") is { } quality) options.Quality = quality;
        var renderer = PdfRenderer.Open(pdf, options.Password);
        var pages = PagesOf(o, renderer.PageCount);
        var images = new byte[pages.Count][];
        for (int i = 0; i < pages.Count; i++)
            images[i] = renderer.RenderPageEncoded(pages[i] - 1, options, token);
        return Frames.Write(images);
    }

    static byte[] PdfToText(byte[] pdf, OptionReader o, CancellationToken token)
    {
        var options = new PdfTextOptions { Password = o.String("password") };
        if (o.String("pages") is { } pages) options.Pages = PdfPageRange.Parse(pages);
        if (o.String("order") is { } order)
            options.Order = order.ToLowerInvariant() switch
            {
                "reading" => PdfTextOrder.Reading,
                "top_to_bottom" => PdfTextOrder.TopToBottom,
                _ => throw new ArgumentException("order must be reading or top_to_bottom, not " + order),
            };
        var texts = PdfText.ExtractPages(pdf, options, token);
        return Frames.Write(texts.Select(t => Encoding.UTF8.GetBytes(t.Text)).ToArray());
    }

    static byte[] Merge(byte[][] pdfs, OptionReader o, CancellationToken token)
    {
        var options = new PdfMergeOptions { Title = o.String("title"), Author = o.String("author") };
        if (o.Bool("bookmarks") is { } bookmarks) options.Bookmarks = bookmarks;
        if (o.Long("creation_date") is { } seconds) options.CreationDate = DateTimeOffset.FromUnixTimeSeconds(seconds);
        return PdfMerger.Merge(pdfs, options, token);
    }

    static string PdfToMarkdownOf(byte[] pdf, OptionReader o, CancellationToken token)
    {
        var options = new PdfMarkdownOptions { Password = o.String("password") };
        if (o.String("pages") is { } pages) options.Pages = PdfPageRange.Parse(pages);
        if (o.Bool("include_links") is { } links) options.IncludeLinks = links;
        if (o.Bool("include_annotations") is { } annotations) options.RenderAnnotations = annotations;
        if (o.Bool("include_images") is { } images) options.IncludeImages = images;
        if (o.Bool("page_comments") is { } comments) options.IncludePageComments = comments;
        if (o.Int("max_pages") is { } maxPages) options.MaxPages = maxPages;
        return PdfToMarkdown.Convert(pdf, options, token);
    }

    // The result is two frames: the converted PDF, then a JSON object with the lists of changes and problems, written
    // with Utf8JsonWriter because serializer reflection would break trimming.
    static byte[] ToPdfA(byte[] pdf, OptionReader o, CancellationToken token)
    {
        var options = new PdfAConversionOptions();
        if (o.String("conformance") is { } conformance)
            options.Conformance = conformance.ToLowerInvariant() switch
            {
                "pdf/a-2b" or "pdfa-2b" => PdfConformance.PdfA2b,
                "pdf/a-2u" or "pdfa-2u" => PdfConformance.PdfA2u,
                "pdf/a-3b" or "pdfa-3b" => PdfConformance.PdfA3b,
                "pdf/a-3u" or "pdfa-3u" => PdfConformance.PdfA3u,
                _ => throw new ArgumentException("conformance must be PDF/A-2b, -2u, -3b or -3u, not " + conformance),
            };
        var result = PdfToPdfA.Convert(pdf, options, token);
        using var report = new MemoryStream();
        using (var json = new Utf8JsonWriter(report))
        {
            json.WriteStartObject();
            WriteList(json, "changes", result.Changes);
            WriteList(json, "problems", result.Problems);
            json.WriteEndObject();
        }
        return Frames.Write([result.Pdf, report.ToArray()]);
    }

    // Areas come as [page, x, y, width, height] lists; text and pattern add the areas of the words that hold them, as
    // PdfRedactor.FindText finds them, so that one call can combine all three.
    static byte[] Redact(byte[] pdf, OptionReader o, CancellationToken token)
    {
        var areas = new List<PdfRedactionArea>();
        if (o.Element("areas") is { } list)
        {
            if (list.ValueKind != JsonValueKind.Array) throw new ArgumentException("areas must be a list of (page, x, y, width, height)");
            foreach (var a in list.EnumerateArray())
            {
                if (a.ValueKind != JsonValueKind.Array || a.GetArrayLength() != 5)
                    throw new ArgumentException("each area must be (page, x, y, width, height), not " + a.GetRawText());
                try { areas.Add(new PdfRedactionArea(a[0].GetInt32(), a[1].GetDouble(), a[2].GetDouble(), a[3].GetDouble(), a[4].GetDouble())); }
                catch (Exception e) when (e is InvalidOperationException or FormatException)
                {
                    throw new ArgumentException("each area must be (page, x, y, width, height) numbers, not " + a.GetRawText());
                }
            }
        }
        bool ignoreCase = o.Bool("ignore_case") ?? false;
        if (o.String("text") is { } text)
            areas.AddRange(PdfRedactor.FindText(pdf, text, ignoreCase ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal, token));
        if (o.String("pattern") is { } pattern)
        {
            var regexOptions = System.Text.RegularExpressions.RegexOptions.CultureInvariant
                | (ignoreCase ? System.Text.RegularExpressions.RegexOptions.IgnoreCase : 0);
            System.Text.RegularExpressions.Regex regex;
            try { regex = new System.Text.RegularExpressions.Regex(pattern, regexOptions, TimeSpan.FromSeconds(5)); }
            catch (ArgumentException e) { throw new ArgumentException("pattern is not a valid regular expression: " + e.Message); }
            areas.AddRange(PdfRedactor.FindText(pdf, regex, token));
        }
        var options = new PdfRedactOptions();
        if (o.Element("fill_color") is { } fill) options.FillColor = fill.ValueKind == JsonValueKind.String
            ? fill.GetString()
            : throw new ArgumentException("fill_color must be a CSS colour or None");
        return PdfRedactor.Redact(pdf, areas, options, token);
    }

    // Reads the barcodes of an image or, when the input starts like a PDF, of its pages. The result is a JSON list
    // written with Utf8JsonWriter, as for ToPdfA.
    static byte[] ReadBarcodes(byte[] input, OptionReader o, CancellationToken token)
    {
        var formats = BarcodeFormat.All;
        if (o.Element("formats") is { } list)
        {
            if (list.ValueKind != JsonValueKind.Array) throw new ArgumentException("formats must be a list of format names");
            formats = 0;
            foreach (var f in list.EnumerateArray())
                formats |= (f.ValueKind == JsonValueKind.String ? f.GetString() : null)?.ToLowerInvariant() switch
                {
                    "qr" or "qr_code" => BarcodeFormat.QrCode,
                    "data_matrix" => BarcodeFormat.DataMatrix,
                    "code128" or "code_128" => BarcodeFormat.Code128,
                    "ean13" or "ean_13" => BarcodeFormat.Ean13,
                    _ => throw new ArgumentException("formats are qr_code, data_matrix, code128 and ean13, not " + f.GetRawText()),
                };
            if (formats == 0) throw new ArgumentException("formats is empty");
        }
        bool tryInverted = o.Bool("try_inverted") ?? true;
        string? password = o.String("password");
        string? pages = o.String("pages");
        float? dpi = o.Float("dpi");
        IReadOnlyList<BarcodeResult> found;
        if (input.AsSpan().StartsWith("%PDF"u8) || input.AsSpan(0, Math.Min(input.Length, 1024)).IndexOf("%PDF-"u8) >= 0)
        {
            var options = new PdfBarcodeOptions { Password = password, Formats = formats, TryInverted = tryInverted };
            if (pages != null) options.Pages = PdfPageRange.Parse(pages);
            if (dpi is { } d) options.Dpi = d;
            found = PdfBarcodes.Find(input, options, token);
        }
        else
        {
            if (password != null || pages != null || dpi != null)
                throw new ArgumentException("password, pages and dpi are only for PDFs");
            found = Barcode.Read(input, new BarcodeReaderOptions { Formats = formats, TryInverted = tryInverted }, token);
        }
        using var output = new MemoryStream();
        using (var json = new Utf8JsonWriter(output))
        {
            json.WriteStartArray();
            foreach (var b in found)
            {
                json.WriteStartObject();
                json.WriteString("format", b.Format switch
                {
                    BarcodeFormat.QrCode => "qr_code",
                    BarcodeFormat.DataMatrix => "data_matrix",
                    BarcodeFormat.Code128 => "code128",
                    BarcodeFormat.Ean13 => "ean13",
                    _ => b.Format.ToString().ToLowerInvariant(),
                });
                json.WriteString("text", b.Text);
                json.WriteBase64String("bytes", b.Bytes);
                json.WriteBoolean("is_gs1", b.IsGs1);
                json.WriteNumber("page", b.PageNumber);
                json.WriteNumber("x", b.X);
                json.WriteNumber("y", b.Y);
                json.WriteNumber("width", b.Width);
                json.WriteNumber("height", b.Height);
                json.WriteStartArray("corners");
                foreach (var c in b.Corners)
                {
                    json.WriteStartArray();
                    json.WriteNumberValue(c.X);
                    json.WriteNumberValue(c.Y);
                    json.WriteEndArray();
                }
                json.WriteEndArray();
                json.WriteEndObject();
            }
            json.WriteEndArray();
        }
        return output.ToArray();
    }

    static void WriteList(Utf8JsonWriter json, string name, IReadOnlyList<string> items)
    {
        json.WriteStartArray(name);
        foreach (var item in items) json.WriteStringValue(item);
        json.WriteEndArray();
    }

    static IReadOnlyList<int> PagesOf(OptionReader o, int pageCount) =>
        o.String("pages") is { } pages
            ? PdfPageRange.Parse(pages).ToPageNumbers(pageCount)
            : Enumerable.Range(1, pageCount).ToList();
}

// Reads options and remembers which were used, so an unknown option fails the call.
sealed class OptionReader(JsonElement root)
{
    readonly HashSet<string> used = new(StringComparer.Ordinal);

    public JsonElement? Element(string name)
    {
        used.Add(name);
        return root.TryGetProperty(name, out var value) && value.ValueKind != JsonValueKind.Null ? value : null;
    }

    public string? String(string name) => Read(name, static e => e.GetString());
    public bool? Bool(string name) => Read(name, static e => e.GetBoolean());
    public int? Int(string name) => Read(name, static e => e.GetInt32());
    public long? Long(string name) => Read(name, static e => e.GetInt64());
    public float? Float(string name) => Read(name, static e => e.GetSingle());

    public T? Parse<T>(string name, Func<JsonElement, T> parse) where T : struct => Read(name, parse);

    // CancellationTokenSource takes at most int.MaxValue milliseconds (about 24.8 days), and TimeSpan.FromSeconds
    // throws OverflowException for a huge value, which would reach the caller as an unexpected error.
    public CancellationTokenSource? Timeout() =>
        Read("timeout", static e => e.GetDouble()) is { } seconds
            ? new CancellationTokenSource(TimeSpan.FromSeconds(seconds is > 0 and <= MaxTimeoutSeconds
                ? seconds
                : throw new ArgumentException("timeout must be positive and at most 2,147,483 seconds")))
            : null;

    const double MaxTimeoutSeconds = int.MaxValue / 1000;

    // JsonElement throws InvalidOperationException or FormatException for a value of the wrong type; the caller gave
    // the wrong type, so it is reported as an argument error that names the option.
    T? Read<T>(string name, Func<JsonElement, T> read) where T : struct => Element(name) is { } e ? Convert(name, e, read) : null;
    string? Read(string name, Func<JsonElement, string?> read) => Element(name) is { } e ? Convert(name, e, read) : null;

    static T Convert<T>(string name, JsonElement e, Func<JsonElement, T> read)
    {
        try { return read(e); }
        catch (Exception ex) when (ex is InvalidOperationException or FormatException or IndexOutOfRangeException)
        {
            throw new ArgumentException($"option {name} has the wrong type: {e.GetRawText()}");
        }
    }

    public void ThrowOnUnused()
    {
        foreach (var property in root.EnumerateObject())
            if (!used.Contains(property.Name))
                throw new ArgumentException("unknown option: " + property.Name);
    }
}

// The list framing of the ABI: an int32 count, then an int64 length and the bytes of each item, little-endian.
static class Frames
{
    public static byte[] Write(IReadOnlyList<byte[]> items)
    {
        long total = 4;
        foreach (var item in items) total += 8 + item.Length;
        if (total > Array.MaxLength) throw new PdfLimitException("the result is larger than 2 GB");
        var output = new byte[total];
        BinaryPrimitives.WriteInt32LittleEndian(output, items.Count);
        int at = 4;
        foreach (var item in items)
        {
            BinaryPrimitives.WriteInt64LittleEndian(output.AsSpan(at), item.Length);
            item.CopyTo(output, at + 8);
            at += 8 + item.Length;
        }
        return output;
    }

    public static byte[][] Read(ReadOnlySpan<byte> input)
    {
        if (input.Length < 4) throw new ArgumentException("the input list is empty");
        int count = BinaryPrimitives.ReadInt32LittleEndian(input);
        if (count < 0 || count > input.Length / 8) throw new ArgumentException("the input list is malformed");
        var items = new byte[count][];
        int at = 4;
        for (int i = 0; i < count; i++)
        {
            if (input.Length - at < 8) throw new ArgumentException("the input list is malformed");
            long length = BinaryPrimitives.ReadInt64LittleEndian(input[at..]);
            at += 8;
            if (length < 0 || length > input.Length - at) throw new ArgumentException("the input list is malformed");
            items[i] = input.Slice(at, (int)length).ToArray();
            at += (int)length;
        }
        return items;
    }
}
