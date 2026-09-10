#!/usr/bin/env python3
"""Consume deltas-for's count/oldest text protocol and archive diagnostics.

Missing or malformed measurements fail closed. Old measurable debt advises;
unacknowledged damage requires attention even when the producer exits zero.
"""
from datetime import datetime, timezone
from typing import Final, Literal


STALE_DAYS: Final = 30
FUTURE_SKEW_SECONDS: Final = 300
Row = tuple[bool | Literal["advisory"], str, str]


def debt_row(lines: list[str], now: datetime | None = None) -> Row | None:
    count: int | None = None
    oldest = ""
    oldest_ref = ""
    saw_count = False
    for line in lines:
        text = line.strip()
        if text.startswith("unconsolidated deltas"):
            saw_count = True
            try:
                count = int(text.rsplit(":", 1)[1].strip())
            except (IndexError, ValueError):
                count = None
        elif text.startswith("oldest unconsolidated created_at:"):
            oldest = text.split(":", 1)[1].strip()
        elif text.startswith("oldest unconsolidated delta:"):
            oldest_ref = text.split(":", 1)[1].strip()
    if not saw_count:
        return True, "fragment-debt", "deltas-for --debt produced no count line; debt UNMEASURED"
    if count is None or count < 0:
        return True, "fragment-debt", "deltas-for --debt count is unparseable; debt UNMEASURED"
    if count == 0:
        return None
    if not oldest:
        return True, "fragment-debt", f"{count} unconsolidated delta(s); age UNKNOWN (no oldest timestamp)"
    try:
        when = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
    except ValueError:
        return True, "fragment-debt", f"{count} unconsolidated delta(s); oldest timestamp unparseable ({oldest})"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = (now or datetime.now(timezone.utc)) - when
    if age.total_seconds() < -FUTURE_SKEW_SECONDS:
        subject = oldest_ref or f"the delta with created_at {oldest}"
        return True, "fragment-debt", f"{count} unconsolidated delta(s); oldest created_at is in the future; repair {subject}"
    days = max(age.days, 0)
    detail = f"{count} unconsolidated delta(s), oldest {days}d old"
    if days >= STALE_DAYS:
        return "advisory", "fragment-debt", detail + f" (>= {STALE_DAYS}d; see consolidation debt breakdown)"
    return False, "fragment-debt", detail


def report(lines: list[str], stderr: str) -> tuple[list[str], list[Row]]:
    extra = [line for line in stderr.splitlines() if any(token in line for token in
             ("DAMAGED", "QUARANTINE", "quarantine registry", "traversal failed"))]
    shown = lines + extra
    bad = [line for line in extra if any(token in line for token in
           ("DAMAGED", "quarantine registry", "traversal failed"))]
    rows: list[Row] = []
    if bad:
        rows.append((True, "fragment-damage", bad[0] + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else "")))
    aged = debt_row(shown)
    if aged is not None:
        rows.append(aged)
    return shown, rows
