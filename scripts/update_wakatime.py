#!/usr/bin/env python3
"""Update the WakaTime README section with Python's standard library."""

import argparse
from datetime import datetime, timedelta
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RANGES = {"last_7_days": "Last 7 days", "last_30_days": "Last 30 days", "all_time": "All time"}
BREAKDOWNS = {"languages": "Languages", "editors": "Editors", "operating_systems": "Operating systems",
              "categories": "Activity categories", "dependencies": "Dependencies"}
AI_METRICS = {
    "ai_additions": "AI lines added", "ai_deletions": "AI lines deleted",
    "human_additions": "Human lines added", "human_deletions": "Human lines deleted",
    "ai_line_changes_total": "AI lines changed", "ai_input_tokens": "Input tokens",
    "ai_output_tokens": "Output tokens", "ai_model_total_cost": "Estimated AI cost (USD)",
    "ai_sessions": "AI sessions", "ai_prompt_events_total": "Prompts",
    "ai_prompt_length_sum": "Total prompt characters", "ai_prompt_length_avg": "Prompt characters (mean)",
    "ai_prompt_length_avg_per_session": "Prompt characters per session (mean)",
    "ai_prompt_length_median_per_session": "Prompt characters per session (median)",
    "ai_prompt_events_avg_per_session": "Prompts per session (mean)",
    "ai_prompt_events_median_per_session": "Prompts per session (median)",
}
START = "<!--START_SECTION:waka-->"
END = "<!--END_SECTION:waka-->"


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def text(value):
    value = html.escape(" ".join(str(value).split()), quote=True)
    return re.sub(r"([\\`*_{}\[\]()|#!])", r"\\\1", value)


def count(value):
    return f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"


def duration(value):
    if not number(value):
        return "Not available"
    minutes = int(value // 60)
    if value > 0 and minutes == 0:
        return "Less than 1 min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours:,} hr{'s' if hours != 1 else ''} {minutes} mins" if hours else f"{minutes} mins"


def inclusive(data, key):
    return data.get(f"{key}_including_other_language")


def table(headers, rows):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ])


