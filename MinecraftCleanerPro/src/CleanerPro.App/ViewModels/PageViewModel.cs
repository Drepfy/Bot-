using CleanerPro.App.Mvvm;

namespace CleanerPro.App.ViewModels;

/// <summary>Base class for navigable pages.</summary>
public abstract class PageViewModel : ObservableObject
{
    public abstract string Key { get; }

    public abstract string Title { get; }

    /// <summary>Glyph from Segoe Fluent Icons / Segoe MDL2 Assets.</summary>
    public abstract string Icon { get; }

    public abstract string Description { get; }

    /// <summary>Called whenever the page becomes visible so it can show current data.</summary>
    public virtual void OnNavigatedTo()
    {
    }
}
