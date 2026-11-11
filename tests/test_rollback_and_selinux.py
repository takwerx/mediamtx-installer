"""Rollback must leave a login that works, and a binary swap must fix the SELinux label (ops #646).

Run: python3 -m unittest discover -s tests   (needs flask, ruamel.yaml, psutil, requests)

Loads the console the same way as test_console_password_hashing.py (paths rewritten into a sandbox).
"""
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from test_console_password_hashing import load_editor

# What a console from before password hashing (v2.1.14) does at login: plain-text compare.
def old_build_login(stored, typed):
    return stored == typed

OLD_BUILD = 'CURRENT_VERSION = "v2.1.14"\n# older console: passwords are compared as plain text\n'
NEW_BUILD = 'CURRENT_VERSION = "v2.1.15"\ndef is_password_hashed(stored):\n    return True\n'


class RollbackLoginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_rb_')
        cls.m = load_editor(cls._tmp.name)
        cls.dir = os.path.dirname(cls.m.USERS_FILE)
        cls.live = os.path.join(cls.dir, 'mediamtx_config_editor.py')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for path in (self.m.USERS_FILE, self.m.INITIAL_PASSWORD_FILE):
            if os.path.exists(path):
                os.remove(path)
        with open(self.live, 'w') as f:
            f.write(NEW_BUILD)
        self.write_users([
            {'username': 'alice', 'password': self.m.hash_password('alice-secret'), 'role': 'admin'},
            {'username': 'bob', 'password': 'bob-plain', 'role': 'viewer'},
            {'username': 'carol', 'password': self.m.hash_password('carol-secret'), 'role': 'viewer'},
        ])

    def write_users(self, users):
        with open(self.m.USERS_FILE, 'w') as f:
            json.dump(users, f)

    def raw_users(self):
        with open(self.m.USERS_FILE) as f:
            return {u['username']: u for u in json.load(f)}

    def password_file(self):
        with open(self.m.INITIAL_PASSWORD_FILE) as f:
            return dict(l.split(': ', 1) for l in f.read().splitlines() if l and not l.startswith('#'))

    def backup(self, text, name='mediamtx_config_editor.py.backup_20260101_000000'):
        with open(os.path.join(self.dir, name), 'w') as f:
            f.write(text)
        return name

    def rollback(self, filename):
        c = self.m.app.test_client()
        with c.session_transaction() as s:
            s['logged_in'] = True
            s['role'] = 'admin'
            s['username'] = 'alice'
        with mock.patch.object(self.m, 'schedule_editor_self_restart', return_value=True):
            return c.post('/api/webeditor/rollback', json={'filename': filename})

    def test_rollback_to_pre_hash_build_leaves_a_login_that_works(self):
        r = self.rollback(self.backup(OLD_BUILD))
        body = r.get_json()
        self.assertEqual(r.status_code, 200, body)
        self.assertEqual(sorted(body['passwords_reset']), ['alice', 'carol'])
        self.assertEqual(body['password_file'], self.m.INITIAL_PASSWORD_FILE)
        self.assertIn(self.m.INITIAL_PASSWORD_FILE, body['notice'])
        self.assertNotIn(self.password_file()['alice'], json.dumps(body))  # the result never shows a password
        with open(self.live) as f:
            self.assertEqual(f.read(), OLD_BUILD)
        users = self.raw_users()
        new = self.password_file()
        self.assertEqual(sorted(new), ['alice', 'carol'])
        self.assertEqual(stat.S_IMODE(os.stat(self.m.INITIAL_PASSWORD_FILE).st_mode), 0o600)
        # the older console compares plain text: the new passwords log in, the old ones do not
        for name in ('alice', 'carol'):
            self.assertTrue(old_build_login(users[name]['password'], new[name]), name)
            self.assertFalse(old_build_login(users[name]['password'], name + '-secret'), name)
        self.assertTrue(old_build_login(users['bob']['password'], 'bob-plain'))  # a plain entry is left alone
        # and updating forward again still accepts them, and hashes them at that login
        self.assertEqual(self.m.authenticate_user('alice', new['alice']), 'admin')
        self.assertTrue(self.m.is_password_hashed(self.raw_users()['alice']['password']))

    def test_rollback_to_a_hash_aware_build_keeps_the_passwords(self):
        before = self.raw_users()
        r = self.rollback(self.backup(NEW_BUILD))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['passwords_reset'], [])
        self.assertNotIn('notice', r.get_json())
        self.assertEqual(self.raw_users(), before)
        self.assertFalse(os.path.exists(self.m.INITIAL_PASSWORD_FILE))
        self.assertEqual(self.m.authenticate_user('alice', 'alice-secret'), 'admin')

    def test_rollback_stops_and_changes_nothing_when_the_password_file_cannot_be_written(self):
        before = self.raw_users()
        with mock.patch.object(self.m, '_write_initial_password_file', return_value=False):
            r = self.rollback(self.backup(OLD_BUILD))
        self.assertEqual(r.status_code, 500)
        self.assertIn('Nothing was changed', r.get_json()['error'])
        self.assertEqual(self.raw_users(), before)
        with open(self.live) as f:
            self.assertEqual(f.read(), NEW_BUILD)
        self.assertEqual(self.m.authenticate_user('alice', 'alice-secret'), 'admin')


class MediaMTXBinaryLabelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_label_')
        cls.m = load_editor(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def swap(self, restorecon_path):
        """Run the root-mode binary swap; returns the restorecon calls and the binary's text at that moment."""
        m = self.m
        os.makedirs(os.path.dirname(m.MEDIAMTX_BINARY), exist_ok=True)
        with open(m.MEDIAMTX_BINARY, 'w') as f:
            f.write('old binary')
        src = os.path.join(self._tmp.name, 'new-mediamtx')
        with open(src, 'w') as f:
            f.write('new binary')
        calls = []

        def fake_run(cmd, *a, **kw):
            with open(m.MEDIAMTX_BINARY) as f:
                calls.append((list(cmd), f.read()))
            return mock.Mock(returncode=0)

        real_exists = os.path.exists
        with mock.patch.object(m.os, 'geteuid', return_value=0), \
                mock.patch.object(m.shutil, 'which', side_effect=lambda n: restorecon_path if n == 'restorecon' else None), \
                mock.patch.object(m.os.path, 'exists',
                                  side_effect=lambda p: False if p in ('/usr/sbin/restorecon', '/sbin/restorecon') else real_exists(p)), \
                mock.patch.object(m.subprocess, 'run', side_effect=fake_run):
            backup = m.mtx_install_binary(src)
        return calls, backup

    def test_swap_runs_restorecon_on_the_new_binary(self):
        calls, backup = self.swap('/usr/sbin/restorecon')
        self.assertEqual(calls, [(['/usr/sbin/restorecon', self.m.MEDIAMTX_BINARY], 'new binary')])
        self.assertTrue(backup.startswith(self.m.MEDIAMTX_BINARY + '.backup_'))

    def test_swap_works_on_a_box_without_restorecon(self):
        calls, _backup = self.swap(None)
        self.assertEqual(calls, [])
        with open(self.m.MEDIAMTX_BINARY) as f:
            self.assertEqual(f.read(), 'new binary')

    def test_relabel_failure_does_not_stop_the_swap(self):
        with mock.patch.object(self.m.shutil, 'which', return_value='/usr/sbin/restorecon'), \
                mock.patch.object(self.m.subprocess, 'run', side_effect=OSError('boom')):
            self.assertFalse(self.m.mtx_selinux_relabel('/x'))


if __name__ == '__main__':
    unittest.main()
