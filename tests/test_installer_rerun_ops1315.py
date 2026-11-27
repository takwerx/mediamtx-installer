"""Re-running an installer on a box that already has MediaMTX must not break it (ops #1315).

Re-running the installer is how people update MediaMTX: it fetches the newest binary, keeps the old
configuration and restarts. These tests run the real scripts (tests/installer_sandbox.py) against fake
system commands and check what a customer would see:

  * a new MediaMTX that will not start with the kept configuration is taken out again, the old one runs,
    and the script says so (it used to print "is running!" with MediaMTX down)
  * the binary it replaces is kept, a service that dies after one second is not "running"
  * a half-written configuration is never kept; a missing MoQ setting is added, an operator's value is not
  * a hand-edited service file and a closed port 5000 stay as the operator left them
  * the web editor's Python packages are built beside the old ones, an older checkout never replaces a
    newer editor

Run: python3 -I -m unittest discover -s tests -v
"""
import os
import re
import unittest

from installer_sandbox import (EDITOR_SCRIPT, ROCKY_SCRIPT, ROCKY_STDIN, UBUNTU_SCRIPT, Sandbox, binary_version,
                               fake_mediamtx)

OLD_CONFIG = """logLevel: info
legacyKey: yes
authInternalUsers:
- user: any
  pass: ''
  ips: ['127.0.0.1', '::1']
  permissions:
  - action: api
paths:
  all_others:
"""


