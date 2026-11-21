"""Rocky/RHEL 9 builds the web editor's venv from python3.12 (ops #1030).

urllib3 2.8.0 and requests 2.34.2 (the releases with the security fixes) need Python 3.10 or newer, and
Rocky 9's own python3 is 3.9. So:
  * a fresh install gets python3.12 from the AppStream and builds the venv from it;
  * a box installed earlier moves its venv to python3.12 the first time the new editor starts, because the
    console's Update only replaces the editor file and never touches the venv.

No root, no Rocky box and no network are needed here: the installer's own install_python function runs
against fake dnf/apt-get, and the editor's refresh runs against a fake command runner in a sandbox.

Run: python3 -m unittest discover -s tests -v   (needs flask, ruamel.yaml, psutil, requests)
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_console_password_hashing import load_editor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
INSTALLER = os.path.join(ROOT, 'config-editor', 'Install_MediaMTX_Config_Editor.sh')


def installer_text():
    with open(INSTALLER, encoding='utf-8') as f:
        return f.read()


def install_python_function():
    m = re.search(r'# >>> install_python\n(.*?)# <<< install_python\n', installer_text(), re.S)
    return m.group(1) if m else None


def write_exe(path, body):
    with open(path, 'w') as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class InstallPythonTest(unittest.TestCase):
    def run_function(self, manager, makes_python312=True, system_python_old=True):
        """Run install_python with only fake tools on PATH. Returns (rc, output, calls, VENV_PYTHON)."""
        fn = install_python_function()
        self.assertIsNotNone(fn, 'the installer has no install_python function between its markers')
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, 'calls')
            # Stand-ins, so the result does not depend on the Python that runs the tests (CI runs 3.9):
            # a "python3.12" that passes the installer's version check, and Rocky's own python3, which is 3.9 and fails it.
            new_py = os.path.join(d, 'python3.12')
            template = os.path.join(d, 'python3.12.template')
            write_exe(template, '#!/bin/bash\nexit 0\n')
            if manager == 'dnf':
                write_exe(os.path.join(d, 'dnf'),
                          '#!/bin/bash\necho "dnf $*" >> "%s"\n'
                          '%s\nexit 0\n' % (log, ('[[ "$*" == *python3.12* ]] && /bin/cp "%s" "%s"' % (template, new_py)) if makes_python312 else ':'))
                write_exe(os.path.join(d, 'python3'),
                          '#!/bin/bash\n[ "$1" = -c ] && exit 1\nexit 0\n' if system_python_old else '#!/bin/bash\nexit 0\n')
            else:
                write_exe(os.path.join(d, 'apt-get'), '#!/bin/bash\necho "apt-get $*" >> "%s"\nexit 0\n' % log)
                write_exe(os.path.join(d, 'python3'), '#!/bin/bash\nexit 0\n')
            script = fn + '\ninstall_python\necho "VENV_PYTHON=$VENV_PYTHON"\n'
            r = subprocess.run(['/bin/bash', '-c', script], env={'PATH': d}, capture_output=True, text=True, timeout=60)
            calls = open(log).read().splitlines() if os.path.exists(log) else []
            m = re.search(r'VENV_PYTHON=(\S+)', r.stdout)
            return r.returncode, r.stdout, calls, (m.group(1) if m else None)

    def test_rocky_9_installs_python312_and_builds_the_venv_from_it(self):
        rc, out, calls, venv_python = self.run_function('dnf')
        self.assertEqual(rc, 0, out)
        self.assertEqual(venv_python, 'python3.12')
        self.assertTrue(any(c.startswith('dnf install') and 'python3.12' in c and 'python3.12-pip' in c for c in calls), calls)

    def test_rocky_9_stops_with_a_plain_message_when_python312_cannot_be_installed(self):
        rc, out, calls, venv_python = self.run_function('dnf', makes_python312=False)
        self.assertNotEqual(rc, 0)
        self.assertIn('python3.12 is not available', out)
        self.assertIsNone(venv_python)

    def test_ubuntu_keeps_using_the_system_python3(self):
        rc, out, calls, venv_python = self.run_function('apt')
        self.assertEqual(rc, 0, out)
        self.assertEqual(venv_python, 'python3')
        self.assertTrue(all(c.startswith('apt-get') for c in calls), calls)

    def test_venv_is_built_from_the_chosen_python(self):
        s = installer_text()
        self.assertRegex(s, r'"\$VENV_PYTHON" -m venv --clear --system-site-packages "\$VENV_DIR"')
        self.assertNotRegex(s, r'(?m)^\s*(if ! )?python3 -m venv')


SANDBOX_PY39 = (3, 9, 25)


class VenvRefreshTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='mtx_venv_')
        cls.m = load_editor(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        m = self.m
        for p in (m.VENV_DIR, m.VENV_PREV_DIR, m.VENV_NEW_DIR, m.VENV_REFRESH_STATE):
            if os.path.isdir(p):
                import shutil
                shutil.rmtree(p)
            elif os.path.exists(p):
                os.remove(p)
        os.makedirs(os.path.join(m.VENV_DIR, 'bin'))
        with open(os.path.join(m.VENV_DIR, 'old.txt'), 'w') as f:
            f.write('python 3.9 venv')

    # ---- when does it run -------------------------------------------------------------------
    def needed(self, **kw):
        args = dict(prefix=self.m.VENV_DIR, version_info=SANDBOX_PY39, euid=0, have_dnf=True, state={}, now=1000.0)
        args.update(kw)
        return self.m.venv_refresh_needed(**args)

    def test_runs_for_the_standalone_venv_on_python_39_as_root_with_dnf(self):
        self.assertTrue(self.needed())

    def test_does_not_run_when_python_is_already_310_or_newer(self):
        self.assertFalse(self.needed(version_info=(3, 10, 12)))
        self.assertFalse(self.needed(version_info=(3, 12, 16)))

    def test_does_not_run_outside_the_standalone_venv(self):
        # infra-TAK runs the editor on the system python3 as its own account.
        self.assertFalse(self.needed(prefix='/usr'))
        self.assertFalse(self.needed(euid=1001))

    def test_does_not_run_without_dnf(self):
        self.assertFalse(self.needed(have_dnf=False))

    def test_a_failure_is_not_retried_on_every_start_but_after_a_day(self):
        state = {'status': 'failed', 'time': 1000.0}
        self.assertFalse(self.needed(state=state, now=1000.0 + 3600))
        self.assertTrue(self.needed(state=state, now=1000.0 + 25 * 3600))

    # ---- the rebuild ---------------------------------------------------------------------------
    def fake_run(self, fail_on=None, calls=None):
        m = self.m

        def run(cmd, **kw):
            calls.append(cmd)
            joined = ' '.join(cmd)
            rc, err = 0, ''
            if fail_on and fail_on in joined:
                rc, err = 1, 'boom from ' + fail_on
            elif '-m venv' in joined:
                os.makedirs(os.path.join(m.VENV_NEW_DIR, 'bin'))
                with open(os.path.join(m.VENV_NEW_DIR, 'pyvenv.cfg'), 'w') as f:
                    f.write('command = /usr/bin/python3.12 -m venv ' + m.VENV_NEW_DIR + '\n')
                with open(os.path.join(m.VENV_NEW_DIR, 'bin', 'pip'), 'w') as f:
                    f.write('#!' + m.VENV_NEW_DIR + '/bin/python3\nprint("pip")\n')
            elif 'import psutil' in joined and '-c' in cmd and 'flask' not in joined:
                rc = 1  # psutil is not in the venv yet, so the psutil file is installed too
            return subprocess.CompletedProcess(cmd, rc, '', err)
        return run

    def fetch(self, url):
        return 'flask==3.1.3 \\\n    --hash=sha256:' + 'a' * 64 + '\n'

    def refresh(self, **kw):
        calls = []
        with mock.patch.object(self.m.shutil, 'which', return_value='/usr/bin/python3.12'):
            ok, msg = self.m.refresh_venv_to_newer_python(
                run=self.fake_run(calls=calls, **kw), fetch=self.fetch, editor_file=__file__)
        return ok, msg, calls

    def test_success_swaps_the_venv_and_keeps_the_old_one(self):
        m = self.m
        ok, msg, calls = self.refresh()
        self.assertTrue(ok, msg)
        self.assertTrue(os.path.exists(os.path.join(m.VENV_PREV_DIR, 'old.txt')), 'the old venv is kept for one generation')
        self.assertFalse(os.path.exists(os.path.join(m.VENV_DIR, 'old.txt')))
        self.assertFalse(os.path.exists(m.VENV_NEW_DIR))
        # pip is installed with hashes, from the new venv's python, both requirement files
        pips = [c for c in calls if 'pip' in c and 'install' in c]
        self.assertEqual(len(pips), 2)
        for c in pips:
            self.assertIn('--require-hashes', c)
            self.assertTrue(c[0].startswith(m.VENV_NEW_DIR), c)
        # the scripts in the moved venv no longer point at the folder it was built in
        with open(os.path.join(m.VENV_DIR, 'pyvenv.cfg')) as f:
            self.assertNotIn('venv.new', f.read())
        with open(os.path.join(m.VENV_DIR, 'bin', 'pip')) as f:
            self.assertEqual(f.readline().strip(), '#!' + m.VENV_DIR + '/bin/python3')

    def test_failures_leave_the_working_venv_alone(self):
        m = self.m
        for step in ('--require-hashes', '-m venv', 'import sys, ast'):
            with self.subTest(step=step):
                os.makedirs(m.VENV_DIR, exist_ok=True)
                with open(os.path.join(m.VENV_DIR, 'old.txt'), 'w') as f:
                    f.write('python 3.9 venv')
                ok, msg, calls = self.refresh(fail_on=step)
                self.assertFalse(ok)
                self.assertIn('boom', msg)
                self.assertTrue(os.path.exists(os.path.join(m.VENV_DIR, 'old.txt')), 'the old venv must still be in place')
                self.assertFalse(os.path.exists(m.VENV_NEW_DIR), 'no half-built venv is left behind')
                self.assertFalse(os.path.exists(m.VENV_PREV_DIR))

    def test_a_requirements_file_that_is_not_pinned_is_refused(self):
        with mock.patch.object(self.m.shutil, 'which', return_value='/usr/bin/python3.12'):
            ok, msg = self.m.refresh_venv_to_newer_python(
                run=self.fake_run(calls=[]), fetch=lambda url: '404: Not Found', editor_file=__file__)
        self.assertFalse(ok)
        self.assertIn('pinned requirements', msg)
        self.assertTrue(os.path.exists(os.path.join(self.m.VENV_DIR, 'old.txt')))

    def test_python312_is_installed_with_dnf_when_missing(self):
        calls = []
        seen = iter([None, '/usr/bin/python3.12'])
        with mock.patch.object(self.m.shutil, 'which', side_effect=lambda n: next(seen)):
            ok, msg = self.m.refresh_venv_to_newer_python(
                run=self.fake_run(calls=calls), fetch=self.fetch, editor_file=__file__)
        self.assertTrue(ok, msg)
        self.assertEqual(calls[0][:3], ['dnf', 'install', '-y'])
        self.assertIn('python3.12', calls[0])

    # ---- the startup hook ------------------------------------------------------------------------
    def test_start_records_success_and_restarts_once(self):
        m = self.m
        started = []

        class Inline:
            def __init__(self, target, **kw): self.target = target
            def start(self): started.append(1); self.target()
        with mock.patch.object(m, 'venv_refresh_needed', return_value=True), \
             mock.patch.object(m, 'refresh_venv_to_newer_python', return_value=(True, 'venv rebuilt')), \
             mock.patch.object(m, 'schedule_editor_self_restart') as restart, \
             mock.patch.object(m.threading, 'Thread', Inline):
            self.assertTrue(m.start_venv_refresh())
        restart.assert_called_once()
        self.assertEqual(json.load(open(m.VENV_REFRESH_STATE))['status'], 'done')

    def test_start_records_failure_and_does_not_restart(self):
        m = self.m

        class Inline:
            def __init__(self, target, **kw): self.target = target
            def start(self): self.target()
        with mock.patch.object(m, 'venv_refresh_needed', return_value=True), \
             mock.patch.object(m, 'refresh_venv_to_newer_python', return_value=(False, 'pip install failed')), \
             mock.patch.object(m, 'schedule_editor_self_restart') as restart, \
             mock.patch.object(m.threading, 'Thread', Inline):
            m.start_venv_refresh()
        restart.assert_not_called()
        state = json.load(open(m.VENV_REFRESH_STATE))
        self.assertEqual(state['status'], 'failed')
        self.assertIn('pip install failed', state['message'])

    def test_start_does_nothing_when_not_needed(self):
        with mock.patch.object(self.m, 'venv_refresh_needed', return_value=False), \
             mock.patch.object(self.m.threading, 'Thread') as thread:
            self.assertFalse(self.m.start_venv_refresh())
        thread.assert_not_called()

    def test_the_editor_calls_it_at_startup(self):
        with open(os.path.join(ROOT, 'config-editor', 'mediamtx_config_editor.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertRegex(src, r"(?m)^    start_venv_refresh\(\).*\n    app\.run\(")


if __name__ == '__main__':
    unittest.main()
