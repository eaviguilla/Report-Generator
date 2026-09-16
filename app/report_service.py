from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime
from itertools import zip_longest
from typing import Literal

from app.models import CHANNEL_LABELS, CHANNELS, COMPONENT_CHANNELS, Channel, Content, Engagement, Environment, ImageFragment, ListFragment, ListItem, ParagraphFragment, Report, Run, TableFragment, Vulnerability, resolve_tested_channels

REPORT_TYPE_LABELS = {
    "annual_pentest": "Annual Pentest",
    "retest": "Retest",
    "deployment_pentest": "Deployment Pentest",
    "new_test": "New Test",
}
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._@\\-]*[A-Za-z0-9])?$")
RESOLVED_REMEDIATION = "None, the vulnerability has been remediated."
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


APP_NAME_SYMBOLS = "-:;.()"
# Twin of componentScopeRule in app.js. A strict superset of the retired mobile set, so every value
# that validated before still does; the backslash and brackets are what make an install path typable.
COMPONENT_SCOPE_SYMBOLS = "/,.;:()&'\"-_\\[]"


def valid_application_name(value: str) -> bool:
    return _has_allowed_characters(value, APP_NAME_SYMBOLS)


def setup_input_issues(engagement: Engagement) -> list[str]:
    """Return invalid Setup values without treating blank draft fields as errors."""
    issues = []
    if engagement.app_name and (issue := invalid_character_issue("Application name", engagement.app_name, APP_NAME_SYMBOLS)):
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
    if engagement.limitations and (issue := invalid_character_issue("Limitations", engagement.limitations, "/,.;:()&'\"-", allow_line_breaks=True)):
        issues.append(issue)
    # Only when it can reach the document. An unticked Non-Production leaves the field disabled, and a
    # disabled input is exempt from browser validation, so checking it here would 422 a save the
    # client had no way to block.
    if "non_production" in engagement.tested_environments and engagement.non_production_label:
        if issue := invalid_character_issue("Non-Production name", engagement.non_production_label, "/-"):
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
        status = "Resolved" if vulnerability.status == "resolved" else "Open"
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
    """Single owner of the rule: an image left behind for an environment the finding no longer
    affects is stale, so it is neither the tester's to complete nor ours to render. Previous proof
    of concept is exempt, because it records the engagement that found the finding rather than
    this one, and a retest is usually narrower than the test before it."""
    if content_type == "previous_proof_of_concept":
        return True
    environment = getattr(fragment, "environment", None)
    return not environment or environment in affected_environments(vulnerability, report)


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
    # An empty slot for an environment the finding no longer affects is nobody's to fill, so it goes
    # rather than lingering as a second demand. An uploaded screenshot stays exactly where it is:
    # relabelling it would file the tester's evidence under a heading it never belonged to.
    for content in vulnerability.contents:
        if content.type == "previous_proof_of_concept":
            continue
        content.fragments = [
            fragment
            for fragment in content.fragments
            if not (
                isinstance(fragment, ImageFragment)
                and fragment.environment
                and fragment.environment not in environments
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


STATUS_CONCLUSION_PATTERN = re.compile(r'The finding ".*" is(?: still)? (?:Open|Resolved)\.', re.DOTALL)


def status_conclusion_runs(title: str, status_word: str) -> list[Run]:
    """Single owner of the default conclusion sentence. Paired with STATUS_CONCLUSION_PATTERN, which
    must keep matching whatever this builds: relax one and every default on disk freezes at the title
    and status it was stored with, because nothing recognises it as the app's own sentence any more."""
    return [
        Run(text=f'The finding "{title}" is still ' if status_word == "Open" else f'The finding "{title}" is '),
        Run(text=status_word, bold=True),
        Run(text="."),
    ]


def default_conclusion_span(text: str) -> tuple[int, int] | None:
    """Return the app-owned sentence's bounds when it remains in the paragraph."""
    stripped = text.rstrip()
    marker = 'The finding "'
    index = stripped.rfind(marker)
    while index != -1:
        match = STATUS_CONCLUSION_PATTERN.match(stripped, index)
        if match:
            return match.span()
        index = stripped.rfind(marker, 0, index)
    return None


def default_conclusion_start(text: str) -> int | None:
    """Where the app's own sentence begins, if the paragraph still ends with it.

    The quoted proof-of-concept step shares this paragraph and sits in front, so the sentence is a
    tail rather than the whole text. Scanning right to left and testing a full match on each suffix
    keeps one regex honest for titles that themselves contain a quotation mark."""
    span = default_conclusion_span(text)
    return span[0] if span is not None and span[1] == len(text.rstrip()) else None


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
        raise ValueError("select at least one app type")
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
            if not isinstance(component_text, str) or not isinstance(description_text, str):
                raise ValueError("scope target values must be text")
            environment_label = "Production" if environment == "production" else "Non-Production"
            scope_label = f"{environment_label} {CHANNEL_LABELS[channel]} scope"
            # Paired by raw index before cleaning, so a blank or commented component line still
            # consumes its index and cannot shift every description below it onto the wrong row.
            cleaned: list[tuple[str, str]] = []
            seen: set[str] = set()
            for value, description in zip_longest(component_text.splitlines(), description_text.splitlines(), fillvalue=""):
                value, description = value.strip(), description.strip()
                if not value or value.startswith("#"):
                    continue
                # Target IDs are reused by value, so a repeated line would claim the same ID twice.
                # For a URL that is the same place typed twice; for a component it is a second build
                # whose description would vanish with it, so say so rather than dropping it.
                if value in seen:
                    if channel in COMPONENT_CHANNELS:
                        raise ValueError(f"{scope_label} lists the same component twice: {json.dumps(value, ensure_ascii=False)}")
                    continue
                seen.add(value)
                cleaned.append((value, description))
            for order, (value, description) in enumerate(cleaned):
                if channel in COMPONENT_CHANNELS:
                    for label, text in ((scope_label, value), (f"{scope_label} description", description)):
                        if issue := invalid_character_issue(label, text, COMPONENT_SCOPE_SYMBOLS):
                            raise ValueError(issue)
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
    if not engagement.tester.strip():
        issues.append("tester")
    if not engagement.tested_environments:
        issues.append("selected environment")
    # The only home for the mutual-exclusion rule. Raising in validate_coverage or
    # resolve_tested_channels would demote the draft on load, where nothing can repair it; an issue
    # line bounces the tester to Setup, the one page holding both checkboxes.
    covered_components = [channel for channel in COMPONENT_CHANNELS if channel in engagement.tested_channels]
    if len(covered_components) > 1:
        issues.append(f"only one of {' and '.join(CHANNEL_LABELS[channel] for channel in covered_components)} -- deselect the other")
    for environment in engagement.tested_environments:
        test_window = engagement.test_windows.get(environment)
        if not test_window or not test_window.start_date or not test_window.end_date:
            issues.append(f"{environment.replace('_', '-')} testing dates")
        if not any(target.environment == environment and target.value.strip() for target in report.scope_targets):
            issues.append(f"{environment.replace('_', '-')} scope target")
        # Named per component rather than counted: among ten rows a tally cannot say which one.
        for target in report.scope_targets:
            if target.environment == environment and target.channel in COMPONENT_CHANNELS and target.value.strip() and not target.description.strip():
                issues.append(f"{environment.replace('_', '-')} {CHANNEL_LABELS[target.channel]} description for \"{target.value.strip()}\"")
    return [*issues, *setup_input_issues(engagement)]


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