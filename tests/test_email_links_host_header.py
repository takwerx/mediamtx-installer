"""Email links must never be built from the request's Host header (ops #622).

Run: python3 -I -m unittest discover -s tests -v   (needs flask, ruamel.yaml, psutil)

The console file writes to /opt and /usr/local at import time, so, like the
verify-console-ui skill, every such path is rewritten into a temp sandbox first.
"""
import json
import os
import re
import sys
import tempfile
import types
import unittest

EDITOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config-editor', 'mediamtx_config_editor.py')
EVIL = 'evil.example'
USER_EMAIL = 'victim@agency.example'
CERT_DOMAIN = 'stream.agency.example'


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


class EmailLinkHostHeaderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sandbox = self._tmp.name
        self._saved_env = os.environ.pop('MEDIAMTX_CONSOLE_URL', None)
        self.addCleanup(self._restore_env)
        self.mod = load_editor(self.sandbox)
        with open(self.mod.CONFIG_FILE, 'w') as f:
            f.write('logLevel: info\n')
        self.mod.save_users([
            {'username': 'admin', 'password': 'admin', 'role': 'admin'},
            {'username': 'victim', 'password': 'x', 'role': 'viewer', 'email': USER_EMAIL},
        ])
        self.mod.save_email_config({'method': 'smtp', 'notify_email': 'admin@agency.example'})
        self.sent = []
        self.mod.send_email = lambda subject, body, to_email=None: self.sent.append((subject, body, to_email)) or (True, None)
        self.mod._local_ip = lambda: '192.0.2.10'
        self.client = self.mod.app.test_client()

    def _restore_env(self):
        os.environ.pop('MEDIAMTX_CONSOLE_URL', None)
        if self._saved_env is not None:
            os.environ['MEDIAMTX_CONSOLE_URL'] = self._saved_env

    def _write_cert_domain(self, domain):
        with open(self.mod.CONFIG_FILE, 'w') as f:
            f.write(f'hlsEncryption: yes\nhlsServerCert: /etc/caddy/certs/{domain}/{domain}.crt\n')

    def _forgot_password(self, headers):
        resp = self.client.post('/forgot-password', data={'email': USER_EMAIL}, headers=headers)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(self.sent), 1, 'reset email was not sent')
        subject, body, to_email = self.sent[0]
        self.assertEqual(to_email, USER_EMAIL)
        return body

    def _reset_link(self, body):
        links = re.findall(r'href="([^"]*reset-password\?token=[^"]+)"', body)
        self.assertEqual(len(links), 1)
        return links[0]

    def test_forged_host_header_does_not_reach_reset_link(self):
        for headers in (
            {'Host': EVIL},
            {'Host': EVIL + ':5000'},
            {'Host': 'localhost', 'X-Forwarded-Host': EVIL},
            {'Host': 'localhost', 'X-Forwarded-Host': EVIL, 'X-Forwarded-Proto': 'https'},
            {'Host': 'localhost', 'Forwarded': f'host={EVIL};proto=https'},
        ):
            with self.subTest(headers=headers):
                self.sent.clear()
                body = self._forgot_password(headers)
                self.assertNotIn(EVIL, body)
                self.assertTrue(self._reset_link(body).startswith('http://192.0.2.10:5000/reset-password?token='))

    def test_reset_link_uses_certificate_domain_when_known(self):
        self._write_cert_domain(CERT_DOMAIN)
        body = self._forgot_password({'Host': EVIL})
        self.assertNotIn(EVIL, body)
        self.assertTrue(self._reset_link(body).startswith(f'https://{CERT_DOMAIN}/reset-password?token='))

    def test_configured_console_url_wins(self):
        self._write_cert_domain(CERT_DOMAIN)
        self.mod.save_email_config({'method': 'smtp', 'console_url': 'https://console.agency.example/'})
        body = self._forgot_password({'Host': EVIL})
        self.assertTrue(self._reset_link(body).startswith('https://console.agency.example/reset-password?token='))
        os.environ['MEDIAMTX_CONSOLE_URL'] = 'https://env.agency.example:8443'
        self.sent.clear()
        body = self._forgot_password({'Host': EVIL})
        self.assertTrue(self._reset_link(body).startswith('https://env.agency.example:8443/reset-password?token='))

    def test_bad_configured_url_is_ignored(self):
        for bad in ('javascript:alert(1)', 'https://', 'ftp://x.example', 'https://u:p@x.example', 'https://x.example:99999',
                    'https://x.example/"><a href="//evil', 'not a url', 'https://x.example?next=//evil'):
            with self.subTest(bad=bad):
                self.mod.save_email_config({'method': 'smtp', 'console_url': bad})
                self.assertEqual(self.mod.get_console_base_url(), 'http://192.0.2.10:5000')

    def test_approval_email_login_link_ignores_host_header(self):
        self.mod.save_pending_registrations([{
            'full_name': 'New Person', 'email': 'new@agency.example', 'agency': 'A',
            'username': 'newperson', 'password': 'secret1', 'requested_at': '2026-11-10T00:00:00',
        }])
        # The session cookie is bound to the host, so log in under the forged host too.
        with self.client.session_transaction(base_url='http://' + EVIL) as s:
            s.update(logged_in=True, role='admin', username='admin')
        resp = self.client.post('/api/webeditor/registrations/approve', json={'username': 'newperson', 'role': 'viewer'},
                                headers={'Host': EVIL})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        approvals = [s for s in self.sent if s[2] == 'new@agency.example']
        self.assertEqual(len(approvals), 1)
        self.assertNotIn(EVIL, approvals[0][1])
        self.assertIn('href="http://192.0.2.10:5000/login"', approvals[0][1])

    def test_saving_email_settings_keeps_console_url(self):
        self.mod.save_email_config({'method': 'disabled', 'console_url': 'https://console.agency.example'})
        with self.client.session_transaction() as s:
            s.update(logged_in=True, role='admin', username='admin')
        resp = self.client.post('/api/webeditor/email/config', json={'method': 'disabled'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.mod.load_email_config().get('console_url'), 'https://console.agency.example')


if __name__ == '__main__':
    unittest.main()
