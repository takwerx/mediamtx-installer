#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ops #1014: CodeQL and OpenSSF Scorecard run in GitHub, safely.

Run it: python3 -I .github/ci/test_workflow_pins.py        (standard library only, Python 3.9+)

Pins, read from the workflow files as text (no YAML library needed):
  * codeql.yml exists, covers exactly the languages this repo has (python,  javascript-typescript,  actions), runs on PRs into
    dev, on pushes to dev and main, and weekly, and builds nothing (build-mode none);
  * scorecard.yml exists, runs weekly and on main, publishes results, and is never a pull_request
    check (Scorecard only publishes from the default branch);
  * every `uses:` in EVERY workflow is a full 40-character commit SHA with a version comment
    (a tag or branch can be moved under us; a SHA cannot);
  * every workflow has a top-level `permissions:` block with no write access (a job that needs
    a write asks for it on the job);
  * neither new workflow uses a self-hosted runner, pull_request_target or a secret;
  * neither new workflow is wired into checks-ok yet: a new check must run clean once before it
    is required.
It exits 1 and prints every problem it finds.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
WORKFLOWS = ROOT / '.github' / 'workflows'
CODEQL = WORKFLOWS / 'codeql.yml'
SCORECARD = WORKFLOWS / 'scorecard.yml'
PR_CHECKS = WORKFLOWS / 'pr-checks.yml'

# The CodeQL languages this repo really has. Add one here and in codeql.yml together.
EXPECTED_LANGUAGES = {'python', 'javascript-typescript', 'actions'}

USES = re.compile(r'^\s*-?\s*uses:\s*(\S+)(.*)$', re.M)
FULL_SHA = re.compile(r'^[^@\s]+@[0-9a-f]{40}$')


def _code(text):
    """The file without comment lines, so a word in a comment never counts."""
    return '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))


def _read(p, problems):
    if not p.is_file():
        problems.append('%s is missing' % p.relative_to(ROOT))
        return None
    return p.read_text(encoding='utf-8')


def _triggers(code):
    """The block under the top-level `on:` key, as text ('' if there is none)."""
    m = re.search(r'^on:\s*\n((?:[ \t]+.*\n|\s*\n)+)', code + '\n', re.M)
    return m.group(1) if m else ''


def check_pins(name, text):
    """Every action in one workflow is a full SHA with a version comment."""
    bad = []
    for m in USES.finditer(_code(text)):
        ref, rest = m.group(1), m.group(2)
        if ref.startswith('./'):
            continue
        if not FULL_SHA.match(ref):
            bad.append('%s: %s is not pinned to a full commit SHA' % (name, ref))
        elif not re.search(r'#\s*v?\d', rest):
            bad.append('%s: %s has no version comment' % (name, ref))
    return bad


def check_top_permissions(name, text):
    """A top-level permissions block exists and grants no write."""
    code = _code(text)
    top = re.search(r'^permissions:[ \t]*(.*)\n((?:[ \t]+.*\n)*)', code + '\n', re.M)
    if not top:
        return ['%s has no top-level permissions block (default token may be read-write)' % name]
    if 'write' in top.group(0):
        return ['%s: top-level permissions must be read-only (put a write on the job)' % name]
    return []


def check_codeql(text):
    t = _code(text)
    p = []
    langs = re.search(r'language:\s*\[([^\]]*)\]', t)
    if not langs:
        p.append('codeql.yml has no language matrix')
    else:
        got = {x.strip() for x in langs.group(1).split(',')}
        if got != EXPECTED_LANGUAGES:
            p.append('codeql.yml languages are %s, expected %s' % (sorted(got), sorted(EXPECTED_LANGUAGES)))
    if not re.search(r'build-mode:\s*none', t):
        p.append('codeql.yml must use build-mode: none')
    if 'github/codeql-action/init@' not in t or 'github/codeql-action/analyze@' not in t:
        p.append('codeql.yml must use the codeql-action init and analyze steps')
    on = _triggers(t)
    if 'pull_request:' not in on or not re.search(r'branches:\s*\[[^\]]*\bdev\b', on):
        p.append('codeql.yml must run on pull requests into dev')
    if 'push:' not in on:
        p.append('codeql.yml must run on pushes')
    if 'schedule:' not in on or not re.search(r"cron:\s*'[^']+'", on):
        p.append('codeql.yml must run weekly')
    return p


