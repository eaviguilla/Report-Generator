"""Case tables run against each Python rule and its rules.js twin, each side checked against the expected results."""
from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from app import report_service
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
            "network": "Internal",
            "tester": "QA Tester",
            "report_date": "2026-01-05",
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
    return refusal("invalid_characters", field="scope", environment=environment, app_type=channel, box=box, line=line, characters=list(characters))


def long_scope(environment: str, channel: str, box: str, line: int, limit: int) -> dict:
    return refusal("too_long", field="scope", environment=environment, app_type=channel, box=box, line=line, limit=limit)


def thick_client(component: str, description: str, **engagement) -> dict:
    """A Production-only Thick Client report whose one scope box holds the given text."""
    engagement = {"tested_environments": ["production"], "tested_channels": ["thick_client"], **engagement}
    return scoped({("production", "thick_client"): components(component, description)}, **engagement)


def bad_field(field: str, *characters: str, **context) -> dict:
    return refusal("invalid_characters", field=field, **context, characters=list(characters))


def timed(environment: str, test_time: str) -> dict:
    return undated(environment, test_time=test_time)


def accounts(*pairs: tuple[str, str]) -> list[dict]:
    return [{"user_role": role, "username": username} for role, username in pairs]


def too_long(field: str, limit: int, **context) -> dict:
    return refusal("too_long", field=field, **context, limit=limit)


# A letter outside the Basic Multilingual Plane: one code point, two UTF-16 units, as maxlength counts it.
WIDE_LETTER = "\U0001d400"


