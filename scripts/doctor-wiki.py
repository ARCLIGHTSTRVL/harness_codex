from collections import Counter

ADVISORY = "advisory"
DEBT_CATEGORIES = {"documentation-gap"}
CANONICAL_SEVERITIES = ("critical", "high", "medium", "low", "info")


def classify_wiki_issues(issues):
    """(state, detail) for a wiki-lint JSON payload. Module-level so it is testable.

    It lived inside doctor's per-row closure, reachable only by running a real
    linter against a real wiki -- which is how the fail-closed regression below
    shipped unpinned. Unreachable code is untested code whatever the reason.
    """
    severities = [str(i.get("severity", "unknown")) if isinstance(i, dict)
                  else "invalid-item" for i in issues]
    counts = Counter(severities)
    ordered = [s for s in CANONICAL_SEVERITIES if counts[s]]
    ordered += sorted(s for s in counts if s not in CANONICAL_SEVERITIES)
    summary = ", ".join("%d %s" % (counts[s], s) for s in ordered) or "no issues"
    # FAIL CLOSED FIRST, before any category reasoning (r1 Major 3). This used to
    # fall out of the severity test -- `invalid-item` and any future severity
    # simply were not in ("low", "info"), so they were attention. Moving the
    # decision onto CATEGORIES moved it onto a Counter that DROPS non-dict items,
    # so a payload of `[42]` produced no categories, hence "clean", hence a
    # stamped .last-doctor on a linter whose output could not be read. When a
    # decision changes axis, the properties riding the old axis have to be carried
    # across by hand; this one was not.
    unusable = sorted({s for s in severities if s not in CANONICAL_SEVERITIES})
    if unusable:
        return (True, summary + " -> linter output not understood: "
                + ", ".join(unusable))
    # Medium structural debt is attention; low/info remain visible but do not keep
    # the weekly doctor cadence armed.
    categories = Counter(str(i.get("category", "unknown"))
                         for i in issues
                         if isinstance(i, dict)
                         and str(i.get("severity", "unknown")) not in ("low", "info"))
    gap_files = 0
    gap_measurable = True
    for issue in issues:
        if (not isinstance(issue, dict)
                or str(issue.get("category", "")) != "documentation-gap"
                or str(issue.get("severity", "unknown")) in ("low", "info")):
            continue
        extra = issue.get("extra")
        n = extra.get("count") if isinstance(extra, dict) else None
        if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
            gap_files += n
        else:
            gap_measurable = False
    debt = set(DEBT_CATEGORIES)
    if not gap_measurable:
        debt.discard("documentation-gap")
    actionable = sum(n for c, n in categories.items() if c not in debt)
    detail = summary
    if categories:
        detail += " -> " + ", ".join("%s=%d" % item
                                     for item in sorted(categories.items()))
    if "documentation-gap" in categories:
        detail += (", %d unpinned file(s)" % gap_files if gap_measurable
                   else ", unpinned file count unreadable")
    exclusions = set()
    exclusions_valid = True
    for issue in issues:
        if (not isinstance(issue, dict)
                or str(issue.get("category", "")) != "documentation-gap-exclusion"):
            continue
        extra = issue.get("extra")
        names = extra.get("excluded") if isinstance(extra, dict) else None
        if (not isinstance(names, list)
                or any(not isinstance(name, str) or not name for name in names)):
            exclusions_valid = False
        else:
            exclusions.update(names)
    if not exclusions_valid:
        return (True, detail + " -> doc-gap exclusion disclosure unreadable")
    if exclusions:
        detail += " (doc-gap excludes: %s)" % ", ".join(sorted(exclusions))
    if actionable:
        return (True, detail)
    if categories:
        return (ADVISORY, detail)
    return (False, detail)
