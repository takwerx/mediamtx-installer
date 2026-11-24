"""Everything root downloads must be checked against a checksum first (ops #623).

Run: python3 -I -m unittest discover -s tests -v   (needs flask, ruamel.yaml, psutil)

The console file writes to /opt and /usr/local at import time, so, like the
verify-console-ui skill, every such path is rewritten into a temp sandbox first.
"""
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
import urllib.request
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
EDITOR = os.path.join(ROOT, 'config-editor', 'mediamtx_config_editor.py')
GOOD = b'genuine bytes'
EVIL = b'tampered bytes'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_editor(sandbox):
    with open(EDITOR, encoding='utf-8') as f:
        src = f.read()
    src = src.replace('/usr/local/', sandbox + '/usr/local/').replace('/opt/', sandbox + '/opt/')
    os.makedirs(sandbox + '/usr/local/etc', exist_ok=True)
    os.makedirs(sandbox + '/opt/mediamtx-webeditor', exist_ok=True)
    mod = types.ModuleType('mediamtx_config_editor_under_test')
    mod.__file__ = EDITOR
    sys.modules[mod.__name__] = mod
    exec(compile(src, EDITOR, 'exec'), mod.__dict__)
    return mod


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class EditorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = load_editor(self._tmp.name)
        self.client = self.mod.app.test_client()
        with self.client.session_transaction() as s:
            s['logged_in'] = True
            s['role'] = 'admin'
            s['username'] = 'admin'


class ParseChecksumsTest(EditorTestCase):
    def test_both_sha256sum_formats_and_junk(self):
        a, b = 'a' * 64, 'b' * 64
        got = self.mod.parse_checksums(f'{a} *one.tar.gz\n{b}  two.tar.gz\nnot a checksum line\n\n')
        self.assertEqual(got, {'one.tar.gz': a, 'two.tar.gz': b})


class MediaMTXUpgradeChecksumTest(EditorTestCase):
    """The console's own MediaMTX upgrade must verify the tarball before unpacking it."""

    def _run_upgrade(self, tar_bytes, sums_text, with_sums_asset=True):
        arch = self.mod.MEDIAMTX_ARCH
        name = f'mediamtx_v9.9.9_linux_{arch}.tar.gz'
        base = 'https://example.test/dl/'
        assets = [{'name': name, 'browser_download_url': base + name}]
        if with_sums_asset:
            assets.append({'name': 'checksums.sha256', 'browser_download_url': base + 'checksums.sha256'})
        release = ('{"tag_name": "v9.9.9", "assets": %s}' % __import__('json').dumps(assets)).encode()
        bodies = {self.mod.MEDIAMTX_GITHUB_API: release, base + name: tar_bytes,
                  base + 'checksums.sha256': sums_text.encode()}

        def fake_urlopen(req, *a, **kw):
            return FakeResponse(bodies[req.full_url])

        reached_extract = []

        def fake_tar_open(*a, **kw):
            reached_extract.append(True)
            raise RuntimeError('reached-extract')

        self.mod.mtx_priv_mode = lambda: 'root'
        with mock.patch.object(urllib.request, 'urlopen', fake_urlopen), \
                mock.patch.object(tarfile, 'open', fake_tar_open):
            resp = self.client.post('/api/mediamtx/version/upgrade')
        return resp, bool(reached_extract), name

    def test_tampered_tarball_is_refused_before_extraction(self):
        good_tar = b'the real tarball'
        resp, extracted, name = self._run_upgrade(b'evil tarball', f'{sha(good_tar)} *mediamtx_v9.9.9_linux_{self.mod.MEDIAMTX_ARCH}.tar.gz\n')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Checksum mismatch', resp.get_json()['error'])
        self.assertFalse(extracted, 'tarball was unpacked despite a checksum mismatch')

    def test_no_checksums_asset_is_refused(self):
        resp, extracted, _ = self._run_upgrade(GOOD, '', with_sums_asset=False)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('checksums.sha256', resp.get_json()['error'])
        self.assertFalse(extracted)

    def test_missing_entry_is_refused(self):
        resp, extracted, _ = self._run_upgrade(GOOD, f'{sha(GOOD)} *some_other_file.tar.gz\n')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('no entry', resp.get_json()['error'])
        self.assertFalse(extracted)

    def test_matching_tarball_goes_on_to_extraction(self):
        name = f'mediamtx_v9.9.9_linux_{self.mod.MEDIAMTX_ARCH}.tar.gz'
        resp, extracted, _ = self._run_upgrade(GOOD, f'{sha(GOOD)} *{name}\n')
        self.assertTrue(extracted)
        self.assertIn('reached-extract', resp.get_json()['error'])


