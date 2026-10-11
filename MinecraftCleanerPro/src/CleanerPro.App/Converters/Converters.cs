using System.Globalization;
using System.Windows;
using System.Windows.Data;
using CleanerPro.Core;
using CleanerPro.Core.Models;

namespace CleanerPro.App.Converters;

public sealed class InverseBooleanConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) => value is not true;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => value is not true;
}

public sealed class BooleanToVisibilityInverseConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) => value is true ? Visibility.Collapsed : Visibility.Visible;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => Binding.DoNothing;
}

/// <summary>Visible when the value is not null and not an empty string or collection.</summary>
public sealed class HasValueToVisibilityConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object parameter, CultureInfo culture)
    {
        var hasValue = value switch
        {
            null => false,
            string s => !string.IsNullOrWhiteSpace(s),
            int i => i != 0,
            long l => l != 0,
            System.Collections.ICollection c => c.Count > 0,
            _ => true,
        };
        var invert = parameter is string p && p == "invert";
        return hasValue ^ invert ? Visibility.Visible : Visibility.Collapsed;
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => Binding.DoNothing;
}

public sealed class ClassificationTextConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) => value switch
    {
        Classification c => ClassificationOrder.ToDisplay(c),
        RecommendedAction a => ClassificationOrder.ToDisplay(a),
        CleanupStatus s => ClassificationOrder.ToDisplay(s),
        null => string.Empty,
        _ => value.ToString() ?? string.Empty,
    };

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => Binding.DoNothing;
}

/// <summary>Maps a classification to its theme brush (looked up dynamically so theme changes apply).</summary>
public sealed class ClassificationBrushConverter : IValueConverter
{
    public object? Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        var key = value switch
        {
            Classification.KnownMatch => "Brush.Class.Known",
            Classification.HighConfidenceSuspicion => "Brush.Class.High",
            Classification.NeedsReview => "Brush.Class.Review",
            Classification.LikelyLegitimate => "Brush.Class.Legit",
            _ => "Brush.Class.Unverified",
        };
        return Application.Current?.TryFindResource(key);
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => Binding.DoNothing;
}

public sealed class BytesConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) => value switch
    {
        long bytes => Format(bytes),
        int bytes => Format(bytes),
        _ => "—",
    };

    public static string Format(long bytes) => bytes switch
    {
        < 1024 => $"{bytes} B",
        < 1024 * 1024 => $"{bytes / 1024.0:0.#} KB",
        < 1024L * 1024 * 1024 => $"{bytes / (1024.0 * 1024):0.#} MB",
        _ => $"{bytes / (1024.0 * 1024 * 1024):0.##} GB",
    };

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => Binding.DoNothing;
}

public sealed class LocalTimeConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) => value switch
    {
        DateTimeOffset time => time.ToLocalTime().ToString("g", culture),
        null => "—",
        _ => value.ToString() ?? "—",
    };

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => Binding.DoNothing;
}

public sealed class JoinConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is System.Collections.IEnumerable items and not string
            ? string.Join(parameter as string ?? ", ", items.Cast<object>())
            : value?.ToString() ?? string.Empty;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) => Binding.DoNothing;
}
