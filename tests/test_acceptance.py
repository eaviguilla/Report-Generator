"""Report acceptance through its own interface: no HTTP and no data folder."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from app import acceptance
from app.models import Engagement, ImageFragment, Report, Scope, ScopeTarget, Vulnerability
from app.report_service import RESOLVED_REMEDIATION, character_issue, content_types_for_status
from app.workspace import StaleReportError

REVISION = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
PRODUCTION_SITE = "https://prod.example.test"


def stored_report(targets: list[ScopeTarget] = (), findings: list[Vulnerability] = ()) -> Report:
    """A production-only web report as it sits on disk."""
    return Report(
        report_id="r_acceptance",
        app_id="unnamed",
        saved_at=REVISION,
        engagement=Engagement(tested_environments=["production"]),
        scope_targets=list(targets),
        vulnerabilities=list(findings),
    )


def submission(report: Report) -> dict:
    """What the browser sends back for an unchanged report."""
    return report.model_dump(mode="json", by_alias=True)


def production_target() -> ScopeTarget:
    return ScopeTarget(target_id="tgt_prod", environment="production", channel="web", value=PRODUCTION_SITE)


class CheckTests(unittest.TestCase):
    def test_a_submission_from_an_older_revision_is_refused_as_stale(self) -> None:
        stored = stored_report()
        stale = submission(stored)
        stale["saved_at"] = (REVISION - timedelta(seconds=1)).isoformat()

        with self.assertRaisesRegex(StaleReportError, "^r_acceptance$"):
            acceptance.check(stored, stale)
        self.assertEqual(acceptance.check(stored, submission(stored)).saved_at, REVISION)

    def test_scope_text_that_cannot_become_targets_is_refused_with_the_rule_message(self) -> None:
        stored = stored_report()
        unreadable = submission(stored)
        unreadable["scope_text"] = PRODUCTION_SITE
        readable = submission(stored)
        readable["scope_text"] = {"production": {"web": PRODUCTION_SITE}}

        with self.assertRaisesRegex(acceptance.InvalidScope, "^scope_text and engagement must be objects$") as raised:
            acceptance.check(stored, unreadable)
        # The import route catches ValueError, so the refusal has to stay one.
        self.assertIsInstance(raised.exception, ValueError)
        self.assertEqual([target.value for target in acceptance.check(stored, readable).scope_targets], [PRODUCTION_SITE])

    def test_a_scope_change_that_leaves_a_finding_without_a_location_names_the_finding(self) -> None:
        finding = Vulnerability(uid="v_scoped", title="Scoped finding", scope=Scope(target_ids=["tgt_prod"]))
        stored = stored_report([production_target()], [finding])
        emptied = submission(stored)
        emptied["scope_text"] = {"production": {"web": ""}}
        kept = submission(stored)
        kept["scope_text"] = {"production": {"web": PRODUCTION_SITE}}

        with self.assertRaisesRegex(acceptance.ScopeTargetRemoved, "^Scoped finding$") as raised:
            acceptance.check(stored, emptied)
        self.assertEqual(raised.exception.findings, ["Scoped finding"])
        self.assertEqual(acceptance.check(stored, kept).vulnerabilities[0].scope.target_ids, ["tgt_prod"])

    def test_a_malformed_report_passes_through_as_a_validation_error(self) -> None:
        stored = stored_report([], [Vulnerability(uid="v_status")])
        malformed = submission(stored)
        malformed["vulnerabilities"][0]["status"] = "half_open"

        with self.assertRaisesRegex(ValidationError, "status") as raised:
            acceptance.check(stored, malformed)
        self.assertNotIsInstance(raised.exception, acceptance.Refusal)

    def test_invalid_setup_and_finding_fields_are_refused_with_both_lists(self) -> None:
        setup_issue = character_issue("app_name", "Bad/App")
        finding_issue = character_issue("cvss_score", "9,8", portable_names=True)
        stored = stored_report([], [Vulnerability(uid="v_fields")])
        cases = [
            ("Setup only", "Bad/App", "", [setup_issue], []),
            ("finding only", "Good App", "9,8", [], [finding_issue]),
            ("both", "Bad/App", "9,8", [setup_issue], [finding_issue]),
        ]
        for label, app_name, cvss_score, setup_issues, finding_issues in cases:
            with self.subTest(label):
                submitted = submission(stored)
                submitted["engagement"]["app_name"] = app_name
                submitted["vulnerabilities"][0]["cvss_score"] = cvss_score
                with self.assertRaisesRegex(acceptance.InvalidFields, "contains invalid character") as raised:
                    acceptance.check(stored, submitted)
                self.assertEqual((raised.exception.setup_issues, raised.exception.finding_issues), (setup_issues, finding_issues))

        valid = submission(stored)
        valid["engagement"]["app_name"] = "Good App"
        valid["vulnerabilities"][0]["cvss_score"] = "9.8"
        self.assertEqual(acceptance.check(stored, valid).vulnerabilities[0].cvss_score, "9.8")

    def test_a_retired_scope_mode_resolves_against_the_targets_the_submission_writes(self) -> None:
        stored = stored_report([], [Vulnerability(uid="v_legacy", title="Legacy finding")])
        submitted = submission(stored)
        submitted["scope_text"] = {"production": {"web": PRODUCTION_SITE}}
        submitted["vulnerabilities"][0]["scope"] = {"mode": "all"}

        report = acceptance.check(stored, submitted)

        self.assertEqual(report.vulnerabilities[0].scope.target_ids, [report.scope_targets[0].target_id])


class ProvisionTests(unittest.TestCase):
    def test_every_finding_gets_its_status_sections_and_an_image_slot_per_environment(self) -> None:
        findings = [Vulnerability(uid=f"v_{status}", status=status, scope=Scope(target_ids=["tgt_prod"])) for status in ("open_new", "resolved")]
        report = stored_report([production_target()], findings)

        acceptance.provision(report)

        for finding in report.vulnerabilities:
            with self.subTest(finding.status):
                self.assertEqual([content.type for content in finding.contents], content_types_for_status(finding.status))
                proof = next(content for content in finding.contents if content.type == "proof_of_concept")
                self.assertEqual([fragment.environment for fragment in proof.fragments if fragment.type == "image"], ["production"])
        remediation = next(content for content in report.vulnerabilities[1].contents if content.type == "recommended_remediation")
        self.assertEqual(remediation.fragments[0].runs[0].text, RESOLVED_REMEDIATION)

    def test_an_untouched_image_slot_stays_while_its_environment_is_tested(self) -> None:
        cases = [
            ("tested, so it is a supporting slot", ["production", "non_production"], ["production", "non_production"]),
            ("not tested", ["production"], ["production"]),
        ]
        for label, tested_environments, expected in cases:
            with self.subTest(label):
                report = stored_report([production_target()], [Vulnerability(uid="v_prod", scope=Scope(target_ids=["tgt_prod"]))])
                acceptance.provision(report)
                report.engagement.tested_environments = tested_environments
                proof = next(content for content in report.vulnerabilities[0].contents if content.type == "proof_of_concept")
                proof.fragments.append(ImageFragment(frag_id="f_other", type="image", environment="non_production", evidence_id=None, caption=""))

                acceptance.provision(report)

                self.assertEqual([fragment.environment for fragment in proof.fragments if fragment.type == "image"], expected)


if __name__ == "__main__":
    unittest.main()