FIELD_CASES = [
    ("an application name character", setup_report(app_name="Bad/App"), [bad_field("app_name", "/")]),
    ("a letter outside ASCII in the application name", setup_report(app_name="Café Portal-2: (Web)"), []),
    ("a CI number character", setup_report(ci_number="CI_123"), [bad_field("ci_number", "_")]),
    ("a space in the BSN number", setup_report(bsn_number="BSN 1.2"), [bad_field("bsn_number", " ", ".")]),
    ("a digit in the application owner", setup_report(app_owner="Owner 2"), [bad_field("app_owner", "2")]),
    ("a tester character", setup_report(tester="QA_Tester"), [bad_field("tester", "_")]),
    ("a limitations character", setup_report(limitations="No testing @ production\nRead only"), [bad_field("limitations", "@")]),
    ("a test time character", setup_report(test_windows=timed("non_production", "08:00_17:00")), [bad_field("test_time", "_", environment="non_production")]),
    ("an untested environment's time is not checked", setup_report(tested_environments=["production"], test_windows=timed("non_production", "08:00_17:00")), []),
    ("a user role character", setup_report(test_accounts=accounts(("Admin_2", "N/A"))), [bad_field("user_role", "_", account=1)]),
    ("a username character", setup_report(test_accounts=accounts(("N/A", "N/A"), ("Admin", "bad/user"))), [bad_field("username", "/", account=2)]),
    ("a username of N/A", setup_report(test_accounts=accounts(("N/A", "N/A"))), []),
    ("a blank account", setup_report(test_accounts=accounts(("", ""))), []),
    ("a username with a domain and a space", setup_report(test_accounts=accounts(("Admin", "DOMAIN\\qa user@example"))), []),
    ("a username may start and end with punctuation", setup_report(test_accounts=accounts(("Service", "_svc"), ("Service", "svc-"), ("Admin", "qa.user."))), []),
    ("a username starting with a space", setup_report(test_accounts=accounts(("Admin", " qa"))), [refusal("invalid_username", account=1)]),
    ("a username ending in a space", setup_report(test_accounts=accounts(("Admin", "qa "))), [refusal("invalid_username", account=1)]),
    ("a username with a letter outside ASCII names it", setup_report(test_accounts=accounts(("Admin", "José"))), [bad_field("username", "é", account=1)]),
    ("apostrophes and periods in names", setup_report(app_owner="O'Brien-Smith", tester="J. O’Neil"), []),
    ("a digit in the tester", setup_report(tester="Tester 2"), [bad_field("tester", "2")]),
    ("a hyphenated CI number", setup_report(ci_number="CI-12345", bsn_number="BSN-9"), []),
    ("Production dates out of order", setup_report(test_windows=undated("production", start_date="2026-01-03")), [refusal("test_dates_out_of_order", environment="production")]),
    ("Non-Production dates out of order", setup_report(test_windows=undated("non_production", end_date="2026-01-02")), [refusal("test_dates_out_of_order", environment="non_production")]),
    ("one day is in order", setup_report(test_windows=undated("production", end_date="2026-01-01")), []),
    ("a Non-Production name character", setup_report(non_production_label="UAT!"), [bad_field("non_production_label", "!")]),
    ("a Non-Production name is checked trimmed", setup_report(non_production_label="\u0085UAT "), []),
    ("a bad Non-Production name with Non-Production not tested", setup_report(tested_environments=["production"], non_production_label="UAT!"), []),
    ("every field at its limit", setup_report(
        app_name="a" * 100, ci_number="1" * 30, bsn_number="2" * 30, app_owner="o" * 60, tester="t" * 60, limitations="l" * 2000,
        test_windows=timed("production", "9" * 40), test_accounts=accounts(("r" * 60, "u" * 100)),
    ), []),
    ("every field one past its limit, in field order", setup_report(
        app_name="a" * 101, ci_number="1" * 31, bsn_number="2" * 31, app_owner="o" * 61, tester="t" * 61, limitations="l" * 2001,
        test_windows=timed("production", "9" * 41), test_accounts=accounts(("r" * 61, "u" * 101)),
    ), [
        too_long("app_name", 100), too_long("ci_number", 30), too_long("bsn_number", 30), too_long("app_owner", 60), too_long("tester", 60),
        too_long("test_time", 40, environment="production"), too_long("user_role", 60, account=1), too_long("username", 100, account=1),
        too_long("limitations", 2000),
    ]),
    ("length counts UTF-16 units", setup_report(app_name=WIDE_LETTER * 50), []),
    ("a letter outside the BMP counts twice", setup_report(app_name=WIDE_LETTER * 51), [too_long("app_name", 100)]),
    ("an untested environment's time is not measured", setup_report(tested_environments=["production"], test_windows=timed("non_production", "9" * 41)), []),
    ("fifty test accounts", setup_report(test_accounts=accounts(*[("Admin", f"user{index}") for index in range(50)])), []),
    ("fifty-one test accounts", setup_report(test_accounts=accounts(*[("Admin", f"user{index}") for index in range(51)])), [refusal("too_many_accounts", limit=50)]),
    (
        "a whitespace-only application name is refused and missing",
        setup_report(app_name="\x1c"),
        [bad_field("app_name", "\x1c"), issue("missing_app_name")],
    ),
    (
        "every field refusal, in field order, after the scope refusals and before the issues",
        scoped(
            {("production", "thick_client"): components("Acme\x07.exe", "")},
            app_name="Bad/App", ci_number="CI_1", bsn_number="BSN.1", app_owner="Owner 2", tester="QA_Tester",
            tested_channels=["web", "thick_client"], non_production_label="UAT!", limitations="No testing @ prod",
            test_windows={
                "production": {"start_date": "2026-01-03", "end_date": "2026-01-02", "test_time": "08:00_17:00"},
                "non_production": {"start_date": None, "end_date": "2026-01-01", "test_time": "Any|time"},
            },
            test_accounts=accounts(("Admin_2", "bad/user"), ("N/A", " user")),
        ),
        [
            bad_scope("production", "thick_client", "component", 0, "\x07"),
            bad_field("app_name", "/"), bad_field("ci_number", "_"), bad_field("bsn_number", "."), bad_field("app_owner", "2"), bad_field("tester", "_"),
            refusal("test_dates_out_of_order", environment="production"), bad_field("test_time", "_", environment="production"),
            bad_field("test_time", "|", environment="non_production"),
            bad_field("user_role", "_", account=1), bad_field("username", "/", account=1), refusal("invalid_username", account=2),
            bad_field("limitations", "@"), bad_field("non_production_label", "!"),
            undescribed("production", "thick_client", "Acme\x07.exe"), issue("missing_test_dates", environment="non_production"),
        ],
    ),
]


