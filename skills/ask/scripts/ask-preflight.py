#!/usr/bin/env python3
"""Local pre-egress scanner for /ask prompt files.

This is intentionally conservative: it never prints matching secret-shaped lines and
never rewrites the payload.

A hit REPORTS a block; it cannot stop a send. This script reads a file and exits --
nothing in this standalone command sends the payload. The ask executors call
verdict() on the composed string immediately before passing it on stdin; callers
using this standalone command must send only the reviewed payload. A blocked
credential hunk must be removed or explicitly redacted before any invocation.

Exit: 0 = no blocked pattern found, 1 = blocked, 2 = usage/read error.
"""
from pathlib import Path
import re
import sys

# Basename classes exclude only path separators, never whitespace: a credential
# file may be named "my cert.pfx", and git writes such a path unquoted into its
# diff headers. The JSON branch bounds both classes because two unbounded ones
# around a literal backtrack quadratically, and DIFF_PATH feeds this arbitrary
# text (a "---" line consumes the newline and captures the line after it). The
# terminator accepts a quote because a C-quoted `diff --git` line puts both paths
# in one capture, so the first path ends at a quote rather than a separator.
#
# The qualified-key JSON branch is separate from the keyword branch beside it
# rather than another word inside it, because it is the only one needing a
# BOUNDARY: the surrounding [^/\\]{0,128} wildcards would swallow one. And the
# QUALIFIER carries the signal, not the word `key` -- a bare boundary-delimited
# key(s) segment also matches primary_key.json, foreign_key.json,
# translation_keys.json and public_keys.json, which are ordinary schema,
# localisation and JWKS files. Trading one false-positive class for another is
# not a fix: a gate that cries wolf gets weakened. Deliberately not extended to
# a bare secret/token segment either -- `secrets-` would match this repository's
# own registry file, secrets-exceptions.json, which would then need an exception
# entry for itself.
CREDENTIAL_PATH = re.compile(
    r"(?:^|[/\\])(?:\.env(?:\.[^/\\\s]+)?|\.envrc|auth\.json|[^/\\]{0,128}(?:service[_-]?account|credential|client[_-]?secret)[^/\\]{0,128}\.json|(?:[^/\\]{0,64}[_.-])?(?:sa|private|secret|api|access|client|signing|auth|master|encryption)[_-]keys?(?:[_.-][^/\\]{0,64})?\.json|\.npmrc|id_(?:rsa|dsa|ed25519|ecdsa)|[^/\\]*\.(?:pfx|p12|p8|pem|key|token|jks|keystore|ppk))(?:$|[/\\\s\"])",
    re.IGNORECASE,
)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----", re.IGNORECASE)
# The npm branch is npm_ + exactly 36 alphanumerics, in its own alternative
# rather than the {12,} prefix group beside it: that group's class allows
# underscores, and npm_package_* / npm_config_* lifecycle env-var NAMES are
# ubiquitous in JS tooling text -- an underscore-free fixed-length run is what
# keeps a name from ever looking like a token.
KNOWN_SECRET = re.compile(
    r"(?i)(?:\bAKIA[0-9A-Z]{16}\b|\b(?:sk-(?:live|prod|test)?|gh[pousr]_|xox[baprs]-)[A-Za-z0-9_-]{12,}|\bnpm_[A-Za-z0-9]{36}\b)"
)
URL_CREDENTIAL = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@[^\s]+")
# The key may be quoted (JSON/YAML), so the optional quotes bracket the name and
# the redaction lookahead allows one before the marker -- putting the quote in
# the lookahead rather than consuming it keeps "key": "<redacted>" from slipping
# through on backtracking. The leading guard skips one shape only: a plural
# "...tokens" key whose value is a bare count. That is LLM usage telemetry, which
# would otherwise swamp the pre-commit gate; excluding plurals outright would let
# TOKENS=<secret> and "access_tokens": [...] through, so the value must be
# numeric too -- [0-9] rather than \d, since a non-ASCII digit is not a count.
# Every quantifier here is bounded or a single class: "\s*[+>]?\s*" splits
# ambiguously and made a guard failure quadratic in the line's indent, and the
# unbounded key classes did the same around the keyword. {0,128} is a trade with
# a known cliff -- a key needing 129+ characters before or after the keyword is
# missed -- taken because the longest realistic nested config keys measured here
# run about 60-70, while unbounded cost 38 s on a single 64 KB line.
ASSIGNMENT = re.compile(
    r"(?im)^(?![\s+>]*[\"']?[A-Z0-9_.-]{0,128}TOKENS[\"']?\s*[:=]\s*[0-9]+[,;]?\s*$)[\s+>]*(?:export\s+)?[\"']?[A-Z0-9_.-]{0,128}(?:API[_-]?KEY|SECRET(?:[_-]?ACCESS)?[_-]?KEY|TOKEN|PASSWORD|PASSWD|PASSPHRASE|PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|AUTH[_-]?TOKEN)[A-Z0-9_.-]{0,128}[\"']?\s*[:=]\s*(?![\"']?(?:<redacted>|\[redacted\]|redacted\b|test[_-]?only\b|example\b))\S+"
)
BEARER = re.compile(r"(?i)\b(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+/=-]{12,}")
# The one credential line ASSIGNMENT structurally cannot see: npm's scoped
# registry auth, `//host/path/:_authToken=value`. ASSIGNMENT is start-anchored
# and its key class has no slash or colon, so the URL prefix hides the keyword
# from it -- the audited fixtures-npm hole. Closed as its own rule rather than
# by letting ASSIGNMENT's key class swallow slashes, which would turn every
# path-ish line ending in a keyword into a hit. The `//...:` scope prefix is
# MANDATORY: top-level `_authToken=` / `_password=` already carry ASSIGNMENT
# keywords, and claiming a bare leading `_auth` would flag the ordinary
# `_auth = get_auth()` private-variable shape in real code. What the scoping
# gives up, named: the legacy TOP-LEVEL `_auth=<base64>` npmrc line stays
# invisible to both layers (pinned as an accepted residual in the suite).
# Bounded quantifiers and the redaction lookahead mirror ASSIGNMENT.
NPM_AUTH = re.compile(
    r"(?im)^[\s+>]*[\"']?//[^\s\"']{0,512}:_(?:authToken|auth|password)[\"']?\s*[:=]\s*(?![\"']?(?:<redacted>|\[redacted\]|redacted\b|test[_-]?only\b|example\b))\S+"
)
# git C-quotes a path containing a tab/quote/backslash/non-ASCII byte, and a
# binary-file diff emits no ---/+++ lines, so the quoted `diff --git` header is
# the only path such a change ever shows. scan() strips the quotes back off.
# The copy/rename record lines are parsed too: a 100%-similarity copy or
# rename emits no ---/+++ lines either, and under --no-prefix its `diff --git`
# line loses the `a/` anchor -- the records are then the only place the paths
# survive at all. Prose that happens to open with the phrase is over-captured
# and checked as a path, the same accepted posture as a bare `---` line
# consuming its following line.
DIFF_PATH = re.compile(r"(?m)^(?:diff --git \"?a/|---\s+\"?(?:a/)?|\+\+\+\s+\"?(?:b/)?|(?:copy|rename) (?:from|to) \"?)([^\t\r\n]+)")


