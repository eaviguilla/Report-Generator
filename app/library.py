from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from app.models import Channel, Content, Fragment, Severity, StableId


class LibraryEntry(BaseModel):
    library_id: StableId
    source_id: int | str
    title: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    default_likelihood: Severity | None = None
    default_impact: Severity | None = None
    default_severity: Severity | None = None
    requires_tester_input: bool = False
    status: str = "approved"
    contents: list[Content] = Field(default_factory=list)
    # Ready-made proof-of-concept steps per tested app type. A missing key means no steps for that type.
    proof_of_concept: dict[Channel, list[Fragment]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fragment_ids(self) -> "LibraryEntry":
        fragment_ids = [fragment.frag_id for content in self.contents for fragment in content.fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError("library entry contains duplicate fragment IDs")
        return self

    @model_validator(mode="after")
    def validate_proof_of_concept(self) -> "LibraryEntry":
        # Checked per app type, not across them: a finding installing several remints every copy.
        for channel, fragments in self.proof_of_concept.items():
            if not fragments:
                raise ValueError(f"proof of concept for {channel} has no steps; omit the key instead")
            ids = [fragment.frag_id for fragment in fragments]
            if len(ids) != len(set(ids)):
                raise ValueError(f"proof of concept for {channel} contains duplicate fragment IDs")
        return self


class LibraryDocument(BaseModel):
    schema_version: str
    source: str = ""
    entry_count: int = Field(ge=0)
    entries: list[LibraryEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entries(self) -> "LibraryDocument":
        ids = [entry.library_id for entry in self.entries]
        if self.entry_count != len(self.entries):
            raise ValueError("library entry_count does not match entries")
        if len(ids) != len(set(ids)):
            raise ValueError("library contains duplicate library IDs")
        return self


class Library:
    """Loads and searches the locally exported vulnerability library."""

    def __init__(self, path: Path) -> None:
        """Read and validate library entries once at application startup."""
        document = LibraryDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
        self.entries = [entry.model_dump(mode="json") for entry in document.entries]
        self._by_id = {entry["library_id"]: entry for entry in self.entries}
        self.load_error = ""

    @classmethod
    def load_or_empty(cls, path: Path) -> "Library":
        """Never let an unreadable library stop the app, which loads it before any route exists."""
        try:
            return cls(path)
        except (OSError, ValueError) as error:
            empty = cls.__new__(cls)
            empty.entries, empty._by_id = [], {}
            empty.load_error = f"{path}: {error}"
            return empty

    def search(self, query: str) -> list[dict]:
        """Return up to twenty entries whose title or tags match the query."""
        needle = query.lower().strip()
        return [entry for entry in self.entries if not needle or needle in entry["title"].lower() or needle in " ".join(entry.get("tags", [])).lower()][:20]

    def get(self, library_id: str) -> dict | None:
        """Look up one library entry by its stable library identifier."""
        return self._by_id.get(library_id)
