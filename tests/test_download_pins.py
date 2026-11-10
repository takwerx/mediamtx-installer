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

    def test_installer_installs_only_with_require_hashes(self):
        src = self._text('config-editor/Install_MediaMTX_Config_Editor.sh')
        self.assertIn('--require-hashes', src)
        self.assertNotRegex(src, r'pip"? install[^\n]*\b(Flask|ruamel\.yaml|requests|psutil)\b(?!\.txt)')


if __name__ == '__main__':
    unittest.main()
