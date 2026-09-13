from __future__ import annotations

from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Severity = Literal["critical", "high", "medium", "low", "informational"]
Status = Literal["open_new", "open_previously_discovered", "resolved"]
Environment = Literal["production", "non_production"]
Channel = Literal["api", "web", "mobile"]
TestType = Literal["web", "api", "mobile", "web_api"]
# Only labels the Proof of Concept evidence groups; it never renames the environment itself.
NonProductionLabel = Literal["UAT", "TEST/MO", "DEV"]
Segment = Literal["JH", "GWAM", "Asia"]
ReportType = Literal["annual_pentest", "retest", "deployment_pentest", "new_test"]
ContentType = Literal["description", "recommended_remediation", "previous_proof_of_concept", "proof_of_concept", "in_conclusion"]
StableId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class Run(BaseModel):
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


class ParagraphFragment(BaseModel):
    frag_id: StableId
    type: Literal["paragraph"]
    runs: list[Run] = Field(default_factory=list)
    generated: Literal["status_conclusion"] | None = None


class ListItem(BaseModel):
    runs: list[Run] = Field(default_factory=list)


class ListFragment(BaseModel):
    frag_id: StableId
    type: Literal["numbered_list", "bulleted_list"]
    items: list[ListItem] = Field(min_length=1)


class TableFragment(BaseModel):
    frag_id: StableId
    type: Literal["table"]
    caption: str | None = None
    header: list[ListItem] = Field(default_factory=list)
    rows: list[list[ListItem]] = Field(default_factory=list)


class NoteFragment(BaseModel):
    frag_id: StableId
    type: Literal["note"]
    runs: list[Run] = Field(default_factory=list)


class ImageFragment(BaseModel):
    frag_id: StableId
    type: Literal["image"]
    environment: Environment | None = None
    evidence_id: str | None = None
    caption: str = ""
    width_mm: float | None = None


class CodeFragment(BaseModel):
    frag_id: StableId
    type: Literal["code_block"]
    caption: str | None = None
    text: str = ""


class InstanceTitleFragment(BaseModel):
    frag_id: StableId
    type: Literal["instance_title"]
    text: str = ""


Fragment = Annotated[ParagraphFragment | ListFragment | TableFragment | NoteFragment | ImageFragment | CodeFragment | InstanceTitleFragment, Field(discriminator="type")]


class Content(BaseModel):
    type: ContentType
    fragments: list[Fragment] = Field(default_factory=list)


class Scope(BaseModel):
    mode: Literal["all", "all_production", "all_non_production", "custom"] = "all"
    target_ids: list[str] = Field(default_factory=list)
    location_values: dict[str, str] = Field(default_factory=dict)
    # Keyed environment then channel, mirroring scope_text, so a typed-in location still knows its app type.
    custom_locations: dict[Environment, dict[Channel, list[str]]] = Field(default_factory=dict)


class ScopeTarget(BaseModel):
    target_id: StableId
    environment: Environment
    channel: Channel
    value: str
    order: int = 0


