from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime

from app.models import Content, Engagement, Environment, ImageFragment, ListFragment, ListItem, ParagraphFragment, Report, Run, Vulnerability

REPORT_TYPE_LABELS = {
    "annual_pentest": "Annual Pentest",
    "retest": "Retest",
    "deployment_pentest": "Deployment Pentest",
    "new_test": "New Test",
}
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._@\\-]*[A-Za-z0-9])?$")
CHARACTER_NAMES = {
    " ": "space", "\t": "tab", "\n": "line feed", "\r": "carriage return",
    "!": "exclamation mark", '"': "double quote", "#": "number sign", "$": "dollar sign",
    "%": "percent sign", "&": "ampersand", "'": "apostrophe", "(": "left parenthesis",
    ")": "right parenthesis", "*": "asterisk", "+": "plus sign", ",": "comma", "-": "hyphen",
    ".": "period", "/": "slash", ":": "colon", ";": "semicolon", "<": "less-than sign",
    "=": "equals sign", ">": "greater-than sign", "?": "question mark", "@": "at sign",
    "[": "left bracket", "\\": "backslash", "]": "right bracket", "^": "caret", "_": "underscore",
    "`": "grave accent", "{": "left brace", "|": "vertical bar", "}": "right brace", "~": "tilde",
}


def _invalid_characters(
    value: str,
    symbols: str,
    *,
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
            character.isalpha()
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
    allow_numbers: bool = True,
    allow_spaces: bool = True,
    allow_line_breaks: bool = False,
) -> str | None:
    """Describe the unique invalid characters in a field value."""
    invalid = _invalid_characters(
        value,
        symbols,
        allow_numbers=allow_numbers,
        allow_spaces=allow_spaces,
        allow_line_breaks=allow_line_breaks,
    )
    if not invalid:
        return None
    descriptions = ", ".join(
        f"{json.dumps(character, ensure_ascii=False)} ({CHARACTER_NAMES.get(character, unicodedata.name(character, f'Unicode U+{ord(character):04X}').lower())})"
        for character in invalid
    )
    noun = "character" if len(invalid) == 1 else "characters"
    return f"{label} contains invalid {noun}: {descriptions}"


def _has_allowed_characters(
    value: str,
    symbols: str,
    *,
    allow_numbers: bool = True,
    allow_spaces: bool = True,
    allow_line_breaks: bool = False,
) -> bool:
    return not _invalid_characters(
        value,
        symbols,
        allow_numbers=allow_numbers,
        allow_spaces=allow_spaces,
        allow_line_breaks=allow_line_breaks,
    )


def valid_application_name(value: str) -> bool:
    return _has_allowed_characters(value, "-:()")


def setup_input_issues(engagement: Engagement) -> list[str]:
    """Return invalid Setup values without treating blank draft fields as errors."""
    issues = []
    if engagement.app_name and (issue := invalid_character_issue("Application name", engagement.app_name, "-:()")):
        issues.append(issue)
    for label, value in (("CI number", engagement.ci_number), ("BSN number", engagement.bsn_number)):
        if value and (issue := invalid_character_issue(label, value, "-", allow_spaces=False)):
            issues.append(issue)
    for label, value in (("Application owner", engagement.app_owner), ("Tester", engagement.tester)):
        if value and (issue := invalid_character_issue(label, value, "-", allow_numbers=False)):
            issues.append(issue)
    for environment in engagement.tested_environments:
        test_window = engagement.test_windows.get(environment)
        if test_window is None:
            continue
        environment_label = "Production" if environment == "production" else "Non-Production"
        if test_window.start_date and test_window.end_date and test_window.start_date > test_window.end_date:
            issues.append(f"{environment_label} start date cannot be after its end date")
        if test_window.test_time and (issue := invalid_character_issue(f"{environment_label} time", test_window.test_time, ":/-")):
            issues.append(issue)
    for index, account in enumerate(engagement.test_accounts, start=1):
        if account.user_role and (issue := invalid_character_issue(f"User role {index}", account.user_role, "/-")):
            issues.append(issue)
        if account.username and account.username != "N/A" and not USERNAME_PATTERN.fullmatch(account.username):
            issue = invalid_character_issue(f"Username {index}", account.username, "._@\\-", allow_spaces=False)
            issues.append(issue or f"Username {index} must start and end with a letter or number")
    if engagement.limitations and not _has_allowed_characters(
        engagement.limitations,
        "/,.()&'\"-",
        allow_line_breaks=True,
    ):
        issues.append(invalid_character_issue("Limitations", engagement.limitations, "/,.()&'\"-", allow_line_breaks=True))
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


