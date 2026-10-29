# Profile Graphics Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in the current checkout.

**Goal:** Publish the selected profile graphics with recent language percentages.

**Architecture:** The current Python generator renders static SVG assets from its
existing three Stats responses. README picture elements select theme and layout.
The existing Actions job publishes Markdown and assets together.

**Tech Stack:** Python standard library, unittest, SVG, GitHub Actions.

**Spec:** ../specs/2026-10-29-profile-graphics.md

## Global Constraints

- Current main checkout; no worktree.
- Human and AI banner measurements use all-time data. Languages use last_30_days.
- Recent focus replaces the overview table; detail sections remain.
- No daily activity section, private fields, new packages, or additional API calls.
- Neutral public headings; no pronouns.

## Review Focus

- Last-30-day language values must not come from all-time data.
- Missing fields must not become measured zeroes.
- Names must remain XML text and must not inject markup or overflow the image.
- Preview images must stay beside the preview, not modify public assets.
- Image-only changes must be included in the workflow commit.

### Task 1: Render and publish the chosen graphics

**Files:** Modify `scripts/update_wakatime.py`, `tests/test_update_wakatime.py`,
`.github/workflows/waka.yml`, `README.md`, and `docs/wakatime-setup.md`.
Generate `assets/wakatime-*.svg`.

**Interfaces:** `render_graphic(stats: dict, kind: str, theme: str, compact: bool = False) -> str`;
existing `render_stats` returns Markdown with pictures; `update_readme` writes all
validated output beside the target Markdown.

- [ ] Write tests for period selection, category hours and line counts, missing and
  zero measurements, escaping, theme/mobile variants, preview isolation, and assets.
- [ ] Run the suite and observe the new tests fail before implementing.
- [ ] Implement the two layouts and their theme/mobile variants.
- [ ] Replace overview Markdown and update preview/publish steps to include assets.
- [ ] Run unittest, actionlint, and git diff --check. Expect all checks to pass.
- [ ] Render light/dark and narrow layouts with local data and inspect the images.
- [ ] Get an independent review. Fix material findings and rerun checks.
- [ ] Commit, push, and run the approved publisher. Verify the public image paths
  and recent language period, then sync the local checkout.
