"""A box that already runs a NEWER MediaMTX than the newest release is never moved back (ops #1354).

Re-running the install scripts is how people update MediaMTX, and the console has an Upgrade button. Both fetched
"the newest release" and installed it without asking what the box runs now. A pre-release put there by hand, or a
release MediaMTX pulled, would have been replaced by an older binary, and an older MediaMTX can refuse a config that
the newer one wrote.

Run: python3 -I -m unittest discover -s tests -v   (the console tests need flask, ruamel.yaml, psutil)

The install-script tests run the real "newest release -> download -> check -> install binary" part of each script
against fake curl and wget and a fake root folder. Nothing touches the real /usr/local.
"""
import hashlib
import io
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ROCKY = os.path.join(ROOT, 'rocky-9', 'Rocky_9_MediaMTX_install.sh')
UBUNTU = os.path.join(ROOT, 'ubuntu-22.04', 'Ubuntu_22.04_MediaMTX_install.sh')
ROCKY_CADDY = os.path.join(ROOT, 'rocky-9', 'Rocky_9_Caddy_setup.sh')
EDITOR = os.path.join(ROOT, 'config-editor', 'mediamtx_config_editor.py')

RELEASE = '1.20.0'


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def write_exe(path, text):
    with open(path, 'w') as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


def version_functions(script):
    m = re.search(r'# >>> keep_newer_binary\n(.*?)# <<< keep_newer_binary\n', read(script), re.S)
    return m.group(1) if m else None


def fake_mediamtx(path, version_line):
    """A stand-in binary: prints `version_line` for --version (nothing if it is None), exits 1 otherwise."""
    body = '#!/bin/bash\n'
    if version_line is None:
        body += 'exit 0\n'
    else:
        body += '[ "$1" = "--version" ] && { echo "%s"; exit 0; }\necho "fake mediamtx"\n' % version_line
    write_exe(path, body)


