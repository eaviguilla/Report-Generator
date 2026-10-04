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


def scoped(boxes: dict[tuple[str, str], object], **engagement) -> dict:
    """A report whose scope boxes, keyed by (environment, app type), hold the given text."""
    report = setup_report(**engagement)
    for (environment, channel), value in boxes.items():
        report["scope_text"][environment][channel] = value
    return report


def components(component: str, description: str) -> dict:
    return {"component": component, "description": description}


def undescribed(environment: str, channel: str, component: str) -> dict:
    return issue("missing_component_description", environment=environment, app_type=channel, component=component)


def refusal(code: str, **context) -> dict:
    return {"kind": "refusal", "code": code, **context}


def repeated(environment: str, channel: str, component: str) -> dict:
    return refusal("duplicate_component", environment=environment, app_type=channel, component=component)


def bad_scope(environment: str, channel: str, box: str, line: int, *characters: str) -> dict:
    return refusal("invalid_characters", field="component_scope", environment=environment, app_type=channel, box=box, line=line, characters=list(characters))


def thick_client(component: str, description: str, **engagement) -> dict:
    """A Production-only Thick Client report whose one scope box holds the given text."""
    engagement = {"tested_environments": ["production"], "tested_channels": ["thick_client"], **engagement}
    return scoped({("production", "thick_client"): components(component, description)}, **engagement)


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
            issue("missing_test_dates", environment="production"), issue("missing_scope_target", environment="production"),
            issue("missing_test_dates", environment="non_production"), issue("missing_scope_target", environment="non_production"),
        ],
    ),
    (
        "no environment comes before the app types",
        setup_report(tester="", tested_environments=[], tested_channels=["mobile", "thick_client"]),
        [issue("missing_tester"), issue("no_tested_environment"), issue("mobile_and_thick_client", app_types=["mobile", "thick_client"])],
    ),
    ("no scope target", scoped({("production", "web"): ""}), [issue("missing_scope_target", environment="production")]),
    ("whitespace-only scope target", scoped({("non_production", "web"): " \t "}), [issue("missing_scope_target", environment="non_production")]),
    ("only blank and # scope lines", scoped({("production", "web"): "\n# staging later\n   \n"}), [issue("missing_scope_target", environment="production")]),
    ("a # line among targets", scoped({("production", "web"): "# old\nhttps://app.example.test"}), []),
    (
        "scope text under an app type not covered",
        scoped({("production", "web"): "", ("production", "api"): "https://api.example.test"}),
        [issue("missing_scope_target", environment="production")],
    ),
    (
        "an untested environment's scope text is ignored",
        scoped({("non_production", "web"): "", ("non_production", "thick_client"): components("Acme.exe", "")}, tested_environments=["production"], tested_channels=["web", "thick_client"]),
        [],
    ),
    (
        "a component with no description",
        scoped({("production", "thick_client"): components("Acme.exe", "")}, tested_channels=["web", "thick_client"]),
        [undescribed("production", "thick_client", "Acme.exe")],
    ),
    (
        "a whitespace-only description",
        scoped({("production", "mobile"): components(" Acme.apk ", " \t ")}, tested_channels=["web", "mobile"]),
        [undescribed("production", "mobile", "Acme.apk")],
    ),
    (
        "several components, one without a description",
        scoped({("production", "thick_client"): components("Acme.exe\nUpdater.exe\nAgent.exe", "Main client\n\nBackground agent")}, tested_channels=["web", "thick_client"]),
        [undescribed("production", "thick_client", "Updater.exe")],
    ),
    (
        "a # component line keeps the description below it in place",
        scoped({("production", "thick_client"): components("# retired\nAcme.exe", "\nMain client")}, tested_environments=["production"], tested_channels=["thick_client"]),
        [],
    ),
    (
        "a blank component line mid-box does not pass its description on",
        scoped({("production", "thick_client"): components("Acme.exe\n\n# retired\nUpdater.exe", "Main client\nstray\nold")}, tested_environments=["production"], tested_channels=["thick_client"]),
        [undescribed("production", "thick_client", "Updater.exe")],
    ),
    (
        "a description against a blank component names no target",
        scoped({("production", "thick_client"): components("", "Main client")}, tested_environments=["production"], tested_channels=["thick_client"]),
        [issue("missing_scope_target", environment="production")],
    ),
    (
        "descriptions follow the app type order",
        scoped({("production", "thick_client"): components("Acme.exe", ""), ("production", "mobile"): components("Acme.apk", "")}, tested_environments=["production"], tested_channels=["thick_client", "mobile"]),
        [issue("mobile_and_thick_client", app_types=["mobile", "thick_client"]), undescribed("production", "mobile", "Acme.apk"), undescribed("production", "thick_client", "Acme.exe")],
    ),
    (
        "each environment's dates, scope target and descriptions together",
        scoped(
            {("production", "thick_client"): components("Acme.exe", ""), ("non_production", "web"): ""},
            tested_channels=["web", "thick_client"], test_windows={},
        ),
        [
            issue("missing_test_dates", environment="production"), undescribed("production", "thick_client", "Acme.exe"),
            issue("missing_test_dates", environment="non_production"), issue("missing_scope_target", environment="non_production"),
        ],
    ),
    (
        "no app type",
        setup_report(tested_channels=[]),
        [refusal("no_app_type"), issue("missing_scope_target", environment="production"), issue("missing_scope_target", environment="non_production")],
    ),
    ("a component typed twice", thick_client("Acme.exe\n Acme.exe ", "Main client\nSecond build"), [repeated("production", "thick_client", "Acme.exe")]),
    (
        "each repeated component once, in the order it repeats",
        thick_client("Acme.exe\nUpdater.exe\nUpdater.exe\nAcme.exe\nAcme.exe", "a\nb\nc\nd\ne"),
        [repeated("production", "thick_client", "Updater.exe"), repeated("production", "thick_client", "Acme.exe")],
    ),
    ("a repeated # line is not a component", thick_client("# old\n# old\nAcme.exe", "\n\nMain client"), []),
    ("a URL typed twice on web is dropped", scoped({("production", "web"): "https://app.example.test\nhttps://app.example.test"}), []),
    (
        "a URL typed twice on API is dropped",
        scoped({("production", "api"): "https://api.example.test\n https://api.example.test"}, tested_channels=["web", "api"]),
        [],
    ),
    ("a component character", thick_client("Acme!.exe", "Main client"), [bad_scope("production", "thick_client", "component", 0, "!")]),
    ("description characters, in the order typed", thick_client("Acme.exe", "Crashes <on> start!<"), [bad_scope("production", "thick_client", "description", 0, "<", ">", "!")]),
    ("an install path is allowed", thick_client("C:\\Program Files\\Acme\\acme.exe [x64]", "Client's \"main\" binary; build 2.1 (x64)"), []),
    ("a letter outside ASCII is allowed", thick_client("Café.exe", "Ünïcode client"), []),
    ("surrounding whitespace is trimmed before the check", thick_client("\tAcme.exe ", " Main client\t"), []),
    ("whitespace JavaScript's trim keeps is trimmed", thick_client("\u0085Acme.exe\x1c", "\u3000Main client\x1f"), []),
    ("a byte-order mark is not whitespace", thick_client("\ufeffAcme.exe", "Main client"), [bad_scope("production", "thick_client", "component", 0, "\ufeff")]),
    ("a # description is checked", thick_client("Acme.exe", "# main client"), [bad_scope("production", "thick_client", "description", 0, "#")]),
    (
        "a description against a blank or # component is not checked",
        thick_client("\n# retired!\nAcme.exe", "stray!\nold?\nMain client"),
        [],
    ),
    ("a line separator is not a line break", thick_client("Alpha\u2028Beta", "One"), [bad_scope("production", "thick_client", "component", 0, "\u2028")]),
    ("web and API are not checked", scoped({("production", "web"): "https://app.example.test/path?x=1&y=2"}), []),
    (
        "untested environments and uncovered app types are not checked",
        scoped(
            {("non_production", "thick_client"): components("Bad!\nBad!", ""), ("production", "mobile"): components("Bad!", "")},
            tested_environments=["production"], tested_channels=["web", "thick_client"],
        ),
        [],
    ),
    (
        "a repeated component's characters are checked on every row",
        thick_client("Acme!\nAcme!", "Main\nSecond?"),
        [
            repeated("production", "thick_client", "Acme!"),
            bad_scope("production", "thick_client", "component", 0, "!"),
            bad_scope("production", "thick_client", "component", 1, "!"), bad_scope("production", "thick_client", "description", 1, "?"),
        ],
    ),
    (
        "refusals come first, box by box, then issues",
        scoped(
            {
                ("production", "thick_client"): components("Acme.exe\nTool!\nAcme.exe", "\nTool?\nAgain"),
                ("non_production", "thick_client"): components("Agent.exe\nAgent.exe", "Agent\nAgent"),
            },
            app_name="", tested_channels=["web", "thick_client"],
        ),
        [
            repeated("production", "thick_client", "Acme.exe"),
            bad_scope("production", "thick_client", "component", 1, "!"), bad_scope("production", "thick_client", "description", 1, "?"),
            repeated("non_production", "thick_client", "Agent.exe"),
            issue("missing_app_name"), undescribed("production", "thick_client", "Acme.exe"),
        ],
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