class GstPluginPinTest(EditorTestCase):
    def test_pin_matches_the_committed_plugin(self):
        # Rebuilding the .so without updating GST_RTSPSINK_SO_SHA256 must fail here.
        with open(os.path.join(ROOT, 'config-editor', 'assets', 'gst', 'el9', 'libgstrtspclientsink.so'), 'rb') as f:
            self.assertEqual(sha(f.read()), self.mod.GST_RTSPSINK_SO_SHA256['9'])

    def test_every_committed_plugin_has_a_pin(self):
        gst = os.path.join(ROOT, 'config-editor', 'assets', 'gst')
        for el in os.listdir(gst):
            if os.path.isdir(os.path.join(gst, el)):
                self.assertIn(el[2:], self.mod.GST_RTSPSINK_SO_SHA256, f'{el} plugin has no pinned checksum')

    def _post_gstreamer_update(self, so_bytes):
        """Drive /api/deps/update as an unprivileged console on Rocky: it fetches only the plugin."""
        self.mod.GST_LOCAL_PLUGIN_DIR = os.path.join(self._tmp.name, 'gstplugins')
        self.mod._host_pkg_mgr = lambda: 'dnf'
        self.mod._broker_available = lambda: False
        self.mod._el_major = lambda: '9'
        self.mod._detect_gstreamer = lambda: {'version': '1.22.12'}
        self.mod.shutil.which = lambda name: '/usr/bin/' + name
        fail = lambda cmd, *a, **kw: subprocess.CompletedProcess(cmd, 1, b'', b'')  # no sudo, no plugin yet
        with mock.patch.object(os, 'geteuid', lambda: 1000), \
                mock.patch.object(urllib.request, 'urlopen', lambda *a, **kw: FakeResponse(so_bytes)), \
                mock.patch.object(subprocess, 'run', fail):
            resp = self.client.post('/api/deps/update', json={'component': 'gstreamer'})
        return resp, os.path.join(self.mod.GST_LOCAL_PLUGIN_DIR, 'libgstrtspclientsink.so')

    def test_tampered_plugin_is_not_installed(self):
        resp, dest = self._post_gstreamer_update(b'\x7fELF' + b'x' * 20000)
        self.assertEqual(resp.status_code, 500, resp.get_data(as_text=True))
        self.assertIn('checksum mismatch', resp.get_json()['error'])
        self.assertFalse(os.path.exists(dest))

    def test_genuine_plugin_is_still_installed(self):
        with open(os.path.join(ROOT, 'config-editor', 'assets', 'gst', 'el9', 'libgstrtspclientsink.so'), 'rb') as f:
            genuine = f.read()
        resp, dest = self._post_gstreamer_update(genuine)
        self.assertNotIn('checksum', resp.get_json().get('error', ''), resp.get_data(as_text=True))
        self.assertTrue(os.path.exists(dest))


