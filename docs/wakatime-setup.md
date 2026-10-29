# WakaTime README setup

GitHub Actions runs the script on GitHub servers. Your computer can stay off.
The daily schedule runs at 00:00 UTC (21:00 in São Paulo).

## Credentials

Get a personal token at [WakaTime OAuth](https://wakatime.com/oauth). Save it as
`WAKATIME_ACCESS_TOKEN` in the repository's
[Actions secrets](https://github.com/onhate/onhate/settings/secrets/actions).
Allow `read_stats` and `read_summaries` if WakaTime asks for scopes. Check the
token's expiry during setup. Replace the secret if the token expires or is revoked.

GitHub does not let a script read back a saved repository secret. The Actions
runner receives it at run time. The generator uses a Bearer header and never
prints the token or raw responses. See [WakaTime authentication](https://wakatime.com/developers#authentication).

The workflow uses GitHub's built-in token to commit the README. It does not need
`CUSTOM_GITHUB_TOKEN` or `WAKATIME_API_KEY`. Those old repository secrets can be
removed after the first successful run. Keep the WakaTime API key in your editor
plugins; they still need it to send activity.

## Preview and publish

Open **Actions → Waka Readme → Run workflow**. Leave **publish** disabled to make
a preview. Download the `wakatime-preview` artifact to read the generated Markdown.
This run does not change README.md. Preview artifacts expire after seven days.

Enable **publish** to update the README. Scheduled runs also publish. Pushes and
pull requests run tests only. The workflow commits only README.md when it changes.

## Data

The overview compares 7 days, 30 days, and all time. Each period has an expandable
section with the returned languages, editors, operating systems, categories,
and AI measurements. No language filters or row limits are applied.
The daily section shows 30 calendar days, including today, in the account's time zone.

Time totals include Other. Recent Stats ranges can exclude today. Each expanded
section shows the provider's period and time zone. Missing measurements do not
become zeroes. Missing optional fields and empty breakdowns are omitted.
AI costs are provider estimates. The script does not infer productivity or review habits.

The README displays WakaTime's `Codex Vscode` and `Codex-Vscode` labels as `Codex`.
Desktop app sessions can also have `source: vscode`, so these labels do not reliably
identify VS Code usage. This display change applies to editor and AI model tables.
It does not change WakaTime records, measured values, or other editor names.

The renderer uses an explicit list of allowed fields. It omits projects, machines,
and dependencies. Dependency names can contain internal project and package names.
It also omits
paths, branches, heartbeats, and raw API responses. It retries temporary errors
and stale stats up to four times per request. Authentication errors stop the run.
If a required request or rendering fails, it keeps the previous README.

## Development

Use Python 3.13 or later. No extra Python packages are required.

```sh
python3 -m unittest discover -s tests -v
```

If your secret manager sets `WAKATIME_ACCESS_TOKEN` in your environment, you can
also make a preview on your computer:

```sh
python3 scripts/update_wakatime.py --output /tmp/wakatime-preview.md
```

This leaves README.md unchanged. Never commit credentials or raw account exports.
