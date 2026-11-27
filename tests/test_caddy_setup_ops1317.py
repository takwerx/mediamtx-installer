"""The Caddy setup scripts change only their own site in a customer's Caddyfile (ops #1317).

Before: answering "y" for example.com deleted the tak.example.com block too (the old match was a
substring and a regex), the Rocky script's sed range ran to the end of the file when it found no
"}" in column 0, nothing was validated on Rocky, a failed validation left the edited file in
place, and ((WAIT_COUNT++)) ended the Ubuntu script on its first wait for the certificate.

These tests run the scripts' own functions (between the "# >>> name" and "# <<< name" markers)
against real files and fake caddy/sleep commands, so no root, Caddy or box is needed.

Run: python3 -I -m unittest discover -s tests -v
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
UBUNTU = os.path.join(ROOT, 'ubuntu-22.04', 'Ubuntu_22.04_Install_MediaMTX_Caddy.sh')
ROCKY = os.path.join(ROOT, 'rocky-9', 'Rocky_9_Caddy_setup.sh')


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def block(name, path=UBUNTU):
    m = re.search(r'# >>> %s\n(.*?)# <<< %s\n' % (name, name), read(path), re.S)
    return m.group(1) if m else None


def fake_command(directory, name, body):
    path = os.path.join(directory, name)
    with open(path, 'w') as f:
        f.write('#!/bin/bash\n' + body + '\n')
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


APEX = 'example.com'
APEX_BLOCK = '''# MediaMTX Web Configuration Editor
example.com {
    # Reverse proxy to MediaMTX Config Editor
    reverse_proxy localhost:5000
}'''

TAK_SITE = '''tak.example.com {
    reverse_proxy localhost:8443 {
        transport http {
            tls_insecure_skip_verify
        }
    }
}
'''

OTHER_SITE = '''portal.example.com {
    handle /api/* {
        reverse_proxy localhost:3000
    }
    handle {
        reverse_proxy localhost:3001
    }
}
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.cf = os.path.join(self.dir, 'Caddyfile')

    def write_cf(self, text):
        with open(self.cf, 'w') as f:
            f.write(text)

    def read_cf(self):
        return read(self.cf)

    def functions(self):
        fn = block('caddy_site_functions')
        self.assertIsNotNone(fn, 'the script has no caddy_site_functions block between its markers')
        return fn

    def remove(self, domain, text):
        self.write_cf(text)
        out = os.path.join(self.dir, 'out')
        r = subprocess.run(
            ['bash', '-c', self.functions() + '\ncaddy_remove_site "$1" "$2" "$3"; echo "rc=$?"',
             'x', self.cf, out, domain], capture_output=True, text=True, timeout=30)
        rc = int(re.search(r'rc=(\d+)', r.stdout).group(1))
        return rc, (read(out) if os.path.exists(out) else None)


class RemoveSite(Fixture):
    def test_apex_answer_leaves_the_tak_block_alone(self):
        """The reported case: an apex block and a tak. block, setup for the apex."""
        text = TAK_SITE + '\n' + APEX_BLOCK + '\n\n' + OTHER_SITE
        rc, out = self.remove(APEX, text)
        self.assertEqual(rc, 0)
        self.assertIn('tak.example.com {', out)
        self.assertIn('tls_insecure_skip_verify', out)
        self.assertIn('portal.example.com {', out)
        self.assertNotIn('\nexample.com {', '\n' + out)
        self.assertNotIn('localhost:5000', out)

    def test_domain_that_is_only_a_part_of_another_site_is_not_found(self):
        """Setup for tak.example.com must not match anything in a file that has only longer names."""
        rc, out = self.remove('example.com', TAK_SITE + OTHER_SITE)
        self.assertEqual(rc, 3)
        self.assertIsNone(out)

    def test_dots_in_the_domain_are_not_a_regex(self):
        rc, _ = self.remove('example.com', 'exampleXcom {\n    respond "x"\n}\n')
        self.assertEqual(rc, 3)

    def test_indented_closing_brace_does_not_eat_the_rest_of_the_file(self):
        """The Rocky sed range ran to the end of the file when no "}" stood in column 0."""
        text = ('example.com {\n    reverse_proxy localhost:5000\n    }\n\n' + TAK_SITE + OTHER_SITE)
        rc, out = self.remove(APEX, text)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), (TAK_SITE + OTHER_SITE).strip())

    def test_nested_blocks_inside_the_site_go_with_it(self):
        text = ('example.com {\n    handle /a/* {\n        respond "a"\n    }\n    handle {\n'
                '        respond "b"\n    }\n}\n' + TAK_SITE)
        rc, out = self.remove(APEX, text)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), TAK_SITE.strip())

    def test_braces_that_do_not_close_refuse_and_write_nothing(self):
        rc, out = self.remove(APEX, TAK_SITE + 'example.com {\n    reverse_proxy localhost:5000\n')
        self.assertEqual(rc, 5)
        self.assertIsNone(out)

    def test_block_shared_with_another_address_is_refused(self):
        rc, out = self.remove(APEX, 'example.com, www.example.com {\n    respond "x"\n}\n' + TAK_SITE)
        self.assertEqual(rc, 4)
        self.assertIsNone(out)

    def test_https_prefix_and_port_443_forms_match(self):
        for head in ('https://example.com', 'example.com:443', 'EXAMPLE.com'):
            rc, out = self.remove(APEX, head + ' {\n    respond "x"\n}\n' + TAK_SITE)
            self.assertEqual(rc, 0, head)
            self.assertIn('tak.example.com', out, head)

    def test_global_options_and_snippets_are_kept(self):
        text = '{\n    email admin@example.com\n}\n\n(common) {\n    encode gzip\n}\n\n' + APEX_BLOCK + '\n'
        rc, out = self.remove(APEX, text)
        self.assertEqual(rc, 0)
        self.assertIn('email admin@example.com', out)
        self.assertIn('(common) {', out)

    def test_our_own_comment_line_goes_with_the_block(self):
        """Replacing twice must not stack up "# MediaMTX ..." comments."""
        rc, out = self.remove(APEX, TAK_SITE + '\n' + APEX_BLOCK + '\n')
        self.assertEqual(rc, 0)
        self.assertNotIn('MediaMTX Web Configuration Editor', out)


class ConfigureSite(Fixture):
    def run_configure(self, domain, answer='', text=None):
        if text is not None:
            self.write_cf(text)
        script = self.functions() + '\ncaddy_configure_site "$1" "$2" "$3"; echo "rc=$?"; echo "backup=$CADDYFILE_BACKUP"'
        r = subprocess.run(['bash', '-c', script, 'x', self.cf, domain,
                            APEX_BLOCK.replace('example.com', domain)],
                           input=answer, capture_output=True, text=True, timeout=30)
        rc = int(re.search(r'rc=(\d+)', r.stdout).group(1))
        backup = re.search(r'backup=(.*)', r.stdout).group(1)
        return rc, backup, r.stdout

    def test_new_domain_is_appended_and_every_other_site_is_unchanged(self):
        original = TAK_SITE + '\n' + OTHER_SITE
        rc, backup, _ = self.run_configure(APEX, text=original)
        self.assertEqual(rc, 0)
        self.assertTrue(self.read_cf().startswith(original))
        self.assertIn('example.com {', self.read_cf())
        self.assertEqual(read(backup), original, 'the backup is the file as it was')

    def test_apex_answer_y_replaces_only_the_apex_block(self):
        original = TAK_SITE + '\n' + APEX_BLOCK + '\n\n' + OTHER_SITE
        rc, backup, _ = self.run_configure(APEX, answer='y\n', text=original)
        self.assertEqual(rc, 0)
        cf = self.read_cf()
        self.assertEqual(cf.count('tak.example.com {'), 1)
        self.assertEqual(cf.count('portal.example.com {'), 1)
        self.assertEqual(len(re.findall(r'(?m)^example\.com \{', cf)), 1)
        self.assertEqual(read(backup), original)

    def test_answer_n_changes_nothing(self):
        original = TAK_SITE + '\n' + APEX_BLOCK + '\n'
        rc, _, _ = self.run_configure(APEX, answer='n\n', text=original)
        self.assertEqual(rc, 2)
        self.assertEqual(self.read_cf(), original)

    def test_no_answer_at_all_changes_nothing(self):
        original = APEX_BLOCK + '\n'
        rc, _, _ = self.run_configure(APEX, answer='', text=original)
        self.assertEqual(rc, 2)
        self.assertEqual(self.read_cf(), original)

    def test_file_owner_mode_is_kept(self):
        self.write_cf(TAK_SITE + '\n' + APEX_BLOCK + '\n')
        os.chmod(self.cf, 0o640)
        self.run_configure(APEX, answer='y\n')
        self.assertEqual(stat.S_IMODE(os.stat(self.cf).st_mode), 0o640)

    def test_shared_block_and_broken_braces_leave_the_file_alone(self):
        for original in ('example.com, www.example.com {\n    respond "x"\n}\n',
                         TAK_SITE + 'example.com {\n    respond "x"\n'):
            rc, backup, _ = self.run_configure(APEX, answer='y\n', text=original)
            self.assertEqual(rc, 1)
            self.assertEqual(self.read_cf(), original)
            self.assertEqual(read(backup), original)

    def test_missing_caddyfile_is_created(self):
        rc, backup, _ = self.run_configure(APEX)
        self.assertEqual(rc, 0)
        self.assertEqual(backup, '')
        self.assertIn('reverse_proxy localhost:5000', self.read_cf())

    def test_a_domain_that_could_add_config_lines_is_refused(self):
        original = TAK_SITE
        for bad in ('x.com {\n respond "pwned"\n}\nevil.com', 'a b.com', 'a.com}', '.'):
            rc, _, _ = self.run_configure(bad, text=original)
            self.assertEqual(rc, 1, bad)
            self.assertEqual(self.read_cf(), original)


class ValidateOrRestore(Fixture):
    def run_validate(self, caddy_body):
        bindir = os.path.join(self.dir, 'bin')
        os.mkdir(bindir)
        fake_command(bindir, 'caddy', caddy_body)
        backup = os.path.join(self.dir, 'Caddyfile.backup')
        with open(backup, 'w') as f:
            f.write(TAK_SITE)
        self.write_cf(TAK_SITE + 'broken {\n')
        r = subprocess.run(['bash', '-c', self.functions() + '\ncaddy_validate_or_restore "$1" "$2"; echo "rc=$?"',
                            'x', self.cf, backup],
                           env=dict(os.environ, PATH=bindir + os.pathsep + os.environ['PATH']),
                           capture_output=True, text=True, timeout=30)
        return int(re.search(r'rc=(\d+)', r.stdout).group(1)), r.stdout

    def test_failed_validation_puts_the_old_file_back(self):
        rc, out = self.run_validate('echo "adapting config: unexpected EOF" >&2; exit 1')
        self.assertEqual(rc, 1)
        self.assertEqual(self.read_cf(), TAK_SITE)
        self.assertIn('Restored', out)
        self.assertIn('unexpected EOF', out)

    def test_valid_file_is_left_as_it_is(self):
        rc, _ = self.run_validate('exit 0')
        self.assertEqual(rc, 0)
        self.assertTrue(self.read_cf().endswith('broken {\n'))


class CertWait(unittest.TestCase):
    """The old loop used ((WAIT_COUNT++)), which returns 1 at 0 and ends a set -e script."""

    def fn(self):
        f = block('wait_for_certs')
        self.assertIsNotNone(f, 'the Ubuntu script has no wait_for_certs block between its markers')
        return f

    def test_running_out_of_time_returns_instead_of_ending_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run(['bash', '-c', 'set -e\n' + self.fn() +
                                '\nif wait_for_certs "$1/a.crt" "$1/a.key"; then echo found; else echo timeout; fi\necho after',
                                'x', d], env=dict(os.environ, CERT_WAIT_SECONDS='2'),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.stdout.split(), ['timeout', 'after'], r.stderr)

    def test_slow_certificate_is_found_when_it_arrives(self):
        with tempfile.TemporaryDirectory() as d:
            script = ('set -e\n' + self.fn() +
                      '\n( sleep 2; touch "$1/a.crt" "$1/a.key" ) &\n'
                      'if wait_for_certs "$1/a.crt" "$1/a.key"; then echo found; else echo timeout; fi\nwait\necho after')
            r = subprocess.run(['bash', '-c', script, 'x', d],
                               env=dict(os.environ, CERT_WAIT_SECONDS='10'),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.stdout.split(), ['found', 'after'], r.stderr)

    def test_certificate_already_there_returns_at_once(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ('a.crt', 'a.key'):
                open(os.path.join(d, n), 'w').close()
            r = subprocess.run(['bash', '-c', 'set -e\n' + self.fn() + '\nwait_for_certs "$1/a.crt" "$1/a.key"; echo ok',
                                'x', d], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.stdout.strip(), 'ok')


class ScriptsUseIt(unittest.TestCase):
    def test_both_scripts_carry_the_same_caddyfile_code(self):
        a, b = block('caddy_site_functions', UBUNTU), block('caddy_site_functions', ROCKY)
        self.assertIsNotNone(a)
        self.assertEqual(a, b)

    def test_old_unsafe_patterns_are_gone(self):
        u, r = read(UBUNTU), read(ROCKY)
        self.assertNotIn('((WAIT_COUNT++))', u)
        self.assertNotRegex(u, r'grep -q "\$DOMAIN"')
        self.assertNotRegex(r, r'grep -q "\$DOMAIN"')
        self.assertNotRegex(r, r'sed -i "/\$DOMAIN \{/')
        self.assertNotIn('$0 ~ domain " {"', u)

    def test_both_scripts_edit_through_the_function_and_validate_before_restart(self):
        for path in (UBUNTU, ROCKY):
            s = read(path)
            body = s.split('# <<< caddy_site_functions', 1)[1]
            configure = body.index('caddy_configure_site /etc/caddy/Caddyfile')
            validate = body.index('caddy_validate_or_restore /etc/caddy/Caddyfile')
            restart = body.index('systemctl restart caddy')
            self.assertLess(configure, validate, path)
            self.assertLess(validate, restart, path)

    def test_a_failed_validation_in_either_script_stops_before_the_restart(self):
        for path in (UBUNTU, ROCKY):
            body = read(path).split('# <<< caddy_site_functions', 1)[1]
            m = re.search(r'if ! caddy_validate_or_restore[^\n]*\n(?:[^\n]*\n)*?\s*exit 1\nfi', body)
            self.assertIsNotNone(m, path)
            self.assertLess(m.end(), body.index('systemctl restart caddy'), path)


if __name__ == '__main__':
    unittest.main()