def check_scorecard(text):
    t = _code(text)
    p = []
    on = _triggers(t)
    if 'schedule:' not in on or not re.search(r"cron:\s*'[^']+'", on):
        p.append('scorecard.yml must run weekly')
    if not re.search(r'branches:\s*\[main\]', on):
        p.append('scorecard.yml must run on pushes to main')
    if 'pull_request' in on:
        p.append('scorecard.yml must not be a pull_request check (it publishes from main only)')
    if 'ossf/scorecard-action@' not in t:
        p.append('scorecard.yml must use ossf/scorecard-action')
    if not re.search(r'publish_results:\s*true', t):
        p.append('scorecard.yml must publish results')
    if re.search(r'^(env|defaults):', t, re.M):
        p.append('scorecard.yml: a top-level env or defaults block makes the publish step refuse')
    return p


def check_hosted_and_quiet(name, text):
    t = _code(text)
    p = []
    if 'self-hosted' in t:
        p.append('%s must not use the Studio runners' % name)
    if 'pull_request_target' in t:
        p.append('%s must not use pull_request_target' % name)
    if 'secrets.' in t:
        p.append('%s needs no secret' % name)
    if not re.search(r'runs-on:\s*ubuntu-24\.04', t):
        p.append('%s must run on a GitHub-hosted ubuntu-24.04 runner' % name)
    if 'persist-credentials: false' not in t:
        p.append('%s: checkout must set persist-credentials: false' % name)
    return p


def check_not_required(text):
    needs = re.search(r'checks-ok:.*?needs:\s*\[([^\]]*)\]', text, re.S)
    if not needs:
        return ['pr-checks.yml: checks-ok has no needs list']
    p = []
    low = text.lower()
    if 'codeql' in needs.group(1).lower() or 'scorecard' in needs.group(1).lower():
        p.append('checks-ok must not wait on CodeQL or Scorecard yet')
    if 'codeql' in low or 'scorecard' in low:
        p.append('pr-checks.yml must not mention CodeQL or Scorecard yet')
    return p


def run_all():
    problems = []
    texts = {}
    for f in sorted(WORKFLOWS.glob('*.yml')):
        texts[f.name] = f.read_text(encoding='utf-8')
    for f, check in ((CODEQL, check_codeql), (SCORECARD, check_scorecard)):
        t = _read(f, problems)
        if t is not None:
            problems += check(t)
            problems += check_hosted_and_quiet(f.name, t)
    for name, t in texts.items():
        problems += check_pins(name, t)
        problems += check_top_permissions(name, t)
    t = _read(PR_CHECKS, problems)
    if t is not None:
        problems += check_not_required(t)
    return problems


def self_test():
    """The checks above must catch what they claim to (red on purpose)."""
    good = 'steps:\n  - uses: actions/checkout@' + 'a' * 40 + ' # v4.4.0\n'
    assert not check_pins('x.yml', good)
    assert check_pins('x.yml', 'steps:\n  - uses: actions/checkout@v4\n')
    assert check_pins('x.yml', 'steps:\n  - uses: actions/checkout@main # v4\n')
    assert check_pins('x.yml', 'steps:\n  - uses: actions/checkout@' + 'a' * 40 + '\n')
    assert check_pins('x.yml', 'steps:\n  - uses: actions/checkout@' + 'a' * 39 + ' # v4\n')
    assert not check_pins('x.yml', '# - uses: actions/checkout@v4\n' + good)
    assert not check_top_permissions('x.yml', 'permissions:\n  contents: read\njobs: {}\n')
    assert not check_top_permissions('x.yml', 'permissions: read-all\njobs: {}\n')
    assert check_top_permissions('x.yml', 'jobs:\n  a:\n    permissions:\n      contents: read\n')
    assert check_top_permissions('x.yml', 'permissions:\n  contents: write\njobs: {}\n')
    assert check_top_permissions('x.yml', 'permissions: write-all\njobs: {}\n')
    assert check_hosted_and_quiet('x.yml', 'runs-on: [self-hosted, macOS]\n')
    assert check_hosted_and_quiet('x.yml', 'runs-on: ubuntu-24.04\nenv:\n  T: ${{ secrets.X }}\n')
    assert check_not_required('checks-ok:\n  needs: [static, codeql]\n')
    assert not check_not_required('checks-ok:\n  needs: [static]\n')


def main():
    self_test()
    problems = run_all()
    for p in problems:
        print('::error::' + p)
    if problems:
        return 1
    print('workflow pins ok: CodeQL (%s), Scorecard, every action pinned, top-level permissions read-only'
          % ', '.join(sorted(EXPECTED_LANGUAGES)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
