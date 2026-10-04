from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from itertools import zip_longest
from typing import Callable, Literal

from app.models import CHANNEL_LABELS, CHANNELS, COMPONENT_CHANNELS, REPORT_TYPE_LABELS, Channel, Content, Engagement, Environment, ImageFragment, ListFragment, ListItem, ParagraphFragment, Report, Run, ScopeTarget, TableFragment, Vulnerability, resolve_tested_channels

INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._@\\-](?:[ A-Za-z0-9._@\\-]*[A-Za-z0-9._@\\-])?$")
RESOLVED_REMEDIATION = "None, the vulnerability has been remediated."
# Guidance left in library text, such as "(insert version here)"; generation refuses it.
PLACEHOLDER_TEXT = re.compile(
    r"\(\s*insert[^)]*\)|insert\s+(technology|version|eol\s+date|cves|latest)\s+\w*\s*here",
    re.IGNORECASE,
)
@cache
def unicode_character_ranges() -> dict[str, tuple[tuple[int, int], ...]]:
    """Expose Python's exact character categories to the browser's twin validators."""
    def ranges(predicate: Callable[[str], bool]) -> tuple[tuple[int, int], ...]:
        result: list[tuple[int, int]] = []
        start = previous = None
        for code_point in range(0x110000):
            if not predicate(chr(code_point)):
                continue
            if start is None:
                start = previous = code_point
            elif code_point == previous + 1:
                previous = code_point
            else:
                result.append((start, previous))
                start = previous = code_point
        if start is not None:
            result.append((start, previous))
        return tuple(result)

    return {
        "letters": ranges(str.isalpha),
        "decimals": ranges(str.isdecimal),
        "hidden": ranges(lambda character: unicodedata.category(character)[:1] in {"C", "Z"}),
    }


def _invalid_characters(
    value: str,
    symbols: str,
    *,
    allow_letters: bool = True,
    allow_numbers: bool = True,
    allow_spaces: bool = True,
    allow_line_breaks: bool = False,
) -> list[str]:
    spacing = {" "} if allow_spaces else set()
    if allow_line_breaks:
        spacing.update({"\r", "\n"})
    invalid = (
        character
        for character in value
        if not (
            (allow_letters and character.isalpha())
            or (allow_numbers and character.isdecimal())
            or character in symbols
            or character in spacing
        )
    )
    return list(dict.fromkeys(invalid))


def invalid_character_issue(
    label: str,
    value: str,
    symbols: str,
    *,
    field: str | None = None,
    allow_letters: bool = True,
    allow_numbers: bool = True,
    allow_spaces: bool = True,
    allow_line_breaks: bool = False,
) -> str | None:
    """Return the plain message for invalid characters in a field value."""
    invalid = _invalid_characters(
        value,
        symbols,
        allow_letters=allow_letters,
        allow_numbers=allow_numbers,
        allow_spaces=allow_spaces,
        allow_line_breaks=allow_line_breaks,
    )
    if not invalid:
        return None
    return format_rule_message({"code": "invalid_characters", "field": field, "label": label, "characters": invalid, "value": value})


