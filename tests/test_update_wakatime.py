import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts import update_wakatime as waka


def sample_stats():
    data = {
        "is_up_to_date": True,
        "start": "2026-10-01T00:00:00Z",
        "end": "2026-10-29T23:59:59Z",
        "timezone": "America/Sao_Paulo",
        "total_seconds": 3600,
        "total_seconds_including_other_language": 5400,
        "daily_average_including_other_language": 1800,
        "days_minus_holidays": 3,
        "days_including_holidays": 7,
        "best_day": {"date": "2026-10-28", "total_seconds": 3600},
        "languages": [
            {"name": "Other", "total_seconds": 1800, "percent": 33.33},
            {"name": "YAML", "total_seconds": 900, "percent": 16.67},
        ],
        "editors": [{"name": "VS Code", "total_seconds": 5400, "percent": 100}],
        "operating_systems": [{"name": "Mac", "total_seconds": 5400, "percent": 100}],
        "categories": [{"name": "Coding", "total_seconds": 5400, "percent": 100}],
        "dependencies": [{"name": "react", "total_seconds": 5400, "percent": 100}],
        "projects": [{"name": "SECRET_PROJECT"}],
        "machines": [{"name": "SECRET_HOST 192.0.2.1"}],
        "ai_additions": 25,
        "ai_deletions": 5,
        "human_additions": 70,
        "human_deletions": 10,
        "ai_input_tokens": 12000,
        "ai_output_tokens": 800,
        "ai_sessions": 2,
        "ai_prompt_events_total": 8,
        "ai_prompt_length_avg": 120,
        "ai_prompt_length_sum": 960,
        "ai_prompt_length_avg_per_session": 110,
        "ai_prompt_length_median_per_session": 100,
        "ai_prompt_events_avg_per_session": 4,
        "ai_prompt_events_median_per_session": 3,
        "ai_model_total_cost": 0.1234,
        "ai_model_breakdown": [{"name": "Test Model", "lines": 30, "cost": 0.1234}],
    }
    return {key: copy.deepcopy(data) for key in ("last_7_days", "last_30_days", "all_time")}


SUMMARIES = {"data": [{
    "range": {"date": "2026-10-29"},
    "grand_total": {"total_seconds": 5400},
    "projects": [{"name": "SECRET_DAILY_PROJECT"}],
}]}


