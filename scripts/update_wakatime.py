#!/usr/bin/env python3
"""Update the WakaTime README section with Python's standard library."""

import argparse
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RANGES = {"last_7_days": "Last 7 days", "last_30_days": "Last 30 days", "all_time": "All time"}
GRAPHIC_KINDS = ('profile',)
BREAKDOWNS = {"languages": "Languages", "editors": "Editors", "operating_systems": "Operating systems",
              "categories": "Activity categories"}
# Desktop Codex sessions can also report source=vscode. Do not imply a VS Code install.
CODEX_DISPLAY_NAMES = {"Codex Vscode": "Codex", "Codex-Vscode": "Codex"}
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


def models_for(data):
    models = data.get('ai_model_breakdown')
    if not models:
        changes, costs = data.get('ai_model_line_changes') or {}, data.get('ai_model_costs') or {}
        if not isinstance(changes, dict) or not isinstance(costs, dict):
            raise RuntimeError('WakaTime returned invalid AI model data. README kept.')
        models = [{'name': name, 'lines': changes.get(name), 'cost': costs.get(name)}
                  for name in sorted(set(changes) | set(costs))]
    if not isinstance(models, list) or any(not isinstance(row, dict) or not isinstance(row.get('name'), str) for row in models):
        raise RuntimeError('WakaTime returned invalid AI model data. README kept.')
    return models


