# report builders for json / structured output.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .. import __version__
from .bsp import BspInfo
from .vmf import VmfAnalysis

REPORT_SCHEMA_VERSION = 1


@dataclass
class Report:
    schema_version: int = REPORT_SCHEMA_VERSION
    tool_version: str = __version__
    inputs: Dict[str, str] = field(default_factory=dict)
    vmf: Optional[Dict[str, object]] = None
    bsp: Optional[Dict[str, object]] = None
    findings: List[Dict[str, object]] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)


# build a structured json-friendly dict from raw analyses. callers can pass
# either, both, or neither.
def build_report(
    vmf: Optional[VmfAnalysis] = None,
    bsp: Optional[BspInfo] = None,
    inputs: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    findings: List[Dict[str, object]] = []
    if vmf is not None:
        findings.extend(f.to_dict() for f in vmf.findings)

    severities = ("error", "warn", "info")
    summary = {sev: sum(1 for f in findings if f.get("severity") == sev) for sev in severities}
    summary["total"] = len(findings)
    summary["fixable"] = sum(1 for f in findings if f.get("fixable"))

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool_version": __version__,
        "inputs": dict(inputs or {}),
        "vmf": vmf.to_dict() if vmf is not None else None,
        "bsp": bsp.to_dict() if bsp is not None else None,
        "findings": findings,
        "summary": summary,
    }


# write a report dict to disk as pretty json. parents are created.
def write_report(report: Dict[str, object], dest: Path) -> Path:
    dest = Path(dest).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return dest
