"""The closed lists the browser needs, sent as one payload so no page or script keeps its own copy."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import get_args

from .models import CHANNEL_LABELS, CHANNELS, COMPONENT_CHANNELS, NON_PRODUCTION_LABEL_PRESETS, REPORT_TYPE_LABELS, STATUS_LABELS, NetworkAccess, ReportType, Segment, Severity, Status
from .report_service import CHARACTER_RULES, MAX_TEST_ACCOUNTS, PLACEHOLDER_TEXT, RESOLVED_REMEDIATION, SCOPE_LIMITS

# Each report page by the last part of its address, with the name a tester sees.
REPORT_PAGES = (("setup", "Setup"), ("findings", "Findings"), ("edit", "Content"))


def client_vocabulary() -> dict:
    """Every list in the model's own order, JSON-ready. A labelled list is [value, label] pairs."""
    return {
        "statuses": [[status, STATUS_LABELS[status]] for status in get_args(Status)],
        "severities": list(get_args(Severity)),
        "segments": list(get_args(Segment)),
        "report_types": [[report_type, REPORT_TYPE_LABELS[report_type]] for report_type in get_args(ReportType)],
        "network_access": list(get_args(NetworkAccess)),
        "channels": [[channel, CHANNEL_LABELS[channel]] for channel in CHANNELS],
        "component_channels": list(COMPONENT_CHANNELS),
        "non_production_label_presets": list(NON_PRODUCTION_LABEL_PRESETS),
        "character_rules": {field: asdict(rule) for field, rule in CHARACTER_RULES.items()},
        "max_test_accounts": MAX_TEST_ACCOUNTS,
        "scope_limits": SCOPE_LIMITS,
        "placeholder_pattern": {"source": PLACEHOLDER_TEXT.pattern, "flags": "i" if PLACEHOLDER_TEXT.flags & re.IGNORECASE else ""},
        "resolved_remediation": RESOLVED_REMEDIATION,
        "report_pages": [list(report_page) for report_page in REPORT_PAGES],
    }