def render_graphic(stats: dict, kind: str, theme: str, compact: bool = False) -> str:
    """Render the approved profile layouts as standalone, script-free SVGs."""
    if kind not in GRAPHIC_KINDS or theme not in ('light', 'dark', 'auto'):
        raise ValueError('Invalid graphic kind or theme')
    dark = theme == 'dark'
    theme_colors = {
        'bg': ('#ffffff', '#0d1117'), 'ink': ('#1f2328', '#e6edf3'),
        'muted': ('#59636e', '#9198a1'), 'border': ('#d1d9e0', '#30363d'),
        'soft': ('#f6f8fa', '#161b22'), 'human': ('#0969da', '#58a6ff'),
        'ai': ('#8250df', '#bc8cff'), 'human_soft': ('#f1f7ff', '#101c2d'),
        'ai_soft': ('#f8f3ff', '#1c152b'), 'track': ('#e3e7eb', '#303943'),
        'language_1': ('#3178c6', '#58a6ff'), 'language_2': ('#b35c00', '#f4a454'),
        'language_3': ('#9a7b00', '#e3c84a'),
    }
    palette = {name: f'var(--tone-{name})' if theme == 'auto' else colors[int(dark)]
               for name, colors in theme_colors.items()}
    width = 400 if compact else 760
    height = 660 if compact else 440
    title = 'Human and AI coding history and recent activity'
    root = ET.Element('svg', {
        'xmlns': 'http://www.w3.org/2000/svg', 'width': str(width), 'height': str(height),
        'viewBox': f'0 0 {width} {height}', 'role': 'img',
        'aria-labelledby': 'graphic-title graphic-description',
        'font-family': '-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif',
    })
    ET.SubElement(root, 'title', id='graphic-title').text = title
    description = ET.SubElement(root, 'desc', id='graphic-description')
    if theme == 'auto':
        # Embedded SVG inherits the page's color scheme. GitHub cannot rewrite
        # these rules as it does a picture source's theme media condition.
        light = ';'.join(f'--tone-{name}:{colors[0]}' for name, colors in theme_colors.items())
        dark_colors = ';'.join(f'--tone-{name}:{colors[1]}' for name, colors in theme_colors.items())
        ET.SubElement(root, 'style').text = f':root{{{light}}}@media (prefers-color-scheme: dark){{:root{{{dark_colors}}}}}'

    def label(x, y, value, size=16, color='ink', weight=400, anchor=None):
        attrs = {'x': str(x), 'y': str(y), 'font-size': str(size),
                 'fill': palette.get(color, color), 'font-weight': str(weight)}
        if anchor:
            attrs['text-anchor'] = anchor
        node = ET.SubElement(root, 'text', attrs)
        node.text = ''.join(char for char in ' '.join(str(value).split()) if ord(char) >= 32)
        return node

    def box(x, y, w, h, fill, radius=0, stroke=None):
        attrs = {'x': str(x), 'y': str(y), 'width': str(w), 'height': str(h),
                 'fill': palette.get(fill, fill), 'rx': str(radius)}
        if stroke:
            attrs['stroke'] = palette[stroke]
        return ET.SubElement(root, 'rect', attrs)

    def rule(x1, y1, x2, y2):
        ET.SubElement(root, 'line', {'x1': str(x1), 'y1': str(y1), 'x2': str(x2),
                                   'y2': str(y2), 'stroke': palette['border']})

    def short_count(value):
        if not number(value):
            return 'Not available'
        return f'{value / 1000000000:.2f}B' if value >= 1000000000 else f'{value / 1000000:.2f}M' if value >= 1000000 else f'{value / 1000:.1f}K' if value >= 1000 else count(value)

    background = box(1, 1, width - 2, 1, 'bg', 16, 'border')
    defs = ET.SubElement(root, 'defs')
    descriptions = []

    def fitted(x, y, value, available, size=14, color='ink', weight=400):
        node = label(x, y, value, size, color, weight)
        clip_id = f'text-{len(defs)}'
        clip = ET.SubElement(defs, 'clipPath', id=clip_id)
        ET.SubElement(clip, 'rect', {'x': str(x), 'y': str(y - size - 2),
                                   'width': str(available), 'height': str(size + 8)})
        node.set('clip-path', f'url(#{clip_id})')
        ET.SubElement(node, 'title').text = str(value)
        descriptions.append(str(value))

    def ranked(data, field, limit):
        rows = data.get(field)
        rows = rows if isinstance(rows, list) else []
        rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get('name'), str)]
        return sorted(rows, key=lambda row: row.get('total_seconds') if number(row.get('total_seconds')) else -1, reverse=True)[:limit]

    def pair(x, y, name, value, span, color='muted'):
        fitted(x, y, name, span * .62, 13, color)
        label(x + span, y, value, 13, anchor='end')
        descriptions.append(f'{name}: {value}.')

    def languages(data, x, y, span, limit):
        rows = ranked(data, 'languages', limit)
        if not rows:
            fitted(x, y, 'No language percentages available', span, 13, 'muted')
            return y + 28
        for row in rows:
            percent = row.get('percent')
            valid = number(percent) and percent <= 100
            pair(x, y, row['name'], f'{percent:.1f}%' if valid else 'Not available', span)
            if valid:
                box(x, y + 9, span, 5, 'track', 2)
                box(x, y + 9, span * percent / 100, 5, 'human', 2)
            y += 33
        return y

    all_time = stats['all_time']
    if compact:
        label(32, 43, 'Human experience.', 23, weight=600)
        label(32, 70, 'AI in practice.', 23, weight=600)
    else:
        label(32, 43, 'Human experience. AI in practice.', 27, weight=600)
    label(32, 97 if compact else 70, 'All-time coding history', 14, 'muted')
    span = width - 64 if compact else (width - 112) / 2
    categories = all_time.get('categories')
    categories = categories if isinstance(categories, list) else []
    for index, (category, heading, prefix, color) in enumerate((
        ('Coding', 'Human coding', 'human', 'human'),
        ('AI Coding', 'AI coding', 'ai', 'ai'),
    )):
        x = 32 if compact else 32 + index * (span + 48)
        y = 109 + (27 + index * 132 if compact else 0)
        label(x, y, heading, 17, color, 500)
        row = next((row for row in categories if isinstance(row, dict) and row.get('name') == category), {})
        seconds = row.get('total_seconds')
        hours = f'{int(seconds // 3600):,} hrs' if number(seconds) else 'Not available'
        label(x, y + 39, hours, 31 if number(seconds) else 23, weight=600)
        descriptions.append(f'{heading}: {duration(seconds)}.')
        pair(x, y + 66, 'Lines added', short_count(all_time.get(prefix + '_additions')), span)
        pair(x, y + 88, 'Lines deleted', short_count(all_time.get(prefix + '_deletions')), span)
    y = 396 if compact else 237
    rule(32, y, width - 32, y)
    label(32, y + 35, 'Recent focus', 20, weight=600)
    period_start = y + 73
    ends = []
    for index, key in enumerate(('last_7_days', 'last_30_days')):
        data = stats[key]
        x = 32 if compact else 32 + index * (span + 48)
        y = period_start if not compact or index == 0 else ends[0] + 44
        label(x, y, RANGES[key], 17, weight=500)
        total = duration(inclusive(data, 'total_seconds'))
        fitted(x, y + 37, total, span, 25, weight=600)
        fitted(x, y + 62, duration(inclusive(data, 'daily_average')) + ' daily average', span, 13, 'muted')
        active, days = data.get('days_minus_holidays'), data.get('days_including_holidays')
        valid = number(days) and int(days) == days and 0 < days <= 31 and number(active) and int(active) == active and active <= days
        active_text = f'{count(active)} / {count(days)} active days' if valid else f'{count(active)} active days' if number(active) else 'Active days not available'
        fitted(x, y + 85, active_text, span, 13, 'muted')
        if valid:
            block_width = (span - 3 * (int(days) - 1)) / days
            for day in range(int(days)):
                box(x + day * (block_width + 3), y + 97, block_width, 8, 'human' if day < active else 'track', 2)
        y += 142
        languages(data, x, y, span, 5)
        y += 5 * 33 + 19
        tools_start = y
        for editor in ranked(data, 'editors', 2):
            name = CODEX_DISPLAY_NAMES.get(editor['name'], editor['name'])
            pair(x, y, name, f'{editor["percent"]:.1f}%' if number(editor.get('percent')) else 'Not available', span)
            y += 23
        y = tools_start + 2 * 23 + 17
        # Keep the same row positions in both recent columns, even for missing data.
        for field, name, color in (
            ('human_additions', 'Human lines added', 'human'), ('human_deletions', 'Human lines deleted', 'human'),
            ('ai_additions', 'AI lines added', 'ai'), ('ai_deletions', 'AI lines deleted', 'ai'),
            ('ai_sessions', 'AI sessions', 'muted'), ('ai_prompt_events_total', 'Prompts', 'muted'),
            ('ai_line_changes_total', 'AI lines changed', 'muted'), ('ai_input_tokens', 'Input tokens', 'muted'),
            ('ai_output_tokens', 'Output tokens', 'muted'), ('ai_model_total_cost', 'Estimated AI cost (USD)', 'muted'),
        ):
            value = data.get(field)
            display = f'${value:,.2f}' if field == 'ai_model_total_cost' and number(value) else short_count(value)
            pair(x, y, name, display, span, color)
            y += 24
        models = [CODEX_DISPLAY_NAMES.get(row['name'], row['name']) for row in models_for(data)]
        if models:
            y += 10
            fitted(x, y, ' · '.join(models[:4]) + (f' · +{len(models) - 4} more' if len(models) > 4 else ''), span, 12, 'muted')
            y += 23
        best = data.get('best_day')
        if isinstance(best, dict) and isinstance(best.get('date'), str) and number(best.get('total_seconds')):
            fitted(x, y, f'Best day · {best["date"][:10]} · {duration(best["total_seconds"])}', span, 12, 'muted')
            y += 23
        systems = ranked(data, 'operating_systems', 2)
        if systems:
            fitted(x, y, ' · '.join(row['name'] + (f' {row["percent"]:.1f}%' if number(row.get('percent')) else '') for row in systems), span, 12, 'muted')
            y += 23
        for row in ranked(data, 'categories', 2):
            fitted(x, y, row['name'] + ' · ' + duration(row.get('total_seconds')), span, 12, 'muted')
            y += 23
        start, end = data.get('start'), data.get('end')
        if isinstance(start, str) and isinstance(end, str):
            fitted(x, y, f'{start[:10]} to {end[:10]}', span, 12, 'muted')
            y += 23
        ends.append(y)
    y = max(ends) + 12
    rule(32, y, width - 32, y)
    label(32, y + 35, 'All time', 20, weight=600)
    lifetime = duration(inclusive(all_time, 'total_seconds'))
    fitted(32, y + 65, lifetime + (f' · {count(all_time["days_minus_holidays"])} active days' if number(all_time.get('days_minus_holidays')) else ''), width - 64, 14, 'muted')
    descriptions.append('All-time total: ' + lifetime)
    history_y = y + 101
    y = languages(all_time, 32, history_y, span, 3)
    tools_y = y + 20 if compact else history_y
    tools_x = 32 if compact else 32 + span + 48
    for editor in ranked(all_time, 'editors', 3):
        name = CODEX_DISPLAY_NAMES.get(editor['name'], editor['name'])
        pair(tools_x, tools_y, name, f'{editor["percent"]:.1f}%' if number(editor.get('percent')) else 'Not available', span)
        tools_y += 33
    y = max(y, tools_y) + 18
    for field, name in (('ai_sessions', 'AI sessions'), ('ai_prompt_events_total', 'Prompts'),
                        ('ai_line_changes_total', 'AI lines changed'), ('ai_input_tokens', 'Input tokens'),
                        ('ai_output_tokens', 'Output tokens'), ('ai_model_total_cost', 'Estimated AI cost (USD)')):
        value = all_time.get(field)
        display = f'${value:,.2f}' if field == 'ai_model_total_cost' and number(value) else short_count(value)
        pair(32, y, name, display, width - 64)
        y += 23
    if isinstance(all_time.get('timezone'), str):
        fitted(32, y + 10, all_time['timezone'], width - 64, 12, 'muted')
        y += 23
    height = int(y + 24)
    root.set('height', str(height))
    root.set('viewBox', f'0 0 {width} {height}')
    background.set('height', str(height - 2))
    description.text = ' '.join(descriptions) + ' Active-day blocks show counts, not dates.'
    for node in root.iter():
        if node.text:
            node.text = ''.join(char for char in node.text if ord(char) >= 32)
    return ET.tostring(root, encoding='unicode') + '\n'


