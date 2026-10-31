#!/usr/bin/env python3
"""Release-hygiene check for PRs (ops #371). Run it the same way CI does:

    python3 -I .github/ci/release_hygiene.py            (needs network for the tag list and release notes)
    python3 -I .github/ci/release_hygiene.py --self-test (offline, tests the rules below)

Fails when:
  1. CURRENT_VERSION in config-editor/mediamtx_config_editor.py is older than the newest vX.Y.Z tag.
     A "-dev" suffix is stripped before comparing, so dev can sit at or ahead of the tag
     (v2.1.14-dev after v2.1.13 is fine). A version ahead of the tag WITHOUT "-dev" is only
     allowed on a PR to main (a release in progress: the tag comes after the merge); on dev
     it fails, because dev-channel boxes would mistake it for a release.
  2. The newest tag has no published GitHub release, or the release is empty. The GitHub release
     is where this repo's release notes live, and main-channel boxes only see releases.
  3. The GitHub "latest" release is not the newest tag (a tag was pushed without its release,
     or an older release was marked latest).
  4. The newest release notes read like developer notes: private repo names, local paths, test box
     names or ops issue numbers. Release notes are for users (release skill, step 6).

Exit 0 = clean, 1 = a rule failed, 2 = the check could not run (no network, no version line).
"""
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request

VERSION_FILE = "config-editor/mediamtx_config_editor.py"
VERSION_RE = re.compile(r'^CURRENT_VERSION\s*=\s*"v(\d+)\.(\d+)\.(\d+)(-dev)?"\s*$', re.M)
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# Things a user-facing note must not contain. Kept narrow on purpose: product names such as
# infra-TAK and port numbers are fine; private repos, local paths and test boxes are not.
DEV_NOTE_PATTERNS = [
    (r"-notes\b", "mentions a private notes repo"),
    (r"/Users/|~/GitHub", "contains a local path"),
    (r"\b(?:test6|test8|test12|aws-arm)\b", "names an internal test box"),
    (r"\bops\s*#\d+", "refers to an internal ops issue"),
]


def parse_version(text):
    """Return ((major, minor, patch), is_dev) from the version file text, or None."""
    m = VERSION_RE.search(text)
    if not m:
        return None
    return tuple(int(x) for x in m.groups()[:3]), bool(m.group(4))


def newest_tag(tag_names):
    found = [tuple(int(x) for x in m.groups()) for t in tag_names if (m := TAG_RE.match(t))]
    return max(found) if found else None


def fmt(v):
    return "v%d.%d.%d" % v


def check_version(version, is_dev, tag, base_branch):
    """Rule 1. Returns a list of problems."""
    if tag is None:
        return []
    if version < tag:
        return ["CURRENT_VERSION is %s%s but the newest tag is %s. The version file is behind the "
                "last release; it must be at or ahead of it." % (fmt(version), "-dev" if is_dev else "", fmt(tag))]
    if version > tag and not is_dev and base_branch != "main":
        return ["CURRENT_VERSION is %s, ahead of the newest tag %s, but has no -dev suffix. On dev it must "
                "read %s-dev until the release is cut (release skill, step 7)." % (fmt(version), fmt(tag), fmt(version))]
    return []


def check_notes(tag, release, latest_tag):
    """Rules 2 to 4. release is the GitHub release dict for the newest tag, or None."""
    if tag is None:
        return []
    problems = []
    if release is None:
        return ["The newest tag %s has no GitHub release. Release notes live on the release, and "
                "main-channel boxes only see releases." % fmt(tag)]
    if release.get("draft"):
        problems.append("The release for %s is still a draft, so users cannot see its notes." % fmt(tag))
    body = (release.get("body") or "").strip()
    if not body:
        problems.append("The release notes for %s are empty." % fmt(tag))
    for pattern, why in DEV_NOTE_PATTERNS:
        if re.search(pattern, body):
            problems.append("The release notes for %s %s. They are for users, not developers." % (fmt(tag), why))
    if latest_tag != fmt(tag):
        problems.append("The GitHub latest release is %s but the newest tag is %s." % (latest_tag or "missing", fmt(tag)))
    return problems


def run_checks(version_text, tag_names, release, latest_tag, base_branch):
    parsed = parse_version(version_text)
    if parsed is None:
        raise ValueError('no line like CURRENT_VERSION = "vX.Y.Z" or "vX.Y.Z-dev" in %s' % VERSION_FILE)
    version, is_dev = parsed
    tag = newest_tag(tag_names)
    return check_version(version, is_dev, tag, base_branch) + check_notes(tag, release, latest_tag)


# --- network and git -----------------------------------------------------------------------------
def list_tags():
    for cmd in (["git", "ls-remote", "--tags", "--refs", "origin"], ["git", "for-each-ref", "--format=%(refname)", "refs/tags"]):
        try:
            out = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60).stdout
        except (subprocess.SubprocessError, OSError):
            continue
        names = [line.split("refs/tags/", 1)[1] for line in out.splitlines() if "refs/tags/" in line]
        if names:
            return names
    raise RuntimeError("could not list tags (git ls-remote and local both came back empty)")