class RerunMixin:
    """The checks both MediaMTX installers must pass. A subclass sets the script and how it runs."""
    script = None
    stdin = ''
    rocky = False
    done_marker = None          # text the script prints only when it believes it worked

    def setUp(self):
        self.sb = Sandbox(with_firewalld=self.rocky)
        self.addCleanup(self.sb.cleanup)
        self.sb.checkout()

    def release(self, binary):
        self.sb.release(binary, with_config=self.rocky)

    def box(self, config=OLD_CONFIG, version='1.0.0'):
        self.sb.installed(fake_mediamtx(version), config)

    def run_script(self, env=None):
        return self.sb.run(self.script, stdin=self.stdin, env=env)

    def out(self, r):
        return r.stdout + r.stderr

    # --- the new binary will not start ----------------------------------------------------------------
    def test_new_version_that_refuses_the_kept_config_is_taken_out_again(self):
        self.box()
        self.release(fake_mediamtx('9.9.9', rejects=['legacyKey']))
        r = self.run_script()
        out = self.out(r)
        self.assertNotEqual(r.returncode, 0, out)
        self.assertNotIn(self.done_marker, out, 'the script says it worked while MediaMTX is down')
        self.assertIn('did not stay running', out)
        self.assertIn('unknown field "legacyKey"', out, 'the reason from the log is shown')
        self.assertIn('previous MediaMTX is back and running', out)
        self.assertEqual(binary_version(self.sb.binary), 'v1.0.0', 'the old binary is back')
        self.assertEqual(self.sb.read(self.sb.config), OLD_CONFIG, 'the configuration is as it was')
        self.assertEqual(self.sb.calls().count('systemctl restart mediamtx'), 2, 'restarted onto the old binary')

    def test_a_service_that_dies_after_the_first_check_is_not_running(self):
        self.box()
        self.release(fake_mediamtx('9.9.9', flaps=True))
        r = self.run_script()
        out = self.out(r)
        self.assertNotEqual(r.returncode, 0, out)
        self.assertNotIn(self.done_marker, out)
        self.assertEqual(binary_version(self.sb.binary), 'v1.0.0')

    def test_a_fresh_install_that_does_not_start_says_so(self):
        self.release(fake_mediamtx('9.9.9', rejects=['logLevel']))
        r = self.run_script()
        out = self.out(r)
        self.assertNotEqual(r.returncode, 0, out)
        self.assertNotIn(self.done_marker, out)
        self.assertIn('no earlier MediaMTX', out)

    def test_both_failing_says_so_and_leaves_the_old_files(self):
        self.box(config=OLD_CONFIG + 'otherKey: 1\n')
        self.sb.write(self.sb.binary, fake_mediamtx('1.0.0', rejects=['otherKey']), 0o755)   # the old one fails too
        self.release(fake_mediamtx('9.9.9', rejects=['legacyKey']))
        r = self.run_script()
        out = self.out(r)
        self.assertNotEqual(r.returncode, 0, out)
        self.assertIn('does not stay running either', out)
        self.assertEqual(binary_version(self.sb.binary), 'v1.0.0')

    # --- the binary it replaces ------------------------------------------------------------------------
    def test_a_good_update_keeps_the_old_binary(self):
        self.box(config=OLD_CONFIG.replace('legacyKey: yes\n', ''))
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        self.assertEqual(binary_version(self.sb.binary), 'v9.9.9')
        kept = self.sb.backups(self.sb.binary + '.backup_')
        self.assertEqual(len(kept), 1, kept)
        self.assertEqual(binary_version(os.path.join(self.sb.bin_dir, kept[0])), 'v1.0.0')
        self.assertFalse(self.sb.backups(self.sb.binary + '.new'), 'no temporary binary is left')

    def test_a_download_that_does_not_match_its_checksum_is_refused(self):
        # checked and found safe (ops #1315): the box is left exactly as it was
        self.box(config=OLD_CONFIG.replace('legacyKey: yes\n', ''))
        self.release(fake_mediamtx('9.9.9'))
        self.sb.write(os.path.join(self.sb.fixtures, 'checksums.sha256'),
                      '%s  mediamtx_v9.9.9_linux_amd64.tar.gz\n' % ('0' * 64))
        before = self.sb.read(self.sb.binary)
        r = self.run_script()
        self.assertNotEqual(r.returncode, 0, self.out(r))
        self.assertIn('Checksum mismatch', self.out(r))
        self.assertEqual(self.sb.read(self.sb.binary), before)
        self.assertEqual(self.sb.backups(self.sb.binary + '.backup_'), [])

    # --- MoQ -----------------------------------------------------------------------------------------------
    def test_a_kept_config_without_a_moq_setting_gets_moq_no(self):
        self.box(config=OLD_CONFIG.replace('legacyKey: yes\n', ''))
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        cfg = self.sb.read(self.sb.config)
        self.assertEqual(len(re.findall(r'(?m)^moq: no$', cfg)), 1, cfg)
        self.assertIn('authInternalUsers:', cfg, 'the rest of the configuration is untouched')

    def test_a_kept_config_with_moq_yes_keeps_the_operators_choice(self):
        self.box(config=OLD_CONFIG.replace('legacyKey: yes\n', 'moq: yes\n'))
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        cfg = self.sb.read(self.sb.config)
        self.assertIn('moq: yes', cfg)
        self.assertNotIn('moq: no', cfg)
        self.assertIn('MoQ is on in this configuration', self.out(r), 'the script says it left MoQ on')
        self.assertNotIn('Added', self.out(r))

    def test_a_fresh_install_has_moq_off_and_leaves_no_temporary_files(self):
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        cfg = self.sb.read(self.sb.config)
        self.assertEqual(len(re.findall(r'(?m)^moq: (no|yes|true)$', cfg)), 1, cfg)
        self.assertIn('moq: no', cfg)
        leftovers = [n for n in os.listdir(self.sb.etc_dir) if n.startswith('mediamtx.yml.')]
        self.assertEqual(leftovers, [], 'no half-written copy is left')

    # --- a stopped run ----------------------------------------------------------------------------------------
    def test_a_run_stopped_half_way_does_not_leave_a_config_the_next_run_keeps(self):
        self.release(fake_mediamtx('9.9.9'))
        first = self.run_script(env={'FAKE_KILL_SED': 'mediamtx.yml'})
        self.assertNotEqual(first.returncode, 0, 'the first run was stopped')
        second = self.run_script()
        self.assertEqual(second.returncode, 0, self.out(second))
        self.assertNotIn('Existing configuration kept', self.out(second),
                         'a config left by the stopped run was kept as if it were the operator\'s')
        self.check_secured(self.sb.read(self.sb.config))

    # --- the service file --------------------------------------------------------------------------------------
    def test_a_hand_edited_service_file_is_kept(self):
        self.box(config=OLD_CONFIG.replace('legacyKey: yes\n', ''))
        self.sb.write(self.sb.unit, '[Unit]\nDescription=MediaMTX RTSP Server\n\n[Service]\nType=simple\n'
                      'ExecStart=%s %s\nRestart=always\nUser=mediamtx\nNoNewPrivileges=true\n\n[Install]\nWantedBy=multi-user.target\n'
                      % (self.sb.binary, self.sb.config))
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        unit = self.sb.read(self.sb.unit)
        self.assertIn('User=mediamtx', unit)
        self.assertIn('NoNewPrivileges=true', unit)
        self.assertNotIn('User=root', unit)

    def test_an_old_start_line_is_fixed_but_the_operators_lines_stay(self):
        self.box(config=OLD_CONFIG.replace('legacyKey: yes\n', ''))
        self.sb.write(self.sb.unit, '[Unit]\nDescription=old\n\n[Service]\nExecStart=%s\nUser=mediamtx\n\n[Install]\nWantedBy=multi-user.target\n'
                      % self.sb.binary)
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        unit = self.sb.read(self.sb.unit)
        self.assertIn('ExecStart=%s %s' % (self.sb.binary, self.sb.config), unit)
        self.assertIn('User=mediamtx', unit)
        self.assertEqual(unit.count('ExecStart='), 1)
        self.assertTrue(self.sb.backups(self.sb.unit + '.backup_'), 'the unit it changed is kept')

    def test_a_service_file_that_is_already_right_is_not_touched_or_backed_up(self):
        self.release(fake_mediamtx('9.9.9'))
        self.assertEqual(self.run_script().returncode, 0)          # first install writes the unit
        before = self.sb.read(self.sb.unit)
        r = self.run_script()                                       # re-run
        self.assertEqual(r.returncode, 0, self.out(r))
        self.assertEqual(self.sb.read(self.sb.unit), before)
        self.assertEqual(self.sb.backups(self.sb.unit + '.backup_'), [])


