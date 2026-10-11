using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using CleanerPro.Core;

namespace CleanerPro.App.Controls;

/// <summary>Application-wide switch and masker for private information on screen.</summary>
public static class PrivacyDisplay
{
    private static bool _hidePrivateInformation = true;

    public static PrivateDataMasker Masker { get; set; } = PrivateDataMasker.ForCurrentUser();

    /// <summary>When true (default), user and computer names are covered by black bars until clicked.</summary>
    public static bool HidePrivateInformation
    {
        get => _hidePrivateInformation;
        set
        {
            if (_hidePrivateInformation != value)
            {
                _hidePrivateInformation = value;
                Changed?.Invoke(null, EventArgs.Empty);
            }
        }
    }

    public static event EventHandler? Changed;

    /// <summary>Text with private values replaced, for places that show plain strings (window title, clipboard-safe summaries).</summary>
    public static string Mask(string? text) => HidePrivateInformation ? Masker.Mask(text) : text ?? string.Empty;
}

/// <summary>
/// Shows text with private parts (user name, computer name) covered by black bars. Clicking a bar, or pressing
/// Enter or Space on it, reveals that part; clicking again hides it. While hidden, the private text is not in the
/// visual tree at all, so screenshots, copying and screen readers cannot reveal it.
/// </summary>
public sealed class PrivateText : TextBlock
{
    public static readonly DependencyProperty ValueProperty = DependencyProperty.Register(
        nameof(Value), typeof(string), typeof(PrivateText), new PropertyMetadata(null, (d, _) => ((PrivateText)d).Rebuild()));

    private readonly HashSet<int> _revealed = [];

    public PrivateText()
    {
        TextWrapping = TextWrapping.Wrap;
        Loaded += (_, _) =>
        {
            PrivacyDisplay.Changed += OnPrivacyChanged;
            Rebuild();
        };
        Unloaded += (_, _) => PrivacyDisplay.Changed -= OnPrivacyChanged;
    }

    public string? Value
    {
        get => (string?)GetValue(ValueProperty);
        set => SetValue(ValueProperty, value);
    }

    private void OnPrivacyChanged(object? sender, EventArgs e)
    {
        _revealed.Clear();
        Rebuild();
    }

    private void Rebuild()
    {
        Inlines.Clear();
        var text = Value ?? string.Empty;
        if (!PrivacyDisplay.HidePrivateInformation)
        {
            Inlines.Add(new Run(text));
            AutomationProperties.SetName(this, text);
            return;
        }

        var spoken = new System.Text.StringBuilder();
        var index = 0;
        foreach (var segment in PrivacyDisplay.Masker.Split(text))
        {
            if (!segment.IsPrivate)
            {
                Inlines.Add(new Run(segment.Text));
                spoken.Append(segment.Text);
                continue;
            }

            var position = index++;
            var revealed = _revealed.Contains(position);
            Inlines.Add(new InlineUIContainer(CreateBar(segment.Text, position, revealed)) { BaselineAlignment = BaselineAlignment.Center });
            spoken.Append(revealed ? segment.Text : "[hidden]");
        }

        AutomationProperties.SetName(this, spoken.ToString());
    }

    private Button CreateBar(string secret, int position, bool revealed)
    {
        var bar = new Button
        {
            // While hidden, the button holds placeholder blocks, never the private text itself.
            Content = revealed ? secret : new string('█', Math.Clamp(secret.Length, 4, 10)),
            Padding = new Thickness(2, 0, 2, 0),
            Margin = new Thickness(0),
            MinWidth = 0,
            MinHeight = 0,
            BorderThickness = new Thickness(1),
            Cursor = Cursors.Hand,
            FontFamily = FontFamily,
            FontSize = FontSize,
            Focusable = true,
            ToolTip = revealed ? "Private information. Click to hide it again." : "Private information hidden. Click to show it.",
            Template = BarTemplate(),
        };
        bar.SetResourceReference(FrameworkElement.FocusVisualStyleProperty, "FocusOutline");
        bar.SetResourceReference(Control.BorderBrushProperty, "Brush.Border"); // keeps the black bar visible on dark and high-contrast themes
        if (revealed)
        {
            bar.SetResourceReference(Control.BackgroundProperty, "Brush.Selection");
            bar.SetResourceReference(Control.ForegroundProperty, "Brush.Text");
        }
        else
        {
            bar.Background = Brushes.Black;
            bar.Foreground = Brushes.Black;
        }

        AutomationProperties.SetName(bar, revealed ? $"{secret}. Press to hide this private information." : "Hidden private information. Press to show it.");
        bar.Click += (_, e) =>
        {
            if (!_revealed.Add(position))
            {
                _revealed.Remove(position);
            }

            Rebuild();
            e.Handled = true;
        };
        return bar;
    }

    private static ControlTemplate? _barTemplate;

    /// <summary>A flat template so the bar looks like text-height highlighting, with a visible keyboard focus outline.</summary>
    private static ControlTemplate BarTemplate()
    {
        if (_barTemplate is not null)
        {
            return _barTemplate;
        }

        var border = new FrameworkElementFactory(typeof(Border));
        border.SetValue(Border.BackgroundProperty, new TemplateBindingExtension(Control.BackgroundProperty));
        border.SetValue(Border.BorderBrushProperty, new TemplateBindingExtension(Control.BorderBrushProperty));
        border.SetValue(Border.BorderThicknessProperty, new TemplateBindingExtension(Control.BorderThicknessProperty));
        border.SetValue(Border.PaddingProperty, new TemplateBindingExtension(Control.PaddingProperty));
        border.SetValue(Border.CornerRadiusProperty, new CornerRadius(2));
        var content = new FrameworkElementFactory(typeof(ContentPresenter));
        content.SetValue(ContentPresenter.VerticalAlignmentProperty, VerticalAlignment.Center);
        border.AppendChild(content);
        _barTemplate = new ControlTemplate(typeof(Button)) { VisualTree = border };
        return _barTemplate;
    }
}