class Response(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status


class RenderTests(unittest.TestCase):
    def test_codex_source_labels_are_displayed_as_codex_without_changing_values(self):
        stats = sample_stats()
        stats["last_7_days"]["editors"] = [
            {"name": "Codex Vscode", "total_seconds": 3600, "percent": 66.67},
            {"name": "VS Code", "total_seconds": 1800, "percent": 33.33},
        ]
        stats["last_7_days"]["ai_model_breakdown"] = [{"name": "Codex-Vscode", "lines": 30, "cost": 0.1234}]
        output = waka.render_stats(stats, SUMMARIES)
        self.assertIn("| Codex | 1 hr 0 mins | 66.67% |", output)
        self.assertIn("| VS Code | 30 mins | 33.33% |", output)
        self.assertIn("| Codex | 30 | $0.1234 |", output)
        self.assertNotIn("Codex Vscode", output)
        self.assertNotIn("Codex-Vscode", output)
        self.assertEqual(stats["last_7_days"]["editors"][0]["name"], "Codex Vscode")

    def test_codex_label_is_also_corrected_for_model_map_fallback(self):
        stats = sample_stats()
        stats["all_time"].pop("ai_model_breakdown")
        stats["all_time"]["ai_model_line_changes"] = {"Codex-Vscode": 8}
        stats["all_time"]["ai_model_costs"] = {"Codex-Vscode": 0.25}
        output = waka.render_stats(stats, SUMMARIES)
        self.assertIn("| Codex | 8 | $0.2500 |", output)
        self.assertNotIn("Codex-Vscode", output)

    def test_inclusive_totals_and_all_languages_after_other(self):
        output = waka.render_stats(sample_stats(), SUMMARIES)
        self.assertIn("1 hr 30 mins", output)
        self.assertIn("YAML", output)
        self.assertIn("Other", output)
        for name in ("VS Code", "Mac", "Coding", "2026-10-28", "2026-10-29"):
            self.assertIn(name, output)
        self.assertIn("16.67%", output)

    def test_private_fields_never_reach_readme(self):
        output = waka.render_stats(sample_stats(), SUMMARIES)
        self.assertNotIn("SECRET", output)
        self.assertNotIn("192.0.2.1", output)

    def test_dependencies_are_omitted_because_they_can_contain_internal_project_names(self):
        stats = sample_stats()
        stats["last_7_days"]["dependencies"] = [{"name": "PRIVATE_PACKAGE", "total_seconds": 120, "percent": 5}]
        output = waka.render_stats(stats, SUMMARIES)
        self.assertNotIn("PRIVATE_PACKAGE", output)
        self.assertNotIn("Dependencies", output)

    def test_ai_measurements_and_cost_are_not_inferred(self):
        output = waka.render_stats(sample_stats(), SUMMARIES)
        for value in ("12,000", "800", "$0.1234", "Test Model", "960", "110"):
            self.assertIn(value, output)
        self.assertIn("AI lines added", output)
        self.assertIn("Human lines deleted", output)
        self.assertIn("Prompts per session (median)", output)

    def test_missing_measurements_are_not_zero_and_measured_zero_is_kept(self):
        stats = sample_stats()
        for data in stats.values():
            data.pop("ai_input_tokens")
            data["ai_output_tokens"] = 0
        output = waka.render_stats(stats, SUMMARIES)
        self.assertNotIn("Input tokens", output)
        self.assertIn("| Output tokens | 0 |", output)

    def test_untrusted_names_cannot_inject_markdown_or_html(self):
        stats = sample_stats()
        stats["all_time"]["languages"][0]["name"] = "<img src=x>|[click](bad)\n# Heading"
        output = waka.render_stats(stats, SUMMARIES)
        self.assertNotIn("<img", output)
        self.assertNotIn("[click](bad)", output)
        self.assertNotIn("\n# Heading", output)
        self.assertIn("&lt;img", output)


class FetchTests(unittest.TestCase):
    def test_uses_bearer_header_and_fixed_api_origin(self):
        def serve(request, timeout):
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertEqual(request.full_url, "https://api.wakatime.com/api/v1/users/current/stats/all_time")
            self.assertGreater(timeout, 0)
            return Response({"data": sample_stats()["all_time"]})

        with patch.object(waka, "urlopen", side_effect=serve):
            self.assertEqual(waka.fetch_data("stats/all_time", "test-token")["data"]["total_seconds"], 3600)

    def test_stale_and_accepted_responses_are_retried(self):
        responses = [
            Response({"data": {"is_up_to_date": False}}, 202),
            Response({"data": {"is_up_to_date": False}}),
            Response({"data": sample_stats()["all_time"]}),
        ]
        with patch.object(waka, "urlopen", side_effect=responses), patch.object(waka.time, "sleep"):
            self.assertTrue(waka.fetch_data("stats/all_time", "secret")["data"]["is_up_to_date"])

    def test_authentication_errors_are_safe_and_not_retried(self):
        error = HTTPError("https://example.com/secret", 401, "secret", {}, io.BytesIO(b"secret"))
        with patch.object(waka, "urlopen", side_effect=error) as request:
            with self.assertRaisesRegex(RuntimeError, "401") as caught:
                waka.fetch_data("stats/all_time", "secret")
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(request.call_count, 1)

    def test_temporary_failures_have_bounded_retries(self):
        for error in (URLError("secret"), HTTPError("url", 429, "secret", {}, None),
                      HTTPError("url", 503, "secret", {}, None)):
            with self.subTest(error=type(error).__name__):
                with patch.object(waka, "urlopen", side_effect=error) as request, patch.object(waka.time, "sleep"):
                    with self.assertRaises(RuntimeError) as caught:
                        waka.fetch_data("stats/all_time", "secret")
                    self.assertNotIn("secret", str(caught.exception))
                    self.assertEqual(request.call_count, 4)

    def test_stale_responses_never_return_as_fresh(self):
        with patch.object(waka, "urlopen", side_effect=lambda *a, **k: Response({"data": {"is_up_to_date": False}})), patch.object(waka.time, "sleep"):
            with self.assertRaises(RuntimeError):
                waka.fetch_data("stats/all_time", "secret")

    def test_invalid_json_and_error_payloads_are_rejected(self):
        for payload in ({"error": "secret"}, {"data": None}):
            with patch.object(waka, "urlopen", return_value=Response(payload)):
                with self.assertRaises(RuntimeError) as caught:
                    waka.fetch_data("stats/all_time", "secret")
                self.assertNotIn("secret", str(caught.exception))
        with patch.object(waka, "urlopen", return_value=io.BytesIO(b"not JSON")):
            with self.assertRaises(RuntimeError):
                waka.fetch_data("stats/all_time", "secret")


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "README.md"
        self.original = "Greeting\r\n<!--START_SECTION:waka-->\r\nold\r\n<!--END_SECTION:waka-->\r\nFooter\r\n"
        self.path.write_bytes(self.original.encode())

    def test_replaces_only_marked_section(self):
        payloads = [{"data": value} for value in sample_stats().values()] + [SUMMARIES]
        with patch.object(waka, "fetch_data", side_effect=payloads):
            waka.update_readme(self.path, "secret")
        output = self.path.read_bytes().decode()
        self.assertTrue(output.startswith("Greeting\r\n<!--START_SECTION:waka-->"))
        self.assertTrue(output.endswith("<!--END_SECTION:waka-->\r\nFooter\r\n"))
        self.assertNotIn("\r\nold\r\n", output)

    def test_failed_final_request_leaves_readme_unchanged(self):
        payloads = [{"data": value} for value in sample_stats().values()] + [RuntimeError("API failed")]
        with patch.object(waka, "fetch_data", side_effect=payloads):
            with self.assertRaises(RuntimeError):
                waka.update_readme(self.path, "secret")
        self.assertEqual(self.path.read_bytes(), self.original.encode())

    def test_invalid_data_leaves_readme_unchanged(self):
        payloads = [{"data": value} for value in sample_stats().values()] + [{"data": [{}]}]
        with patch.object(waka, "fetch_data", side_effect=payloads):
            with self.assertRaises(RuntimeError):
                waka.update_readme(self.path, "secret")
        self.assertEqual(self.path.read_bytes(), self.original.encode())

    def test_missing_or_duplicate_markers_are_rejected(self):
        for original in ("no markers", self.original + self.original):
            self.path.write_text(original)
            with self.assertRaises(RuntimeError):
                waka.update_readme(self.path, "secret")
            self.assertEqual(self.path.read_bytes(), original.encode())

    def test_missing_token_leaves_readme_unchanged(self):
        with self.assertRaisesRegex(RuntimeError, "WAKATIME_ACCESS_TOKEN"):
            waka.update_readme(self.path, "")
        self.assertEqual(self.path.read_bytes(), self.original.encode())

    def test_preview_writes_output_without_changing_readme(self):
        output = self.path.parent / "preview.md"
        payloads = [{"data": value} for value in sample_stats().values()] + [SUMMARIES]
        with patch.object(waka, "fetch_data", side_effect=payloads):
            waka.update_readme(self.path, "secret", output)
        self.assertEqual(self.path.read_bytes(), self.original.encode())
        self.assertIn("Coding activity", output.read_text())


if __name__ == "__main__":
    unittest.main()