MESSAGE_CASES = [
    (
        "a disallowed character",
        bad_field("app_owner", "0"),
        setup_report(app_owner="Owner 0"),
        'Application owner cannot have "0". Remove or replace it.',
    ),
    (
        "several disallowed characters",
        bad_field("app_owner", "#", "&", "0"),
        setup_report(app_owner="Owner #&0"),
        'Application owner cannot have "#", "&" or "0". Remove or replace them.',
    ),
    (
        "spaces in a field that forbids them",
        bad_field("ci_number", " "),
        setup_report(ci_number="CI 1"),
        "CI number cannot have spaces. Remove the space.",
    ),
    (
        "a hidden character after visible text",
        bad_field("app_name", "\x07"),
        setup_report(app_name="North\x07star"),
        'Application name has a hidden character after "North". Delete it.',
    ),
    (
        "a hidden character at the start",
        bad_field("app_name", "\x07"),
        setup_report(app_name="\x07Bank"),
        "Application name has a hidden character at the start. Delete it.",
    ),
    (
        "a tab",
        bad_field("app_name", "\t"),
        setup_report(app_name="Bank\t"),
        'Application name has a tab after "Bank". Delete it.',
    ),
    (
        "a line break",
        bad_field("app_name", "\n"),
        setup_report(app_name="Bank\nName"),
        'Application name has a line break after "Bank". Delete it.',
    ),
    (
        "an allowed line break before a disallowed character",
        bad_field("limitations", "@"),
        setup_report(limitations="First line\nSecond @"),
        'Limitations cannot have "@". Remove or replace it.',
    ),
    (
        "a non-breaking space",
        bad_field("app_name", "\u00a0"),
        setup_report(app_name="Bank\u00a0Name"),
        'Application name has a non-breaking space after "Bank". Delete it.',
    ),
    (
        "a Unicode 16 unassigned character in Additional Information",
        refusal("invalid_characters", field="cvss_score", label="CVSS Score", characters=["\U00011de0"], value="9.8\U00011de0"),
        setup_report(),
        'CVSS Score has a hidden character after "9.8". Delete it.',
    ),
    (
        "a newly assigned Unicode character follows the server category",
        refusal("invalid_characters", field="cvss_vector", label="CVSS Vector", characters=["\u088f"], value="CVSS:3.1/AV:\u088f"),
        setup_report(),
        'CVSS Vector has a hidden character after "CVSS:3.1/AV:". Delete it.',
    ),
    (
        "the twelve code points before a hidden character",
        bad_field("app_name", "\x07"),
        setup_report(app_name="abcdefghijklmnop\x07"),
        'Application name has a hidden character after "...efghijklmnop". Delete it.',
    ),
    (
        "code-point clipping does not split a non-BMP character",
        bad_field("app_name", "\x07"),
        setup_report(app_name=f"{WIDE_LETTER * 13}\x07"),
        f'Application name has a hidden character after "...{WIDE_LETTER * 12}". Delete it.',
    ),
    (
        "a hidden character in a Web scope line",
        bad_scope("production", "web", "component", 3, "\x07"),
        scoped({("production", "web"): "one\ntwo\nthree\napi.bank.\x07"}, tested_environments=["production"], tested_channels=["web"]),
        'Line 4 has a hidden character after "api.bank.". Delete it.',
    ),
    (
        "a scope refusal names its box away from Setup",
        bad_scope("production", "web", "component", 3, "\x07"),
        scoped({("production", "web"): "one\ntwo\nthree\napi.bank.\x07"}, tested_environments=["production"], tested_channels=["web"]),
        'In the Production Web scope, line 4 has a hidden character after "api.bank.". Delete it.',
        {"scopeContext": True},
    ),
    (
        "a value over its field limit",
        too_long("app_name", 100),
        setup_report(app_name="A" * 101),
        "Application name has 101 characters. Shorten it to 100 or fewer.",
    ),
    (
        "a long scope line names its line",
        long_scope("production", "web", "component", 3, 500),
        scoped({("production", "web"): "\n\n\n" + "A" * 501}, tested_environments=["production"], tested_channels=["web"]),
        "Line 4 has 501 characters. Shorten it to 500 or fewer.",
    ),
    (
        "a long scope line names its box away from Setup",
        long_scope("production", "web", "component", 3, 500),
        scoped({("production", "web"): "\n\n\n" + "A" * 501}, tested_environments=["production"], tested_channels=["web"]),
        "In the Production Web scope, line 4 has 501 characters. Shorten it to 500 or fewer.",
        {"scopeContext": True},
    ),
    (
        "a username with a leading space",
        refusal("invalid_username", account=2),
        setup_report(test_accounts=accounts(("Admin", "N/A"), ("User", " qa"))),
        "Username 2 starts with a space. Delete it.",
    ),
    (
        "a username with a trailing space",
        refusal("invalid_username", account=1),
        setup_report(test_accounts=accounts(("User", "qa "))),
        "Username 1 ends with a space. Delete it.",
    ),
    (
        "a username with spaces at both ends",
        refusal("invalid_username", account=1),
        setup_report(test_accounts=accounts(("User", " qa "))),
        "Username 1 starts and ends with a space. Delete them.",
    ),
    (
        "production dates in the wrong order",
        refusal("test_dates_out_of_order", environment="production"),
        setup_report(test_windows=undated("production", start_date="2026-01-03")),
        "Production start date is after its end date. Change one of them.",
    ),
    (
        "a repeated test account",
        issue("repeated_test_account", account=4, first=1),
        setup_report(test_accounts=accounts(("Admin", "qa"), ("User", "bob"), ("Guest", "guest"), ("Admin", "qa"))),
        "Test account 4 is the same as test account 1. Remove one of them.",
    ),
    (
        "a repeated component",
        repeated("production", "thick_client", "Agent.exe"),
        scoped({("production", "thick_client"): components("Agent.exe\nOther.exe\nAgent.exe", "Run it\nRun it\nRun it")}, tested_environments=["production"], tested_channels=["thick_client"]),
        "Component 3 is the same as component 1. Remove one of them.",
    ),
    (
        "a repeated component names its box away from Setup",
        repeated("production", "thick_client", "Agent.exe"),
        scoped({("production", "thick_client"): components("Agent.exe\nOther.exe\nAgent.exe", "Run it\nRun it\nRun it")}, tested_environments=["production"], tested_channels=["thick_client"]),
        "In the Production Thick Client scope, Component 3 is the same as component 1. Remove one of them.",
        {"scopeContext": True},
    ),
    (
        "more than fifty test accounts",
        refusal("too_many_accounts", limit=50),
        setup_report(test_accounts=accounts(*[("Admin", f"user{index}") for index in range(51)])),
        "A report can list at most 50 test accounts. Remove some.",
    ),
    ("a missing segment", issue("missing_segment"), setup_report(segment=None), "Choose a segment."),
    ("a missing application name", issue("missing_app_name"), setup_report(app_name=""), "Enter the application name."),
    ("a missing report type", issue("missing_report_type"), setup_report(report_type=None), "Choose a report type."),
    ("a missing network access", issue("missing_network"), setup_report(network=None), "Choose the network access."),
    ("a missing tester name", issue("missing_tester"), setup_report(tester=""), "Enter the tester's name."),
    ("a missing report date", issue("missing_report_date"), setup_report(report_date=None), "Enter the report date."),
    (
        "a missing production end date",
        issue("missing_test_dates", environment="production"),
        setup_report(test_windows=undated("production", end_date=None)),
        "Enter the Production end date.",
    ),
    (
        "a missing production start date",
        issue("missing_test_dates", environment="production"),
        setup_report(test_windows=undated("production", start_date=None)),
        "Enter the Production start date.",
    ),
    (
        "missing production start and end dates",
        issue("missing_test_dates", environment="production"),
        setup_report(test_windows=undated("production", start_date=None, end_date=None)),
        "Enter the Production start and end dates.",
    ),
    (
        "a missing scope target",
        issue("missing_scope_target", environment="production"),
        scoped({("production", "web"): ""}, tested_environments=["production"]),
        "Add a scope target for Production.",
    ),
    (
        "a missing username in a test account",
        issue("incomplete_test_account", account=3, missing="username"),
        setup_report(test_accounts=accounts(("Admin", "qa"), ("Admin", ""), ("User", ""))),
        "Enter a username for test account 3, or clear its user role.",
    ),
    (
        "a missing user role in a test account",
        issue("incomplete_test_account", account=3, missing="user_role"),
        setup_report(test_accounts=accounts(("Admin", "qa"), ("Admin", ""), ("", "qa"))),
        "Enter a user role for test account 3, or clear its username.",
    ),
    (
        "a missing component description",
        issue("missing_component_description", environment="production", app_type="thick_client", component="Editor.exe"),
        scoped({("production", "thick_client"): components("Agent.exe\nEditor.exe", "Runs\n")}, tested_environments=["production"], tested_channels=["thick_client"]),
        "Enter a description for component 2.",
    ),
    (
        "both component app types selected",
        issue("mobile_and_thick_client", app_types=["mobile", "thick_client"]),
        setup_report(tested_channels=["mobile", "thick_client"]),
        "Choose Mobile or Thick Client, not both.",
    ),
    (
        "no app type selected",
        refusal("no_app_type"),
        setup_report(tested_channels=[]),
        "Choose at least one app type.",
    ),
    (
        "no environment selected",
        issue("no_tested_environment"),
        setup_report(tested_environments=[]),
        "Choose at least one environment to test.",
    ),
]


