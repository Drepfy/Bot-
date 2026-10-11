# Privacy and network policy

## Summary

- Scans, findings, reports, history, logs and quarantined files stay **on this computer**, under
  `%LocalAppData%\MinecraftCleanerPro\` (or folders you configure).
- **No telemetry, analytics, crash uploads, accounts, remote control or remote command execution.**
- **No collection** of credentials, browser cookies, Discord tokens, Minecraft/Microsoft account data or any
  other personal data. The scanner reads file *metadata, hashes and archive structure*; it never uploads anything.
- No hidden background activity: the application runs only while its window is open, creates no services,
  scheduled tasks or startup entries, does not hide its process and does not interfere with security software.
- **Offline mode is on by default** and blocks every network request.

## Network endpoints

| Purpose | Endpoint | When | What is sent |
|---|---|---|---|
| Signed rule-database update | `<ruleUpdates.endpoint>/rules.json` and `/rules.json.sig` | Only if offline mode is **off**, `ruleUpdates.enabled` is **on**, an HTTPS endpoint **and** a trusted signing key are configured, and you press *Check for signed rule update* (or enabled the startup check) | A plain HTTPS `GET` with `User-Agent: MinecraftCleanerPro/<version>`. No cookies, credentials, scan data, file names, paths, hardware or account identifiers. Redirects are not followed. |

That is the complete list. No endpoint is configured in this release, so by default the application never
contacts any server.

Enforcement is in code, not only in settings: all HTTP goes through `GuardedHttpClient`, which asks
`NetworkAccessPolicy` before every request (offline mode, HTTPS only, configured host and port only), applies
a size limit and timeout, and records every request **and every blocked attempt** in
`network-activity.jsonl`, which you can read on the *Privacy & Updates* page. Automated tests verify that
offline mode makes zero requests and that requests carry no cookies or authorization headers.

Optional Windows features that could touch the network are configured not to: Authenticode verification uses
`WTD_REVOKE_NONE` and cache-only URL retrieval (no revocation lookup).

## Data stored locally

| Location | Contents | How to remove |
|---|---|---|
| `config.json`, `config-backups\` | Settings, last 20 backups | Delete the files |
| `history\` | Scan sessions (paths, hashes, evidence), verification results, `operations.jsonl` audit log | *Delete scan history* (audit log kept) or delete the folder |
| `reports\` | Reports you exported | *Delete saved reports* |
| `quarantine\` | Encoded copies of quarantined files + manifests | Restore or *Delete permanently* |
| `logs\` | Diagnostic logs (no file contents), size-capped, 14-day retention | Delete the folder |
| `cache\` | Hashes of unchanged clean files | *Clear scan cache* |
| `rules\` | Installed signed updates and their status | Delete the folder |
| `network-activity.jsonl` | Network audit log | *Clear log* |

## Reports

Reports may contain file paths that include your Windows user name. Exports default to **redacted personal
paths** (`%USERPROFILE%`, `%APPDATA%`, `%LOCALAPPDATA%`, `<user>`, `<computer>` placeholders) and offer a
*file names only* mode. Choosing full paths requires an extra confirmation. User and computer names are only
included if you enable them in the configuration.

## Verification of these claims

The privacy behaviour is covered by automated tests (`InfrastructureTests`, `RuleUpdateTests`,
`EndToEndTests.OfflineScanningMakesNoNetworkRequests`). Dependencies were reviewed for network behaviour —
see [DEPENDENCIES.md](DEPENDENCIES.md). A setting alone is not proof of privacy; you can verify the behaviour
yourself with a firewall or network monitor.