class TestWindow(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    test_time: str = "Any time"

    @model_validator(mode="after")
    def validate_order(self) -> "TestWindow":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("test window end date cannot precede its start date")
        return self


class TestAccount(BaseModel):
    user_role: str = "N/A"
    username: str = "N/A"


class LibraryRef(BaseModel):
    library_id: StableId
    source_id: int | str
    inserted_at: datetime


class Vulnerability(BaseModel):
    uid: StableId
    display_id: Annotated[str, Field(pattern=r"^[0-9]{1,5}$")] | None = None
    title: str = ""
    likelihood: Severity | None = None
    impact: Severity | None = None
    severity: Severity | None = None
    status: Status = "open_new"
    scope: Scope = Field(default_factory=Scope)
    library_ref: LibraryRef | None = None
    # Which app type the current proof-of-concept steps came from, and which offers the tester has refused.
    # Kept on the finding because both library insert paths rebuild library_ref from scratch.
    poc_variant: TestType | None = None
    poc_variant_declined: list[TestType] = Field(default_factory=list)
    contents: list[Content] = Field(default_factory=list)


class Engagement(BaseModel):
    app_name: str = ""
    ci_number: str = ""
    bsn_number: str = ""
    app_owner: str = ""
    segment: Segment | None = None
    report_type: ReportType | None = None
    start_date: date | None = None
    end_date: date | None = None
    tested_environments: list[Environment] = Field(default_factory=lambda: ["production", "non_production"])
    test_type: TestType = "web"
    non_production_label: NonProductionLabel = "UAT"
    test_windows: dict[Environment, TestWindow] = Field(default_factory=dict)
    test_accounts: list[TestAccount] = Field(default_factory=lambda: [TestAccount()])
    limitations: str = "N/A"
    tester: str = ""
    report_date: date | None = None
    classification: str = "Confidential"
    template_set: str = "default-v1"

    @model_validator(mode="after")
    def validate_environments(self) -> "Engagement":
        if len(self.tested_environments) != len(set(self.tested_environments)):
            raise ValueError("tested environments must be unique")
        return self


class FolderHint(BaseModel):
    app_folder: str = ""
    report_folder: str = ""


class EvidenceItem(BaseModel):
    file: str
    original_name: str = ""
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    uploaded_at: datetime

    @field_validator("file")
    @classmethod
    def validate_file(cls, value: str) -> str:
        """Keep evidence references inside the report's evidence directory."""
        path = PurePosixPath(value)
        if path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "evidence" or path.suffix.lower() != ".png":
            raise ValueError("evidence file must be a PNG directly under evidence/")
        return value


class Report(BaseModel):
    schema_version: Literal["1.4"] = "1.4"
    report_id: StableId
    app_id: str
    app_version: str = "0.1.0"
    saved_at: datetime
    folder_name_hint: FolderHint = Field(default_factory=FolderHint, alias="_folder_name_hint")
    engagement: Engagement = Field(default_factory=Engagement)
    scope_targets: list[ScopeTarget] = Field(default_factory=list)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    evidence: dict[StableId, EvidenceItem] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "Report":
        """Reject drafts with orphaned custom targets or duplicate fragment IDs."""
        target_id_values = [target.target_id for target in self.scope_targets]
        if len(target_id_values) != len(set(target_id_values)):
            raise ValueError("duplicate scope target id")
        vulnerability_ids = [vulnerability.uid for vulnerability in self.vulnerabilities]
        if len(vulnerability_ids) != len(set(vulnerability_ids)):
            raise ValueError("duplicate vulnerability id")
        numbers = [vulnerability.display_id for vulnerability in self.vulnerabilities if vulnerability.display_id]
        if len(numbers) != len(set(numbers)):
            raise ValueError("two findings cannot share the same finding number")
        target_ids = set(target_id_values)
        frag_ids: set[str] = set()
        referenced_evidence_ids: set[str] = set()
        for vulnerability in self.vulnerabilities:
            content_types = [content.type for content in vulnerability.contents]
            if len(content_types) != len(set(content_types)):
                raise ValueError(f"duplicate content type for finding: {vulnerability.uid}")
            if vulnerability.scope.mode == "custom" and not set(vulnerability.scope.target_ids) <= target_ids:
                raise ValueError("custom scope references a missing target")
            for content in vulnerability.contents:
                for fragment in content.fragments:
                    if fragment.frag_id in frag_ids:
                        raise ValueError(f"duplicate fragment id: {fragment.frag_id}")
                    frag_ids.add(fragment.frag_id)
                    if isinstance(fragment, ImageFragment) and fragment.evidence_id:
                        referenced_evidence_ids.add(fragment.evidence_id)
        if not referenced_evidence_ids <= self.evidence.keys():
            raise ValueError("image fragment references missing evidence")
        for evidence_id, evidence in self.evidence.items():
            if PurePosixPath(evidence.file).name != f"{evidence_id}.png":
                raise ValueError("evidence filename must match its evidence id")
        return self