def format_rule_message(result: dict, report: dict | None = None, *, scope_context: bool = False) -> str:
    """Turn one coded rule result into the words shown to the tester."""
    code = result["code"]
    engagement = (report or {}).get("engagement", {})
    fixed_messages = {
        "missing_app_name": "Enter the application name.",
        "missing_segment": "Choose a segment.",
        "missing_report_type": "Choose a report type.",
        "missing_network": "Choose the network access.",
        "missing_tester": "Enter the tester's name.",
        "missing_report_date": "Enter the report date.",
        "no_tested_environment": "Choose at least one environment to test.",
        "no_app_type": "Choose at least one app type.",
    }
    if code in fixed_messages:
        return fixed_messages[code]
    if code == "too_many_accounts":
        return f"A report can list at most {result['limit']} test accounts. Remove some."
    if code == "mobile_and_thick_client":
        return f"Choose {' or '.join(CHANNEL_LABELS[channel] for channel in result['app_types'])}, not both."
    if code == "repeated_test_account":
        return f"Test account {result['account']} is the same as test account {result['first']}. Remove one of them."
    if code == "missing_test_dates":
        environment = _environment_label(result["environment"])
        window = engagement.get("test_windows", {}).get(result["environment"], {}) or {}
        missing = [name for name in ("start", "end") if not window.get(f"{name}_date")]
        dates = "start and end dates" if len(missing) == 2 else f"{missing[0]} date"
        return f"Enter the {environment} {dates}."
    if code == "missing_scope_target":
        return f"Add a scope target for {_environment_label(result['environment'])}."
    if code == "missing_component_description":
        scope = (report or {}).get("scope_text", {}).get(result["environment"], {}).get(result["app_type"], "")
        text = scope.get("component", "") if isinstance(scope, dict) else scope
        row = next((index for index, component in enumerate(text.split("\n") if isinstance(text, str) else [], start=1) if component.strip() == result["component"]), 0)
        return f"Enter a description for component {row}."
    if code == "incomplete_test_account":
        detail = "username" if result["missing"] == "username" else "user role"
        other = "user role" if result["missing"] == "username" else "username"
        return f"Enter a {detail} for test account {result['account']}, or clear its {other}."
    if code == "invalid_username":
        accounts = engagement.get("test_accounts") or []
        account = result["account"]
        username = accounts[account - 1].get("username", "") if account <= len(accounts) and isinstance(accounts[account - 1], dict) else ""
        starts, ends = username.startswith(" "), username.endswith(" ")
        position = "starts and ends" if starts and ends else "starts" if starts else "ends"
        pronoun = "them" if starts and ends else "it"
        return f"Username {account} {position} with a space. Delete {pronoun}."
    if code == "test_dates_out_of_order":
        environment = _environment_label(result["environment"])
        return f"{environment} start date is after its end date. Change one of them."
    if code == "duplicate_component":
        scope = (report or {}).get("scope_text", {}).get(result["environment"], {}).get(result["app_type"], "")
        text = scope.get("component", "") if isinstance(scope, dict) else scope
        seen: dict[str, int] = {}
        first = row = 0
        for index, component in enumerate(text.split("\n") if isinstance(text, str) else [], start=1):
            component = component.strip()
            if component == result["component"]:
                if component in seen:
                    first, row = seen[component], index
                    break
                seen[component] = index
        message = f"Component {row} is the same as component {first}. Remove one of them."
        if scope_context:
            scope_label = f"{_environment_label(result['environment'])} {CHANNEL_LABELS[result['app_type']]} scope"
            return f"In the {scope_label}, {message}"
        return message
    if code == "too_long":
        field = result["field"]
        rule = CHARACTER_RULES.get(field)
        label = result.get("label") or (rule.label if rule else "Scope target")
        value = result.get("value")
        if field == "scope":
            scope = (report or {}).get("scope_text", {}).get(result["environment"], {}).get(result["app_type"], "")
            value = value if value is not None else scope.get("description", "") if result.get("box") == "description" and isinstance(scope, dict) else scope.get("component", "") if isinstance(scope, dict) else scope
            lines = value.split("\n") if isinstance(value, str) else []
            value = lines[result["line"]] if result["line"] < len(lines) else ""
            label = f"In the {_environment_label(result['environment'])} {CHANNEL_LABELS[result['app_type']]} scope, line {result['line'] + 1}" if scope_context else f"Line {result['line'] + 1}"
        elif field == "test_time" and value is None:
            value = (engagement.get("test_windows", {}).get(result["environment"], {}) or {}).get("test_time", "")
            label = f"{_environment_label(result['environment'])} time"
        elif "account" in result and value is None:
            accounts = engagement.get("test_accounts") or []
            account = accounts[result["account"] - 1] if result["account"] <= len(accounts) else {}
            value = account.get(field, "") if isinstance(account, dict) else ""
            label = f"{label} {result['account']}"
        elif value is None:
            value = engagement.get(field, "")
        count = len(value) if isinstance(value, str) else 0
        return f"{label} has {count} characters. Shorten it to {result['limit']} or fewer."
    if code == "invalid_characters":
        field = result.get("field")
        rule = CHARACTER_RULES.get(field) if field else None
        label = result.get("label") or (rule.label if rule else "Scope target")
        characters = result["characters"]
        engagement = (report or {}).get("engagement", {})
        value = result.get("value")
        if field == "scope" and value is None:
            environment = result["environment"]
            channel = result["app_type"]
            scope = (report or {}).get("scope_text", {}).get(environment, {}).get(channel, "")
            box_value = scope.get("description", "") if result.get("box") == "description" and isinstance(scope, dict) else scope.get("component", "") if isinstance(scope, dict) else scope
            lines = box_value.split("\n") if isinstance(box_value, str) else []
            value = lines[result["line"]] if result["line"] < len(lines) else ""
            label = f"In the {_environment_label(result['environment'])} {CHANNEL_LABELS[result['app_type']]} scope, line {result['line'] + 1}" if scope_context else f"Line {result['line'] + 1}"
        elif field == "test_time" and value is None:
            environment = _environment_label(result["environment"])
            value = (engagement.get("test_windows", {}).get(result["environment"], {}) or {}).get("test_time", "")
            label = f"{environment} time"
        elif "account" in result and value is None:
            accounts = engagement.get("test_accounts") or []
            account = accounts[result["account"] - 1] if result["account"] <= len(accounts) else {}
            value = account.get(field, "") if isinstance(account, dict) else ""
            label = f"{label} {result['account']}"
        elif value is None and field:
            value = engagement.get(field, "")
        if isinstance(value, str):
            for index, character in enumerate(value):
                if character in characters and ((unicodedata.category(character)[:1] in {"C", "Z"} and character != " ") or WORD_REFUSED_CHARACTERS.fullmatch(character)):
                    before = value[:index]
                    context = f'after "{"..." if len(before) > 12 else ""}{before[-12:]}"' if before else "at the start"
                    detail = {"\t": "a tab", "\n": "a line break", "\r": "a line break", "\u00a0": "a non-breaking space"}.get(character, "a hidden character")
                    return f"{label} has {detail} {context}. Delete it."
        if rule and characters == [" "] and not rule.spaces:
            count = value.count(" ") if isinstance(value, str) else 1
            instruction = "the spaces" if count > 1 else "the space"
            return f"{label} cannot have spaces. Remove {instruction}."
        if len(characters) == 1:
            return f'{label} cannot have {json.dumps(characters[0], ensure_ascii=False)}. Remove or replace it.'
        quoted = [json.dumps(character, ensure_ascii=False) for character in characters]
        return f'{label} cannot have {", ".join(quoted[:-1])} or {quoted[-1]}. Remove or replace them.'
    raise ValueError(f"Unknown rule message: {code}")


# Outside XML 1.0's Char production: python-docx refuses them, so generation would abort.
WORD_REFUSED_CHARACTERS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")
# In UTF-16 units.
SCOPE_LIMITS = {"line": 500, "component": 200, "description": 500}


@dataclass(frozen=True)
class CharacterRule:
    """What one free-text field may hold. app/vocabulary.py sends the same table to the browser."""

    label: str
    symbols: str
    letters: bool = True
    numbers: bool = True
    spaces: bool = True
    line_breaks: bool = False
    # In UTF-16 units, as the browser's maxlength counts; see text_length.
    max_length: int | None = None


ASCII_LETTERS_AND_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
MAX_TEST_ACCOUNTS = 50

CHARACTER_RULES: dict[str, CharacterRule] = {
    "app_name": CharacterRule("Application name", "-:;.()", max_length=100),
    "ci_number": CharacterRule("CI number", "-", spaces=False, max_length=30),
    "bsn_number": CharacterRule("BSN number", "-", spaces=False, max_length=30),
    "app_owner": CharacterRule("Application owner", "-'\u2019.", numbers=False, max_length=60),
    "tester": CharacterRule("Tester", "-'\u2019.", numbers=False, max_length=60),
    "test_time": CharacterRule("Time", ":/-", max_length=40),
    "user_role": CharacterRule("User role", "/-", max_length=60),
    "limitations": CharacterRule("Limitations", "/,.;:()&'\"-", line_breaks=True, max_length=2000),
    # A subset of Limitations, because the retest suggestion writes this name into that field.
    "non_production_label": CharacterRule("Non-Production name", "/-"),
    # No symbol at all: the GRIMPEN- prefix belongs to the document, not to the stored value.
    "severity_review_tickets": CharacterRule("Severity Review Tickets", "", letters=False, spaces=False, line_breaks=True),
    "cvss_score": CharacterRule("CVSS Score", ".", letters=False, spaces=False),
    "cvss_vector": CharacterRule("CVSS Vector", "./:", spaces=False),
    # ASCII only, so a letter such as é is named rather than reported as a bad first or last character.
    "username": CharacterRule("Username", f"{ASCII_LETTERS_AND_DIGITS}._@\\-", letters=False, numbers=False, max_length=100),
}


