using CleanerPro.App.Services;
using CleanerPro.Configuration;
using CleanerPro.Core.Models;
using CleanerPro.Infrastructure.Platform;
using CleanerPro.Reporting;

namespace CleanerPro.App.ViewModels;

/// <summary>Shared export flow: format choice, privacy choice (with a warning for personal paths), destination.</summary>
public static class ReportExportFlow
{
    public static void Run(ScanSession session, ReportService reports, IDialogService dialogs, AppConfiguration config, IShellLauncher shell, AppState state)
    {
        var format = dialogs.Ask(new ConfirmationRequest
        {
            Title = "Export report",
            Message = "Choose a report format. Reports are saved locally; nothing is uploaded.",
            Choices =
            [
                new DialogChoice("Html", "HTML", IsDefault: config.Reports.DefaultFormat == ReportFormat.Html),
                new DialogChoice("Txt", "Text", IsDefault: config.Reports.DefaultFormat == ReportFormat.Txt),
                new DialogChoice("Json", "JSON", IsDefault: config.Reports.DefaultFormat == ReportFormat.Json),
                new DialogChoice("cancel", "Cancel", IsCancel: true),
            ],
        });
        if (format is null or "cancel" || !Enum.TryParse<ReportFormat>(format, out var reportFormat))
        {
            return;
        }

        var privacy = dialogs.Ask(new ConfirmationRequest
        {
            Title = "Personal information in the report",
            Message = "Full file paths can contain your Windows user name and folder names. If you plan to share the report, keep personal paths redacted.",
            Choices =
            [
                new DialogChoice("redact", "Redact personal paths (recommended)", IsDefault: config.Reports.RedactPersonalPathsByDefault),
                new DialogChoice("names", "File names only"),
                new DialogChoice("full", "Include full paths", IsDefault: !config.Reports.RedactPersonalPathsByDefault),
                new DialogChoice("cancel", "Cancel", IsCancel: true),
            ],
        });
        if (privacy is null or "cancel")
        {
            return;
        }

        if (privacy == "full" && !dialogs.Confirm("Include personal paths?",
                "The report will contain full paths, which may include your user name and folder names. Only share it with people you trust.", null, "Include full paths"))
        {
            return;
        }

        var redaction = privacy switch
        {
            "names" => RedactionLevel.FileNamesOnly,
            "full" => RedactionLevel.None,
            _ => RedactionLevel.PersonalPaths,
        };
        var extension = ReportExporter.Extension(reportFormat);
        var destination = dialogs.SaveFile("Save report", $"{reportFormat} report (*{extension})|*{extension}", $"MinecraftCleanerPro-{session.Id}{extension}");
        if (destination is null)
        {
            return;
        }

        try
        {
            var path = reports.Export(session, reportFormat, redaction, destination);
            state.StatusMessage = $"Report saved to {path}.";
            if (dialogs.Confirm("Report saved", $"The report was saved to:\n{path}", null, "Open report"))
            {
                var result = shell.OpenFile(path);
                if (!result.Succeeded)
                {
                    dialogs.ShowError("Could not open the report", result.Message);
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            dialogs.ShowError("Report not saved", ex.Message);
        }
    }
}