def graphic_picture(kind: str, alt: str) -> str:
    prefix = f'assets/wakatime-{kind}'
    return '\n'.join([
        '<picture>',
        f'  <source media="(max-width: 540px)" srcset="{prefix}-mobile.svg">',
        f'  <source media="(prefers-color-scheme: dark)" srcset="{prefix}-dark.svg">',
        f'  <img alt="{html.escape(alt, quote=True)}" src="{prefix}-light.svg" width="760">',
        '</picture>',
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
            if not isinstance(data, dict):
                raise RuntimeError("WakaTime returned invalid data. README kept.")
            if status == 200 and data.get("is_up_to_date") is True:
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


def render_stats(stats: dict) -> str:
    lines = ['## Coding activity', '', graphic_picture('profile', 'Human and AI coding history, last 7 and 30 days, and all-time summary.'), '']
    for key in RANGES:
        data = stats[key]
        if not isinstance(data, dict) or not number(inclusive(data, "total_seconds")):
            raise RuntimeError("WakaTime returned invalid totals. README kept.")
    for key, label in RANGES.items():
        data = stats[key]
        if key != 'all_time':
            continue
        lines += ['<details>', '<summary>Complete historical measurements</summary>', '']
        lines += [
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
                name = CODEX_DISPLAY_NAMES.get(entry["name"], entry["name"]) if field == "editors" else entry["name"]
                rows.append([text(name), duration(entry.get("total_seconds")),
                             f"{percent:.2f}%" if number(percent) else "Not available"])
            lines += [f"#### {title}", "", table(["Name", "Time", "Share"], rows), ""]
        lines += ["#### AI and human activity", ""]
        rows = []
        for field, title in AI_METRICS.items():
            value = data.get(field)
            if number(value):
                rows.append([title, f"${value:,.4f}" if field == "ai_model_total_cost" else count(value)])
        lines += [table(["Measurement", "Value"], rows) if rows else "No AI or human line measurements available.", ""]
        models = models_for(data)
        if models:
            rows = []
            for model in models:
                if not isinstance(model, dict) or not isinstance(model.get("name"), str):
                    raise RuntimeError("WakaTime returned invalid AI model data. README kept.")
                rows.append([text(CODEX_DISPLAY_NAMES.get(model["name"], model["name"])), count(model["lines"]) if number(model.get("lines")) else "Not available",
                             f"${model['cost']:,.4f}" if number(model.get("cost")) else "Not available"])
            lines += [table(["AI model", "Lines changed", "Estimated cost (USD)"], rows), ""]
        lines += ["</details>", ""]
    lines += ["Source: [WakaTime](https://wakatime.com/@onhate). AI costs are estimates. "
              "Recent totals follow WakaTime's date ranges and can exclude today."]
    return "\n".join(lines)


def update_readme(path: Path, token: str, output: Path | None = None) -> None:
    if not token.strip():
        raise RuntimeError("Set the WAKATIME_ACCESS_TOKEN repository secret. README kept.")
    if output is not None and output.parent.resolve() == path.parent.resolve():
        raise RuntimeError('Use a separate directory for preview output to keep public images unchanged.')
    original = path.read_bytes().decode("utf-8")
    if original.count(START) != 1 or original.count(END) != 1 or original.index(START) >= original.index(END):
        raise RuntimeError("README must have one ordered pair of WakaTime section markers.")
    stats = {key: fetch_data(f"stats/{key}", token)["data"] for key in RANGES}
    section = render_stats(stats)
    graphics = {
        f'wakatime-{kind}{"-mobile" if compact else "-" + theme}.svg': render_graphic(stats, kind, theme, compact)
        for kind in GRAPHIC_KINDS for theme, compact in (('light', False), ('dark', False), ('auto', True))
    }
    newline = "\r\n" if "\r\n" in original else "\n"
    section = ("\n\n" + section + "\n\n").replace("\n", newline)
    updated = original[:original.index(START) + len(START)] + section + original[original.index(END):]
    target = output or path
    asset_dir = target.parent / 'assets'
    asset_dir.mkdir(exist_ok=True)
    for old in asset_dir.glob('wakatime-*.svg'):
        if old.name not in graphics:
            old.unlink()
    for filename, content in graphics.items():
        (asset_dir / filename).write_text(content, encoding='utf-8')
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