def text_length(value: str) -> int:
    """Length in UTF-16 units, as HTML maxlength and JavaScript's length count. Twin: value.length in rules.js."""
    return len(value.encode("utf-16-le", "surrogatepass")) // 2


def _rule_characters(field: str, value: str) -> list[str]:
    rule = CHARACTER_RULES[field]
    return _invalid_characters(value, rule.symbols, allow_letters=rule.letters, allow_numbers=rule.numbers, allow_spaces=rule.spaces, allow_line_breaks=rule.line_breaks)


def character_issue(field: str, value: str, label: str | None = None) -> str | None:
    """Check a value against its field's rule. `label` names a numbered or per-environment copy."""
    rule = CHARACTER_RULES[field]
    return invalid_character_issue(
        label or rule.label,
        value,
        rule.symbols,
        field=field,
        allow_letters=rule.letters,
        allow_numbers=rule.numbers,
        allow_spaces=rule.spaces,
        allow_line_breaks=rule.line_breaks,
    )


def setup_field_refusals(engagement: dict) -> list[dict]:
    """The Setup values a save refuses, in field order, for an engagement in the browser's shape. Twin: fieldRefusals in rules.js."""
    results: list[dict] = []

    def refuse(code: str, **context) -> None:
        results.append({"kind": "refusal", "code": code, **context})

    def check(field: str, value, **context) -> None:
        if not isinstance(value, str) or not value:
            return
        if characters := _rule_characters(field, value):
            refuse("invalid_characters", field=field, **context, characters=characters)
        limit = CHARACTER_RULES[field].max_length
        if limit is not None and text_length(value) > limit:
            refuse("too_long", field=field, **context, limit=limit)

    for field in ("app_name", "ci_number", "bsn_number", "app_owner", "tester"):
        check(field, engagement.get(field))
    environments = engagement.get("tested_environments") or []
    windows = engagement.get("test_windows")
    windows = windows if isinstance(windows, dict) else {}
    for environment in environments:
        window = windows.get(environment)
        if not isinstance(window, dict):
            continue
        start, end = window.get("start_date"), window.get("end_date")
        if isinstance(start, str) and isinstance(end, str) and start and end and start > end:
            refuse("test_dates_out_of_order", environment=environment)
        check("test_time", window.get("test_time"), environment=environment)
    test_accounts = engagement.get("test_accounts") or []
    if len(test_accounts) > MAX_TEST_ACCOUNTS:
        refuse("too_many_accounts", limit=MAX_TEST_ACCOUNTS)
    for number, account in enumerate(test_accounts, start=1):
        if not isinstance(account, dict):
            continue
        check("user_role", account.get("user_role"), account=number)
        username = account.get("username")
        if not isinstance(username, str) or not username or username == "N/A":
            continue
        if not USERNAME_PATTERN.fullmatch(username):
            if characters := _rule_characters("username", username):
                refuse("invalid_characters", field="username", account=number, characters=characters)
            else:
                refuse("invalid_username", account=number)
        if text_length(username) > (limit := CHARACTER_RULES["username"].max_length):
            refuse("too_long", field="username", account=number, limit=limit)
    check("limitations", engagement.get("limitations"))
    # A disabled input is exempt from browser validation, so an unticked Non-Production goes unchecked.
    if "non_production" in environments:
        label = engagement.get("non_production_label")
        # Stripped as the model's strip_label does.
        check("non_production_label", label.strip() if isinstance(label, str) else label)
    return results


def _environment_label(environment: str) -> str:
    return "Production" if environment == "production" else "Non-Production"


def setup_refusal_message(result: dict, report: dict | None = None) -> str:
    """Format a coded Setup refusal for the tester."""
    scope_context = result.get("field") == "scope" or result.get("code") == "duplicate_component"
    return format_rule_message(result, report, scope_context=scope_context)


def _refused_value(engagement: dict, result: dict):
    """The value a Setup field refusal is about, so a value the stored report already held can be told apart."""
    windows = engagement.get("test_windows")
    window = windows.get(result["environment"]) if isinstance(windows, dict) and "environment" in result else None
    window = window if isinstance(window, dict) else {}
    accounts = engagement.get("test_accounts") or []
    if result["code"] == "test_dates_out_of_order":
        return (window.get("start_date"), window.get("end_date"))
    if result["code"] == "too_many_accounts":
        return len(accounts)
    # invalid_username is the one account result that names no field.
    field = result.get("field", "username")
    if field == "test_time":
        return window.get("test_time")
    if "account" in result:
        row = accounts[result["account"] - 1] if result["account"] <= len(accounts) else None
        return row.get(field) if isinstance(row, dict) else None
    return engagement.get(field)


def _already_stored(result: dict, engagement: dict, prior: dict) -> bool:
    value = _refused_value(engagement, result)
    if result["code"] == "too_many_accounts":
        return value <= _refused_value(prior, result)
    # Any row, so removing or reordering accounts does not turn an old value into a new one.
    if "account" in result:
        field = result.get("field", "username")
        return any(isinstance(row, dict) and row.get(field) == value for row in prior.get("test_accounts") or [])
    return value == _refused_value(prior, result)


def setup_input_issues(engagement: Engagement, prior: Engagement | None = None) -> list[str]:
    """Return invalid Setup values without treating blank draft fields as errors.

    With `prior`, only values that differ from it: a stored value that breaks a rule, such as one an
    import brought in, stays savable and is reported by setup_issues instead."""
    current = engagement.model_dump(mode="json")
    results = setup_field_refusals(current)
    if prior is not None:
        before = prior.model_dump(mode="json")
        results = [result for result in results if not _already_stored(result, current, before)]
    context = {"engagement": current}
    return [setup_refusal_message(result, context) for result in results]


def finding_input_issues(report: Report) -> list[str]:
    """Return invalid Additional Information values without treating blank draft fields as errors."""
    # Deliberately ungated by whether the field is on screen. A value stays valid while hidden, so a
    # report moving off Asia and back cannot strand a draft that no longer saves.
    issues = []
    for finding in report.vulnerabilities:
        for field in ("severity_review_tickets", "cvss_score", "cvss_vector"):
            value = getattr(finding, field)
            if value and (issue := character_issue(field, value)):
                issues.append(issue)
    return issues


