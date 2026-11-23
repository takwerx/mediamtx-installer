# SPDX-License-Identifier: AGPL-3.0-or-later
"""ops #1014 step 4 and ops #1112: the CI test jobs install their packages by hash, and test what customers run.

The unit-test jobs install config-editor/requirements.txt and requirements-psutil.txt (the console's own
pins, the files customers get) plus .github/ci/requirements-testtools.lock (the test runner only), all with
pip --require-hashes. There is one copy of every console pin, so a Dependabot bump of requirements.txt is
the whole change: nothing else has to be relocked by hand (before ops #1112 a second constraints file and a
second hash lock had to agree, and every Dependabot python PR went red).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CI = ROOT / '.github' / 'ci'
CONSOLE_FILES = ('requirements.txt', 'requirements-psutil.txt')
TEST_JOBS = ('unit', 'tests')


def _name(raw):
    return raw.lower().replace('_', '-').replace('.', '-')


def _pins(text):
    out = {}
    for l in text.splitlines():
        m = re.match(r'^([A-Za-z0-9_.\-]+)==([^\s;\\#]+)', l)
        if m:
            out[_name(m.group(1))] = m.group(2)
    return out


def _console_pins():
    pins = {}
    for name in CONSOLE_FILES:
        pins.update(_pins((ROOT / 'config-editor' / name).read_text(encoding='utf-8')))
    return pins


def doubled_pins(console, tools):
    """Packages pinned in both the console files and the tools lock. Two sources for one package is how
    the lock fell out of step with the console before ops #1112."""
    return sorted(n for n in console if n in tools)


def job_installs(workflow, job):
    """The pip install lines of one job in pr-checks.yml (text between its 'job:' key and the next job)."""
    m = re.search(r'(?ms)^  %s:\n(.*?)(?=^  [A-Za-z0-9_\-]+:\n|\Z)' % re.escape(job), workflow)
    assert m, f'job {job} not found in pr-checks.yml'
    return [l for l in m.group(1).splitlines() if re.search(r'\bpip3?\s+install\b', l) and not l.lstrip().startswith('#')]


def missing_console_files(line):
    """The console requirements files a pip install line does not read (empty when it reads both)."""
    return [f for f in CONSOLE_FILES if not re.search(r'-r\s+config-editor/%s(\s|$)' % re.escape(f), line)]


def test_every_lock_pin_has_a_hash():
    for f in sorted(CI.glob('*.lock')):
        blocks = re.split(r'\n(?=[A-Za-z0-9_.\-]+==)', f.read_text(encoding='utf-8'))
        pins = [b for b in blocks if re.match(r'^[A-Za-z0-9_.\-]+==', b)]
        assert pins, f.name
        for b in pins:
            assert '--hash=sha256:' in b, f'{f.name}: no hash for {b.splitlines()[0]}'


def test_test_jobs_install_the_console_pins_themselves():
    # Proof test (ops #1112): on the base branch the jobs installed a separate lock, so this fails there.
    workflow = (ROOT / '.github' / 'workflows' / 'pr-checks.yml').read_text(encoding='utf-8')
    for job in TEST_JOBS:
        lines = job_installs(workflow, job)
        assert len(lines) == 1, f'{job}: expected one pip install line, found {lines}'
        assert '--require-hashes' in lines[0], f'{job}: pip install must use --require-hashes'
        assert not missing_console_files(lines[0]), f'{job}: does not install {missing_console_files(lines[0])}'
        assert re.search(r'-r\s+\.github/ci/requirements-testtools\.lock\b', lines[0]), f'{job}: tools lock missing'


def test_tools_lock_does_not_pin_a_console_package():
    # Proof test (ops #1112): on the base branch the lock pinned flask, requests, click and the rest a second
    # time, so a Dependabot bump of requirements.txt alone left the two out of step and this failed.
    console = _console_pins()
    assert console, 'no console pins found'
    tools = _pins((CI / 'requirements-testtools.lock').read_text(encoding='utf-8'))
    assert tools.get('pytest'), 'pytest is not in the tools lock'
    assert not doubled_pins(console, tools), f'pinned in both the console files and the tools lock: {doubled_pins(console, tools)}'
    constraints = CI / 'requirements-tests.constraints'
    assert not constraints.exists(), 'the constraints copy of the console pins is gone (ops #1112); do not bring it back'


def test_the_checks_above_go_red_on_purpose():
    # The checks must catch what they claim to: a second copy of a console pin, and a job that skips the console files.
    assert doubled_pins({'click': '8.5.1', 'flask': '3.1.3'}, {'click': '8.1.8', 'pytest': '9.2.0'}) == ['click']
    assert not doubled_pins({'click': '8.5.1'}, {'pytest': '9.2.0'})
    good = '      - run: pip install --require-hashes -r config-editor/requirements.txt -r config-editor/requirements-psutil.txt -r .github/ci/requirements-testtools.lock'
    assert not missing_console_files(good)
    assert missing_console_files('      - run: pip install --require-hashes -r .github/ci/requirements-testtools.lock') == list(CONSOLE_FILES)
    assert missing_console_files('      - run: pip install --require-hashes -r config-editor/requirements.txt -r .github/ci/x.lock') == ['requirements-psutil.txt']
    wf = 'jobs:\n  unit:\n    steps:\n      - run: pip install a\n  tests:\n    steps:\n      - run: pip install b\n'
    assert job_installs(wf, 'unit') == ['      - run: pip install a']
    assert job_installs(wf, 'tests') == ['      - run: pip install b']


def test_static_lock_pins_shellcheck():
    assert _pins((CI / 'requirements-static.lock').read_text(encoding='utf-8')).get('shellcheck-py') == '0.11.0.1'
