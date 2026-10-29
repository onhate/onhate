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


def render_graphic(stats: dict, kind: str, theme: str, compact: bool = False) -> str:
    """Render the approved profile layouts as standalone, script-free SVGs."""
    if kind not in ('summary', 'activity') or theme not in ('light', 'dark', 'auto'):
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
    title = 'Human experience. AI in practice.' if kind == 'summary' else 'Recent coding activity'
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
        return f'{value / 1000000:.2f}M' if value >= 1000000 else f'{value / 1000:.1f}K' if value >= 1000 else count(value)

    background = box(1, 1, width - 2, height - 2, 'bg', 16, 'border')
    label(32, 34, 'ONHATE · DEVELOPER ACTIVITY' if kind == 'summary' else 'WAKATIME · CODING ACTIVITY', 14, 'muted', 500)

    if kind == 'summary':
        defs = ET.SubElement(root, 'defs')
        gradient = ET.SubElement(defs, 'linearGradient', id='banner-background')
        for offset, color in (('0%', 'human_soft'), ('48%', 'bg'), ('100%', 'ai_soft')):
            ET.SubElement(gradient, 'stop', {'offset': offset, 'stop-color': palette[color]})
        # Insert the fill behind the content and retain the outer border.
        root.insert(list(root).index(background) + 1, ET.Element('rect', {'x': '2', 'y': '2', 'width': str(width - 4),
                                         'height': str(height - 4), 'rx': '15', 'fill': 'url(#banner-background)'}))
        label(32, 78, 'Human experience.', 32, weight=600)
        label(32, 113, 'AI in practice.', 32, weight=600)
        label(32, 140, 'All-time tracked coding activity', 16, 'muted')
        all_time = stats['all_time']
        category_rows = all_time.get('categories')
        categories = {row['name']: row.get('total_seconds') for row in (category_rows if isinstance(category_rows, list) else [])
                      if isinstance(row, dict) and isinstance(row.get('name'), str)}
        metric_description = []
        for index, (category, heading, line_key, suffix, color) in enumerate((
            ('Coding', 'Human coding', 'human_additions', 'lines added by hand', 'human'),
            ('AI Coding', 'AI coding', 'ai_additions', 'lines added by AI', 'ai'),
        )):
            x = 32 if compact or index == 0 else 408
            y = (199 + index * 144) if compact else 186
            label(x, y, heading, 18, color, 500)
            seconds = categories.get(category)
            hours = f'{int(seconds // 3600):,}' if number(seconds) else 'Not available'
            node = label(x, y + 48, hours, 44 if number(seconds) else 26, weight=600)
            if number(seconds):
                ET.SubElement(node, 'tspan', {'dx': '8', 'font-size': '18', 'font-weight': '400',
                                              'fill': palette['muted']}).text = 'hrs'
            lines = short_count(all_time.get(line_key))
            label(x, y + 76, f'{lines} {suffix}' if lines != 'Not available' else f'{suffix}: Not available', 16, 'muted')
            metric_description.append(f'{heading}: {hours} hrs; {lines} {suffix}.')
        if compact:
            rule(32, 305, 368, 305)
        else:
            rule(380, 169, 380, 271)
        language_y = 455 if compact else 306
        label(32, language_y, 'TOP LANGUAGES', 14, 'muted', 500)
        label(width - 32, language_y, 'LAST 30 DAYS', 14, 'muted', 500, 'end')
        language_rows = stats['last_30_days'].get('languages')
        candidates = [row for row in (language_rows if isinstance(language_rows, list) else [])
                      if isinstance(row, dict) and isinstance(row.get('name'), str)
                      and number(row.get('percent')) and 0 < row['percent'] <= 100]
        languages = sorted(candidates, key=lambda row: row['percent'], reverse=True)[:3]
        if sum(row['percent'] for row in languages) > 100.1:
            raise RuntimeError('WakaTime returned invalid language percentages. README kept.')
        if languages:
            colors = tuple(palette[f'language_{index}'] for index in (1, 2, 3))
            segments = [(row['name'], row['percent'], colors[i]) for i, row in enumerate(languages)]
            segments.append(('Remaining languages', max(0, 100 - sum(row['percent'] for row in languages)), palette['track']))
            bar_width = width - 64
            cursor = 32.0
            for name, percent, color in segments:
                segment_width = bar_width * percent / 100
                if segment_width:
                    node = box(cursor, language_y + 18, segment_width, 10, color)
                    ET.SubElement(node, 'title').text = f'{name}: {percent:.1f}% of the last 30 days'
                cursor += segment_width
            for index, (name, percent, color) in enumerate(segments):
                column = 0 if compact else index % 2
                row = index if compact else index // 2
                x = 32 + column * 352
                y = language_y + 57 + row * 25
                box(x, y - 10, 8, 8, color, 4)
                shown_name = name if len(name) <= 20 else name[:19] + '…'
                name_node = label(x + 16, y, shown_name, 15)
                clip_id = f'language-name-{index}'
                clip = ET.SubElement(defs, 'clipPath', id=clip_id)
                ET.SubElement(clip, 'rect', {'x': str(x + 16), 'y': str(y - 17),
                                           'width': str((width - 64 if compact else 320) - 80), 'height': '23'})
                name_node.set('clip-path', f'url(#{clip_id})')
                ET.SubElement(name_node, 'title').text = name
                label(width - 32 if compact else x + 320, y, f'{percent:.1f}%', 15, 'muted', anchor='end')
            description.text = ' '.join(metric_description) + ' Last 30 days: ' + '; '.join(f'{name} {percent:.1f}%' for name, percent, _ in segments)
        else:
            label(32, language_y + 43, 'No language percentages available', 16, 'muted')
            description.text = ' '.join(metric_description) + ' Last-30-day language percentages unavailable.'
        label(32, height - 22, 'WakaTime · Languages: last 30 days' if compact else 'WakaTime · All-time totals · Languages: last 30 days', 14, 'muted')
    else:
        label(32, 80, 'Recent coding activity.', 30, weight=600)
        label(32, 109, 'Recent activity, with a longer view below', 16, 'muted')
        descriptions = []
        for index, key in enumerate(('last_7_days', 'last_30_days')):
            data = stats[key]
            x = 32 if compact or index == 0 else 408
            y = 155 + (index * 185 if compact else 0)
            span = width - 64 if compact else 320
            label(x, y, RANGES[key], 18, weight=500)
            total = duration(inclusive(data, 'total_seconds'))
            average = duration(inclusive(data, 'daily_average'))
            label(x, y + 46, total, 30, weight=600)
            label(x, y + 75, f'{average} daily average', 16, 'muted')
            active, days = data.get('days_minus_holidays'), data.get('days_including_holidays')
            valid_days = number(days) and int(days) == days and 0 < days <= 31
            valid_active = number(active) and int(active) == active
            count_label = f'{count(active)} / {count(days)}' if valid_days and valid_active and active <= days else f'{count(active)} active' if valid_active else 'Not available'
            label(x, y + 113, 'Active days', 14, 'muted')
            label(x + span, y + 113, count_label, 14, anchor='end')
            if valid_days and valid_active and active <= days:
                block_width = (span - 3 * (int(days) - 1)) / days
                for day in range(int(days)):
                    box(x + day * (block_width + 3), y + 127, block_width, 12, 'human' if day < active else 'track', 2)
            descriptions.append(f'{RANGES[key]}: {total}; {average} daily average; {count_label} days.')
        y = 524 if compact else 326
        box(32, y, width - 64, 87, 'soft', 10)
        label(48, y + 25, 'ALL TIME', 14, 'muted', 500)
        total = duration(inclusive(stats['all_time'], 'total_seconds'))
        label(48 if compact else width - 48, y + (52 if compact else 28), total, 22, weight=500, anchor=None if compact else 'end')
        lifetime_active = stats['all_time'].get('days_minus_holidays')
        active_text = f' · {count(lifetime_active)} active days' if number(lifetime_active) else ''
        label(48, y + (74 if compact else 62), duration(inclusive(stats['all_time'], 'daily_average')) + (' daily avg' if compact else ' daily average') + active_text, 14, 'muted')
        label(32, height - 21, 'Time includes Other · Blocks show counts, not dates', 14, 'muted')
        description.text = ' '.join(descriptions) + f' All time: {total}. Blocks show counts, not dates.'
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
    lines = [graphic_picture('summary', 'Human and AI coding totals. Top language percentages from the last 30 days.'), '',
             graphic_picture('activity', 'Recent coding activity: last 7 days, last 30 days, and all-time totals.'), '',
             'Time totals include Other. Missing measurements are not treated as zero.', '']
    for key in RANGES:
        data = stats[key]
        if not isinstance(data, dict) or not number(inclusive(data, "total_seconds")):
            raise RuntimeError("WakaTime returned invalid totals. README kept.")
    for key, label in RANGES.items():
        data = stats[key]
        lines += ["<details open>" if key == 'all_time' else "<details>", f"<summary>{label}: full stats</summary>", "",
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
        for kind in ('summary', 'activity') for theme, compact in (('light', False), ('dark', False), ('auto', True))
    }
    newline = "\r\n" if "\r\n" in original else "\n"
    section = ("\n\n" + section + "\n\n").replace("\n", newline)
    updated = original[:original.index(START) + len(START)] + section + original[original.index(END):]
    target = output or path
    asset_dir = target.parent / 'assets'
    asset_dir.mkdir(exist_ok=True)
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