def report_export_filename(report: Report, suffix: str = ".zip") -> str:
    """Build a portable report filename from the required Setup metadata."""
    engagement = report.engagement

    def component(value: str | None, fallback: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
        cleaned = re.sub(r"\s+", " ", INVALID_FILENAME_CHARACTERS.sub("", ascii_value)).strip(" .")
        return cleaned[:100] or fallback

    segment = component(engagement.segment, "Unassigned")
    application = component(engagement.app_name, "Untitled Application")
    report_type = component(REPORT_TYPE_LABELS.get(engagement.report_type or ""), "Report")
    year = (engagement.report_date or datetime.now().astimezone().date()).year
    return f"{segment} - {application} - {report_type} {year}{suffix}"


def ensure_proof_steps(content: Content) -> None:
    """Single owner of the rule: steps are the substance of a proof of concept, so one numbered list
    survives a deletion, a status change, and a library replacement that carried none."""
    if not any(fragment.type == "numbered_list" for fragment in content.fragments):
        content.fragments.insert(0, ListFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="numbered_list", items=[ListItem(runs=[])]))


def content_types_for_status(status: str) -> list[str]:
    """Single owner of which sections a finding's status puts in the document."""
    if status == "open_new":
        return ["description", "recommended_remediation", "proof_of_concept"]
    return ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"]


def content_has_work(content: Content) -> bool:
    """Whether a section holds anything a tester would be sorry to lose.

    Boilerplate this app wrote itself does not count: it is regenerated on demand, so treating it as
    work would mean every finding looks like it has something to lose."""
    for fragment in content.fragments:
        if isinstance(fragment, ParagraphFragment) and (fragment.generated or is_default_status_conclusion(fragment)):
            continue
        if any(run.text.strip() for run in getattr(fragment, "runs", [])):
            return True
        if any(run.text.strip() for item in getattr(fragment, "items", []) for run in item.runs):
            return True
        if getattr(fragment, "text", "").strip() or getattr(fragment, "caption", None) and fragment.caption.strip():
            return True
        if getattr(fragment, "evidence_id", None):
            return True
        if isinstance(fragment, TableFragment) and any(
            run.text.strip() for cell in [*fragment.header, *(cell for row in fragment.rows for cell in row)] for run in cell.runs
        ):
            return True
    return False


def provision(vulnerability: Vulnerability) -> None:
    """Create the status-required content blocks and starter fragments for a finding."""
    types = content_types_for_status(vulnerability.status)
    existing = {content.type: content for content in vulnerability.contents}
    # A status change must not destroy work. A section this status does not print is kept when it
    # still holds something written, so changing status and back brings the tester's work with it.
    # in_conclusion is the exception: it is a statement about the status, so carrying it would keep a
    # sentence the status has just made false. It is dropped, and offered back fresh on the way in.
    carried = [content for content in vulnerability.contents if content.type not in types and content.type != "in_conclusion" and content_has_work(content)]
    vulnerability.contents = [existing.get(content_type, Content(type=content_type)) for content_type in types] + carried
    required_fragments = {
        "description": ["paragraph"],
        "recommended_remediation": ["paragraph"],
        "previous_proof_of_concept": ["numbered_list", "image"],
        "proof_of_concept": ["numbered_list", "image"],
        "in_conclusion": [],
    }
    for content in vulnerability.contents:
        if content.fragments or content.type not in required_fragments:
            continue
        for fragment_type in required_fragments[content.type]:
            if fragment_type == "paragraph":
                fragment = ParagraphFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="paragraph", runs=[])
            elif fragment_type == "numbered_list":
                fragment = ListFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="numbered_list", items=[ListItem(runs=[])])
            else:
                fragment = ImageFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="image", evidence_id=None, caption="", width_mm=None)
            content.fragments.append(fragment)
    for content in vulnerability.contents:
        if content.type.endswith("proof_of_concept"):
            ensure_proof_steps(content)
    remediation = next(content for content in vulnerability.contents if content.type == "recommended_remediation")
    if vulnerability.status == "resolved":
        remediation.fragments = [ParagraphFragment(
            frag_id=f"f_{uuid.uuid4().hex[:8]}",
            type="paragraph",
            runs=[Run(text=RESOLVED_REMEDIATION)],
            generated="resolved_remediation",
        )]
    else:
        # Reopening a finding leaves boilerplate describing a remediation that no longer happened.
        kept = [fragment for fragment in remediation.fragments if getattr(fragment, "generated", None) != "resolved_remediation"]
        remediation.fragments = kept or [ParagraphFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="paragraph", runs=[])]
    conclusion = next((content for content in vulnerability.contents if content.type == "in_conclusion"), None)
    if conclusion is not None:
        status = status_conclusion_word(vulnerability.status)
        paragraphs = [fragment for fragment in conclusion.fragments if isinstance(fragment, ParagraphFragment)]
        generated = next((fragment for fragment in paragraphs if fragment.generated == "status_conclusion"), None)
        # Deliberately no "first paragraph with no text" arm: a paragraph the tester emptied is theirs.
        # Refilling it wrote boilerplate above a conclusion they had just written, and the client twin
        # runs on editor boot, so it came back on a page load. The Content page offers it back instead.
        spans = {id(fragment): default_conclusion_span("".join(run.text for run in fragment.runs)) for fragment in paragraphs}
        # The regex alone decides: the marker outlives the text and overwrote written conclusions.
        default = next((fragment for fragment in paragraphs if spans[id(fragment)] is not None), None)
        if not paragraphs:
            # Created empty, never filled. The app offers the sentence on the Content page instead:
            # a conclusion the app wrote for you is not a conclusion, and the tester owes a real one.
            conclusion.fragments.insert(0, ParagraphFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="paragraph", runs=[]))
        elif default is not None:
            default.generated = None
            # Only the sentence is re-derived; text around it belongs to the tester and keeps its runs.
            span = spans[id(default)]
            before = _runs_up_to(default.runs, span[0])
            after = _runs_after(default.runs, span[1])
            default.runs = before + status_conclusion_runs(vulnerability.title, status) + after
        if generated is not None:
            conclusion.fragments = [
                fragment for fragment in conclusion.fragments
                if fragment is generated or not isinstance(fragment, ParagraphFragment) or _fragment_has_text(fragment)
            ]


def location_lines(values) -> list[str]:
    """Single owner of which typed lines in an "additional affected locations" box name a real place.

    Same cleaning the scope textarea gets in reconcile_targets: blanks are nothing, a "#" line is a
    note to the tester, and a repeat is the same place said twice. The raw text stays in the draft
    so the note survives an edit; it just never counts as a location or reaches the document."""
    cleaned: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if not text or text.startswith("#") or text in cleaned:
            continue
        cleaned.append(text)
    return cleaned


