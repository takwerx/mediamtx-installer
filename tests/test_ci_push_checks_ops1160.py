# SPDX-License-Identifier: AGPL-3.0-or-later
"""ops #1160: the repo's checks also run on every push to dev and main, not only on pull requests.

In the v2.1.19 test, PR 66 (click 8.5.1) and PR 67 (VENV_PINS) each passed alone. Together on dev the repo's
own pin test failed, and nothing ran after the merge to say so. These tests read pr-checks.yml and fail when
the push trigger, the concurrency group for push events, or the push-aware release-hygiene base branch is gone.
"""
import importlib.util
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / '.github' / 'workflows' / 'pr-checks.yml'


def _code():
    """The workflow without comment lines, so a word in a comment never counts."""
    text = WORKFLOW.read_text(encoding='utf-8')
    return '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))


def _on_block(code):
    m = re.search(r'^on:\s*\n((?:[ \t]+.*\n|\s*\n)+)', code + '\n', re.M)
    assert m, 'pr-checks.yml has no top-level on: block'
    return m.group(1)


def _push_branches(on):
    m = re.search(r'(?m)^  push:\s*\n(?:    .*\n)*?    branches:\s*\[([^\]]*)\]', on + '\n')
    return {b.strip() for b in m.group(1).split(',')} if m else set()


def test_checks_run_on_push_to_dev_and_main():
    # Proof test: on the base branch pr-checks.yml had only a pull_request trigger, so this fails there.
    assert _push_branches(_on_block(_code())) >= {'dev', 'main'}


def test_checks_still_run_on_pull_requests():
    on = _on_block(_code())
    assert re.search(r'(?m)^  pull_request:\s*$', on)
    assert re.search(r'(?m)^    branches:\s*\[dev, main\]', on)
    assert 'pull_request_target' not in on


def test_concurrency_group_works_for_push_events():
    # A push has no pull_request.number, so a group made only from it would put every push to dev and every
    # push to main in one group ("pr-checks-") and they would cancel each other.
    code = _code()
    group = re.search(r'(?m)^  group:\s*(.+)$', code).group(1)
    assert 'github.event.pull_request.number' in group
    assert 'github.ref' in group, 'the group needs github.ref for push events'
    cancel = re.search(r'(?m)^  cancel-in-progress:\s*(.+)$', code).group(1)
    assert "github.event_name == 'pull_request'" in cancel, 'a push run must not be cancelled by the next push'


def test_every_job_still_feeds_checks_ok():
    code = _code()
    jobs = re.findall(r'(?m)^  ([A-Za-z0-9_\-]+):\n    (?:if:.*\n    )?(?:needs:.*\n    )?(?:runs-on|name)', code)
    needs = re.search(r'checks-ok:.*?needs:\s*\[([^\]]*)\]', code, re.S).group(1)
    listed = {j.strip() for j in needs.split(',')}
    assert {'static', 'unit', 'tests', 'release-hygiene', 'workflow-pins'} <= listed
    assert set(jobs) - {'checks-ok'} <= listed, 'a job runs on push but checks-ok does not wait for it'


def _release_hygiene():
    spec = importlib.util.spec_from_file_location('release_hygiene', ROOT / '.github' / 'ci' / 'release_hygiene.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_release_hygiene_knows_the_pushed_branch():
    # Proof test: on the base branch there was no branch_for_rules, and the base was empty on a push, so a
    # push to main during a release (version ahead of the tag, no -dev) was judged like a push to dev and failed.
    rh = _release_hygiene()
    assert rh.branch_for_rules({'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': 'main', 'GITHUB_REF_TYPE': 'branch'}) == 'main'
    assert rh.branch_for_rules({'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': 'dev', 'GITHUB_REF_TYPE': 'branch'}) == 'dev'
    assert rh.branch_for_rules({'GITHUB_BASE_REF': 'main', 'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF_NAME': '9/merge'}) == 'main'
    assert rh.branch_for_rules({}) == ''
    # And the rule itself: a release in progress on main passes, the same version on dev fails.
    assert not rh.check_version((2, 1, 20), False, (2, 1, 19), rh.branch_for_rules({'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': 'main'}))
    assert rh.check_version((2, 1, 20), False, (2, 1, 19), rh.branch_for_rules({'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': 'dev'}))
