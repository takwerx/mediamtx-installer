"""Web editor audit fixes (ops #1316): rollback, users.json, startup patches, editor self-update.

Run: python3 -m unittest discover -s tests   (needs flask, ruamel.yaml, psutil, requests)

Every test here fails on the editor as it was before ops #1316 and passes with the fix. They load the
console the same way as test_console_password_hashing.py (paths rewritten into a sandbox) and drive it
with a fake MediaMTX host: a "binary" file whose text is its version, and a fake systemd.
"""
import glob
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from unittest import mock

from test_console_password_hashing import load_editor


class Killed(BaseException):
    """Stands for kill -9 of the editor: not an Exception, so no handler in the editor catches it."""


def admin_client(m):
    c = m.app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'admin'
        s['username'] = 'alice'
    return c


# ---------------------------------------------------------------------------------------------
# 2. One failed read of users.json must not wipe the accounts
# ---------------------------------------------------------------------------------------------
class UsersFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_uf_')
        cls.m = load_editor(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        m = self.m
        for p in [m.USERS_FILE, m.USERS_FILE + '.tmp', m.INITIAL_PASSWORD_FILE] + glob.glob(m.USERS_FILE + '.unreadable_*'):
            if os.path.exists(p):
                os.remove(p)

    def write_raw(self, data):
        with open(self.m.USERS_FILE, 'wb') as f:
            f.write(data)

    def read_raw(self):
        with open(self.m.USERS_FILE, 'rb') as f:
            return f.read()

    def copies(self):
        return glob.glob(self.m.USERS_FILE + '.unreadable_*')

    def test_a_cut_off_users_file_is_kept_and_no_new_admin_is_made(self):
        cut = b'[{"username": "alice", "password": "scrypt:32768:8:1$x$ab", "role": "admin"}, {"username": "bo'
        self.write_raw(cut)
        c = self.m.app.test_client()
        r = c.get('/login')
        self.assertEqual(r.status_code, 503)
        self.assertIn('users.json', r.get_data(as_text=True))
        self.assertEqual(self.read_raw(), cut)                              # not replaced by a new admin
        self.assertFalse(os.path.exists(self.m.INITIAL_PASSWORD_FILE))      # no new password handed out
        self.assertEqual(len(self.copies()), 1)
        with open(self.copies()[0], 'rb') as f:
            self.assertEqual(f.read(), cut)                                 # a copy of what was unreadable
        c.get('/login')
        self.assertEqual(len(self.copies()), 1)                             # asking again makes no second copy

    def test_an_empty_users_file_is_kept_too(self):
        self.write_raw(b'')
        r = self.m.app.test_client().get('/login')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.read_raw(), b'')
        self.assertFalse(os.path.exists(self.m.INITIAL_PASSWORD_FILE))

    def test_a_users_file_that_is_not_a_list_of_accounts_is_kept(self):
        self.write_raw(b'{"admin": "x"}')
        r = self.m.app.test_client().get('/login')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.read_raw(), b'{"admin": "x"}')

    def test_signing_in_against_an_unreadable_file_changes_nothing_and_says_why(self):
        self.write_raw(b'not json')
        r = self.m.app.test_client().post('/login', data={'username': 'admin', 'password': 'x'})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.read_raw(), b'not json')
        self.assertFalse(os.path.exists(self.m.INITIAL_PASSWORD_FILE))

    def test_the_api_answers_json_with_the_same_message(self):
        self.write_raw(b'not json')
        r = admin_client(self.m).get('/api/webeditor/users')
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.get_json()['success'])
        self.assertIn('users.json', r.get_json()['error'])
        self.assertEqual(self.read_raw(), b'not json')

    def test_a_box_with_no_users_file_still_gets_its_first_admin(self):
        users = self.m.load_users()
        self.assertEqual([u['username'] for u in users], ['admin'])
        self.assertTrue(os.path.exists(self.m.INITIAL_PASSWORD_FILE))

    def test_a_save_that_fails_halfway_leaves_the_old_file_whole(self):
        old = [{'username': 'alice', 'password': 'x', 'role': 'admin'}, {'username': 'bob', 'password': 'y', 'role': 'viewer'}]
        self.m.save_users(old)
        before = self.read_raw()

        def dies_halfway(obj, f, **kw):
            f.write('[{"username": "al')
            raise OSError('No space left on device')

        with mock.patch.object(self.m.json, 'dump', side_effect=dies_halfway):
            with self.assertRaises(OSError):
                self.m.save_users([{'username': 'carol', 'password': 'z', 'role': 'admin'}])
        self.assertEqual(self.read_raw(), before)
        self.assertEqual(self.m.load_users(), old)
        self.assertFalse(os.path.exists(self.m.USERS_FILE + '.tmp'))

    def test_the_users_file_stays_private(self):
        self.m.save_users([{'username': 'alice', 'password': 'x', 'role': 'admin'}])
        self.assertEqual(os.stat(self.m.USERS_FILE).st_mode & 0o777, 0o600)


