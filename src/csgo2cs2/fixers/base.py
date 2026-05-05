# fixer registry and shared types.

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Tuple

from ..analyzers.vmf import Finding


@dataclass
class FixResult:
    issue_id: str
    applied: bool
    detail: str = ""


# fixer signature: (vmf_text, finding) -> (new_text, applied, detail)
Fixer = Callable[[str, Finding], Tuple[str, bool, str]]


_REGISTRY: Dict[str, Fixer] = {}


def register(issue_id: str, fixer: Fixer) -> None:
    _REGISTRY[issue_id] = fixer


def get(issue_id: str) -> Fixer | None:
    return _REGISTRY.get(issue_id)


# apply registered fixers in order.
def apply_all(text: str, findings) -> Tuple[str, list[FixResult]]:
    results: list[FixResult] = []
    for f in findings:
        if not f.fixable:
            continue
        fn = get(f.issue_id)
        if not fn:
            continue
        new_text, applied, detail = fn(text, f)
        results.append(FixResult(issue_id=f.issue_id, applied=applied, detail=detail))
        if applied:
            text = new_text
    return text, results
