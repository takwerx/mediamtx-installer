# SPDX-License-Identifier: AGPL-3.0-or-later
"""ops #1014 step 4: the CI test jobs install their packages by hash, and test what customers run.

.github/ci/requirements-tests.lock is what the unit-test jobs install (pip --require-hashes). Its
pins for the console's own packages must equal config-editor/requirements.txt and
requirements-psutil.txt, so a green test run means the versions customers get were tested.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CI = ROOT / '.github' / 'ci'


def _pins(path):
    out = {}
    for l in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^([A-Za-z0-9_.\-]+)==([^\s;\\#]+)', l)
        if m:
            out[m.group(1).lower().replace('_', '-').replace('.', '-')] = m.group(2)
    return out


def test_every_lock_pin_has_a_hash():
    for f in sorted(CI.glob('*.lock')):
        blocks = re.split(r'\n(?=[A-Za-z0-9_.\-]+==)', f.read_text(encoding='utf-8'))
        pins = [b for b in blocks if re.match(r'^[A-Za-z0-9_.\-]+==', b)]
        assert pins, f.name
        for b in pins:
            assert '--hash=sha256:' in b, f'{f.name}: no hash for {b.splitlines()[0]}'


def test_tests_lock_has_the_same_versions_as_the_console_pins():
    product = {}
    for name in ('requirements.txt', 'requirements-psutil.txt'):
        product.update(_pins(ROOT / 'config-editor' / name))
    assert product, 'no console pins found'
    lock = _pins(CI / 'requirements-tests.lock')
    constraints = _pins(CI / 'requirements-tests.constraints')
    for name, ver in product.items():
        assert constraints.get(name) == ver, f'{name}: constraints file has {constraints.get(name)}, console pins {ver}'
        assert lock.get(name) == ver, (
            f'{name}: requirements-tests.lock has {lock.get(name)} but the console pins {ver}; '
            'regenerate it (command in the lock header)')


def test_static_lock_pins_shellcheck():
    assert _pins(CI / 'requirements-static.lock').get('shellcheck-py') == '0.11.0.1'