# ---------------------------------------------------------------------------------------------
# A fake MediaMTX host for the upgrade and rollback tests
# ---------------------------------------------------------------------------------------------
class FakeHost:
    """The binary is a file whose text is its version. `starts(binary_text, config_text)` returns what
    systemd would log for a failed start ('' = it starts). The clock-like names of saved binaries
    always count up, as real timestamps do."""

    def __init__(self, m):
        self.m = m
        self.swaps = 0
        self.active = True
        self.actions = []          # every systemctl action, in order
        self.last_journal = ''
        self.starts = lambda binary_text, config_text: ''
        self.kill_on_install = False

    # --- files
    def installed(self):
        with open(self.m.MEDIAMTX_BINARY) as f:
            return f.read()

    def set_installed(self, text):
        os.makedirs(os.path.dirname(self.m.MEDIAMTX_BINARY), exist_ok=True)
        with open(self.m.MEDIAMTX_BINARY, 'w') as f:
            f.write(text)

    def add_backup(self, stamp, text):
        path = f'{self.m.MEDIAMTX_BINARY}.backup_{stamp}'
        with open(path, 'w') as f:
            f.write(text)
        return path

    def config(self):
        with open(self.m.CONFIG_FILE) as f:
            return f.read()

    def write_config(self, text, path=None):
        with open(path or self.m.CONFIG_FILE, 'w') as f:
            f.write(text)

    def clean(self):
        m = self.m
        for p in (glob.glob(m.MEDIAMTX_BINARY + '*') + glob.glob(m.CONFIG_FILE + '.*')
                  + [m.ROLLBACK_STATE_FILE, m.UPGRADE_MARKER_FILE]):
            if os.path.isfile(p):
                os.remove(p)

    # --- fakes
    def _systemctl(self, action):
        self.actions.append(action)
        if action in ('start', 'restart'):
            self.last_journal = self.starts(self.installed(), self.config())
            self.active = not self.last_journal
        else:
            self.active = False
        return mock.Mock(returncode=0, stdout=b'', stderr=b'')

    def _install(self, src):
        if self.kill_on_install:
            raise Killed()
        self.swaps += 1
        backup = f'{self.m.MEDIAMTX_BINARY}.backup_20261201_{self.swaps:06d}'
        with open(backup, 'w') as f:
            f.write(self.installed())
        with open(self.m.MEDIAMTX_BINARY, 'w') as f:
            with open(src) as s:
                f.write(s.read())
        return backup

    def _run(self, cmd, *a, **kw):
        if cmd[0] == 'systemctl':
            return mock.Mock(returncode=0, stdout='active\n' if self.active else 'inactive\n', stderr='')
        if cmd[0] == 'journalctl':
            return mock.Mock(returncode=0, stdout=self.last_journal, stderr='')
        with open(cmd[0]) as f:                                   # <binary> --version
            return mock.Mock(returncode=0, stdout=f.read() + '\n', stderr='')

    def patched(self):
        m = self.m
        stack = [
            mock.patch.object(m, 'mtx_priv_mode', return_value='root'),
            mock.patch.object(m, 'mtx_systemctl', side_effect=self._systemctl),
            mock.patch.object(m, 'mtx_install_binary', side_effect=self._install),
            mock.patch.object(m, 'mtx_copy_priv', side_effect=lambda s, d: open(d, 'w').write(open(s).read())),
            mock.patch.object(m, 'backup_config_file', return_value=None),
            mock.patch.object(m, 'mtx_wait_active', side_effect=lambda *a, **k: (self.active, 'active' if self.active else 'inactive')),
            mock.patch.object(m, 'mtx_unit_state', side_effect=lambda: 'active' if self.active else 'inactive'),
            mock.patch.object(m.subprocess, 'run', side_effect=self._run),
            mock.patch.object(m.time, 'sleep'),
        ]
        return _Stack(stack)