class NetBirdInstallPinTest(EditorTestCase):
    def test_url_is_a_pinned_release_not_latest(self):
        self.assertRegex(self.mod.NETBIRD_INSTALL_URL,
                         r'^https://github\.com/netbirdio/netbird/releases/download/v\d+\.\d+\.\d+/install\.sh$')
        self.assertRegex(self.mod.NETBIRD_INSTALL_SHA256, r'^[0-9a-f]{64}$')

    def test_no_curl_pipe_shell_left(self):
        with open(EDITOR, encoding='utf-8') as f:
            src = f.read()
        self.assertNotRegex(src, r'curl[^\n]*\|\s*(sudo\s+)?(sh|bash)\b')

    def test_tampered_script_is_not_run(self):
        ran = []
        with mock.patch.object(urllib.request, 'urlopen', lambda *a, **kw: FakeResponse(EVIL)), \
                mock.patch.object(subprocess, 'run', lambda *a, **kw: ran.append(a)):
            err = self.mod.install_netbird_agent()
        self.assertIn('does not match the checksum', err)
        self.assertEqual(ran, [], 'a script that failed the checksum was executed')

    def test_connect_endpoint_refuses_tampered_script(self):
        ran = []
        self.mod.shutil.which = lambda name: None
        with mock.patch.object(urllib.request, 'urlopen', lambda *a, **kw: FakeResponse(EVIL)), \
                mock.patch.object(subprocess, 'run', lambda *a, **kw: ran.append(a)):
            resp = self.client.post('/api/netbird/connect',
                                    json={'setupKey': 'k', 'managementUrl': 'https://nb.example'})
        self.assertEqual(resp.status_code, 500)
        self.assertIn('does not match the checksum', resp.get_json()['error'])
        self.assertEqual(ran, [])

    def test_matching_script_runs_once_from_a_private_file(self):
        self.mod.NETBIRD_INSTALL_SHA256 = sha(GOOD)
        ran = []
        with mock.patch.object(urllib.request, 'urlopen', lambda *a, **kw: FakeResponse(GOOD)), \
                mock.patch.object(subprocess, 'run', lambda cmd, *a, **kw: ran.append(cmd)):
            self.assertIsNone(self.mod.install_netbird_agent())
        self.assertEqual(len(ran), 1)
        self.assertEqual(ran[0][:2], ['sudo', 'sh'])
        self.assertFalse(os.path.exists(ran[0][2]), 'script was left on disk')


class InstallerChecksumTest(unittest.TestCase):
    """Run the real checksum block from each MediaMTX install script against fake downloads."""

    SCRIPTS = ['ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh', 'rocky-9/Rocky_9_MediaMTX_install.sh']

    def _block(self, path):
        with open(os.path.join(ROOT, path), encoding='utf-8') as f:
            src = f.read()
        m = re.search(r'^TARBALL_NAME=.*?^echo "✓ Checksum verified.*?$', src, re.S | re.M)
        self.assertIsNotNone(m, f'{path} has no checksum block')
        return m.group(0), src

    def _run(self, block, tarball, checksums):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'mediamtx.tar.gz'), 'wb') as f:
                f.write(tarball)
            with open(os.path.join(d, 'served-checksums'), 'w') as f:
                f.write(checksums)
            script = ('set -e\ncd "$1"\nLATEST_VERSION=9.9.9\nMEDIAMTX_ARCH=amd64\n'
                      'wget() { cp served-checksums "$3"; }\n'
                      'if ! command -v sha256sum >/dev/null; then sha256sum() { shasum -a 256 "$@"; }; fi\n'
                      + block + '\necho REACHED-UNPACK\n')
            return subprocess.run(['bash', '-c', script, 'x', d], capture_output=True, text=True)

    def test_installers_verify_before_unpacking(self):
        for path in self.SCRIPTS:
            block, src = self._block(path)
            self.assertLess(src.index('TARBALL_NAME='), src.index('tar -xzf'), path)
            name = 'mediamtx_v9.9.9_linux_amd64.tar.gz'
            ok = self._run(block, GOOD, f'{sha(GOOD)} *{name}\n')
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn('REACHED-UNPACK', ok.stdout)
            bad = self._run(block, EVIL, f'{sha(GOOD)} *{name}\n')
            self.assertNotEqual(bad.returncode, 0, path)
            self.assertIn('Checksum mismatch', bad.stdout)
            self.assertNotIn('REACHED-UNPACK', bad.stdout)
            absent = self._run(block, GOOD, f'{sha(GOOD)} *other.tar.gz\n')
            self.assertNotEqual(absent.returncode, 0, path)
            self.assertNotIn('REACHED-UNPACK', absent.stdout)


