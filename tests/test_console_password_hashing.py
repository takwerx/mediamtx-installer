"""Console passwords must be stored as hashes, never plain text.

Run: python3 -m unittest discover -s tests   (needs flask, ruamel.yaml, psutil, requests)

The editor has import-time side effects on /opt and /usr/local, so the source is
loaded with those prefixes rewritten into a temp sandbox (same as the
verify-console-ui skill).
"""
import json
import os
import sys
import tempfile
import types
import unittest

EDITOR = os.path.join(os.path.dirname(__file__), '..', 'config-editor', 'mediamtx_config_editor.py')


def load_editor(sandbox):
    with open(EDITOR) as f:
        src = f.read()
    src = src.replace('/usr/local/', sandbox + '/usr/local/').replace('/opt/', sandbox + '/opt/')
    os.makedirs(sandbox + '/usr/local/etc', exist_ok=True)
    os.makedirs(sandbox + '/opt/mediamtx-webeditor', exist_ok=True)
    with open(sandbox + '/usr/local/etc/mediamtx.yml', 'w') as f:
        f.write('logLevel: info\napi: yes\npaths:\n  test-stream:\n    source: publisher\n')
    mod = types.ModuleType('mediamtx_config_editor_pwtest')
    mod.__file__ = EDITOR
    sys.modules[mod.__name__] = mod
    exec(compile(src, EDITOR, 'exec'), mod.__dict__)
    return mod


class PasswordHashingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_pw_')
        cls.m = load_editor(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for path in (self.m.USERS_FILE, self.m.PENDING_REG_FILE, self.m.INITIAL_PASSWORD_FILE):
            if os.path.exists(path):
                os.remove(path)

    def raw_users(self):
        with open(self.m.USERS_FILE) as f:
            return json.load(f)

    def write_users(self, users):
        with open(self.m.USERS_FILE, 'w') as f:
            json.dump(users, f)

    def client(self, role='admin', username='webadmin'):
        c = self.m.app.test_client()
        with c.session_transaction() as s:
            s['logged_in'] = True
            s['role'] = role
            s['username'] = username
        return c

    def first_password(self):
        with open(self.m.INITIAL_PASSWORD_FILE) as f:
            return [l for l in f.read().splitlines() if l.startswith('admin: ')][0][len('admin: '):]

    def test_first_run_admin_password_is_random_and_stored_hashed(self):
        self.m.load_users()
        stored = self.raw_users()[0]['password']
        first = self.first_password()
        self.assertTrue(self.m.is_password_hashed(stored))
        self.assertNotIn(first, json.dumps(self.raw_users()))
        self.assertEqual(self.m.authenticate_user('admin', first), 'admin')
        self.assertIsNone(self.m.authenticate_user('admin', 'admin'))
        self.assertIsNone(self.m.authenticate_user('admin', 'wrong'))
        # the login page still says where to find the first password
        page = self.m.app.test_client().get('/login').get_data(as_text=True)
        self.assertIn(self.m.INITIAL_PASSWORD_FILE, page)

    def test_legacy_plaintext_login_converts_to_hash(self):
        self.write_users([
            {'username': 'alice', 'password': 'hunter22', 'role': 'viewer'},
            {'username': 'bob', 'password': 'other-pass', 'role': 'admin'},
        ])
        self.assertIsNone(self.m.authenticate_user('alice', 'nope'))
        self.assertEqual(self.raw_users()[0]['password'], 'hunter22')  # failed login converts nothing
        self.assertEqual(self.m.authenticate_user('alice', 'hunter22'), 'viewer')
        users = self.raw_users()
        self.assertTrue(self.m.is_password_hashed(users[0]['password']))
        self.assertNotIn('hunter22', json.dumps(users[0]))
        self.assertEqual(users[1]['password'], 'other-pass')  # other users wait for their own login
        # the converted entry still logs in, and the wrong password still fails
        self.assertEqual(self.m.authenticate_user('alice', 'hunter22'), 'viewer')
        self.assertIsNone(self.m.authenticate_user('alice', 'hunter23'))

    def test_hash_string_is_not_accepted_as_a_password(self):
        self.m.load_users()
        stored = self.raw_users()[0]['password']
        self.assertIsNone(self.m.authenticate_user('admin', stored))

    def test_old_admin_admin_box_is_rotated_to_a_hashed_random_password(self):
        for stored in ('admin', self.m.hash_password('admin')):  # plain text, and an already-hashed default
            self.write_users([{'username': 'admin', 'password': stored, 'role': 'admin'}])
            self.m.load_users()
            new_stored = self.raw_users()[0]['password']
            self.assertTrue(self.m.is_password_hashed(new_stored))
            self.assertFalse(self.m.verify_password(new_stored, 'admin'))
            self.assertEqual(self.m.authenticate_user('admin', self.first_password()), 'admin')
            self.assertIsNone(self.m.authenticate_user('admin', 'admin'))

    def test_changing_the_first_password_stores_a_hash_and_removes_the_file(self):
        self.m.load_users()
        first = self.first_password()
        c = self.client(username='admin')
        r = c.post('/change_password', data={
            'current_password': first, 'new_password': 'my-own-pass', 'confirm_password': 'my-own-pass'})
        self.assertIn('changed', r.headers['Location'])
        self.assertFalse(os.path.exists(self.m.INITIAL_PASSWORD_FILE))
        self.assertTrue(self.m.is_password_hashed(self.raw_users()[0]['password']))
        self.assertEqual(self.m.authenticate_user('admin', 'my-own-pass'), 'admin')
        self.assertIsNone(self.m.authenticate_user('admin', first))

    def test_add_user_stores_hash(self):
        r = self.client().post('/api/webeditor/users/add', json={
            'username': 'carol', 'email': 'c@example.org', 'password': 'carol-pass', 'role': 'viewer'})
        self.assertEqual(r.status_code, 200)
        carol = next(u for u in self.raw_users() if u['username'] == 'carol')
        self.assertTrue(self.m.is_password_hashed(carol['password']))
        self.assertNotIn('carol-pass', json.dumps(carol))
        self.assertEqual(self.m.authenticate_user('carol', 'carol-pass'), 'viewer')

    def test_change_password_verifies_old_and_stores_hash(self):
        self.write_users([{'username': 'dave', 'password': 'old-pass', 'role': 'viewer'}])
        c = self.client(role='viewer', username='dave')
        bad = c.post('/change_password', data={
            'current_password': 'wrong', 'new_password': 'new-pass', 'confirm_password': 'new-pass'})
        self.assertIn('incorrect', bad.headers['Location'])
        self.assertEqual(self.raw_users()[0]['password'], 'old-pass')
        ok = c.post('/change_password', data={
            'current_password': 'old-pass', 'new_password': 'new-pass', 'confirm_password': 'new-pass'})
        self.assertIn('changed+successfully', ok.headers['Location'].replace('%20', '+'))
        stored = self.raw_users()[0]['password']
        self.assertTrue(self.m.is_password_hashed(stored))
        self.assertEqual(self.m.authenticate_user('dave', 'new-pass'), 'viewer')
        self.assertIsNone(self.m.authenticate_user('dave', 'old-pass'))
        # a second change works against the stored hash
        again = c.post('/change_password', data={
            'current_password': 'new-pass', 'new_password': 'third-pass', 'confirm_password': 'third-pass'})
        self.assertIn('changed', again.headers['Location'])
        self.assertEqual(self.m.authenticate_user('dave', 'third-pass'), 'viewer')

    def test_registration_is_pending_as_hash_and_approved_as_hash(self):
        flag = self.m.__dict__['os'].path.join(self._tmp.name, 'opt/mediamtx-webeditor/registration_enabled')
        with open(flag, 'w') as f:
            f.write('1')
        try:
            r = self.m.app.test_client().post('/register', data={
                'full_name': 'Eve Example', 'email': 'eve@agency.gov', 'agency': 'Agency',
                'username': 'eve', 'password': 'eve-secret', 'confirm_password': 'eve-secret'})
            self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        finally:
            os.remove(flag)
        with open(self.m.PENDING_REG_FILE) as f:
            pending = json.load(f)
        self.assertEqual(len(pending), 1)
        self.assertTrue(self.m.is_password_hashed(pending[0]['password']))
        self.assertNotIn('eve-secret', json.dumps(pending))
        r = self.client().post('/api/webeditor/registrations/approve', json={'username': 'eve', 'role': 'viewer'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.m.authenticate_user('eve', 'eve-secret'), 'viewer')

    def test_approving_a_legacy_plaintext_registration_hashes_it(self):
        self.m.save_pending_registrations([{
            'full_name': 'Old Reg', 'email': 'o@agency.gov', 'agency': 'A', 'username': 'oldreg',
            'password': 'legacy-pass', 'requested_at': '2026-01-01T00:00:00'}])
        r = self.client().post('/api/webeditor/registrations/approve', json={'username': 'oldreg', 'role': 'viewer'})
        self.assertEqual(r.status_code, 200)
        user = next(u for u in self.raw_users() if u['username'] == 'oldreg')
        self.assertTrue(self.m.is_password_hashed(user['password']))
        self.assertNotIn('legacy-pass', json.dumps(user))
        self.assertEqual(self.m.authenticate_user('oldreg', 'legacy-pass'), 'viewer')

    def test_reset_password_stores_hash(self):
        self.write_users([{'username': 'frank', 'email': 'f@example.org', 'password': 'old', 'role': 'viewer'}])
        import datetime
        token = 'tok-' + 'x' * 20
        self.m.save_reset_tokens({token: {
            'username': 'frank',
            'expires': (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()}})
        r = self.m.app.test_client().post('/reset-password?token=' + token, data={
            'new_password': 'brand-new', 'confirm_password': 'brand-new'})
        self.assertEqual(r.status_code, 302)
        stored = self.raw_users()[0]['password']
        self.assertTrue(self.m.is_password_hashed(stored))
        self.assertEqual(self.m.authenticate_user('frank', 'brand-new'), 'viewer')


if __name__ == '__main__':
    unittest.main()
