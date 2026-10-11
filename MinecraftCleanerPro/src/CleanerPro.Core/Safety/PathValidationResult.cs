namespace CleanerPro.Core.Safety;

/// <summary>Why a path was rejected by <see cref="PathSafetyPolicy"/>.</summary>
public enum PathBlockCode
{
    None,
    Empty,
    InvalidCharacters,
    Wildcard,
    NotFullyQualified,
    DevicePath,
    NetworkPath,
    AlternateDataStream,
    TrailingDotOrSpace,
    ReservedDeviceName,
    ShortNameAlias,
    RelativeSegments,
    OutsideApprovedScope,
    IsApprovedRoot,
    ProtectedLocation,
    ProtectedPath,
    ReparsePoint,
    NotFound,
    WrongType,
    ProtectedFileType,
}

public sealed record PathValidationResult
{
    public required bool IsAllowed { get; init; }

    public string? NormalizedPath { get; init; }

    public PathBlockCode Code { get; init; }

    /// <summary>Explanation shown to the user when an operation is blocked.</summary>
    public string? Reason { get; init; }

    public static PathValidationResult Allowed(string normalizedPath) =>
        new() { IsAllowed = true, NormalizedPath = normalizedPath, Code = PathBlockCode.None };

    public static PathValidationResult Blocked(PathBlockCode code, string reason, string? normalizedPath = null) =>
        new() { IsAllowed = false, Code = code, Reason = reason, NormalizedPath = normalizedPath };
}

public enum PathTargetKind
{
    File,
    Directory,
}