def provision(vulnerability: Vulnerability) -> None:
    """Create the status-required content blocks and starter fragments for a finding."""
    types = ["description", "recommended_remediation", "proof_of_concept"]
    if vulnerability.status != "open_new":
        types = ["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"]
    existing = {content.type: content for content in vulnerability.contents}
    vulnerability.contents = [existing.get(content_type, Content(type=content_type)) for content_type in types]
    required_fragments = {
        "description": ["paragraph"],
        "recommended_remediation": ["paragraph"],
        "previous_proof_of_concept": ["numbered_list"],
        "proof_of_concept": ["numbered_list"],
        "in_conclusion": [],
    }
    for content in vulnerability.contents:
        if content.fragments:
            continue
        present = {fragment.type for fragment in content.fragments}
        for fragment_type in required_fragments[content.type]:
            if fragment_type in present:
                continue
            if fragment_type == "paragraph":
                fragment = ParagraphFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="paragraph", runs=[])
            elif fragment_type == "numbered_list":
                fragment = ListFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="numbered_list", items=[ListItem(runs=[])])
            else:
                fragment = ImageFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="image", evidence_id=None, caption="", width_mm=None)
            content.fragments.append(fragment)
    if vulnerability.status == "resolved":
        remediation = next(content for content in vulnerability.contents if content.type == "recommended_remediation")
        remediation.fragments = [ParagraphFragment.model_validate({"frag_id": f"f_{uuid.uuid4().hex[:8]}", "type": "paragraph", "runs": [{"text": "None, the vulnerability has been remediated."}]})]
    conclusion = next((content for content in vulnerability.contents if content.type == "in_conclusion"), None)
    if conclusion is not None:
        status = "Resolved" if vulnerability.status == "resolved" else "Open"
        paragraphs = [fragment for fragment in conclusion.fragments if isinstance(fragment, ParagraphFragment)]
        generated = next((fragment for fragment in paragraphs if fragment.generated == "status_conclusion"), None)
        default = generated or next((fragment for fragment in paragraphs if _is_default_status_conclusion(fragment)), None)
        default = default or next((fragment for fragment in paragraphs if not _fragment_has_text(fragment)), None)
        if default is None and not paragraphs:
            default = ParagraphFragment(frag_id=f"f_{uuid.uuid4().hex[:8]}", type="paragraph", runs=[])
            conclusion.fragments.insert(0, default)
        if default is not None and (generated is not None or not _fragment_has_text(default) or _is_default_status_conclusion(default)):
            default.generated = None
            default.runs = [
            Run(text=f'The finding "{vulnerability.title}" is still ' if status == "Open" else f'The finding "{vulnerability.title}" is '),
            Run(text=status, bold=True),
            Run(text="."),
            ]
        if generated is not None:
            conclusion.fragments = [
                fragment for fragment in conclusion.fragments
                if fragment is generated or not isinstance(fragment, ParagraphFragment) or _fragment_has_text(fragment)
            ]


def affected_environments(vulnerability: Vulnerability, report: Report) -> list[Environment]:
    """Resolve the environments represented by a finding's selected or custom locations."""
    ordered: list[Environment] = []
    target_by_id = {target.target_id: target for target in report.scope_targets}

    def add(environment: Environment) -> None:
        if environment not in ordered:
            ordered.append(environment)

    if vulnerability.scope.mode == "custom":
        for target_id in vulnerability.scope.target_ids:
            target = target_by_id.get(target_id)
            if target:
                add(target.environment)
        for environment, locations in vulnerability.scope.custom_locations.items():
            if any(location.strip() for location in locations):
                add(environment)
    elif vulnerability.scope.mode == "all":
        for target in report.scope_targets:
            add(target.environment)
    elif vulnerability.scope.mode == "all_production":
        if any(target.environment == "production" for target in report.scope_targets):
            add("production")
    elif any(target.environment == "non_production" for target in report.scope_targets):
        add("non_production")
    return ordered


def fragment_applies(fragment, vulnerability: Vulnerability, report: Report) -> bool:
    """Single owner of the rule: an image left behind for an environment the finding no longer
    affects is stale, so it is neither the tester's to complete nor ours to render."""
    environment = getattr(fragment, "environment", None)
    return not environment or environment in affected_environments(vulnerability, report)


def sync_evidence_image_slots(vulnerability: Vulnerability, report: Report) -> None:
    """Ensure each affected environment has an image slot while preserving extra images."""
    environments = affected_environments(vulnerability, report)
    images = [fragment for content in vulnerability.contents for fragment in content.fragments if isinstance(fragment, ImageFragment)]
    if len(environments) == 1:
        for image in images:
            image.environment = environments[0]
    missing = [environment for environment in environments if not any(image.environment == environment for image in images)]
    for image in (image for image in images if image.environment is None):
        if missing:
            image.environment = missing.pop(0)
        elif environments:
            image.environment = environments[0]
    missing = [environment for environment in environments if not any(image.environment == environment for image in images)]
    proof = next((content for content in vulnerability.contents if content.type == "proof_of_concept"), None)
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


