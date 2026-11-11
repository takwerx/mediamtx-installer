"""Rollback onto a config the older MediaMTX cannot read must not leave MediaMTX down (ops #647).

Run: python3 -m unittest discover -s tests   (needs flask, ruamel.yaml, psutil, requests)

Case seen on a box: MediaMTX v1.21.3 config, binary swapped to v1.20.0, then Rollback. v1.20.0 reports
unknown fields with a dotted path for nested ones ("pathDefaults.moqTransport"). The old code only
removed top-level lines, looped five times and gave up with the old binary still installed.
"""
import os
import tempfile
import unittest
from unittest import mock

from test_console_password_hashing import load_editor

V121_CONFIG = """\
# written by v1.21.3
logLevel: info
webrtcIPsFromInterfacesExcludeList: [docker0]
pathDefaults:
  source: publisher
  moqTransport: yes
  alwaysAvailableRecorded:
    - tracks: []
  record: no
paths:
  test-stream:
    source: publisher
    moqTransport: yes
"""

# what v1.20.0 refuses, in the order it reports them (it stops at the first one)
UNKNOWN_IN_V120 = ['webrtcIPsFromInterfacesExcludeList', 'pathDefaults.moqTransport',
                   'pathDefaults.alwaysAvailableRecorded']


class RemoveFieldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_rmf_')
        cls.rm = staticmethod(load_editor(cls._tmp.name).mtx_remove_config_field)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_top_level_field_is_removed(self):
        out, ok = self.rm(V121_CONFIG, 'webrtcIPsFromInterfacesExcludeList')
        self.assertTrue(ok)
        self.assertNotIn('webrtcIPsFromInterfacesExcludeList', out)
        self.assertIn('logLevel: info', out)

    def test_nested_field_is_removed_from_its_parent_only(self):
        out, ok = self.rm(V121_CONFIG, 'pathDefaults.moqTransport')
        self.assertTrue(ok)
        self.assertIn('  record: no', out)
        self.assertEqual(out.count('moqTransport'), 1)             # the one under paths.test-stream stays
        self.assertIn('    moqTransport: yes', out)

    def test_nested_field_with_a_list_under_it_is_removed_whole(self):
        out, ok = self.rm(V121_CONFIG, 'pathDefaults.alwaysAvailableRecorded')
        self.assertTrue(ok)
        self.assertNotIn('alwaysAvailableRecorded', out)
        self.assertNotIn('tracks', out)
        self.assertIn('  record: no', out)

    def test_deeper_path_and_path_name_with_a_dot(self):
        text = 'paths:\n  cam.1:\n    source: publisher\n    extra: 1\n  cam2:\n    extra: 2\n'
        out, ok = self.rm(text, 'paths.cam.1.extra')
        self.assertTrue(ok)
        self.assertEqual(out, 'paths:\n  cam.1:\n    source: publisher\n  cam2:\n    extra: 2\n')

    def test_missing_field_changes_nothing(self):
        out, ok = self.rm(V121_CONFIG, 'pathDefaults.nope')
        self.assertFalse(ok)
        self.assertEqual(out, V121_CONFIG)
        out, ok = self.rm(V121_CONFIG, 'record')       # exists only nested: not a top-level field
        self.assertFalse(ok)

    def test_comments_and_other_lines_are_kept(self):
        out, _ = self.rm(V121_CONFIG, 'pathDefaults.moqTransport')
        self.assertTrue(out.startswith('# written by v1.21.3\n'))
        self.assertEqual(len(out.splitlines()), len(V121_CONFIG.splitlines()) - 1)