class _Stack:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


CONFIG_NOW = """\
logLevel: info
authInternalUsers:
- user: viewer1
  pass: new-password-after-upgrade
paths:
  cam1:
    source: publisher
"""

CONFIG_AT_UPGRADE = """\
logLevel: info
authInternalUsers:
- user: viewer1
  pass: old-password-before-upgrade
- user: revoked-stream-key
  pass: still-works-in-this-copy
paths:
  cam1:
    source: publisher
"""


class HostCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_host_')
        cls.m = load_editor(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.host = FakeHost(self.m)
        self.host.clean()
        os.makedirs(os.path.dirname(self.m.MEDIAMTX_BINARY), exist_ok=True)
        self.client = admin_client(self.m)

    def tearDown(self):
        self.host.clean()


# ---------------------------------------------------------------------------------------------
# 1. Rollback: keep the config the operator has now; never move forward; never skip versions
# ---------------------------------------------------------------------------------------------
class RollbackTest(HostCase):
    def after_an_upgrade(self):
        """v1.15.0 -> v1.16.1 was done here: its saved binary and config copy exist, then the operator
        changed the config (revoked a key, changed a password)."""
        h = self.host
        h.set_installed('v1.16.1')
        saved = h.add_backup('20261101_100000', 'v1.15.0')
        h.write_config(CONFIG_AT_UPGRADE, self.m.CONFIG_FILE + '.backup_20261101_100000')
        h.write_config(CONFIG_NOW)
        with open(self.m.ROLLBACK_STATE_FILE, 'w') as f:
            json.dump({'backup': saved, 'from_version': 'v1.15.0', 'to_version': 'v1.16.1'}, f)
        return saved

    def rollback(self):
        with self.host.patched():
            return self.client.post('/api/mediamtx/version/rollback')

    def test_rollback_keeps_the_config_as_it_is_now(self):
        self.after_an_upgrade()
        r = self.rollback()
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.host.installed(), 'v1.15.0')
        self.assertEqual(self.host.config(), CONFIG_NOW)             # the revoked key and the new password stay as they are
        self.assertNotIn('revoked-stream-key', self.host.config())
        self.assertNotIn('old-password-before-upgrade', self.host.config())
        self.assertEqual(r.get_json()['fields_removed'], [])

    def test_only_a_field_the_old_version_refuses_is_taken_out_and_it_is_reported(self):
        self.after_an_upgrade()
        self.host.write_config(CONFIG_NOW + '    moqTransport: yes\n')
        self.host.starts = lambda binary, config: ('ERR: json: unknown field "paths.cam1.moqTransport"\n'
                                                   if binary == 'v1.15.0' and 'moqTransport' in config else '')
        r = self.rollback()
        body = r.get_json()
        self.assertEqual(r.status_code, 200, body)
        self.assertEqual(body['fields_removed'], ['paths.cam1.moqTransport'])
        self.assertEqual(self.host.config(), CONFIG_NOW)            # exactly the current config minus that one line
        self.assertEqual(self.host.installed(), 'v1.15.0')

    def test_a_second_click_does_not_move_forward_again(self):
        self.after_an_upgrade()
        self.assertEqual(self.rollback().status_code, 200)
        self.assertEqual(self.host.installed(), 'v1.15.0')
        swaps = self.host.swaps
        r = self.rollback()
        self.assertEqual(r.status_code, 400, r.get_json())
        self.assertIn('nothing to go back to', r.get_json()['error'])
        self.assertEqual(self.host.installed(), 'v1.15.0')          # still the older version
        self.assertEqual(self.host.swaps, swaps)                    # no binary was touched
        with self.host.patched():
            status = self.client.get('/api/mediamtx/version/rollback/status').get_json()
        self.assertFalse(status['available'])                       # and the Rollback button is not offered
        self.assertIn('nothing to go back to', status['reason'])

    def test_rollback_refuses_when_mediamtx_was_changed_after_the_upgrade(self):
        self.after_an_upgrade()
        self.host.set_installed('v1.17.0')        # an installer script ran after the upgrade and made no backup
        r = self.rollback()
        self.assertEqual(r.status_code, 400, r.get_json())
        self.assertIn('outside this editor', r.get_json()['error'])
        self.assertEqual(self.host.installed(), 'v1.17.0')
        self.assertNotIn('stop', self.host.actions)                 # MediaMTX was never stopped
        self.assertEqual(self.host.config(), CONFIG_NOW)

    def test_a_box_from_before_this_fix_can_still_roll_back(self):
        self.after_an_upgrade()
        os.remove(self.m.ROLLBACK_STATE_FILE)                       # upgraded by an older editor: no state file
        r = self.rollback()
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.host.installed(), 'v1.15.0')

    def test_a_binary_that_cannot_report_its_version_does_not_block_rollback(self):
        self.after_an_upgrade()
        self.host.set_installed('broken')                           # --version says nothing readable
        r = self.rollback()
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.host.installed(), 'v1.15.0')

    def test_revoke_a_key_after_an_upgrade_then_roll_back_it_stays_revoked(self):
        """The whole path through the real upgrade and rollback handlers."""
        h = self.host
        h.set_installed('v1.15.0')
        h.write_config(CONFIG_AT_UPGRADE)
        up = UpgradeTest.run_upgrade(self, tag='v1.16.1')
        self.assertEqual(up.status_code, 200, up.get_json())
        self.assertEqual(h.installed(), 'v1.16.1')
        h.write_config(CONFIG_NOW)                                  # the operator revokes the key and changes a password
        r = self.rollback()
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(h.installed(), 'v1.15.0')
        self.assertEqual(h.config(), CONFIG_NOW)
        self.assertNotIn('revoked-stream-key', h.config())


