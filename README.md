# Geeklog Plugin Language Audit

Minimal translation completeness audit for plugins in the `Geeklog-Plugins` GitHub organization.

The audit uses `language/english.php` as the reference and currently checks the main languages:

- French (FR)
- German (DE)
- Spanish (ES)
- Japanese (JA)

It compares the language keys structurally and generates `REPORT.md` with only the plugins and languages that require attention.

## Run locally

```bash
python3 audit.py
```

By default the script audits `Geeklog-Plugins`. You can override the organization:

```bash
GEEKLOG_ORG=hostellerie python3 audit.py
```

## GitHub Action

The workflow can be launched manually from the Actions tab and also runs every Monday at 06:00 UTC.

When the generated report changes, the workflow commits the new `REPORT.md` automatically.

## Report statuses

- ✅ complete
- ⚠️ language file exists but one or more English reference keys are missing
- ❌ language file not found

This first version checks only translation key completeness. It does not evaluate translation quality or obsolete extra keys.