class RollbackFlowTest(unittest.TestCase):
    """Drives POST /api/mediamtx/version/rollback with a fake systemd and a fake v1.20.0 binary."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_rbf_')
        cls.m = load_editor(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        m = self.m
        os.makedirs(os.path.dirname(m.MEDIAMTX_BINARY), exist_ok=True)
        self.old_bin = m.MEDIAMTX_BINARY + '.backup_20260101_000000'
        with open(self.old_bin, 'w') as f:
            f.write('v1.20.0')
        for p in (m.MEDIAMTX_BINARY + '.backup_2026010%d_000000' % n for n in (2, 3, 4)):
            if os.path.exists(p):
                os.remove(p)
        for p in (m.CONFIG_FILE + '.backup_20260101_000000',
                  m.CONFIG_FILE + '.pre_rollback'):
            if os.path.exists(p):
                os.remove(p)
        with open(m.MEDIAMTX_BINARY, 'w') as f:
            f.write('v1.21.3')
        self.write_config(V121_CONFIG)
        self.installed = lambda: open(m.MEDIAMTX_BINARY).read()
        self.swaps = 0
        self.started = []   # (binary, config) every time systemd starts the service
        self.active = False

    def write_config(self, text):
        with open(self.m.CONFIG_FILE, 'w') as f:
            f.write(text)

    def config(self):
        with open(self.m.CONFIG_FILE) as f:
            return f.read()

    def post(self, journal=None):
        """Run the rollback. journal(config_text) -> text systemd logged for a failed start of the old binary."""
        m = self.m
        journal = journal or self.v120_journal

        def install(src):
            self.swaps += 1
            backup = m.MEDIAMTX_BINARY + '.backup_2026010%d_000000' % (self.swaps + 1)   # a new name each swap, like the clock
            with open(backup, 'w') as f:
                f.write(self.installed())
            with open(m.MEDIAMTX_BINARY, 'w') as f:
                f.write(open(src).read())
            return backup

        def systemctl(action):
            if action == 'start':
                text = journal(self.config()) if self.installed() == 'v1.20.0' else ''
                self.active = not text
                self.last_journal = text
                self.started.append((self.installed(), self.config()))
            else:
                self.active = False
            return mock.Mock(returncode=0, stderr=b'')

        def run(cmd, *a, **kw):
            if cmd[0] == 'systemctl':
                return mock.Mock(returncode=0, stdout='active\n' if self.active else 'activating\n')
            if cmd[0] == 'journalctl':
                return mock.Mock(returncode=0, stdout=self.last_journal)
            return mock.Mock(returncode=0, stdout=open(cmd[0]).read() + '\n')   # <binary> --version

        c = m.app.test_client()
        with c.session_transaction() as s:
            s['logged_in'] = True
            s['role'] = 'admin'
            s['username'] = 'alice'
        with mock.patch.object(m, 'mtx_priv_mode', return_value='root'), \
                mock.patch.object(m, 'mtx_systemctl', side_effect=systemctl), \
                mock.patch.object(m, 'mtx_install_binary', side_effect=install), \
                mock.patch.object(m, 'mtx_copy_priv', side_effect=lambda s, d: open(d, 'w').write(open(s).read())), \
                mock.patch.object(m, 'backup_config_file', return_value=None), \
                mock.patch.object(m.subprocess, 'run', side_effect=run), \
                mock.patch.object(m.time, 'sleep'):
            return c.post('/api/mediamtx/version/rollback')

    @staticmethod
    def v120_journal(config):
        """v1.20.0 refuses the first v1.21-only field it meets and says nothing when the config is clean."""
        from ruamel.yaml import YAML
        data = YAML(typ='safe').load(config)
        for field in UNKNOWN_IN_V120:
            node = data
            for part in field.split('.'):
                node = node.get(part) if isinstance(node, dict) and part in node else None
                if node is None:
                    break
            if node is not None:
                return 'ERR: json: unknown field "%s"\n' % field
        return ''

    def test_nested_unknown_fields_are_removed_and_the_old_version_starts(self):
        r = self.post()
        body = r.get_json()
        self.assertEqual(r.status_code, 200, body)
        self.assertEqual(body['fields_removed'], UNKNOWN_IN_V120)
        self.assertEqual(self.installed(), 'v1.20.0')
        self.assertTrue(self.active)
        config = self.config()
        self.assertIn('  record: no', config)                        # the rest of the config is untouched
        self.assertNotIn('alwaysAvailableRecorded', config)

    def test_if_the_old_version_still_cannot_start_the_newer_one_is_put_back(self):
        r = self.post(journal=lambda config: 'ERR: something else is wrong\n')
        body = r.get_json()
        self.assertEqual(r.status_code, 500)
        self.assertIn('newer version is back', body['error'])
        self.assertEqual(self.installed(), 'v1.21.3')                # never left on the binary that cannot run
        self.assertEqual(self.config(), V121_CONFIG)                 # and the config from before the rollback
        self.assertTrue(self.active)                                  # MediaMTX is running, not left down
        self.assertTrue(os.path.exists(self.old_bin))                # the backup stays, so a retry is possible

    def test_a_field_that_cannot_be_found_gives_up_at_once_instead_of_looping(self):
        r = self.post(journal=lambda config: 'ERR: json: unknown field "pathDefaults.ghost"\n')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(self.installed(), 'v1.21.3')
        self.assertEqual(len([s for s in self.started if s[0] == 'v1.20.0']), 1)   # one try, not six
        self.assertTrue(self.active)


if __name__ == '__main__':
    unittest.main()
