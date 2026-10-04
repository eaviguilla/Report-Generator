"""Report acceptance: what a submitted report must pass, and what the server completes, before it is written."""
from __future__ import annotations

from datetime import datetime

from .models import Report
from .report_service import changed_target_refusals, finding_input_issues, provision as provision_finding, reconcile_targets, scope_text_from_targets, setup_input_issues, setup_refusal_message, sync_evidence_image_slots
from .workspace import StaleReportError


class Refusal(ValueError):
    """Acceptance turned the report away. The subclass names the rule; the caller words it."""


class InvalidScope(Refusal):
    """The submitted scope text cannot become scope targets."""


class ScopeTargetRemoved(Refusal):
    """The scope change leaves these findings with no location at all."""

    def __init__(self, findings: list[str]) -> None:
        super().__init__(", ".join(findings))
        self.findings = findings


class InvalidFields(Refusal):
    """Setup or finding fields hold characters their rules refuse. Both lists are always computed."""

    def __init__(self, setup_issues: list[str], finding_issues: list[str]) -> None:
        super().__init__("; ".join([*setup_issues, *finding_issues]))
        self.setup_issues = setup_issues
        self.finding_issues = finding_issues


def check(stored: Report, submitted: dict) -> Report:
    """Refuse the submission or return it validated. Rewrites `submitted` in place: scope text becomes targets."""
    try:
        revision = datetime.fromisoformat(submitted.get("saved_at", ""))
    except (TypeError, ValueError):
        revision = None
    if revision and revision != stored.saved_at:
        raise StaleReportError(stored.report_id)
    try:
        stranded = reconcile_targets(submitted, stored)
    except ValueError as error:
        raise InvalidScope(str(error)) from error
    if stranded:
        raise ScopeTargetRemoved(stranded)
    # Validation also freezes retired scope modes, against the targets reconcile_targets just wrote.
    report = Report.model_validate(submitted)
    # Without scope text the targets arrive as stored data, so a changed one never met the Setup checks.
    if stranded is None and (refusals := changed_target_refusals(report.scope_targets, stored.scope_targets)):
        context = {
            "engagement": report.engagement.model_dump(mode="json"),
            "scope_text": scope_text_from_targets(report.scope_targets),
        }
        raise InvalidScope(setup_refusal_message(refusals[0], context))
    setup_issues = setup_input_issues(report.engagement, stored.engagement)
    finding_issues = finding_input_issues(report)
    if setup_issues or finding_issues:
        raise InvalidFields(setup_issues, finding_issues)
    return report


def provision(report: Report) -> None:
    """Complete every finding with the sections, seed fragments and image slots the server owns."""
    for vulnerability in report.vulnerabilities:
        provision_finding(vulnerability)
        sync_evidence_image_slots(vulnerability, report)