class PythonPackagePinTest(unittest.TestCase):
    def _text(self, rel):
        with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
            return f.read()

    def _pins(self):
        """{name: [versions]} of every pin in requirements.txt and requirements-psutil.txt."""
        pins = {}
        for rel in ('config-editor/requirements.txt', 'config-editor/requirements-psutil.txt'):
            for m in re.finditer(r'(?m)^([A-Za-z0-9_.\-]+)==([^\s\\;]+)', self._text(rel)):
                pins.setdefault(re.sub(r'[-_.]+', '-', m.group(1)).lower(), []).append(m.group(2))
        return pins

    def test_each_package_has_exactly_one_pin_and_no_python_marker(self):
        # No `; python_version` lines: Python 3.9 is not supported any more (ops #1030), so there is one
        # pin per package. Two pins that both apply would make pip refuse the file (ops #1020).
        for name, vers in self._pins().items():
            self.assertEqual(len(vers), 1, '%s pinned more than once: %s' % (name, vers))
        for rel in ('config-editor/requirements.txt', 'config-editor/requirements-psutil.txt'):
            self.assertNotIn('python_version', self._text(rel), rel)

    def test_urllib3_and_requests_are_the_fixed_releases(self):
        # urllib3 2.8.0 and requests 2.33.0 are the first releases with the fixes (ops #1020). They need
        # Python 3.10, which is why Rocky 9 builds the editor's venv from python3.12 (ops #1030). Proof
        # test: on the Python 3.9 base this file had a second, older pin for 3.9 and this fails.
        floor = {'urllib3': (2, 8, 0), 'requests': (2, 33, 0)}
        as_tuple = lambda v: tuple(int(x) for x in v.split('.'))
        pins = self._pins()
        for name, minimum in floor.items():
            self.assertGreaterEqual(as_tuple(pins[name][0]), minimum, name)
        self.assertNotIn('2.6.3', pins['urllib3'])
        self.assertNotIn('2.32.5', pins['requests'])

    def test_certifi_is_the_november_2026_ca_bundle(self):
        # certifi 2026.11.20 is the CA bundle refresh the Security lead's upgrade watch asked for (ops #1090).
        # A floor, not an exact version, so a later Dependabot bump of certifi stays green (ops #1112). The hashes
        # of the pinned release are checked for every package by test_every_package_is_pinned_with_hashes, and CI
        # installs this same file, so there is no second copy to keep equal. Proof test: on the 2026.10.23 base
        # this fails.
        as_tuple = lambda v: tuple(int(x) for x in v.split('.'))
        self.assertGreaterEqual(as_tuple(self._pins()['certifi'][0]), (2026, 11, 20))

    def test_every_package_is_pinned_with_hashes(self):
        for rel in ('config-editor/requirements.txt', 'config-editor/requirements-psutil.txt'):
            body = re.sub(r'\s*\\\n\s*', ' ', self._text(rel))
            entries = [l for l in body.splitlines() if l.strip() and not l.lstrip().startswith('#')]
            self.assertTrue(entries, rel)
            for line in entries:
                self.assertRegex(line, r'^[A-Za-z0-9_.\-]+==[0-9][^\s]* (--hash=sha256:[0-9a-f]{64} ?)+$', line)

    def test_every_import_is_covered(self):
        names = ''.join(self._text('config-editor/' + r).lower() for r in ('requirements.txt', 'requirements-psutil.txt'))
        for pkg in ('flask', 'ruamel.yaml', 'requests', 'psutil'):
            self.assertIn(pkg + '==', names)

    def test_dependency_tree_is_pinned_for_every_supported_python(self):
        # What pip pulls in on Python 3.10 (Ubuntu 22.04) through 3.13 (python3.12 is Rocky 9's) must all be
        # pinned with == and hashes, or the installer stops with "all requirements must have their versions
        # pinned with ==" (ops #646). pip's own resolver reads markers for the Python that runs it, so read each
        # pinned release's published requirements from PyPI and apply those Pythons' markers here. Needs
        # network; skipped without.
        try:
            from packaging.requirements import Requirement
        except ImportError:
            from pip._vendor.packaging.requirements import Requirement
        import json
        norm = lambda n: re.sub(r'[-_.]+', '-', n).lower()
        pinned = {n: v[0] for n, v in self._pins().items()}
        self.assertTrue(pinned)
        infos = {}
        for name, ver in sorted(pinned.items()):
            try:
                with urllib.request.urlopen('https://pypi.org/pypi/%s/%s/json' % (name, ver), timeout=30) as r:
                    infos[name] = json.load(r)['info']
            except OSError as e:
                self.skipTest('PyPI not reachable: %s' % e)
        missing = set()
        for py in ('3.10', '3.12', '3.13'):
            env = {'python_version': py, 'python_full_version': py + '.0', 'sys_platform': 'linux',
                   'platform_system': 'Linux', 'os_name': 'posix', 'implementation_name': 'cpython',
                   'platform_python_implementation': 'CPython', 'extra': ''}
            for name, info in infos.items():
                for line in info.get('requires_dist') or []:
                    req = Requirement(line)
                    if req.marker is not None and not req.marker.evaluate(env):
                        continue
                    if norm(req.name) not in pinned:
                        missing.add('%s (needed by %s==%s on Python %s)' % (req.name, name, pinned[name], py))
        self.assertEqual(sorted(missing), [], 'not pinned with == and hashes in requirements.txt')

    def test_every_pinned_release_supports_python_310_through_313(self):
        # Ubuntu 22.04 runs Python 3.10 and Rocky 9's editor venv runs python3.12 (ops #1030). A pin whose
        # release needs a newer Python, or does not support 3.13 yet, makes the whole
        # `pip install --require-hashes` fail on that box (ops #683). Needs network; skipped without.
        try:
            from packaging.specifiers import SpecifierSet
        except ImportError:
            from pip._vendor.packaging.specifiers import SpecifierSet
        import json
        pinned = {n: v[0] for n, v in self._pins().items()}
        self.assertTrue(pinned)
        bad = []
        for name, ver in sorted(pinned.items()):
            try:
                with urllib.request.urlopen('https://pypi.org/pypi/%s/%s/json' % (name, ver), timeout=30) as r:
                    spec = json.load(r)['info'].get('requires_python') or ''
            except OSError as e:
                self.skipTest('PyPI not reachable: %s' % e)
            for py in ('3.10.0', '3.12.0', '3.13.0'):
                if spec and not SpecifierSet(spec).contains(py):
                    bad.append('%s==%s needs Python %s, not %s' % (name, ver, spec, py))
        self.assertEqual(bad, [], 'pinned releases that do not install on a supported Python')

    def test_dependabot_pip_updates_go_to_dev_and_may_move_urllib3_and_requests(self):
        # urllib3 and requests used to be held back for Python 3.9 (ops #683); that hold is gone (ops #1030),
        # so Dependabot may bump them again. Only major versions stay out of the automatic PRs.
        from ruamel.yaml import YAML
        cfg = YAML(typ='safe').load(self._text('.github/dependabot.yml'))
        pip = [u for u in cfg['updates'] if u['package-ecosystem'] == 'pip']
        self.assertEqual(len(pip), 1)
        self.assertEqual(pip[0]['target-branch'], 'dev')
        self.assertEqual(pip[0]['directory'], '/config-editor')
        ignored = {i['dependency-name']: i.get('versions') for i in pip[0]['ignore']}
        self.assertNotIn('urllib3', ignored)
        self.assertNotIn('requests', ignored)

    def test_installer_installs_only_with_require_hashes(self):
        src = self._text('config-editor/Install_MediaMTX_Config_Editor.sh')
        self.assertIn('--require-hashes', src)
        self.assertNotRegex(src, r'pip"? install[^\n]*\b(Flask|ruamel\.yaml|requests|psutil)\b(?!\.txt)')


if __name__ == '__main__':
    unittest.main()
