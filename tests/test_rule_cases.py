"""Case tables run against each Python rule and its rules.js twin, each side checked against the expected results."""
from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from app.report_service import setup_results
from app.vocabulary import client_vocabulary

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - the dev requirements install it
    sync_playwright = None

RULES_JS = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "rules.js"


def setup_report(**engagement) -> dict:
    """A report in the shape the Setup page sends, complete unless `engagement` changes it."""
    report = {
        "engagement": {
            "app_name": "Northstar Banking",
            "segment": "JH",
            "report_type": "annual_pentest",
            "tester": "QA Tester",
            "tested_environments": ["production", "non_production"],
            "tested_channels": ["web"],
            "test_windows": {
                "production": {"start_date": "2026-01-01", "end_date": "2026-01-02", "test_time": "Anytime"},
                "non_production": {"start_date": "2026-01-03", "end_date": "2026-01-04", "test_time": "Anytime"},
            },
        },
        "scope_text": {
            "production": {"web": "https://app.example.test", "api": "", "mobile": {"component": "", "description": ""}, "thick_client": {"component": "", "description": ""}},
            "non_production": {"web": "https://test.example.test", "api": "", "mobile": {"component": "", "description": ""}, "thick_client": {"component": "", "description": ""}},
        },
    }
    report["engagement"].update(engagement)
    return report


def issue(code: str, **context) -> dict:
    return {"kind": "issue", "code": code, **context}


def undated(environment: str, **window) -> dict:
    """The complete report's test windows with one environment's dates changed."""
    windows = deepcopy(setup_report()["engagement"]["test_windows"])
    windows[environment].update(window)
    return windows


SETUP_CASES = [
    ("complete", setup_report(), []),
    ("missing app name", setup_report(app_name=""), [issue("missing_app_name")]),
    ("whitespace-only app name", setup_report(app_name=" \t "), [issue("missing_app_name")]),
    ("missing segment", setup_report(segment=None), [issue("missing_segment")]),
    ("missing report type", setup_report(report_type=None), [issue("missing_report_type")]),
    ("missing tester", setup_report(tester=""), [issue("missing_tester")]),
    ("whitespace-only tester", setup_report(tester="  "), [issue("missing_tester")]),
    ("no tested environment", setup_report(tested_environments=[]), [issue("no_tested_environment")]),
    ("missing end date", setup_report(test_windows=undated("production", end_date=None)), [issue("missing_test_dates", environment="production")]),
    ("missing start date", setup_report(test_windows=undated("non_production", start_date=None)), [issue("missing_test_dates", environment="non_production")]),
    ("no test window at all", setup_report(test_windows={}), [issue("missing_test_dates", environment="production"), issue("missing_test_dates", environment="non_production")]),
    ("untested environment without dates", setup_report(tested_environments=["production"], test_windows=undated("non_production", start_date=None, end_date=None)), []),
    ("dates follow the tested order", setup_report(tested_environments=["non_production", "production"], test_windows={}), [issue("missing_test_dates", environment="non_production"), issue("missing_test_dates", environment="production")]),
    ("Mobile and Thick Client together", setup_report(tested_channels=["thick_client", "web", "mobile"]), [issue("mobile_and_thick_client", app_types=["mobile", "thick_client"])]),
    ("one component app type", setup_report(tested_channels=["web", "thick_client"]), []),
    (
        "every issue, in order",
        setup_report(app_name="", segment=None, report_type=None, tester="", tested_channels=["mobile", "thick_client"], test_windows={}),
        [
            issue("missing_app_name"), issue("missing_segment"), issue("missing_report_type"), issue("missing_tester"),
            issue("mobile_and_thick_client", app_types=["mobile", "thick_client"]),
            issue("missing_test_dates", environment="production"), issue("missing_test_dates", environment="non_production"),
        ],
    ),
    (
        "no environment comes before the app types",
        setup_report(tester="", tested_environments=[], tested_channels=["mobile", "thick_client"]),
        [issue("missing_tester"), issue("no_tested_environment"), issue("mobile_and_thick_client", app_types=["mobile", "thick_client"])],
    ),
]


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class RuleCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)
        cls.page = cls.browser.new_page()
        cls.page.add_script_tag(content=RULES_JS.read_text(encoding="utf-8"))
        cls.vocabulary = client_vocabulary()

    def run_cases(self, cases: list[tuple[str, dict, list[dict]]], python_rule, javascript_name: str) -> None:
        """Run each case against `python_rule` and against `window.vrRules[javascript_name]`."""
        self.assertTrue(cases, "an empty case table checks nothing")
        for name, report, expected in cases:
            with self.subTest(name, side="Python"):
                self.assertEqual(python_rule(deepcopy(report)), expected)
            with self.subTest(name, side="JavaScript"):
                actual = self.page.evaluate(
                    "([name, report, vocabulary]) => window.vrRules[name](report, vocabulary)",
                    [javascript_name, report, self.vocabulary],
                )
                self.assertEqual(actual, expected)

    def test_setup_results(self) -> None:
        self.run_cases(SETUP_CASES, setup_results, "setupResults")


if __name__ == "__main__":
    unittest.main()