# ---------------------------------------------------------------------------------------------
# 1b. Upgrade: only forward, only fresh answers, and never leave MediaMTX down after a kill
# ---------------------------------------------------------------------------------------------
class UpgradeTest(HostCase):
    def run_upgrade(self, tag='v1.16.1', stale=False, new_text=None):
        """POST the upgrade with a fake GitHub release whose binary reads `new_text` (default: the tag)."""
        m, h = self.m, self.host
        name = f'mediamtx_{tag}_linux_{m.MEDIAMTX_ARCH}.tar.gz'
        buf = io.BytesIO()
        payload = (new_text or tag).encode()
        with tarfile.open(fileobj=buf, mode='w:gz') as tar:
            info = tarfile.TarInfo('mediamtx')
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        tar_bytes = buf.getvalue()
        sums = f'{hashlib.sha256(tar_bytes).hexdigest()}  {name}\n'.encode()
        release = {'tag_name': tag, 'assets': [
            {'name': name, 'browser_download_url': 'https://example.invalid/' + name},
            {'name': 'checksums.sha256', 'browser_download_url': 'https://example.invalid/checksums.sha256'}]}
        self.downloads = []

        def urlopen(req, timeout=None, context=None):
            self.downloads.append(req.full_url)
            return io.BytesIO(tar_bytes if req.full_url.endswith('.tar.gz') else sums)

        with h.patched(), \
                mock.patch.object(m, 'github_latest_release', return_value=(release, {'stale': stale, 'checked_at': '', 'notice': ''})), \
                mock.patch('urllib.request.urlopen', side_effect=urlopen):
            return self.client.post('/api/mediamtx/version/upgrade')

    def test_a_release_older_than_the_installed_one_is_refused(self):
        self.host.set_installed('v1.17.0')          # put there by hand, ahead of what GitHub (or a saved answer) names
        r = self.run_upgrade(tag='v1.16.1')
        self.assertEqual(r.status_code, 400, r.get_json())
        self.assertIn('nothing to upgrade to', r.get_json()['error'])
        self.assertEqual(self.host.installed(), 'v1.17.0')
        self.assertEqual(self.host.actions, [])      # MediaMTX was not even stopped
        self.assertEqual(self.downloads, [])

    def test_the_same_version_is_refused(self):
        self.host.set_installed('v1.16.1')
        r = self.run_upgrade(tag='v1.16.1')
        self.assertEqual(r.status_code, 400, r.get_json())
        self.assertEqual(self.host.actions, [])

    def test_an_old_saved_answer_from_github_is_not_acted_on(self):
        self.host.set_installed('v1.15.0')
        r = self.run_upgrade(tag='v1.16.1', stale=True)
        self.assertEqual(r.status_code, 400, r.get_json())
        self.assertIn('older saved answer', r.get_json()['error'])
        self.assertEqual(self.host.installed(), 'v1.15.0')
        self.assertEqual(self.host.actions, [])
        self.assertEqual(self.downloads, [])

    def test_a_good_upgrade_goes_through_and_records_what_rollback_needs(self):
        self.host.set_installed('v1.15.0')
        r = self.run_upgrade(tag='v1.16.1')
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.host.installed(), 'v1.16.1')
        self.assertFalse(os.path.exists(self.m.UPGRADE_MARKER_FILE))     # done: nothing left to recover
        with open(self.m.ROLLBACK_STATE_FILE) as f:
            state = json.load(f)
        self.assertEqual(state['to_version'], 'v1.16.1')
        self.assertEqual(state['from_version'], 'v1.15.0')
        with open(state['backup']) as f:
            self.assertEqual(f.read(), 'v1.15.0')

    def test_a_kill_after_the_stop_leaves_a_marker_and_the_next_start_puts_mediamtx_back(self):
        h = self.host
        h.set_installed('v1.15.0')
        h.kill_on_install = True                     # the editor is killed between "stopped MediaMTX" and "installed the new binary"
        with self.assertRaises(Killed):
            self.run_upgrade(tag='v1.16.1')
        self.assertFalse(h.active)                   # MediaMTX is down ...
        self.assertTrue(os.path.exists(self.m.UPGRADE_MARKER_FILE))   # ... and the editor knows it
        h.kill_on_install = False
        with h.patched():
            said = self.m.recover_interrupted_upgrade()              # what the editor does when it starts again
        self.assertTrue(h.active)
        self.assertIn('started MediaMTX again', said)
        self.assertEqual(h.installed(), 'v1.15.0')
        self.assertFalse(os.path.exists(self.m.UPGRADE_MARKER_FILE))

    def test_a_kill_that_left_a_new_binary_that_will_not_run_gets_the_saved_one_back(self):
        h = self.host
        saved = h.add_backup('20261101_000001', 'v1.15.0')
        h.set_installed('v1.16.1')                   # new binary in place, but the editor was killed before it started it
        h.starts = lambda binary, config: 'ERR: Exec format error\n' if binary == 'v1.16.1' else ''
        h.active = False
        with open(self.m.UPGRADE_MARKER_FILE, 'w') as f:
            json.dump({'binary_backup': saved, 'previous_version': 'v1.15.0'}, f)
        with h.patched():
            said = self.m.recover_interrupted_upgrade()
        self.assertTrue(h.active)
        self.assertEqual(h.installed(), 'v1.15.0')
        self.assertIn('saved MediaMTX binary back', said)
        self.assertFalse(os.path.exists(self.m.UPGRADE_MARKER_FILE))

    def test_nothing_to_recover_when_no_upgrade_was_interrupted(self):
        with self.host.patched():
            self.assertIsNone(self.m.recover_interrupted_upgrade())
        self.assertEqual(self.host.actions, [])

    def test_a_marker_while_mediamtx_runs_is_only_cleared(self):
        with open(self.m.UPGRADE_MARKER_FILE, 'w') as f:
            json.dump({}, f)
        with self.host.patched():
            self.m.recover_interrupted_upgrade()
        self.assertEqual(self.host.actions, [])      # it was not restarted
        self.assertFalse(os.path.exists(self.m.UPGRADE_MARKER_FILE))

    def test_the_binary_is_swapped_by_a_rename_so_a_kill_leaves_it_whole(self):
        """The real root-mode swap: copy beside the binary, then rename over it."""
        m = self.m
        src = os.path.join(self._tmp.name, 'new-binary')
        with open(src, 'w') as f:
            f.write('v1.16.1')
        self.host.set_installed('v1.15.0')
        renames = []
        real_replace = os.replace

        def spy(a, b):
            renames.append((a, b))
            return real_replace(a, b)

        with mock.patch.object(m.os, 'geteuid', return_value=0), \
                mock.patch.object(m, 'mtx_selinux_relabel', return_value=False), \
                mock.patch.object(m.os, 'replace', side_effect=spy):
            backup = m.mtx_install_binary(src)
        self.assertEqual(renames, [(m.MEDIAMTX_BINARY + '.new', m.MEDIAMTX_BINARY)])
        self.assertEqual(self.host.installed(), 'v1.16.1')
        with open(backup) as f:
            self.assertEqual(f.read(), 'v1.15.0')
        self.assertFalse(os.path.exists(m.MEDIAMTX_BINARY + '.new'))

        def dies_in_rename(a, b):
            raise Killed()

        with mock.patch.object(m.os, 'geteuid', return_value=0), \
                mock.patch.object(m, 'mtx_selinux_relabel', return_value=False), \
                mock.patch.object(m.os, 'replace', side_effect=dies_in_rename):
            with self.assertRaises(Killed):
                m.mtx_install_binary(src)
        self.assertEqual(self.host.installed(), 'v1.16.1')          # the binary that was there is whole
        self.assertFalse(os.path.exists(m.MEDIAMTX_BINARY + '.new'))