SETUP_CASES = [
    ("complete", setup_report(), []),
    ("missing app name", setup_report(app_name=""), [issue("missing_app_name")]),
    ("whitespace-only app name", setup_report(app_name=" \t "), [bad_field("app_name", "\t"), issue("missing_app_name")]),
    ("missing segment", setup_report(segment=None), [issue("missing_segment")]),
    ("missing report type", setup_report(report_type=None), [issue("missing_report_type")]),
    ("missing network access", setup_report(network=None), [issue("missing_network")]),
    ("missing report date", setup_report(report_date=None), [issue("missing_report_date")]),
    ("a blank account row is ignored", setup_report(test_accounts=accounts(("", ""), ("  ", ""), ("Admin", "admin"))), []),
    ("no account rows at all", setup_report(test_accounts=[]), []),
    (
        "a half-filled account row names the missing half",
        setup_report(test_accounts=accounts(("Admin", ""), ("", "viewer"), ("N/A", "N/A"))),
        [issue("incomplete_test_account", account=1, missing="username"), issue("incomplete_test_account", account=2, missing="user_role")],
    ),
    ("N/A counts as filled", setup_report(test_accounts=accounts(("N/A", ""))), [issue("incomplete_test_account", account=1, missing="username")]),
    (
        "a repeated account names the row it repeats",
        setup_report(test_accounts=accounts(("Admin", "admin"), ("Viewer", "viewer"), (" Admin ", "admin"), ("Admin", "admin"))),
        [issue("repeated_test_account", account=3, first=1), issue("repeated_test_account", account=4, first=1)],
    ),
    ("one username under two roles", setup_report(test_accounts=accounts(("Admin", "qa"), ("Viewer", "qa"))), []),
    ("case is kept when comparing accounts", setup_report(test_accounts=accounts(("Admin", "QA"), ("Admin", "qa"))), []),
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
        setup_report(
            app_name="", segment=None, report_type=None, network=None, tester="", report_date=None, tested_channels=["mobile", "thick_client"], test_windows={},
            test_accounts=accounts(("Admin", ""), ("Viewer", "viewer"), ("Viewer", "viewer")),
        ),
        [
            issue("missing_app_name"), issue("missing_segment"), issue("missing_report_type"), issue("missing_network"), issue("missing_tester"), issue("missing_report_date"),
            issue("mobile_and_thick_client", app_types=["mobile", "thick_client"]),
            issue("missing_test_dates", environment="production"), issue("missing_scope_target", environment="production"),
            issue("missing_test_dates", environment="non_production"), issue("missing_scope_target", environment="non_production"),
            issue("incomplete_test_account", account=1, missing="username"), issue("repeated_test_account", account=3, first=2),
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
    ("any printable character in a component or description", thick_client("App+Plus@2 #1!.exe", "Crashes <on> start? ~=$%"), []),
    ("a character Word cannot store in a component", thick_client("Acme\x07.exe", "Main client"), [bad_scope("production", "thick_client", "component", 0, "\x07")]),
    (
        "characters Word cannot store in a description, in the order typed",
        thick_client("Acme.exe", "Bad\x0bdata\ufffe\x0b"),
        [bad_scope("production", "thick_client", "description", 0, "\x0b", "\ufffe")],
    ),
    ("a tab is a character Word can store", thick_client("Acme\t.exe", "Main\tclient"), []),
    ("an install path is allowed", thick_client("C:\\Program Files\\Acme\\acme.exe [x64]", "Client's \"main\" binary; build 2.1 (x64)"), []),
    ("a letter outside ASCII is allowed", thick_client("Café.exe", "Ünïcode client"), []),
    ("surrounding whitespace is trimmed before the check", thick_client("\tAcme.exe ", " Main client\t"), []),
    ("whitespace JavaScript's trim keeps is trimmed", thick_client("\u0085Acme.exe\x1c", "\u3000Main client\x1f"), []),
    ("a byte-order mark is allowed", thick_client("\ufeffAcme.exe", "Main client"), []),
    (
        "a description against a blank or # component is not checked",
        thick_client("\n# retired\x07\nAcme.exe", "stray\x07\nold\x07\nMain client"),
        [],
    ),
    ("a component and a description at their limits", thick_client("c" * 200, "d" * 500), []),
    (
        "a component and a description one past their limits",
        thick_client("c" * 201, "d" * 501),
        [long_scope("production", "thick_client", "component", 0, 200), long_scope("production", "thick_client", "description", 0, 500)],
    ),
    ("a web line at its limit", scoped({("production", "web"): "h" * 500}), []),
    ("the web limit is per line, not per box", scoped({("production", "web"): "\n".join(f"{index}" + "h" * 450 for index in range(3))}), []),
    (
        "component limits are per row, not per box",
        thick_client("\n".join(f"{index}" + "c" * 190 for index in range(3)), "\n".join(f"{index}" + "d" * 490 for index in range(3))),
        [],
    ),
    (
        "a web line one past its limit names its line",
        scoped({("production", "web"): "# notes\n\nhttps://app.example.test\n" + "h" * 501}),
        [long_scope("production", "web", "component", 3, 500)],
    ),
    ("a long # line is not a target", scoped({("production", "web"): "#" + "h" * 600 + "\nhttps://app.example.test"}), []),
    (
        "a character Word cannot store in a web or API line",
        scoped({("production", "web"): "https://app.example.test\x00", ("production", "api"): "api\x1f.example.test"}, tested_channels=["web", "api"]),
        [bad_scope("production", "web", "component", 0, "\x00"), bad_scope("production", "api", "component", 0, "\x1f")],
    ),
    ("any kind of scope line on web and API", scoped({("production", "web"): "https://app.example.test/path?x=1&y=2\n*.example.test\n10.0.0.0/24\napp.example.test/api/v1\nintranet"}), []),
    (
        "untested environments and uncovered app types are not checked",
        scoped(
            {("non_production", "thick_client"): components("Bad\x07\nBad\x07", ""), ("production", "mobile"): components("Bad\x07", "")},
            tested_environments=["production"], tested_channels=["web", "thick_client"],
        ),
        [],
    ),
    (
        "a repeated component's characters are checked on every row",
        thick_client("Acme\x07\nAcme\x07", "Main\nSecond\x07"),
        [
            repeated("production", "thick_client", "Acme\x07"),
            bad_scope("production", "thick_client", "component", 0, "\x07"),
            bad_scope("production", "thick_client", "component", 1, "\x07"), bad_scope("production", "thick_client", "description", 1, "\x07"),
        ],
    ),
    (
        "refusals come first, box by box, then issues",
        scoped(
            {
                ("production", "thick_client"): components("Acme.exe\nTool\x07\nAcme.exe", "\nTo\x0bol\nAgain"),
                ("non_production", "thick_client"): components("Agent.exe\nAgent.exe", "Agent\nAgent"),
            },
            app_name="", tested_channels=["web", "thick_client"],
        ),
        [
            repeated("production", "thick_client", "Acme.exe"),
            bad_scope("production", "thick_client", "component", 1, "\x07"), bad_scope("production", "thick_client", "description", 1, "\x0b"),
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
        cls.vocabulary["unicode_character_ranges"] = report_service.unicode_character_ranges()

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

    def test_setup_field_refusals(self) -> None:
        self.run_cases(FIELD_CASES, setup_results, "setupResults")

    def test_rule_messages(self) -> None:
        self.assertTrue(MESSAGE_CASES, "an empty message table checks nothing")
        for case in MESSAGE_CASES:
            name, result, report, expected, *options = case
            message_options = options[0] if options else {}
            with self.subTest(name, side="Python"):
                self.assertEqual(report_service.format_rule_message(deepcopy(result), deepcopy(report), scope_context=message_options.get("scopeContext", False)), expected)
            with self.subTest(name, side="JavaScript"):
                actual = self.page.evaluate(
                    "([result, report, vocabulary, options]) => window.vrRules.formatRuleMessage(result, report, vocabulary, options)",
                    [result, report, self.vocabulary, message_options],
                )
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