def affected_environments(vulnerability: Vulnerability, report: Report) -> list[Environment]:
    """Resolve the environments represented by a finding's selected or custom locations."""
    ordered: list[Environment] = []
    target_by_id = {target.target_id: target for target in report.scope_targets}

    def add(environment: Environment) -> None:
        if environment not in ordered:
            ordered.append(environment)

    for target_id in vulnerability.scope.target_ids:
        target = target_by_id.get(target_id)
        if target:
            add(target.environment)
    for environment, by_channel in vulnerability.scope.custom_locations.items():
        # A line typed under coverage the engagement has since dropped is out of scope, whatever it says.
        if environment not in report.engagement.tested_environments:
            continue
        if any(location_lines(locations) for channel, locations in by_channel.items() if channel in report.engagement.tested_channels):
            add(environment)
    return ordered


def affected_channels(vulnerability: Vulnerability, report: Report) -> list[Channel]:
    """Resolve the app types a finding actually touches, mirroring affected_environments branch for branch."""
    ordered: list[Channel] = []
    target_by_id = {target.target_id: target for target in report.scope_targets}

    def add(channel: Channel) -> None:
        if channel not in ordered:
            ordered.append(channel)

    for target_id in vulnerability.scope.target_ids:
        target = target_by_id.get(target_id)
        if target:
            add(target.channel)
    for environment, by_channel in vulnerability.scope.custom_locations.items():
        if environment not in report.engagement.tested_environments:
            continue
        for channel, locations in by_channel.items():
            if channel in report.engagement.tested_channels and location_lines(locations):
                add(channel)
    return ordered


def applicable_poc_variants(vulnerability: Vulnerability, report: Report, available) -> list[Channel]:
    """The app types a finding touches that the library entry actually carries steps for."""
    channels = set(affected_channels(vulnerability, report))
    return [channel for channel in CHANNELS if channel in channels and channel in (available or {})]


def fragment_applies(fragment, vulnerability: Vulnerability, report: Report, content_type: str) -> bool:
    """Single owner of whether a fragment belongs in the report: what prints, and what generation
    checks. An image prints when its environment is tested, so a supporting image does and an
    untested-environment image does not. A supporting slot nobody has touched is left out rather
    than demanded. Previous proof of concept always applies: it records an earlier engagement."""
    if content_type == "previous_proof_of_concept":
        return True
    environment = getattr(fragment, "environment", None)
    if not environment:
        return True
    if environment not in report.engagement.tested_environments:
        return False
    return environment in affected_environments(vulnerability, report) or bool(fragment.evidence_id or fragment.caption.strip())


def _covered_environments(content: Content | None) -> set[Environment]:
    """Environments already represented by an image inside one content block."""
    if content is None:
        return set()
    return {fragment.environment for fragment in content.fragments if isinstance(fragment, ImageFragment) and fragment.environment}


def sync_evidence_image_slots(vulnerability: Vulnerability, report: Report) -> None:
    """Ensure each affected environment has an image slot while preserving extra images.

    Coverage is a property of the proof of concept alone: a carried previous-PoC image is history,
    not this retest's evidence, so it neither suppresses a slot nor gets relabelled here."""
    environments = affected_environments(vulnerability, report)
    # Only an untested environment's empty slot goes: a tested one may be a supporting image the
    # tester has not uploaded yet. An uploaded screenshot is never removed or relabelled here.
    for content in vulnerability.contents:
        if content.type == "previous_proof_of_concept":
            continue
        content.fragments = [
            fragment
            for fragment in content.fragments
            if not (
                isinstance(fragment, ImageFragment)
                and fragment.environment
                and fragment.environment not in report.engagement.tested_environments
                and not fragment.evidence_id
                and not fragment.caption.strip()
            )
        ]
    proof = next((content for content in vulnerability.contents if content.type == "proof_of_concept"), None)
    images = [
        fragment
        for content in vulnerability.contents
        if content.type != "previous_proof_of_concept"
        for fragment in content.fragments
        if isinstance(fragment, ImageFragment)
    ]
    missing = [environment for environment in environments if environment not in _covered_environments(proof)]
    for image in (image for image in images if image.environment is None):
        if missing:
            image.environment = missing.pop(0)
        elif environments:
            image.environment = environments[0]
    missing = [environment for environment in environments if environment not in _covered_environments(proof)]
    if proof is None:
        return
    for environment in missing:
        proof.fragments.append(ImageFragment(
            frag_id=f"f_{uuid.uuid4().hex[:8]}",
            type="image",
            environment=environment,
            evidence_id=None,
            caption="",
            width_mm=None,
        ))
    # A carried previous-PoC slot still needs an environment to render under, even though it never
    # counts as this engagement's coverage. Provisioning creates it blank, so nothing else would.
    previous = next((content for content in vulnerability.contents if content.type == "previous_proof_of_concept"), None)
    for fragment in previous.fragments if previous else []:
        if isinstance(fragment, ImageFragment) and fragment.environment is None and environments:
            fragment.environment = environments[0]


def _fragment_has_text(fragment: ParagraphFragment) -> bool:
    return any(run.text.strip() for run in fragment.runs)


STATUS_CONCLUSION_PATTERN = re.compile(r'The finding ".*" is(?: still| now)? (?:Open|Resolved|CLOSED)\.', re.DOTALL)


def status_conclusion_word(status: str) -> str:
    """Twin of statusConclusionWord in app.js. CLOSED is upper case deliberately; the patterns are
    case-sensitive, so tidying it to title case freezes every sentence already on disk."""
    return {"resolved": "Resolved", "closed": "CLOSED"}.get(status, "Open")


def status_conclusion_runs(title: str, status_word: str) -> list[Run]:
    """Single owner of the default conclusion sentence. Paired with STATUS_CONCLUSION_PATTERN, which
    must keep matching whatever this builds: relax one and every default on disk freezes at the title
    and status it was stored with, because nothing recognises it as the app's own sentence any more."""
    lead = {"Open": "is still ", "CLOSED": "is now "}.get(status_word, "is ")
    return [
        Run(text=f'The finding "{title}" {lead}'),
        Run(text=status_word, bold=True),
        Run(text="."),
    ]


def default_conclusion_span(text: str) -> tuple[int, int] | None:
    """Return the app-owned sentence's bounds when it remains in the paragraph.

    Scanning right to left and testing a full match at each marker keeps one regex honest for
    titles that themselves contain a quotation mark."""
    stripped = text.rstrip()
    marker = 'The finding "'
    index = stripped.rfind(marker)
    while index != -1:
        match = STATUS_CONCLUSION_PATTERN.match(stripped, index)
        if match:
            return match.span()
        index = stripped.rfind(marker, 0, index)
    return None