# ---------------------------------------------------------------------------------------------
# 3. Startup patches touch only what we wrote
# ---------------------------------------------------------------------------------------------
LEGACY_BLOCK = """\
  ~^live/(.+)$:
    runOnReady: ffmpeg -i rtsp://localhost:8554/live/$G1 -c copy -f rtsp
      rtsp://localhost:8554/$G1
    runOnReadyRestart: true
"""

OPERATOR_PATH = """\
  my-relay:
    runOnReady: python3 /opt/relay.py
    runOnReadyRestart: true
"""


class StartupPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_sp_')
        cls.m = load_editor(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_operators_own_runOnReadyRestart_survives_the_legacy_clean_up(self):
        text = 'paths:\n' + LEGACY_BLOCK + OPERATOR_PATH
        out, changed = self.m.strip_legacy_live_path(text)
        self.assertTrue(changed)
        self.assertEqual(out, 'paths:\n' + OPERATOR_PATH)          # our old default is gone, theirs is untouched

    def test_a_config_with_only_the_operators_setting_is_not_touched_at_all(self):
        text = 'paths:\n' + OPERATOR_PATH
        out, changed = self.m.strip_legacy_live_path(text)
        self.assertFalse(changed)
        self.assertEqual(out, text)

    def test_a_live_path_the_operator_changed_is_kept(self):
        text = 'paths:\n  ~^live/(.+)$:\n    runOnReady: python3 /opt/mine.py\n    runOnReadyRestart: true\n'
        out, changed = self.m.strip_legacy_live_path(text)
        self.assertFalse(changed)
        self.assertEqual(out, text)

    def test_the_loose_lines_an_old_bad_removal_left_are_removed_but_not_other_settings(self):
        text = ('paths:\n  cam1:\n    source: publisher\n'
                '    rtsp://localhost:8554/$G1\n    runOnReadyRestart: true\n' + OPERATOR_PATH)
        out, changed = self.m.strip_legacy_live_path(text)
        self.assertTrue(changed)
        self.assertEqual(out, 'paths:\n  cam1:\n    source: publisher\n' + OPERATOR_PATH)

    def test_the_legacy_block_at_the_end_of_the_file_goes(self):
        out, changed = self.m.strip_legacy_live_path('paths:\n  cam1:\n    source: publisher\n' + LEGACY_BLOCK)
        self.assertTrue(changed)
        self.assertEqual(out, 'paths:\n  cam1:\n    source: publisher\n')

    def test_the_file_patch_keeps_the_operators_setting_through_a_restart(self):
        path = os.path.join(self._tmp.name, 'op.yml')
        text = 'paths:\n' + OPERATOR_PATH
        with open(path, 'w') as f:
            f.write(text)
        with mock.patch.object(self.m, 'backup_config_file', return_value=None) as backup:
            self.m.patch_legacy_live_path(path)
        with open(path) as f:
            self.assertEqual(f.read(), text)
        backup.assert_not_called()

    def test_rtspDemuxMpegts_is_added_only_for_a_version_that_has_the_key(self):
        text = 'logLevel: info\npathDefaults:\n  record: no\npaths:\n  cam1:\n    source: publisher\n'
        add = self.m.add_rtsp_demux_default
        self.assertEqual(add(text, (1, 16, 3)), text)                 # v1.16.x refuses the key: left alone
        self.assertEqual(add(text, None), text)                       # cannot tell: left alone
        self.assertIn('pathDefaults:\n  rtspDemuxMpegts: true\n  record: no', add(text, (1, 17, 0)))
        self.assertIn('pathDefaults:\n  rtspDemuxMpegts: true\n\npaths:', add('paths:\n  cam1:\n    source: publisher\n', (1, 21, 3)))
        self.assertEqual(add(text.replace('record: no', 'rtspDemuxMpegts: false'), (1, 21, 3)),
                         text.replace('record: no', 'rtspDemuxMpegts: false'))   # the operator's choice stays

    def test_the_startup_patch_writes_nothing_for_an_old_mediamtx(self):
        path = os.path.join(self._tmp.name, 'old.yml')
        text = 'pathDefaults:\n  record: no\n'
        with open(path, 'w') as f:
            f.write(text)
        with mock.patch.object(self.m, 'backup_config_file', return_value=None):
            self.m.patch_rtsp_demux_default(path, version=(1, 16, 3))
        with open(path) as f:
            self.assertEqual(f.read(), text)

    def test_saving_hls_settings_on_an_old_mediamtx_does_not_write_the_new_key(self):
        m = self.m
        form = {'hlsVariant': 'mpegts', 'hlsSegmentCount': '7', 'hlsSegmentDuration': '1s', 'hlsPartDuration': '200ms',
                'hlsSegmentMaxSize': '50M', 'hlsAlwaysRemux': 'no', 'hlsMuxerCloseAfter': '60s',
                'writeQueueSize': '512', 'rtspDemuxMpegts': 'true'}
        for version, expect_key in (((1, 16, 3), False), ((1, 17, 0), True), (None, True)):
            with open(m.CONFIG_FILE, 'w') as f:
                f.write('logLevel: info\nhls: yes\npathDefaults:\n  record: no\npaths:\n  cam1:\n    source: publisher\n')
            with mock.patch.object(m, 'mtx_binary_version', return_value=version), \
                    mock.patch.object(m, 'mtx_restart_checked'), mock.patch.object(m.time, 'sleep'), \
                    mock.patch.object(m.subprocess, 'run'):
                r = admin_client(m).post('/save_hls', data=form)
            self.assertEqual(r.status_code, 302)
            with open(m.CONFIG_FILE) as f:
                self.assertEqual('rtspDemuxMpegts' in f.read(), expect_key, version)


# ---------------------------------------------------------------------------------------------
# 4. The editor's own update
# ---------------------------------------------------------------------------------------------
GOOD_EDITOR = ('# a stand-in for the next release\nCURRENT_VERSION = "v2.1.22"\n' + 'x = 1\n' * 400)


class EditorUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_eu_')
        cls.m = load_editor(cls._tmp.name)
        cls.live = os.path.join(os.path.dirname(cls.m.USERS_FILE), 'mediamtx_config_editor.py')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for p in glob.glob(self.live + '*'):
            os.remove(p)
        with open(self.live, 'w') as f:
            f.write('CURRENT_VERSION = "v2.1.21-dev"\n# the running file\n')
        self.client = admin_client(self.m)
        self.fetched = []

    def live_text(self):
        with open(self.live) as f:
            return f.read()

    def release(self, tag):
        return ({'tag_name': tag, 'body': '', 'published_at': '', 'html_url': ''},
                {'stale': False, 'checked_at': '', 'notice': ''})

    def apply(self, tag='v2.1.22', channel='main', code=GOOD_EDITOR):
        def urlopen(req, timeout=None, context=None):
            self.fetched.append(req.full_url)
            return io.BytesIO(code.encode() if 'mediamtx_config_editor.py' in req.full_url else b'x' * 600 + b'ST0601')

        with mock.patch.object(self.m, 'github_latest_release', return_value=self.release(tag)), \
                mock.patch.object(self.m, 'get_update_channel', return_value=channel), \
                mock.patch.object(self.m, 'schedule_editor_self_restart', return_value=False), \
                mock.patch.object(self.m, 'backup_config_file', return_value=None), \
                mock.patch.object(self.m, 'KLV_SIDECAR', os.path.join(self._tmp.name, 'klv-to-cot.py')), \
                mock.patch('urllib.request.urlopen', side_effect=urlopen):
            return self.client.post('/api/update/apply')

    def check(self, tag, channel='main'):
        with mock.patch.object(self.m, 'github_latest_release', return_value=self.release(tag)), \
                mock.patch.object(self.m, 'get_update_channel', return_value=channel), \
                mock.patch.object(self.m, 'CURRENT_VERSION', 'v2.1.21-dev'):
            return self.client.get('/api/update/check').get_json()

    def test_versions_with_a_dev_suffix_sort_before_their_release(self):
        p = self.m.parse_editor_version
        self.assertLess(p('v2.1.21-dev'), p('v2.1.21'))
        self.assertLess(p('v2.1.21'), p('v2.1.22-dev'))
        self.assertLess(p('v2.1.9'), p('v2.1.10'))
        self.assertIsNone(p('latest'))
        self.assertIsNone(p(''))

    def test_a_dev_build_is_not_told_that_an_older_release_is_an_update(self):
        self.assertFalse(self.check('v2.1.20')['update_available'])   # used to read 2.1.21-dev as 0.0.0
        self.assertFalse(self.check('v2.1.9')['update_available'])

    def test_a_dev_build_is_offered_its_own_release_and_newer_ones(self):
        self.assertTrue(self.check('v2.1.21')['update_available'])
        self.assertTrue(self.check('v2.1.22')['update_available'])

    def test_an_unreadable_release_name_is_never_offered(self):
        self.assertFalse(self.check('nightly')['update_available'])

    def test_the_main_channel_pulls_the_release_tag_not_the_tip_of_main(self):
        r = self.apply(tag='v2.1.22')
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn('CURRENT_VERSION = "v2.1.22"', self.live_text())
        editor_urls = [u for u in self.fetched if u.endswith('mediamtx_config_editor.py')]
        self.assertEqual(editor_urls, ['https://raw.githubusercontent.com/takwerx/mediamtx-installer/v2.1.22/config-editor/mediamtx_config_editor.py'])
        self.assertTrue(all('/main/' not in u for u in self.fetched), self.fetched)   # the KLV sidecar too

    def test_the_dev_channel_still_follows_the_dev_branch(self):
        r = self.apply(channel='dev')
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertTrue(any('/dev/config-editor/mediamtx_config_editor.py' in u for u in self.fetched), self.fetched)

    def test_a_release_that_is_not_newer_is_refused(self):
        r = self.apply(tag='v2.1.20')
        self.assertEqual(r.status_code, 400, r.get_json())
        self.assertEqual(self.fetched, [])
        self.assertIn('v2.1.21-dev', self.live_text())

    def test_a_download_that_does_not_compile_is_refused_and_the_running_file_stays(self):
        broken = 'CURRENT_VERSION = "v2.1.22"\ndef broken(:\n' + 'x = 1\n' * 400
        r = self.apply(code=broken)
        self.assertEqual(r.status_code, 400, r.get_json())
        self.assertIn('does not compile', r.get_json()['error'])
        self.assertIn('v2.1.21-dev', self.live_text())
        self.assertFalse(os.path.exists(self.live + '.new'))

    def test_the_new_file_is_put_in_place_by_one_rename(self):
        renames = []
        real = os.replace

        def spy(a, b):
            renames.append((a, b))
            return real(a, b)

        with mock.patch.object(self.m.os, 'replace', side_effect=spy):
            r = self.apply()
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn((self.live + '.new', self.live), renames)

    def test_a_failure_in_the_final_step_leaves_the_running_file_whole(self):
        real = os.replace

        def dies(a, b):
            if str(b) == self.live:
                raise OSError('No space left on device')
            return real(a, b)

        with mock.patch.object(self.m.os, 'replace', side_effect=dies):
            r = self.apply()
        self.assertEqual(r.status_code, 500)
        self.assertEqual(self.live_text(), 'CURRENT_VERSION = "v2.1.21-dev"\n# the running file\n')
        self.assertFalse(os.path.exists(self.live + '.new'))


if __name__ == '__main__':
    unittest.main()
