using CleanerPro.App.Mvvm;
using CleanerPro.Configuration;
using CleanerPro.Core;
using CleanerPro.Core.Models;
using CleanerPro.Scanner.Discovery;
using Microsoft.Extensions.Logging;

namespace CleanerPro.App.Services;

/// <summary>
/// Runs launcher discovery (instant) and the folder search for unlisted game folders (in the background, folder
/// names only), and publishes the merged result to <see cref="AppState.Discovery"/>. The UI never waits for the search.
/// </summary>
public sealed class DiscoveryCoordinator : ObservableObject
{
    private readonly InstallationDiscoveryService _discovery;
    private readonly ConfigurationService _configuration;
    private readonly AppState _state;
    private readonly ILogger<DiscoveryCoordinator> _logger;
    private DiscoveryResult _known = new();
    private DiscoveryResult _unlisted = new();
    private CancellationTokenSource? _search;
    private bool _isSearching;
    private bool _searchedOnce;
    private string _searchStatus = string.Empty;

    public DiscoveryCoordinator(InstallationDiscoveryService discovery, ConfigurationService configuration, AppState state, ILogger<DiscoveryCoordinator> logger)
    {
        _discovery = discovery;
        _configuration = configuration;
        _state = state;
        _logger = logger;
    }

    public bool IsSearching
    {
        get => _isSearching;
        private set => SetProperty(ref _isSearching, value);
    }

    public string SearchStatus
    {
        get => _searchStatus;
        private set => SetProperty(ref _searchStatus, value);
    }

    /// <summary>Re-reads launcher metadata now; starts the folder search the first time if it is enabled.</summary>
    public void Refresh()
    {
        _known = _discovery.Discover(_configuration.Current.Scan.CustomDirectories);
        Publish();
        if (!_searchedOnce && _configuration.Current.Scan.SearchForUnlistedInstallations)
        {
            _ = SearchAsync();
        }
    }

    /// <summary>Searches local drives and the user profile for game folders that no known launcher lists.</summary>
    public async Task SearchAsync()
    {
        if (IsSearching)
        {
            return;
        }

        _searchedOnce = true;
        IsSearching = true;
        SearchStatus = "Searching your user folders and local drives for game folders that no known launcher lists (folder names only)…";
        _search = new CancellationTokenSource();
        var known = _known.Installations.Select(i => i.RootPath).ToList();
        try
        {
            var token = _search.Token;
            _unlisted = await Task.Run(() =>
            {
                using var priority = Infrastructure.Platform.BackgroundPriority.Enter(true);
                return _discovery.SearchForUnlisted(known, cancellationToken: token);
            }, token);
            SearchStatus = _unlisted.Notes.LastOrDefault() ?? string.Empty;
            Publish();
        }
        catch (OperationCanceledException)
        {
            SearchStatus = "The folder search was cancelled.";
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            _logger.LogWarning(ex, "Folder search for unlisted installations failed");
            SearchStatus = $"The folder search stopped: {ex.Message}";
        }
        finally
        {
            IsSearching = false;
            _search.Dispose();
            _search = null;
        }
    }

    public void CancelSearch() => _search?.Cancel();

    private void Publish()
    {
        var installations = _known.Installations.ToList();
        installations.AddRange(_unlisted.Installations.Where(u => !installations.Any(k => PathKey.IsSameOrWithin(u.RootPath, k.RootPath) || PathKey.IsSameOrWithin(k.RootPath, u.RootPath))));
        _state.Discovery = new DiscoveryResult
        {
            Installations = installations,
            Notes = [.. _known.Notes, .. _unlisted.Notes],
            LocationsChecked = [.. _known.LocationsChecked, .. _unlisted.LocationsChecked.Select(l => $"{l} (folder search)")],
        };
    }
}
