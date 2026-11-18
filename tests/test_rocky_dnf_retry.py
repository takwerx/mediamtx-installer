"""The Rocky 9 installer survives a short RPM Fusion mirror outage (ops #640, #693).

On Nov 10, 2026 about 4 PM PT every RPM Fusion mirror answered 404 for the repodata files
for a few minutes, and a fresh Rocky 9 install stopped at "dnf install ffmpeg". The script now
cleans the dnf cache and tries again. These tests run the script's own dnf_retry function
against a fake dnf, so no root or Rocky box is needed.

Run: python3 -I -m unittest discover -s tests -v
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SCRIPT = os.path.join(ROOT, 'rocky-9', 'Rocky_9_MediaMTX_install.sh')


def read_script():
    with open(SCRIPT, encoding='utf-8') as f:
        return f.read()


def retry_function():
    m = re.search(r'# >>> dnf_retry\n(.*?)# <<< dnf_retry\n', read_script(), re.S)
    return m.group(1) if m else None


class DnfRetry(unittest.TestCase):
    def run_with_fake_dnf(self, fail_times, tries='5'):
        """Run dnf_retry against a dnf that fails `fail_times` times for `install`, then works."""
        fn = retry_function()
        self.assertIsNotNone(fn, 'the script has no dnf_retry function between its markers')
        with tempfile.TemporaryDirectory() as d:
            counter = os.path.join(d, 'count')
            log = os.path.join(d, 'calls')
            fake = os.path.join(d, 'dnf')
            with open(fake, 'w') as f:
                f.write('#!/bin/bash\n'
                        'echo "$*" >> "%s"\n'
                        '[ "$1" = clean ] && exit 0\n'
                        'n=$(cat "%s" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "%s"\n'
                        '[ "$n" -gt %d ]\n' % (log, counter, counter, fail_times))
            os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
            env = dict(os.environ, PATH=d + os.pathsep + os.environ['PATH'],
                       DNF_RETRIES=tries, DNF_RETRY_DELAY='0')
            r = subprocess.run(['bash', '-c', fn + '\ndnf_retry install -y ffmpeg'],
                               env=env, capture_output=True, text=True, timeout=30)
            with open(log) as f:
                calls = f.read().splitlines()
            return r.returncode, calls

    def test_recovers_after_two_failures(self):
        rc, calls = self.run_with_fake_dnf(2)
        self.assertEqual(rc, 0)
        self.assertEqual(calls.count('install -y ffmpeg'), 3)
        self.assertEqual(calls.count('clean all'), 2, 'the cache is cleaned between tries')

    def test_gives_up_after_the_last_try(self):
        rc, calls = self.run_with_fake_dnf(99, tries='3')
        self.assertNotEqual(rc, 0)
        self.assertEqual(calls.count('install -y ffmpeg'), 3)

    def test_works_first_time_without_cleaning(self):
        rc, calls = self.run_with_fake_dnf(0)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ['install -y ffmpeg'])


class ScriptUsesIt(unittest.TestCase):
    def test_both_rpmfusion_steps_go_through_the_retry(self):
        s = read_script()
        self.assertRegex(s, r'dnf_retry install -y "https://mirrors\.rpmfusion\.org/free/el/rpmfusion-free-release-')
        self.assertRegex(s, r'dnf_retry install -y ffmpeg')
        self.assertNotRegex(s, r'(?m)^\s*dnf install -y ffmpeg')


if __name__ == '__main__':
    unittest.main()
