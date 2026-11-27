"""The version check says plain things when GitHub gives no notes or no answer (ops #1233).

Found while testing v2.1.20 (ops #1231):
1. With GitHub's API limited, the editor reads the newest tag from github.com. That gives
   no release notes and no date, so the Versions tab showed "No release notes." and
   "Published " with nothing after it.
2. With GitHub unreachable, the page showed "Could not reach GitHub (<urlopen error [Errno 111]
   Connection refused>)". The technical text belongs in the editor log.

Run: python3 -I -m unittest discover -s tests -v   (needs flask, ruamel.yaml, psutil; node for the page tests)
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_download_pins import EditorTestCase  # noqa: E402
from test_github_rate_limit_ops1214 import (  # noqa: E402
    EDITOR_API, EDITOR_LATEST, FakeGitHub, MTX_API, MTX_LATEST, RedirectResponse, rate_limited)


class GitHubUnreachableMessage(EditorTestCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(self.mod.subprocess, 'run', lambda *a, **k: mock.Mock(stdout='v1.0.0', stderr=''))
        p.start()
        self.addCleanup(p.stop)

    def _check(self, path, routes):
        gh = FakeGitHub(routes)
        out = io.StringIO()
        with mock.patch.object(urllib.request, 'urlopen', gh), contextlib.redirect_stdout(out):
            data = self.client.get(path).get_json()
        return data, out.getvalue()

    def test_refused_connection_gives_a_plain_sentence_and_logs_the_reason(self):
        refused = urllib.error.URLError(ConnectionRefusedError(111, 'Connection refused'))
        data, log = self._check('/api/mediamtx/version/check', {MTX_API: refused, MTX_LATEST: refused})
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Could not reach GitHub. Try again in a few minutes.')
        for raw in ('urlopen', 'Errno', 'Connection refused', '111'):
            self.assertNotIn(raw, data['error'])
        self.assertIn('Connection refused', log, 'the technical reason must reach the editor log')

    def test_web_editor_check_gives_the_same_plain_sentence(self):
        refused = urllib.error.URLError(ConnectionRefusedError(111, 'Connection refused'))
        data, log = self._check('/api/update/check', {EDITOR_API: refused, EDITOR_LATEST: refused})
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], 'Could not reach GitHub. Try again in a few minutes.')
        self.assertIn('Connection refused', log)

    def test_rate_limit_sentence_is_unchanged(self):
        data, _ = self._check('/api/mediamtx/version/check', {
            MTX_API: rate_limited(MTX_API), MTX_LATEST: urllib.error.URLError('offline')})
        self.assertIn('limiting version checks', data['error'])
        self.assertIn('Try again in about', data['error'])

    def test_fallback_answer_has_no_notes_and_no_date_for_the_page_to_handle(self):
        data, _ = self._check('/api/mediamtx/version/check', {
            MTX_API: rate_limited(MTX_API),
            MTX_LATEST: RedirectResponse('https://github.com/bluenviron/mediamtx/releases/tag/v9.9.9')})
        self.assertTrue(data['success'])
        self.assertFalse(data['release_notes'])
        self.assertFalse(data['published_at'])


@unittest.skipUnless(shutil.which('node'), 'node is needed to run the page script')
class VersionsTabWording(EditorTestCase):
    """Runs the page's own helper functions in node, not a copy of them."""

    def setUp(self):
        super().setUp()
        # The page refuses to render without a MediaMTX config file.
        self.mod.CONFIG_FILE = os.path.join(self._tmp.name, 'mediamtx.yml')
        with open(self.mod.CONFIG_FILE, 'w') as f:
            f.write('hlsVariant: mpegts\n')

    def _function_source(self, html, name):
        m = re.search(r'function %s\(' % name, html)
        self.assertIsNotNone(m, 'the page has no %s()' % name)
        i = html.index('{', m.start())
        depth = 0
        for j in range(i, len(html)):
            depth += {'{': 1, '}': -1}.get(html[j], 0)
            if depth == 0:
                return html[m.start():j + 1]
        self.fail('unbalanced braces in %s()' % name)

    def _run(self, expr):
        html = self.client.get('/').get_data(as_text=True)
        script = '\n'.join([self._function_source(html, 'releaseNotesText'),
                            self._function_source(html, 'publishedText'),
                            'console.log(JSON.stringify(%s));' % expr])
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_unknown_notes_point_to_github(self):
        self.assertEqual(self._run("releaseNotesText({release_notes: ''})"), 'Release notes: see View on GitHub.')
        self.assertEqual(self._run("releaseNotesText({})"), 'Release notes: see View on GitHub.')
        self.assertEqual(self._run("releaseNotesText({release_notes: '  \\n '})"), 'Release notes: see View on GitHub.')

    def test_real_notes_are_shown_as_they_are(self):
        self.assertEqual(self._run("releaseNotesText({release_notes: 'Fixed video.'})"), 'Fixed video.')

    def test_no_date_gives_nothing_to_print(self):
        self.assertEqual(self._run("publishedText({published_at: ''})"), '')
        self.assertEqual(self._run("publishedText({})"), '')
        self.assertEqual(self._run("publishedText({published_at: 'not a date'})"), '')

    def test_a_real_date_is_printed(self):
        self.assertNotEqual(self._run("publishedText({published_at: '2026-11-01T12:00:00Z'})"), '')

    def test_the_published_word_hides_with_its_date(self):
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('<span id="mtx-published-wrap"> · Published <span id="mtx-published"></span></span>', html)
        self.assertIn("getElementById('mtx-published-wrap').style.display = pub ? '' : 'none'", html)
        self.assertNotIn('No release notes.', html)


if __name__ == '__main__':
    unittest.main()
