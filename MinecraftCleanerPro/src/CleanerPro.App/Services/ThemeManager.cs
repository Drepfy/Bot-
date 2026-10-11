using System.Windows;
using CleanerPro.Configuration;
using Microsoft.Win32;

namespace CleanerPro.App.Services;

/// <summary>Applies the colour theme, high-contrast palette and font scaling from the configuration.</summary>
public static class ThemeManager
{
    private const string ThemeMarker = "Themes/";

    public static string ActiveTheme { get; private set; } = "Light";

    public static void Apply(AppConfiguration config)
    {
        var app = Application.Current;
        if (app is null)
        {
            return;
        }

        var theme = config.Accessibility.HighContrast || SystemParameters.HighContrast
            ? "HighContrast"
            : config.Interface.Theme switch
            {
                ThemePreference.Dark => "Dark",
                ThemePreference.Light => "Light",
                _ => SystemUsesDarkTheme() ? "Dark" : "Light",
            };

        var dictionaries = app.Resources.MergedDictionaries;
        var existing = dictionaries.FirstOrDefault(d => d.Source?.OriginalString.Contains(ThemeMarker, StringComparison.Ordinal) == true &&
                                                        !d.Source.OriginalString.EndsWith("Styles.xaml", StringComparison.Ordinal));
        var replacement = new ResourceDictionary { Source = new Uri($"pack://application:,,,/MinecraftCleanerPro;component/Themes/{theme}.xaml", UriKind.Absolute) };
        if (existing is null)
        {
            dictionaries.Insert(0, replacement);
        }
        else
        {
            dictionaries[dictionaries.IndexOf(existing)] = replacement;
        }

        ActiveTheme = theme;
        var scale = Math.Clamp(config.Accessibility.FontScale, 0.8, 2.0);
        app.Resources["FontSize.Small"] = 12 * scale;
        app.Resources["FontSize.Body"] = 14 * scale;
        app.Resources["FontSize.Subtitle"] = 16 * scale;
        app.Resources["FontSize.Title"] = 22 * scale;
        app.Resources["FontSize.Hero"] = 30 * scale;
        app.Resources["Tooltips.Enabled"] = config.Accessibility.ShowTooltips;
    }

    private static bool SystemUsesDarkTheme()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
            return key?.GetValue("AppsUseLightTheme") is int value && value == 0;
        }
        catch (Exception ex) when (ex is System.Security.SecurityException or UnauthorizedAccessException or IOException)
        {
            return false;
        }
    }
}