def _fragment_has_text(fragment: ParagraphFragment) -> bool:
    return any(run.text.strip() for run in fragment.runs)


def _is_default_status_conclusion(fragment: ParagraphFragment) -> bool:
    """Recognize an untouched default sentence that can still be synchronized."""
    text = "".join(run.text for run in fragment.runs)
    return bool(re.fullmatch(r'The finding ".*" is(?: still)? (?:Open|Resolved)\.', text))


def assign_fresh_fragment_ids(vulnerability: Vulnerability) -> None:
    """Give copied library fragments report-local identifiers."""
    for content in vulnerability.contents:
        for fragment in content.fragments:
            fragment.frag_id = f"f_{uuid.uuid4().hex[:8]}"


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
    channels_by_type = {"web": ["web"], "api": ["api"], "mobile": ["mobile"], "web_api": ["web", "api"]}
    test_type = engagement.get("test_type", "web")
    if test_type not in channels_by_type:
        raise ValueError("test_type is invalid")
    channels = channels_by_type[test_type]
    old = {(target.environment, target.channel, target.value): target.target_id for target in prior.scope_targets}
    targets = []
    for environment in environments:
        environment_values = submitted.get(environment, {})
        if not isinstance(environment_values, dict):
            raise ValueError("scope environment values must be objects")
        for channel in channels:
            raw_values = environment_values.get(channel, "")
            if not isinstance(raw_values, str):
                raise ValueError("scope target values must be text")
            values = raw_values.splitlines()
            for order, value in enumerate(value.strip() for value in values if value.strip() and not value.lstrip().startswith("#")):
                if channel == "mobile":
                    environment_label = "Production" if environment == "production" else "Non-Production"
                    issue = invalid_character_issue(f"{environment_label} Mobile scope", value, ":'\"/.,-_&")
                    if issue:
                        raise ValueError(issue)
                targets.append({"target_id": old.get((environment, channel, value), f"tgt_{uuid.uuid4().hex[:8]}"), "environment": environment, "channel": channel, "value": value, "order": order})
    payload["scope_targets"] = targets
    target_ids = {target["target_id"] for target in targets}
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
        if scope.get("mode") == "custom":
            missing_ids = set(scope.get("target_ids", [])) - target_ids
            if missing_ids:
                removed_references.append(vulnerability.get("title") or "Untitled finding")
    return removed_references


def setup_issues(report: Report) -> list[str]:
    """Return the missing engagement details that block Findings entry."""
    engagement = report.engagement
    issues = []
    if not engagement.app_name.strip():
        issues.append("application name")
    if not engagement.segment:
        issues.append("segment")
    if not engagement.report_type:
        issues.append("report type")
    if not engagement.ci_number.strip() and not engagement.bsn_number.strip():
        issues.append("CI or BSN number")
    if not engagement.tester.strip():
        issues.append("tester")
    if not engagement.tested_environments:
        issues.append("selected environment")
    for environment in engagement.tested_environments:
        test_window = engagement.test_windows.get(environment)
        if not test_window or not test_window.start_date or not test_window.end_date:
            issues.append(f"{environment.replace('_', '-')} testing dates")
        if not any(target.environment == environment and target.value.strip() for target in report.scope_targets):
            issues.append(f"{environment.replace('_', '-')} scope target")
    return [*issues, *setup_input_issues(engagement)]


def setup_is_complete(report: Report) -> bool:
    """Return whether a report meets the canonical Findings entry requirements."""
    return not setup_issues(report)


def scope_has_location(vulnerability: Vulnerability, report: Report) -> bool:
    """Return whether a finding's scope mode resolves to an affected location."""
    scope = vulnerability.scope
    if scope.mode == "custom":
        return bool(scope.target_ids) or any(value.strip() for values in scope.custom_locations.values() for value in values)
    if scope.mode == "all":
        return bool(report.scope_targets)
    environment = "production" if scope.mode == "all_production" else "non_production"
    return any(target.environment == environment for target in report.scope_targets)


def finding_is_complete(vulnerability: Vulnerability, report: Report) -> bool:
    """Return whether a finding can safely enter the content editor."""
    return bool(vulnerability.title.strip() and vulnerability.likelihood and vulnerability.impact and vulnerability.severity and vulnerability.status and scope_has_location(vulnerability, report))