def is_default_status_conclusion(fragment: ParagraphFragment) -> bool:
    """Whether the paragraph is nothing but the app's sentence, with no tester text in front."""
    text = "".join(run.text for run in fragment.runs)
    span = default_conclusion_span(text)
    return span is not None and span == (0, len(text.rstrip()))


def _runs_up_to(runs: list[Run], offset: int) -> list[Run]:
    """The runs covering the first `offset` characters, splitting the run that straddles the cut."""
    kept: list[Run] = []
    seen = 0
    for run in runs:
        if seen >= offset:
            break
        take = min(len(run.text), offset - seen)
        if take:
            kept.append(run.model_copy(update={"text": run.text[:take]}))
        seen += len(run.text)
    return kept


def _runs_after(runs: list[Run], offset: int) -> list[Run]:
    """The runs after `offset`, splitting the run that straddles the cut."""
    kept: list[Run] = []
    seen = 0
    for run in runs:
        start = max(0, offset - seen)
        if start < len(run.text):
            kept.append(run.model_copy(update={"text": run.text[start:]}))
        seen += len(run.text)
    return kept


def assign_fresh_fragment_ids(vulnerability: Vulnerability) -> None:
    """Give copied library fragments report-local identifiers."""
    for content in vulnerability.contents:
        for fragment in content.fragments:
            fragment.frag_id = f"f_{uuid.uuid4().hex[:8]}"


def merge_step_lists(fragments: list) -> list:
    """Collapse consecutive step lists without moving them across intervening content."""
    merged = []
    for fragment in fragments:
        previous = merged[-1] if merged else None
        if isinstance(fragment, ListFragment) and fragment.type == "numbered_list" and isinstance(previous, ListFragment) and previous.type == "numbered_list":
            items = [*previous.items, *fragment.items]
            written = [item for item in items if any(run.text.strip() for run in item.runs)]
            previous.items = written or items[:1]
        else:
            merged.append(fragment)
    return merged


def apply_poc_variant(vulnerability: Vulnerability, fragments: list, variants: list, mode: Literal["replace", "merge"] = "replace") -> None:
    """Install the proof-of-concept steps for one or more app types, keeping uploaded images intact.

    "replace" overwrites the non-image fragments; "merge" appends the library's steps after what
    is already there. Either way, every copied fragment gets a fresh id."""
    proof = next((content for content in vulnerability.contents if content.type == "proof_of_concept"), None)
    if proof is None:
        return
    images = [fragment for fragment in proof.fragments if isinstance(fragment, ImageFragment)]
    kept = [fragment for fragment in proof.fragments if not isinstance(fragment, ImageFragment)] if mode == "merge" else []
    copied = [fragment.model_copy(deep=True) for fragment in fragments]
    for fragment in copied:
        fragment.frag_id = f"f_{uuid.uuid4().hex[:8]}"
    proof.fragments = merge_step_lists(kept + copied) + images
    ensure_proof_steps(proof)
    for variant in variants:
        if variant not in vulnerability.poc_variants:
            vulnerability.poc_variants.append(variant)
    # A refusal is per app type, so installing one must not clear the others.
    vulnerability.poc_variant_declined = [channel for channel in vulnerability.poc_variant_declined if channel not in variants]


def _scope_reaches_a_location(scope: dict, targets: list[dict]) -> bool:
    """Answer scope_has_location for a raw payload scope against a raw target list.

    Runs before the migration on the save path, so a payload still carrying a retired mode is read
    as custom: with IDs present that answers identically, and with none it reports no location,
    which lets the save through for the migration to resolve rather than refusing it."""
    if set(scope.get("target_ids") or []) & {target["target_id"] for target in targets}:
        return True
    return any(location_lines(values) for by_channel in (scope.get("custom_locations") or {}).values() for values in (by_channel or {}).values())


def scope_text_from_targets(targets) -> dict:
    """Serialize stored targets into the request-only shape Setup builds on page load."""
    result = {}
    for environment in ("production", "non_production"):
        result[environment] = {}
        for channel in CHANNELS:
            selected = sorted(
                (target for target in targets if target.environment == environment and target.channel == channel),
                key=lambda target: target.order,
            )
            values = "\n".join(target.value for target in selected)
            result[environment][channel] = (
                {"component": values, "description": "\n".join(target.description for target in selected)}
                if channel in COMPONENT_CHANNELS else values
            )
    return result


def _scope_entry_refusals(environment: str, channel: str, box: str, line: int, text: str, limit: int) -> list[dict]:
    context = {"field": "scope", "environment": environment, "app_type": channel, "box": box, "line": line}
    results = []
    if characters := list(dict.fromkeys(WORD_REFUSED_CHARACTERS.findall(text))):
        results.append({"kind": "refusal", "code": "invalid_characters", **context, "characters": characters})
    if text_length(text) > limit:
        results.append({"kind": "refusal", "code": "too_long", **context, "limit": limit})
    return results


def scope_value_refusals(environment: str, channel: str, line: int, value: str, description: str) -> list[dict]:
    """What one scope line or component row is refused for. Twin: scopeValueRefusals in rules.js."""
    if channel not in COMPONENT_CHANNELS:
        return _scope_entry_refusals(environment, channel, "component", line, value, SCOPE_LIMITS["line"])
    return [
        *_scope_entry_refusals(environment, channel, "component", line, value, SCOPE_LIMITS["component"]),
        *_scope_entry_refusals(environment, channel, "description", line, description, SCOPE_LIMITS["description"]),
    ]


def scope_box_refusals(environment: str, channel: str, component_text: str, description_text: str) -> list[dict]:
    """Every refusal one scope box earns, in the order reconcile_targets raises them. Twin: scopeBoxRefusals in rules.js."""
    # Paired by raw index before cleaning, so a blank or # line cannot shift the descriptions below it.
    named = [
        (line, value.strip(), description.strip())
        for line, (value, description) in enumerate(zip_longest(component_text.split("\n"), description_text.split("\n"), fillvalue=""))
        if value.strip() and not value.strip().startswith("#")
    ]
    results: list[dict] = []
    # Web and API drop a repeated line; a repeated component would lose its description, so it is refused.
    if channel in COMPONENT_CHANNELS:
        seen: set[str] = set()
        repeated: list[str] = []
        for _, value, _ in named:
            if value in seen and value not in repeated:
                repeated.append(value)
            seen.add(value)
        results += [{"kind": "refusal", "code": "duplicate_component", "environment": environment, "app_type": channel, "component": value} for value in repeated]
    for line, value, description in named:
        results += scope_value_refusals(environment, channel, line, value, description)
    return results


