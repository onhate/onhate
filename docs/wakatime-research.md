# WakaTime README research

Checked: 2026-10-29.

## Current repository

The repository has one README and one scheduled workflow. There is no local generator.
The workflow uses `athul/waka-readme@master` and runs each day.
The last five runs passed. The latest run received HTTP 200 from WakaTime.
This confirms that the current job works. It does not establish when WakaTime
will enforce the documented authentication change for this account.

The current settings restrict the output:

- `STOP_AT_OTHER: true` ends the language list at Other.
- `IGNORED_LANGUAGES: YAML JSON TOML` removes those languages.
- `LANG_COUNT: 12` limits the list.
- `TIME_RANGE: all_time` shows only the lifetime view.
- `SHOW_TOTAL: true` uses the total that excludes Other, although the list includes Other.

The action source renders dates, total time, and languages only.
Its API request uses Basic authentication. A personal token was not tested with it.

Evidence: [workflow run](https://github.com/onhate/onhate/actions/runs/40818625826),
[action inputs](https://github.com/athul/waka-readme/blob/master/action.yml),
[action source](https://github.com/athul/waka-readme/blob/master/main.py).

## Authentication

WakaTime now documents API keys as write-only plugin credentials.
Scripts must use OAuth access tokens. Personal README scripts can get a token at
[WakaTime OAuth](https://wakatime.com/oauth), without a published app.
Use an `Authorization: Bearer` header and a repository secret named
`WAKATIME_ACCESS_TOKEN`.

A custom OAuth app requires more setup. Check the personal token's lifetime and
granted scopes during setup. These were not verified here.

Source: [WakaTime authentication](https://wakatime.com/developers#authentication).

## Data and publication scope

The user selected all summary and AI stats, without project names or machine details.

The Stats API supports time totals, averages, best days, languages, editors,
operating systems, categories, dependencies, AI line changes, tokens, model usage,
estimated costs, sessions, and prompt measurements. Use `read_stats` for Stats.
Daily Summaries use `read_summaries`. Availability depends on recorded data and
account access. Stale stats require another request. Never label missing fields
as measured zeroes.

Source: [WakaTime API](https://wakatime.com/developers).

## Approaches

1. Keep the current action. Remove the language filters and migrate its credential.
   This keeps the change small, but its renderer cannot show other data types.
2. Use `anmol098/waka-readme-stats`. It provides editors, OS, and weekly AI sections.
   Its defaults include unrelated GitHub metrics. Its sample setup uses a GitHub PAT.
   Disable unwanted sections and verify authentication before adoption.
3. Use a small local Python script. This provides direct control over authentication,
   output, and failures. Use the standard library; no service or database is needed.
   This is the recommended approach for the requested coverage.

Source for option 2: [action documentation](https://github.com/anmol098/waka-readme-stats).

## Proposed result

Keep the existing greeting, badge, and section markers. Add a compact overview for
7 days, 30 days, and all time. Put full breakdowns and AI measurements in expandable
sections. Use only provider measurements. Do not infer productivity or review habits.
Do not publish raw responses. Omit project and machine fields before rendering.

Keep scheduled and manual runs. Give the workflow only `contents: write`.
Use the built-in GitHub token to commit README changes. Preserve the current README
when authentication fails or data remains incomplete after bounded retries.

No generator code or workflow settings changed during this research.
No token was created, read, or changed.