class UbuntuRerun(RerunMixin, unittest.TestCase):
    script = UBUNTU_SCRIPT
    done_marker = 'is running!'

    def check_secured(self, cfg):
        m = re.search(r'- user: hlsviewer\n  pass: (\S+)\n', cfg)
        self.assertIsNotNone(m, cfg)
        self.assertNotEqual(m.group(1), 'changeme', 'the HLS viewer password is still the placeholder')
        self.assertEqual(len(m.group(1)), 16)

    def test_a_config_left_with_the_placeholder_password_gets_a_random_one(self):
        cfg = ('authInternalUsers:\n- user: any\n  pass: ""\n  ips: [\'127.0.0.1\']\n'
               '- user: hlsviewer\n  pass: changeme\n  ips: []\n  permissions:\n  - action: read\n'
               '- user: operator\n  pass: changeme\n  ips: []\n  permissions:\n  - action: publish\n'
               'paths:\n  all_others:\n')
        self.box(config=cfg)
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        new = self.sb.read(self.sb.config)
        m = re.search(r'- user: hlsviewer\n  pass: (\S+)\n', new)
        self.assertNotEqual(m.group(1), 'changeme')
        self.assertIn('- user: operator\n  pass: changeme\n', new, 'another user with that word is not touched')
        self.assertIn(m.group(1), r.stdout, 'the new password is shown once')

    def test_a_config_with_a_chosen_hls_password_is_not_changed(self):
        self.box(config=OLD_CONFIG.replace('legacyKey: yes\n', '') + '#x\n')
        self.sb.write(self.sb.config, self.sb.read(self.sb.config).replace(
            'paths:', '- user: hlsviewer\n  pass: Chosen-by-me-1\n  ips: []\n  permissions:\n  - action: read\npaths:'))
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        self.assertIn('pass: Chosen-by-me-1', self.sb.read(self.sb.config))

    def test_a_fresh_install_gets_a_random_hls_password(self):
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        self.check_secured(self.sb.read(self.sb.config))