def _stored_scope_refusal(result: dict, component_lines: list[str], description_lines: list[str], stored: dict[str, str]) -> bool:
    """Whether a box refusal is about a line the stored report already held, word for word."""
    if result["code"] == "duplicate_component":
        return False
    line = result["line"]
    value = component_lines[line].strip() if line < len(component_lines) else ""
    if value not in stored:
        return False
    if result["box"] == "component":
        return True
    return stored[value] == (description_lines[line].strip() if line < len(description_lines) else "")


def changed_target_refusals(targets: list[ScopeTarget], prior: list[ScopeTarget]) -> list[dict]:
    """Refusals for the targets a save without scope text changed, which the Setup checks never saw."""
    stored = {(target.environment, target.channel, target.value): target.description for target in prior}
    return [
        refusal
        for target in targets
        for refusal in scope_value_refusals(target.environment, target.channel, target.order, target.value, target.description)
        if (key := (target.environment, target.channel, target.value)) not in stored
        or (refusal["box"] == "description" and stored[key] != target.description)
    ]


def reconcile_targets(payload: dict, prior: Report) -> list[str] | None:
    """Turn setup textarea values into stable scope targets and identify unsafe removals."""
    if "scope_text" not in payload:
        return None
    submitted = payload.pop("scope_text")
    engagement = payload.get("engagement", {})
    if not isinstance(submitted, dict) or not isinstance(engagement, dict):
        raise ValueError("scope_text and engagement must be objects")
    environments = engagement.get("tested_environments", ["production", "non_production"])
    if not isinstance(environments, list):
        raise ValueError("tested_environments must be a list")
    channels = resolve_tested_channels(payload)
    if not channels:
        raise ValueError(setup_refusal_message({"code": "no_app_type"}))
    # Written back for the same reason scope_targets is: this function replaces the target list, so a
    # later derive-from-targets would otherwise read the new one and resolve differently.
    payload["engagement"] = {key: value for key, value in engagement.items() if key != "test_type"}
    payload["engagement"]["tested_channels"] = channels

    old = {(target.environment, target.channel, target.value): target.target_id for target in prior.scope_targets}
    targets = []
    for environment in environments:
        environment_values = submitted.get(environment, {})
        if not isinstance(environment_values, dict):
            raise ValueError("scope environment values must be objects")
        for channel in channels:
            raw_values = environment_values.get(channel, "")
            # A component channel submits {component, description}; every channel still accepts the
            # plain string, so a browser cached from before this shape existed degrades rather than 422s.
            if isinstance(raw_values, str):
                component_text, description_text = raw_values, ""
            elif isinstance(raw_values, dict):
                component_text = raw_values.get("component", "")
                description_text = raw_values.get("description", "")
            else:
                raise ValueError("scope target values must be text")
            component_text = "" if component_text is None else component_text
            description_text = "" if description_text is None else description_text
            if not isinstance(component_text, str) or not isinstance(description_text, str):
                raise ValueError("scope target values must be text")
            stored = {target.value: target.description for target in prior.scope_targets if target.environment == environment and target.channel == channel}
            component_lines, description_lines = component_text.split("\n"), description_text.split("\n")
            if refusals := [
                result for result in scope_box_refusals(environment, channel, component_text, description_text)
                if not _stored_scope_refusal(result, component_lines, description_lines, stored)
            ]:
                context = {"engagement": engagement, "scope_text": submitted}
                raise ValueError(setup_refusal_message(refusals[0], context))
            # Paired by raw index before cleaning, as scope_box_refusals does.
            cleaned: list[tuple[str, str]] = []
            seen: set[str] = set()
            for value, description in zip_longest(component_text.split("\n"), description_text.split("\n"), fillvalue=""):
                value, description = value.strip(), description.strip()
                # Target IDs are reused by value, so a repeated line would claim the same ID twice.
                if not value or value.startswith("#") or value in seen:
                    continue
                seen.add(value)
                cleaned.append((value, description))
            for order, (value, description) in enumerate(cleaned):
                targets.append({"target_id": old.get((environment, channel, value), f"tgt_{uuid.uuid4().hex[:8]}"), "environment": environment, "channel": channel, "value": value, "description": description, "order": order})
    payload["scope_targets"] = targets
    target_ids = {target["target_id"] for target in targets}
    prior_targets = [target.model_dump(mode="json") for target in prior.scope_targets]
    removed_references = []
    vulnerabilities = payload.get("vulnerabilities", [])
    if not isinstance(vulnerabilities, list):
        raise ValueError("vulnerabilities must be a list")
    for vulnerability in vulnerabilities:
        if not isinstance(vulnerability, dict):
            raise ValueError("each vulnerability must be an object")
        scope = vulnerability.get("scope", {})
        if not isinstance(scope, dict):
            raise ValueError("finding scope must be an object")
        reached_before = _scope_reaches_a_location(scope, prior_targets)
        # A typed location outside the tested surface is no longer reachable, so it must not keep
        # the finding looking complete or make it resolve to an app type the engagement dropped.
        custom = scope.get("custom_locations")
        if isinstance(custom, dict):
            scope["custom_locations"] = {
                environment: {channel: values for channel, values in (by_channel or {}).items() if channel in channels}
                for environment, by_channel in custom.items()
                if environment in environments and isinstance(by_channel, dict)
            }
            scope["custom_locations"] = {key: value for key, value in scope["custom_locations"].items() if value}
        title = vulnerability.get("title") or "Untitled finding"
        # A removed target is dropped, not refused. The browser purges the same IDs after its own
        # prompt, so refusing here would block a save the tester was told was safe; and leaving them
        # would fail validate_references with a raw error blob instead of this named one.
        submitted_ids = scope.get("target_ids") or []
        kept_ids = [target_id for target_id in submitted_ids if target_id in target_ids]
        if len(kept_ids) != len(submitted_ids):
            scope["target_ids"] = kept_ids
            location_values = scope.get("location_values")
            if isinstance(location_values, dict):
                scope["location_values"] = {key: value for key, value in location_values.items() if key in target_ids}
        # Losing every location is the only unsafe outcome left, and it reads the same for a finding
        # that held target IDs and one located only by typed-in endpoints.
        if reached_before and not _scope_reaches_a_location(scope, targets):
            removed_references.append(title)
    return removed_references


