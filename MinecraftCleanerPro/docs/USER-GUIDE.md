# User guide

## Before you start

- Close Minecraft and every launcher, so files are not in use.
- The application never needs administrator rights. If Windows SmartScreen warns about an unknown
  publisher, that is because the build is **not code-signed**; compare the file's SHA-256 with the release
  notes (`Get-FileHash .\MinecraftCleanerPro.exe` in PowerShell) before choosing *Run anyway*.

## Pages

### Dashboard
Last completed scan, files inspected, unique detections, confirmed matches, suspicious items, quarantined
files, verified removals, skipped files and the rule-database version. All numbers come from your saved
history and quarantine; before the first scan they show "—". Warnings (for example an invalid configuration
or a recovered interrupted quarantine) appear at the top.

### Installations
Everything discovery found, with launcher, mod loader, folder and how it was found. Untick an installation
to leave it out of Quick/Full scans. **Add folder…** adds portable installations or modpacks that were not
found automatically. Expand *Discovery notes* to see which locations were checked and any metadata that could
not be read.

### Scanner
1. Choose **Quick Scan** (mods, config, versions, resource packs; folder names in the game directory;
   documented malware locations; your startup entries), **Full Minecraft Scan** (everything in each enabled
   installation except saves, screenshots, assets and logs), or **Custom Scan** (only the folders you pick).
2. Review the scope table: every location, its depth and why it is included. Exclusions are listed below it.
3. **Start scan**. Use **Pause**, **Resume** or **Cancel** at any time. Counts are exact; the percentage
   appears once all files have been found.

**Run detection self-test** creates a harmless text file and scans it. It should be reported as a *Known
match* by rule `CP-TEST-0001`; you can then practise quarantine and restore on it safely.

### Findings
One row per unique file or folder. Filter by classification or search by path, family, rule id or hash.
Select a row to see:

- **Why**: the rule, the indicators that matched and the rule's rationale.
- **Assessment**: confidence, severity, reputation, recommended action and cleanup status, mod identity, size,
  SHA-256 and SHA-1.
- **Evidence**: each observed indicator with its strength and location (for example the archive entry).
- **Rules and sources**: rule id and version, verification date, false-positive notes and the public sources.
- **Limitations**.

Tick items and choose **Quarantine selected…**. The confirmation lists every affected path. Items that are
only *Needs review* or *Unverified* are pointed out. Registry startup entries and files in protected system
locations (for example scheduled tasks) cannot be quarantined; their limitations explain how to remove them
with Windows tools.

**Verify cleanup** rescans the affected folders and reports, per item: quarantined, deleted, no longer present,
still present, present elsewhere (same content at another path), not accessible, failed or inconclusive, plus
any related new detections.

**Trust this file…** adds the exact file (hash + path) to your trusted exclusions so it is no longer reported
(not available for known matches; documented malware is always reported).

### Quarantine
Quarantined files with their original location, date, size, family, rules and integrity.
- **Verify integrity** recomputes each copy's SHA-256 ("Missing" usually means antivirus removed it).
- **Restore selected…** returns a file to its original place. If a different file is there now, nothing is
  overwritten: choose *Restore with a new name* or *Choose another folder*.
- **Delete permanently…** deletes the ticked copies forever. You must review the exact list, tick
  "I understand this cannot be undone" and type `DELETE`.

### History
All scans (search, open in Findings, export, delete) and the audit log of every quarantine, restore and
deletion. Deleting history does not touch quarantined files or the audit log.

### Configuration
Edit every supported setting; **Save** validates and backs up first. **Open configuration file** opens
`config.json` in your editor; use **Reload** after saving it. Problems are listed with the exact setting and
how to fix it. See [CONFIGURATION.md](CONFIGURATION.md).

### Privacy & Updates
The privacy statement, the network-activity log (empty unless you enabled updates), the rule-database
status and update configuration, where each kind of data is stored, and buttons to delete history, reports,
the scan cache and the network log.

### About & Limitations
Version, signing status, limitations and sources.

## Exporting reports

Choose HTML, Text or JSON, then the privacy level: **Redact personal paths** (recommended for sharing),
**File names only**, or **Include full paths** (requires confirmation). Reports include application and
rule versions, scan times, scope, statistics, classification breakdown, every finding with evidence and
sources, cleanup operations, verification results, skipped items, notes and limitations.

## If malware was found

If a fractureiser rule matched (or any *Malware* finding), assume credentials on this computer may have been
exposed: quarantine the files, run a full scan with your antivirus, and change your passwords (Microsoft,
Discord, browser-saved accounts) **from a different, clean device**.

## Keyboard

All actions have access keys (underlined letters, shown with **Alt**). Use **Tab** to move between controls,
arrow keys in lists and tables, **Space** to tick items, **Enter**/**Esc** in dialogs. Text size and a
high-contrast palette are available under *Configuration → Interface and accessibility*; Windows high
contrast is detected automatically.