class RockyRerun(RerunMixin, unittest.TestCase):
    script = ROCKY_SCRIPT
    stdin = ROCKY_STDIN
    rocky = True
    done_marker = 'Installation Complete!'

    def check_secured(self, cfg):
        self.assertIn('- user: "tester"', cfg, 'the credentials step ran')
        self.assertNotRegex(cfg, r"(?m)^- user: any\n  pass:\n  ips: \[\]\n  permissions:\n  - action: publish",
                            'upstream\'s open "anyone can publish" entry is gone')

    def test_a_fresh_install_turns_upstreams_moq_off(self):
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, self.out(r))
        cfg = self.sb.read(self.sb.config)
        self.assertIn('moq: no', cfg)
        self.assertNotIn('moq: true', cfg)
        self.check_secured(cfg)

    def test_nothing_is_published_under_the_real_name_until_the_credentials_are_set(self):
        # A stop at the user name prompt, or any failure in the credentials step, must leave no config.
        self.release(fake_mediamtx('9.9.9'))
        r = self.run_script(env={'FAKE_KILL_SED': 'TrustedProxies'})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.sb.config), 'upstream\'s open config was left under the real name')


class EditorInstaller(unittest.TestCase):
    """config-editor/Install_MediaMTX_Config_Editor.sh on a box that already runs the editor."""

    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.installed(fake_mediamtx('1.0.0'), OLD_CONFIG.replace('legacyKey: yes\n', ''))

    def installed_editor(self, version='2.1.21', venv=True, unit=None):
        ed = self.sb.editor_dir
        self.sb.write(os.path.join(ed, 'mediamtx_config_editor.py'), '# installed\nCURRENT_VERSION = "v%s"\n' % version)
        if venv:
            self.sb.write(os.path.join(ed, 'venv', '.pip_ok'), '')
            self.sb.write(os.path.join(ed, 'venv', 'old_marker'), 'the venv that was running\n')
        if unit:
            self.sb.write(self.sb.editor_unit, unit)

    def run_installer(self, checkout_version, env=None):
        self.sb.checkout(editor_version=checkout_version)
        return self.sb.run(EDITOR_SCRIPT, env=env)

    def out(self, r):
        return r.stdout + r.stderr

    def hardened_unit(self):
        return ('[Unit]\nDescription=MediaMTX Web Configuration Editor\nAfter=network.target mediamtx.service\n\n[Service]\n'
                'Type=simple\nExecStart=/usr/bin/python3 %s/mediamtx_config_editor.py\nRestart=always\nRestartSec=5\n'
                'User=webed\nNoNewPrivileges=true\nProtectSystem=full\n\n[Install]\nWantedBy=multi-user.target\n' % self.sb.editor_dir)

    # --- an old checkout ------------------------------------------------------------------------------------
    def test_an_older_checkout_never_replaces_a_newer_editor(self):
        self.installed_editor('2.1.21')
        before = self.sb.read(os.path.join(self.sb.editor_dir, 'mediamtx_config_editor.py'))
        r = self.run_installer('2.1.14')
        out = self.out(r)
        self.assertNotEqual(r.returncode, 0, out)
        self.assertIn('older than the one installed', out)
        self.assertEqual(self.sb.read(os.path.join(self.sb.editor_dir, 'mediamtx_config_editor.py')), before)
        self.assertTrue(os.path.exists(os.path.join(self.sb.editor_dir, 'venv', 'old_marker')), 'the venv was not touched')
        self.assertFalse([c for c in self.sb.calls() if c.startswith('apt-get')], 'nothing was installed')

    def test_which_versions_count_as_older(self):
        cases = [('2.1.21-dev', '2.1.21', 1),      # a dev build is older than the release it leads to
                 ('2.1.22-dev', '2.1.21', 0),
                 ('2.1.21', '2.1.21', 0),          # the same version again is a normal re-run
                 ('2.1.21', '2.1.21-dev', 0),
                 ('2.0.30', '2.1.0', 1),
                 ('2.10.0', '2.9.9', 0),           # numbers, not text
                 ('3.0.0', '2.9.9', 0)]
        for checkout, installed, refused in cases:
            with self.subTest(checkout=checkout, installed=installed):
                self.setUp()
                self.installed_editor(installed)
                r = self.run_installer(checkout)
                self.assertEqual(r.returncode != 0, bool(refused), self.out(r))
                self.sb.cleanup()

    def test_the_editor_it_replaces_is_kept_for_rollback_only_when_it_differs(self):
        self.installed_editor('2.1.20')
        r = self.run_installer('2.1.21')
        self.assertEqual(r.returncode, 0, self.out(r))
        kept = self.sb.backups(os.path.join(self.sb.editor_dir, 'mediamtx_config_editor.py.backup_'))
        self.assertEqual(len(kept), 1, kept)
        self.assertIn('v2.1.20', self.sb.read(os.path.join(self.sb.editor_dir, kept[0])))
        same = self.run_installer('2.1.21')                      # a second run with the same editor file
        self.assertEqual(same.returncode, 0, self.out(same))
        self.assertEqual(len(self.sb.backups(os.path.join(self.sb.editor_dir, 'mediamtx_config_editor.py.backup_'))), 1)

    # --- the Python packages --------------------------------------------------------------------------------
    def test_a_failed_pip_leaves_the_running_editors_packages_in_place(self):
        self.installed_editor('2.1.20')
        r = self.run_installer('2.1.21', env={})
        self.assertEqual(r.returncode, 0, self.out(r))                       # sanity: works when pip works
        self.installed_editor('2.1.20')
        self.sb.write(os.path.join(self.sb.state, 'pip_fail'), '')
        r = self.run_installer('2.1.21')
        out = self.out(r)
        self.assertNotEqual(r.returncode, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.sb.editor_dir, 'venv', '.pip_ok')),
                        'the old venv has lost its packages (no Flask at the next restart)')
        self.assertTrue(os.path.exists(os.path.join(self.sb.editor_dir, 'venv', 'old_marker')))
        self.assertFalse(os.path.exists(os.path.join(self.sb.editor_dir, 'venv.new')), 'the half-built venv is removed')
        self.assertIn('current Python packages were not changed', out)

    def test_the_new_venv_replaces_the_old_one_which_is_kept(self):
        self.installed_editor('2.1.20')
        r = self.run_installer('2.1.21')
        self.assertEqual(r.returncode, 0, self.out(r))
        ed = self.sb.editor_dir
        self.assertTrue(os.path.exists(os.path.join(ed, 'venv', '.pip_ok')))
        self.assertFalse(os.path.exists(os.path.join(ed, 'venv', 'old_marker')), 'the running venv is the new one')
        self.assertTrue(os.path.exists(os.path.join(ed, 'venv.prev', 'old_marker')), 'the old venv is kept')
        self.assertFalse(os.path.exists(os.path.join(ed, 'venv.new')))
        for name in ('pyvenv.cfg', os.path.join('bin', 'pip')):
            text = self.sb.read(os.path.join(ed, 'venv', name))
            self.assertNotIn('venv.new', text, name + ' still points at the folder it was built in')

    # --- the service file and the firewall ----------------------------------------------------------------------
    def test_a_hardened_editor_service_file_is_kept(self):
        self.installed_editor('2.1.20', unit=self.hardened_unit())
        r = self.run_installer('2.1.21')
        self.assertEqual(r.returncode, 0, self.out(r))
        unit = self.sb.read(self.sb.editor_unit)
        self.assertIn('User=webed', unit)
        self.assertIn('NoNewPrivileges=true', unit)
        self.assertIn('ProtectSystem=full', unit)
        self.assertNotIn('User=root', unit)
        self.assertIn('ExecStart=%s/venv/bin/python3 %s/mediamtx_config_editor.py' % (self.sb.editor_dir, self.sb.editor_dir), unit,
                      'the start line points at the venv, which is what the installer needs')
        self.assertIn('WorkingDirectory=%s' % self.sb.editor_dir, unit)
        self.assertEqual(unit.count('ExecStart='), 1)

    def test_a_first_install_gets_the_installers_service_file_and_opens_port_5000(self):
        self.installed_editor('2.1.20', venv=False)
        r = self.run_installer('2.1.21')
        self.assertEqual(r.returncode, 0, self.out(r))
        self.assertIn('User=root', self.sb.read(self.sb.editor_unit))
        self.assertIn('ufw allow 5000/tcp', self.sb.calls())

    def test_a_rerun_does_not_open_port_5000_again(self):
        self.installed_editor('2.1.20', unit=self.hardened_unit())
        r = self.run_installer('2.1.21')
        self.assertEqual(r.returncode, 0, self.out(r))
        self.assertNotIn('ufw allow 5000/tcp', self.sb.calls(), 'a box where port 5000 was closed on purpose was opened again')
        self.assertIn('firewall was left as it is', r.stdout)


if __name__ == '__main__':
    unittest.main()