class VersionFunctions(unittest.TestCase):
    """mtx_installed_version and mtx_is_newer, copied between markers in both install scripts."""

    def call(self, script, snippet, binary_text='unset'):
        fn = version_functions(script)
        self.assertIsNotNone(fn, 'no keep_newer_binary block in %s' % os.path.basename(script))
        with tempfile.TemporaryDirectory() as d:
            binpath = os.path.join(d, 'mediamtx')
            if binary_text != 'unset':
                fake_mediamtx(binpath, binary_text)
            r = subprocess.run(['bash', '-c', fn + snippet.replace('BIN', binpath)],
                               capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout.strip()

    def test_is_newer_table(self):
        cases = [('1.21.0', '1.20.0', True), ('1.20.1', '1.20.0', True), ('2.0.0', '1.99.9', True),
                 ('1.10.0', '1.9.0', True),              # a string compare gets this one wrong
                 ('1.20.0', '1.20.0', False), ('1.19.9', '1.20.0', False), ('1.9.0', '1.10.0', False),
                 ('', '1.20.0', False), ('1.20.0', '', False), ('unknown', '1.20.0', False),
                 ('1.21', '1.20.0', False)]
        for script in (ROCKY, UBUNTU):
            for installed, release, want in cases:
                rc, _ = self.call(script, 'mtx_is_newer "%s" "%s"' % (installed, release))
                self.assertEqual(rc == 0, want, '%s: installed %r vs release %r' % (os.path.basename(script), installed, release))

    def test_reads_the_installed_version(self):
        for script in (ROCKY, UBUNTU):
            for text, want in [('v1.16.1', '1.16.1'), ('1.21.0', '1.21.0'), ('mediamtx v1.99.0 (build x)', '1.99.0')]:
                _, out = self.call(script, 'mtx_installed_version BIN', binary_text=text)
                self.assertEqual(out, want)

    def test_no_binary_or_no_version_prints_nothing(self):
        for script in (ROCKY, UBUNTU):
            _, out = self.call(script, 'mtx_installed_version BIN')          # no file at all
            self.assertEqual(out, '')
            _, out = self.call(script, 'mtx_installed_version BIN', binary_text=None)   # prints nothing
            self.assertEqual(out, '')
            _, out = self.call(script, 'mtx_installed_version BIN', binary_text='no version here')
            self.assertEqual(out, '')


class InstallScriptKeepsNewerBinary(unittest.TestCase):
    """Run the release lookup, download, checksum and binary-install part of each script in a fake root."""

    def region(self, script):
        lines = read(script).splitlines(keepends=True)
        start = next(i for i, l in enumerate(lines) if '# Get latest version from GitHub' in l)
        marker = 'Step 6: Configuring Credentials' if script == ROCKY else 'Step 5: Installing Custom Configuration'
        stop = next(i for i, l in enumerate(lines) if marker in l) - 2
        if script == UBUNTU:
            # Ubuntu's step 5 builds a big config in place; the binary part is all before it.
            pass
        return ''.join(lines[start:stop])

    def run_region(self, script, installed_line, config_exists=True):
        """installed_line: what the installed fake binary prints for --version (None = no binary at all)."""
        with tempfile.TemporaryDirectory() as d:
            fake_root = os.path.join(d, 'root')
            os.makedirs(fake_root + '/usr/local/bin')
            os.makedirs(fake_root + '/usr/local/etc')
            if installed_line is not False:
                fake_mediamtx(fake_root + '/usr/local/bin/mediamtx', installed_line)
            if config_exists:
                with open(fake_root + '/usr/local/etc/mediamtx.yml', 'w') as f:
                    f.write('# the operator config\n')
            # The "release": a tarball with a binary that says it is the release, and a checksum list.
            relbin = os.path.join(d, 'mediamtx')
            write_exe(relbin, '#!/bin/bash\n[ "$1" = "--version" ] && { echo "v%s"; exit 0; }\necho "release binary"\n' % RELEASE)
            with open(os.path.join(d, 'mediamtx.yml'), 'w') as f:
                f.write('# upstream config\n')
            tarball = os.path.join(d, 'release.tar.gz')
            with tarfile.open(tarball, 'w:gz') as t:
                t.add(relbin, arcname='mediamtx')
                t.add(os.path.join(d, 'mediamtx.yml'), arcname='mediamtx.yml')
            with open(tarball, 'rb') as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            stubs = os.path.join(d, 'stubs')
            os.makedirs(stubs)
            write_exe(stubs + '/curl', '#!/bin/bash\necho \'  "tag_name": "v%s",\'\n' % RELEASE)
            write_exe(stubs + '/wget',
                      '#!/bin/bash\nout=""; url=""\n'
                      'while [ $# -gt 0 ]; do case "$1" in -O) out="$2"; shift;; -q) ;; *) url="$1";; esac; shift; done\n'
                      'case "$url" in\n'
                      '  *checksums.sha256) echo "%s  mediamtx_v%s_linux_${FAKE_ARCH}.tar.gz" > "$out";;\n'
                      '  *.tar.gz) cp "%s" "$out";;\n'
                      '  *) exit 1;;\nesac\n' % (digest, RELEASE, tarball))
            body = self.region(script).replace('/usr/local/', fake_root + '/usr/local/')
            # MEDIAMTX_ARCH is set by the script's architecture step, which is before the region: set it here.
            arch = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(os.uname().machine, 'amd64')
            program = ('set -e\nMEDIAMTX_ARCH=%s\n' % arch) + body
            env = dict(os.environ, PATH=stubs + os.pathsep + os.environ['PATH'], FAKE_ARCH=arch)
            r = subprocess.run(['bash', '-c', program], env=env, capture_output=True, text=True, timeout=60)
            result = subprocess.run([fake_root + '/usr/local/bin/mediamtx', '--version'], capture_output=True, text=True) \
                if os.path.exists(fake_root + '/usr/local/bin/mediamtx') else None
            return r, (result.stdout.strip() if result else None)

    def test_newer_installed_binary_is_kept(self):
        for script in (ROCKY, UBUNTU):
            r, now = self.run_region(script, 'v1.99.0')
            self.assertEqual(r.returncode, 0, os.path.basename(script) + ': ' + r.stdout + r.stderr)
            self.assertEqual(now, 'v1.99.0', os.path.basename(script) + ' moved a newer MediaMTX back to the release')
            self.assertIn('newer than the newest release', r.stdout)

    def test_older_installed_binary_is_updated_as_before(self):
        for script in (ROCKY, UBUNTU):
            r, now = self.run_region(script, 'v1.10.0')
            self.assertEqual(r.returncode, 0, os.path.basename(script) + ': ' + r.stdout + r.stderr)
            self.assertEqual(now, 'v' + RELEASE, os.path.basename(script) + ' did not update an older MediaMTX')

    def test_same_version_is_reinstalled_as_before(self):
        for script in (ROCKY, UBUNTU):
            r, now = self.run_region(script, 'v' + RELEASE)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(now, 'v' + RELEASE)

    def test_a_binary_that_prints_no_version_is_replaced_as_before(self):
        for script in (ROCKY, UBUNTU):
            r, now = self.run_region(script, None)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(now, 'v' + RELEASE, os.path.basename(script) + ' left a binary it could not read')

    def test_fresh_install_has_no_binary_to_compare(self):
        for script in (ROCKY, UBUNTU):
            r, now = self.run_region(script, False, config_exists=False)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(now, 'v' + RELEASE)


class RockyCaddyKeepsWhatIsThere(unittest.TestCase):
    """Rocky's Caddy script ran "dnf install caddy" every time. Now it skips a Caddy that is already installed."""

    def run_guard(self, caddy_present):
        m = re.search(r'# >>> caddy_install_guard\n(.*?)# <<< caddy_install_guard\n', read(ROCKY_CADDY), re.S)
        self.assertIsNotNone(m, 'no caddy_install_guard block in the Rocky Caddy script')
        with tempfile.TemporaryDirectory() as d:
            stubs = os.path.join(d, 'stubs')
            os.makedirs(stubs)
            log = os.path.join(d, 'dnf.log')
            write_exe(stubs + '/dnf', '#!/bin/bash\necho "$*" >> "%s"\n' % log)
            write_exe(stubs + '/rpm', '#!/bin/bash\nexit 1\n')   # rpm -q caddy: not installed
            if caddy_present:
                write_exe(stubs + '/caddy', '#!/bin/bash\necho "v2.99.0 h1:fake"\n')
            # A PATH of only the stubs and the system tools, so a real caddy on the machine running the test is not seen.
            env = dict(os.environ, PATH=stubs + os.pathsep + '/usr/bin:/bin')
            for tool in ('caddy',):
                if not caddy_present and os.path.exists('/usr/bin/' + tool):
                    self.skipTest('the machine running this test has its own caddy in /usr/bin')
            r = subprocess.run(['bash', '-c', m.group(1)], env=env, capture_output=True, text=True, timeout=30)
            calls = read(log).splitlines() if os.path.exists(log) else []
        return r, calls

    def test_installed_caddy_is_left_alone(self):
        r, calls = self.run_guard(True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, [], 'dnf ran although Caddy was already installed: %s' % calls)
        self.assertIn('already installed', r.stdout)

    def test_missing_caddy_is_installed(self):
        r, calls = self.run_guard(False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('install -y caddy', calls)


# ----------------------------------------------------------------------------------------------------------------
# The console route
# ----------------------------------------------------------------------------------------------------------------
class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def load_editor(sandbox):
    src = read(EDITOR)
    src = src.replace('/usr/local/', sandbox + '/usr/local/').replace('/opt/', sandbox + '/opt/')
    os.makedirs(sandbox + '/usr/local/etc', exist_ok=True)
    os.makedirs(sandbox + '/opt/mediamtx-webeditor', exist_ok=True)
    mod = types.ModuleType('mediamtx_config_editor_ops1354')
    mod.__file__ = EDITOR
    sys.modules[mod.__name__] = mod
    exec(compile(src, EDITOR, 'exec'), mod.__dict__)
    return mod


# The refusal itself is code from the ops #1316 change (PR 82, "only ever go forward"). Until that change is on this
# branch the route has no such code, so these three tests skip with that reason; they run as soon as it lands.
EDITOR_HAS_FORWARD_GUARD = 'Only ever go forward' in read(EDITOR) and 'def parse_mtx_version' in read(EDITOR)


@unittest.skipUnless(EDITOR_HAS_FORWARD_GUARD, 'the editor route guard comes with ops #1316 (PR 82), not on this branch yet')
class UpgradeRouteKeepsNewer(unittest.TestCase):
    """This keeps the #1354 promise in its own test: a newer installed MediaMTX is never replaced through the Upgrade
    route, and nothing is downloaded."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = load_editor(self._tmp.name)
        self.client = self.mod.app.test_client()
        with self.client.session_transaction() as s:
            s['logged_in'] = True
            s['role'] = 'admin'

    def post_upgrade(self, installed_stdout, release='v1.20.0'):
        arch = self.mod.MEDIAMTX_ARCH
        asset = 'mediamtx_%s_linux_%s.tar.gz' % (release, arch)
        data = {'tag_name': release, 'assets': [
            {'name': asset, 'browser_download_url': 'https://example.invalid/' + asset},
            {'name': 'checksums.sha256', 'browser_download_url': 'https://example.invalid/checksums.sha256'}]}
        fetched = []

        def fake_urlopen(req, *a, **k):
            fetched.append(getattr(req, 'full_url', req))
            raise RuntimeError('download reached')       # past the guard: the route's own catch-all answers 500

        def fake_run(argv, *a, **k):
            return types.SimpleNamespace(returncode=0, stdout=installed_stdout, stderr='')

        with mock.patch.object(self.mod, 'github_latest_release', return_value=(data, {'checked_at': '', 'stale': False, 'notice': ''})), \
             mock.patch.object(self.mod, 'mtx_priv_mode', return_value='direct'), \
             mock.patch.object(self.mod, 'mtx_systemctl', return_value=types.SimpleNamespace(returncode=0, stderr=b'')), \
             mock.patch.object(self.mod.subprocess, 'run', side_effect=fake_run), \
             mock.patch('urllib.request.urlopen', side_effect=fake_urlopen):
            resp = self.client.post('/api/mediamtx/version/upgrade')
        return resp, fetched

    def test_newer_installed_is_refused_before_any_download(self):
        resp, fetched = self.post_upgrade('v1.99.0')
        body = resp.get_json()
        self.assertEqual(resp.status_code, 400, body)
        self.assertIn('Nothing was changed', body['error'])
        self.assertEqual(fetched, [], 'the route downloaded a release although the box is newer')

    def test_older_installed_still_goes_on_to_download(self):
        resp, fetched = self.post_upgrade('v1.10.0')
        self.assertTrue(fetched, 'an older MediaMTX was not upgraded any more')

    def test_unreadable_version_still_goes_on_as_before(self):
        resp, fetched = self.post_upgrade('')
        self.assertTrue(fetched)


if __name__ == '__main__':
    unittest.main()
