#!/usr/bin/env python3
"""Append a closeout section to NEXT-archive.md with both registrations (its digest in NEXT-archive.sha256, its heading in NEXT-archive.index) in one command."""
import argparse
import os
import datetime
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load_digest_module():
    spec = importlib.util.spec_from_file_location("archive_digest", HERE / "archive_digest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refuse(message):
    print("archive-closeout: " + message, file=sys.stderr)
    return 2


def newline_of(raw):
    return b"\r\n" if b"\r\n" in raw else b"\n"


def add(repo, heading, body_path, marker):
    ad = load_digest_module()
    archive = repo / "NEXT-archive.md"
    digests = repo / "NEXT-archive.sha256"
    index = repo / "NEXT-archive.index"
    for path in (archive, digests, index):
        if not path.is_file():
            return refuse("missing %s" % path)
    if not heading.startswith("## "):
        return refuse("the heading must be a '## ' line, got %r" % heading)
    if "\n" in heading or "\r" in heading:
        return refuse("the heading must be one line")
    marker_line = "<!-- %s -->" % marker
    if not ad.MARK.match(marker_line):
        return refuse("the marker %r is not one the archive digest recognises" % marker)
    try:
        body = body_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return refuse("cannot read the body file (%s)" % type(exc).__name__)
    body = body.replace("\r\n", "\n").strip("\n")
    if not body:
        return refuse("the body is empty")
    if any(ad.MARK.match(line.strip()) for line in body.split("\n")):
        return refuse("the body carries an archive marker line; a section holds exactly one, and the tool writes it")
    if any(line.startswith("## ") for line in body.split("\n")):
        return refuse("the body carries a second '## ' heading; one section, one heading")
    arch_raw = archive.read_bytes()
    arch_text = arch_raw.decode("utf-8")
    if heading in ad.sections(arch_text):
        return refuse("heading already present in NEXT-archive.md: %s" % heading)
    if heading in ad.read_digests(digests):
        return refuse("heading already present in NEXT-archive.sha256: %s" % heading)
    if heading in ad.read_index(index):
        return refuse("heading already present in NEXT-archive.index: %s" % heading)

    nl = newline_of(arch_raw)
    section = "\n".join(["", "---", "", marker_line, heading, "", body, ""])
    new_text = arch_text.rstrip("\r\n") + "\n" + section
    new_raw = new_text.encode("utf-8") if nl == b"\n" else new_text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    secs = ad.sections(new_raw.decode("utf-8").replace("\r\n", "\n"))
    if heading not in secs:
        return refuse("the appended section could not be found by the digest routine; nothing written")
    digest = ad.digest(secs[heading])

    d_raw = digests.read_bytes()
    d_nl = newline_of(d_raw)
    i_raw = index.read_bytes()
    i_nl = newline_of(i_raw)
    planned = [
        (archive, new_raw),
        (digests, d_raw.rstrip(b"\r\n") + d_nl + (digest + "  " + heading).encode("utf-8") + d_nl),
        (index, i_raw.rstrip(b"\r\n") + i_nl + heading.encode("utf-8") + i_nl),
    ]
    # Three independent writes meant an interruption after the first or second left
    # a section with no digest, or a digest with no index line -- durable damage the
    # next full pass reports and a human has to reconcile (3B audit 2026-09-02).
    # Every byte is staged beside its target first; only when all three exist does
    # the replace phase run. A crash before that leaves the originals untouched, and
    # a crash inside it leaves at most a stale `.closeout-tmp` sibling, which is
    # visible and carries no meaning of its own. This is not a transaction -- three
    # replaces are three syscalls -- but the window is now three renames wide
    # instead of two file writes.
    staged = [(target, target.with_name(target.name + ".closeout-tmp")) for target, _ in planned]
    try:
        for (target, payload), (_, tmp) in zip(planned, staged):
            tmp.write_bytes(payload)
    except OSError as exc:
        for _, tmp in staged:
            try:
                tmp.unlink()
            except OSError:
                pass
        return refuse("could not stage the registrations (%s); nothing written"
                      % type(exc).__name__)
    for target, tmp in staged:
        os.replace(str(tmp), str(target))
    print("archive-closeout: appended %s" % heading)
    print("archive-closeout: digest %s recorded in %s" % (digest, digests.name))
    print("archive-closeout: heading recorded in %s" % index.name)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="archive-closeout")
    sub = parser.add_subparsers(dest="command")
    p_add = sub.add_parser("add")
    p_add.add_argument("--heading", required=True)
    p_add.add_argument("--body", required=True)
    p_add.add_argument("--marker", default="closeout recorded %s" % datetime.date.today().isoformat())
    p_add.add_argument("--repo", default=str(HERE.parent))
    args = parser.parse_args(argv)
    if args.command != "add":
        parser.print_usage(sys.stderr)
        return 2
    return add(Path(args.repo), args.heading, Path(args.body), args.marker)


if __name__ == "__main__":
    sys.exit(main())