def _scope_box_text(by_channel, channel: str) -> tuple[str, str]:
    """A scope box's component and description text, reading anything that is not text as blank."""
    raw = by_channel.get(channel) if isinstance(by_channel, dict) else None
    component_text = raw if isinstance(raw, str) else raw.get("component") if isinstance(raw, dict) else ""
    description_text = raw.get("description") if isinstance(raw, dict) else ""
    return (
        component_text if isinstance(component_text, str) else "",
        description_text if isinstance(description_text, str) else "",
    )


def scope_text_targets(report: dict) -> list[dict]:
    """The targets scope_text names in tested environments and covered app types. Twin: scopeTargets in rules.js."""
    engagement = report.get("engagement") or {}
    scope_text = report.get("scope_text") or {}
    covered = engagement.get("tested_channels") or []
    targets = []
    for environment in engagement.get("tested_environments") or []:
        by_channel = scope_text.get(environment) or {}
        for channel in (channel for channel in CHANNELS if channel in covered):
            component_text, description_text = _scope_box_text(by_channel, channel)
            seen: set[str] = set()
            # Paired by raw index before cleaning, as reconcile_targets does.
            for value, description in zip_longest(component_text.split("\n"), description_text.split("\n"), fillvalue=""):
                value, description = value.strip(), description.strip()
                if not value or value.startswith("#") or value in seen:
                    continue
                seen.add(value)
                targets.append({"environment": environment, "app_type": channel, "component": value, "description": description})
    return targets


def scope_text_refusals(report: dict) -> list[dict]:
    """Every refusal a save of this scope text would get, in reconcile_targets' order. Twin: scopeRefusals in rules.js."""
    engagement = report.get("engagement") or {}
    covered = engagement.get("tested_channels") or []
    if not covered:
        return [{"kind": "refusal", "code": "no_app_type"}]
    scope_text = report.get("scope_text") or {}
    results: list[dict] = []
    for environment in engagement.get("tested_environments") or []:
        by_channel = scope_text.get(environment) or {}
        for channel in (channel for channel in CHANNELS if channel in covered):
            results += scope_box_refusals(environment, channel, *_scope_box_text(by_channel, channel))
    return results


def setup_results(report: dict) -> list[dict]:
    """Ordered Setup results for a report in the browser's shape. Twin: setupResults in rules.js."""
    engagement = report.get("engagement") or {}
    results: list[dict] = [*scope_text_refusals(report), *setup_field_refusals(engagement)]

    def issue(code: str, **context) -> None:
        results.append({"kind": "issue", "code": code, **context})

    if not (engagement.get("app_name") or "").strip():
        issue("missing_app_name")
    if not engagement.get("segment"):
        issue("missing_segment")
    if not engagement.get("report_type"):
        issue("missing_report_type")
    if not engagement.get("network"):
        issue("missing_network")
    if not (engagement.get("tester") or "").strip():
        issue("missing_tester")
    if not engagement.get("report_date"):
        issue("missing_report_date")
    environments = engagement.get("tested_environments") or []
    if not environments:
        issue("no_tested_environment")
    # The only home for the mutual-exclusion rule. Raising in validate_coverage or
    # resolve_tested_channels would demote the draft on load, where nothing can repair it; an issue
    # line bounces the tester to Setup, the one page holding both checkboxes.
    covered_components = [channel for channel in COMPONENT_CHANNELS if channel in (engagement.get("tested_channels") or [])]
    if len(covered_components) > 1:
        issue("mobile_and_thick_client", app_types=covered_components)
    windows = engagement.get("test_windows") or {}
    targets = scope_text_targets(report)
    for environment in environments:
        test_window = windows.get(environment) or {}
        if not test_window.get("start_date") or not test_window.get("end_date"):
            issue("missing_test_dates", environment=environment)
        named = [target for target in targets if target["environment"] == environment]
        if not named:
            issue("missing_scope_target", environment=environment)
        # Named per component rather than counted: among ten rows a tally cannot say which one.
        for target in named:
            if target["app_type"] in COMPONENT_CHANNELS and not target["description"]:
                issue("missing_component_description", environment=environment, app_type=target["app_type"], component=target["component"])
    # A blank row is a leftover from Add and is left out of the document; N/A counts as filled.
    first_row: dict[tuple[str, str], int] = {}
    for number, account in enumerate(engagement.get("test_accounts") or [], start=1):
        if not isinstance(account, dict):
            continue
        role, username = (value.strip() if isinstance(value, str) else "" for value in (account.get("user_role"), account.get("username")))
        if not role and not username:
            continue
        if not username:
            issue("incomplete_test_account", account=number, missing="username")
        elif not role:
            issue("incomplete_test_account", account=number, missing="user_role")
        elif (role, username) in first_row:
            issue("repeated_test_account", account=number, first=first_row[(role, username)])
        else:
            first_row[(role, username)] = number
    return results


def setup_issues(report: Report) -> list[str]:
    """Return the missing engagement details that block Findings entry."""
    engagement = report.engagement
    results = setup_results({"engagement": engagement.model_dump(mode="json"), "scope_text": scope_text_from_targets(report.scope_targets)})
    context = {"engagement": engagement.model_dump(mode="json"), "scope_text": scope_text_from_targets(report.scope_targets)}
    return [format_rule_message(result, context, scope_context=result.get("field") == "scope" or result.get("code") == "duplicate_component") for result in results]


def setup_is_complete(report: Report) -> bool:
    """Return whether a report meets the canonical Findings entry requirements."""
    return not setup_issues(report)


def scope_has_location(vulnerability: Vulnerability, report: Report) -> bool:
    """Return whether a finding claims any location at all.

    Selected targets are a presence check: whether the IDs still exist is left to
    Report.validate_references and to reconcile_targets' survivor filter. A typed line is held to
    more than that, because nothing else ever revisits it -- it counts only while the engagement
    still covers the environment and app type it was typed under, so a finding cannot pass the
    Content gate on a location the report does not test."""
    scope = vulnerability.scope
    if scope.target_ids:
        return True
    return any(
        location_lines(locations)
        for environment, by_channel in scope.custom_locations.items()
        if environment in report.engagement.tested_environments
        for channel, locations in by_channel.items()
        if channel in report.engagement.tested_channels
    )


def finding_is_complete(vulnerability: Vulnerability, report: Report) -> bool:
    """Return whether a finding can safely enter the content editor."""
    return bool(vulnerability.title.strip() and vulnerability.likelihood and vulnerability.impact and vulnerability.severity and vulnerability.status and scope_has_location(vulnerability, report))