def api_get(repo, path):
    """GET a GitHub API path; return parsed JSON, or None on 404. Retries once on a network blip.
    HYGIENE_API_CMD (e.g. "gh api") runs that command instead, for local runs without a rate limit."""
    cmd = os.environ.get("HYGIENE_API_CMD")
    if cmd:
        r = subprocess.run(shlex.split(cmd) + ["repos/%s/%s" % (repo, path)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            if "404" in r.stderr + r.stdout:
                return None
            raise RuntimeError("%s failed: %s" % (cmd, (r.stderr or r.stdout).strip()[:200]))
        return json.loads(r.stdout)
    req = urllib.request.Request("https://api.github.com/repos/%s/%s" % (repo, path))
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "release-hygiene-check")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == 2:
                raise
        except (urllib.error.URLError, OSError):
            if attempt == 2:
                raise
    return None


def main():
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True).stdout.strip()
    os.chdir(root)
    repo = os.environ.get("GITHUB_REPOSITORY", "takwerx/mediamtx-installer")
    base_branch = os.environ.get("GITHUB_BASE_REF", "")
    try:
        with open(VERSION_FILE, encoding="utf-8") as fh:
            version_text = fh.read()
        tags = list_tags()
        tag = newest_tag(tags)
        release = api_get(repo, "releases/tags/" + fmt(tag)) if tag else None
        latest = api_get(repo, "releases/latest")
        latest_tag = (latest or {}).get("tag_name")
        problems = run_checks(version_text, tags, release, latest_tag, base_branch)
    except Exception as e:  # the check itself could not run
        print("release hygiene could not run: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 2
    shown, shown_dev = parse_version(version_text)
    print("version file: %s%s, newest tag: %s, base: %s" % (
        fmt(shown), "-dev" if shown_dev else "", fmt(tag) if tag else "none", base_branch or "n/a"))
    for p in problems:
        print("::error file=%s::%s" % (VERSION_FILE, p))
    if problems:
        print("release hygiene FAILED", file=sys.stderr)
        return 1
    print("release hygiene passed")
    return 0


# --- self-test -----------------------------------------------------------------------------------
def self_test():
    def vf(v):
        return 'x = 1\nCURRENT_VERSION = "%s"\ny = 2\n' % v

    good = {"draft": False, "body": "A fix for streams that did not restart.\n\nWeb Editor -> Versions -> Update."}
    tags = ["v2.1.12", "v2.1.13", "v2.0.9", "not-a-tag", "v2.1.13-rc1"]
    cases = [
        # (name, version file, release, latest, base, expected number of problems)
        ("dev ahead of tag", vf("v2.1.14-dev"), good, "v2.1.13", "dev", 0),
        ("dev at the tag (stripped suffix matches)", vf("v2.1.13-dev"), good, "v2.1.13", "dev", 0),
        ("released, matches tag", vf("v2.1.13"), good, "v2.1.13", "main", 0),
        ("behind the tag", vf("v2.1.12"), good, "v2.1.13", "dev", 1),
        ("behind the tag, dev suffix", vf("v2.1.12-dev"), good, "v2.1.13", "dev", 1),
        ("ahead without -dev on dev", vf("v2.1.14"), good, "v2.1.13", "dev", 1),
        ("ahead without -dev on a PR to main (release in progress)", vf("v2.1.14"), good, "v2.1.13", "main", 0),
        ("no release for the tag", vf("v2.1.14-dev"), None, "v2.1.12", "dev", 1),
        ("draft release", vf("v2.1.14-dev"), dict(good, draft=True), "v2.1.13", "dev", 1),
        ("empty notes", vf("v2.1.14-dev"), {"draft": False, "body": "  \n"}, "v2.1.13", "dev", 1),
        ("latest release is an older tag", vf("v2.1.14-dev"), good, "v2.1.12", "dev", 1),
        ("developer notes: private repo", vf("v2.1.14-dev"), {"draft": False, "body": "See mediamtx-installer-notes for the root cause."}, "v2.1.13", "dev", 1),
        ("developer notes: test box and path", vf("v2.1.14-dev"), {"draft": False, "body": "Checked on test6 in /Users/aj/x"}, "v2.1.13", "dev", 2),
        ("user notes may name infra-TAK and ports", vf("v2.1.14-dev"), {"draft": False, "body": "On infra-TAK installs the API is on 127.0.0.1:9997."}, "v2.1.13", "dev", 0),
    ]
    bad = 0
    for name, text, release, latest, base, want in cases:
        got = run_checks(text, tags, release, latest, base)
        ok = len(got) == want
        bad += not ok
        print("%s  %s%s" % ("ok  " if ok else "FAIL", name, "" if ok else "  (wanted %d problem(s), got %s)" % (want, got)))
    try:
        run_checks("no version here\n", tags, good, "v2.1.13", "dev")
        print("FAIL  missing version line should raise")
        bad += 1
    except ValueError:
        print("ok    missing version line raises")
    if newest_tag(["v2.9.0", "v2.10.0", "v2.1.99"]) != (2, 10, 0):
        print("FAIL  tags must sort numerically, not as text")
        bad += 1
    else:
        print("ok    tags sort numerically")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv[1:] else main())