def scan(text):
    reasons = set()
    if PRIVATE_KEY.search(text):
        reasons.add("private-key material")
    if KNOWN_SECRET.search(text):
        reasons.add("known credential prefix")
    if URL_CREDENTIAL.search(text):
        reasons.add("URL-embedded credential")
    if ASSIGNMENT.search(text):
        reasons.add("credential-shaped assignment")
    if NPM_AUTH.search(text):
        reasons.add("npm registry credential")
    if BEARER.search(text):
        reasons.add("bearer token")
    for match in DIFF_PATH.finditer(text):
        path = match.group(1).strip().strip('"')
        if path != "/dev/null" and CREDENTIAL_PATH.search("/" + path):
            reasons.add("credential-file diff")
    return sorted(reasons)


def verdict(text):
    """(exit_code, message) for a payload ALREADY IN MEMORY.

    Split out so there is exactly one definition of the verdict. `main()` reads a
    file and calls this; `ask-codex.py` calls it directly on the string it is
    about to send, which is the only way to close the window where a scan reads
    one payload and the caller ships another -- reopening a scanned pathname was
    a Critical in two consecutive review rounds of that unit.
    """
    # The scan answers "does this payload contain a blocked pattern?", and an
    # empty payload honestly does not. The caller is asking a different
    # question -- "is this prompt safe to send?" -- and for an empty payload the
    # answer is that there is nothing to send. Reported as an error rather than
    # a block because nothing was found; the failure it catches is a prompt
    # construction step that left a zero-byte file, where OK reads as
    # "gate passed" and the external CLI receives nothing.
    if not text.strip():
        return 2, "ask preflight ERROR: prompt file is empty -- nothing to send"
    reasons = scan(text)
    if reasons:
        # Do not print snippets: even diagnostic output may later enter an artifact.
        return 1, ("ASK PREFLIGHT BLOCKED: %s. Redact/remove the affected payload "
                   "before egress." % ", ".join(reasons))
    return 0, "ASK PREFLIGHT OK"


def main():
    if len(sys.argv) != 2:
        print("usage: ask-preflight.py <prompt-file>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print("ask preflight ERROR: could not read prompt (%s)" % type(exc).__name__, file=sys.stderr)
        return 2
    code, message = verdict(text)
    print(message, file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