def fetch_data(path: str, token: str) -> dict:
    request = Request("https://api.wakatime.com/api/v1/users/current/" + path,
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                               "User-Agent": "onhate-readme/1.0"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
                status = response.status
            if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
                raise RuntimeError("WakaTime returned an error payload. README kept.")
            data = payload.get("data")
            expected_type = dict if path.startswith("stats/") else list
            if not isinstance(data, expected_type):
                raise RuntimeError("WakaTime returned invalid data. README kept.")
            if status == 200 and (expected_type is list or data.get("is_up_to_date") is True):
                return payload
        except HTTPError as error:
            error.close()
            if error.code != 429 and not 500 <= error.code < 600:
                raise RuntimeError(f"WakaTime request failed (HTTP {error.code}). Check the token and scopes. README kept.") from None
        except (URLError, TimeoutError, OSError):
            pass
        except (ValueError, AttributeError):
            raise RuntimeError("WakaTime returned invalid JSON or response data. README kept.") from None
        if attempt < 3:
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError("WakaTime data is unavailable or stale after four attempts. README kept.")


def render_stats(stats: dict, summaries: dict) -> str:
    lines = ["### Coding activity", "", "Time totals include Other. Missing measurements are not treated as zero.", ""]
    overview = []
    for key, label in RANGES.items():
        data = stats[key]
        if not isinstance(data, dict) or not number(inclusive(data, "total_seconds")):
            raise RuntimeError("WakaTime returned invalid totals. README kept.")
        overview.append([label, duration(inclusive(data, "total_seconds")), duration(inclusive(data, "daily_average")),
                         count(data["days_minus_holidays"]) if number(data.get("days_minus_holidays")) else "Not available"])
    lines += [table(["Period", "Total time", "Daily average", "Active days"], overview), ""]
    for key, label in RANGES.items():
        data = stats[key]
        lines += ["<details>", f"<summary>{label}: full stats</summary>", "",
                  f"Period: {text(data.get('start', 'Not available'))} to {text(data.get('end', 'Not available'))}.",
                  f"Time zone: {text(data.get('timezone', 'Not available'))}.", ""]
        best = data.get("best_day") or {}
        if isinstance(best, dict) and best.get("date") and number(best.get("total_seconds")):
            lines += [f"Best day: {text(best['date'])} — {duration(best['total_seconds'])}.", ""]
        for field, title in BREAKDOWNS.items():
            entries = data.get(field)
            if not isinstance(entries, list) or not entries:
                continue
            rows = []
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                    raise RuntimeError("WakaTime returned an invalid breakdown. README kept.")
                percent = entry.get("percent")
                rows.append([text(entry["name"]), duration(entry.get("total_seconds")),
                             f"{percent:.2f}%" if number(percent) else "Not available"])
            lines += [f"#### {title}", "", table(["Name", "Time", "Share"], rows), ""]
        lines += ["#### AI and human activity", ""]
        rows = []
        for field, title in AI_METRICS.items():
            value = data.get(field)
            if number(value):
                rows.append([title, f"${value:,.4f}" if field == "ai_model_total_cost" else count(value)])
        lines += [table(["Measurement", "Value"], rows) if rows else "No AI or human line measurements available.", ""]
        models = data.get("ai_model_breakdown")
        if not models:
            changes = data.get("ai_model_line_changes") or {}
            costs = data.get("ai_model_costs") or {}
            models = [{"name": name, "lines": changes.get(name), "cost": costs.get(name)}
                      for name in sorted(set(changes) | set(costs))]
        if models:
            rows = []
            for model in models:
                if not isinstance(model, dict) or not isinstance(model.get("name"), str):
                    raise RuntimeError("WakaTime returned invalid AI model data. README kept.")
                rows.append([text(model["name"]), count(model["lines"]) if number(model.get("lines")) else "Not available",
                             f"${model['cost']:,.4f}" if number(model.get("cost")) else "Not available"])
            lines += [table(["AI model", "Lines changed", "Estimated cost (USD)"], rows), ""]
        lines += ["</details>", ""]
    daily = summaries.get("data")
    if not isinstance(daily, list):
        raise RuntimeError("WakaTime returned invalid daily summaries. README kept.")
    rows = []
    for day in daily:
        if not isinstance(day, dict):
            raise RuntimeError("WakaTime returned an invalid daily summary. README kept.")
        date = (day.get("range") or {}).get("date")
        seconds = (day.get("grand_total") or {}).get("total_seconds")
        if not isinstance(date, str) or not number(seconds):
            raise RuntimeError("WakaTime returned an incomplete daily summary. README kept.")
        rows.append([text(date), duration(seconds)])
    lines += ["<details>", "<summary>Daily activity: last 30 calendar days (includes today)</summary>", "",
              table(["Date", "Time"], rows) if rows else "No daily summaries available.", "", "</details>", "",
              "Source: [WakaTime](https://wakatime.com/@onhate). AI costs are estimates. "
              "Recent totals follow WakaTime's date ranges and can exclude today."]
    return "\n".join(lines)


def update_readme(path: Path, token: str, output: Path | None = None) -> None:
    if not token.strip():
        raise RuntimeError("Set the WAKATIME_ACCESS_TOKEN repository secret. README kept.")
    original = path.read_bytes().decode("utf-8")
    if original.count(START) != 1 or original.count(END) != 1 or original.index(START) >= original.index(END):
        raise RuntimeError("README must have one ordered pair of WakaTime section markers.")
    stats = {key: fetch_data(f"stats/{key}", token)["data"] for key in RANGES}
    try:
        zone = ZoneInfo(stats["last_30_days"]["timezone"])
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise RuntimeError("WakaTime returned an invalid time zone. README kept.") from None
    today = datetime.now(zone).date()
    query = urlencode({"start": (today - timedelta(days=29)).isoformat(), "end": today.isoformat()})
    summaries = fetch_data(f"summaries?{query}", token)
    section = render_stats(stats, summaries)
    newline = "\r\n" if "\r\n" in original else "\n"
    section = ("\n\n" + section + "\n\n").replace("\n", newline)
    updated = original[:original.index(START) + len(START)] + section + original[original.index(END):]
    target = output or path
    if target == path and updated == original:
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(updated.encode("utf-8"))
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write a preview instead of changing README.md.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        update_readme(root / "README.md", os.environ.get("WAKATIME_ACCESS_TOKEN", ""), args.output)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Cannot generate WakaTime stats. README kept.", file=sys.stderr)
        return 1
    print("WakaTime README generation finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
