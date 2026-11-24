"""The version check must survive GitHub's 60-calls-an-hour limit (ops #1214).

AJ saw "Could not check: HTTP Error 403: rate limit exceeded" on the Version
Management tab (web editor and MediaMTX), and the update buttons stopped working.

Run: python3 -I -m unittest discover -s tests -v   (needs flask, ruamel.yaml, psutil)
"""
import email.message
import json
import os
import tarfile
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from test_download_pins import EditorTestCase, FakeResponse, GOOD, load_editor, sha

MTX_API = 'https://api.github.com/repos/bluenviron/mediamtx/releases/latest'
MTX_LATEST = 'https://github.com/bluenviron/mediamtx/releases/latest'
EDITOR_API = 'https://api.github.com/repos/takwerx/mediamtx-installer/releases/latest'
EDITOR_LATEST = 'https://github.com/takwerx/mediamtx-installer/releases/latest'


class RedirectResponse(FakeResponse):
    """What urlopen returns after following github.com/<repo>/releases/latest."""

    def __init__(self, final_url):
        super().__init__(b'')
        self._final = final_url

    def geturl(self):
        return self._final


def rate_limited(url, reset_in=1800, remaining='0'):
    hdrs = email.message.Message()
    hdrs['X-RateLimit-Remaining'] = remaining
    hdrs['X-RateLimit-Reset'] = str(int(time.time()) + reset_in)
    return urllib.error.HTTPError(url, 403, 'rate limit exceeded', hdrs, None)


def api_release(tag, body='Notes for ' + 'x', assets=None):
    return FakeResponse(json.dumps({'tag_name': tag, 'body': body, 'published_at': '2026-11-01T00:00:00Z',
                                    'html_url': 'https://example.test/' + tag,
                                    'assets': assets or []}).encode())


class FakeGitHub:
    """urlopen stand-in: `api` and `latest` map a URL to a response or an exception."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, req, *a, **kw):
        url = req.full_url
        self.calls.append(url)
        r = self.routes[url]
        if isinstance(r, Exception):
            raise r
        return r() if callable(r) else r


class RateLimitTest(EditorTestCase):
    def setUp(self):
        super().setUp()
        # `mod.subprocess` is the real subprocess module: undo the patch after each test.
        p = mock.patch.object(self.mod.subprocess, 'run', lambda *a, **k: mock.Mock(stdout='v1.0.0', stderr=''))
        p.start()
        self.addCleanup(p.stop)

    def _get(self, path, routes):
        gh = FakeGitHub(routes)
        with mock.patch.object(urllib.request, 'urlopen', gh):
            resp = self.client.get(path)
        return resp.get_json(), gh

    def test_mediamtx_check_still_answers_when_api_is_rate_limited(self):
        data, gh = self._get('/api/mediamtx/version/check', {
            MTX_API: rate_limited(MTX_API),
            MTX_LATEST: RedirectResponse('https://github.com/bluenviron/mediamtx/releases/tag/v9.9.9')})
        self.assertTrue(data['success'], data)
        self.assertEqual(data['remote_version'], 'v9.9.9')
        self.assertTrue(data['update_available'])
        self.assertIn('limiting', data['notice'])
        self.assertNotIn('403', json.dumps(data))

    def test_web_editor_check_still_answers_when_api_is_rate_limited(self):
        data, _ = self._get('/api/update/check', {
            EDITOR_API: rate_limited(EDITOR_API),
            EDITOR_LATEST: RedirectResponse('https://github.com/takwerx/mediamtx-installer/releases/tag/v99.0.0')})
        self.assertTrue(data['success'], data)
        self.assertEqual(data['remote_version'], 'v99.0.0')
        self.assertTrue(data['update_available'])

    def test_both_paths_down_shows_last_good_answer(self):
        ok, _ = self._get('/api/mediamtx/version/check', {MTX_API: api_release('v2.0.0', 'real notes')})
        self.assertTrue(ok['success'])
        # Ten minutes later the cached answer is no longer fresh, and GitHub refuses both ways.
        entry = self.mod._gh_mem_cache['bluenviron/mediamtx']
        entry['fetched_at'] -= 3600
        data, _ = self._get('/api/mediamtx/version/check', {
            MTX_API: rate_limited(MTX_API), MTX_LATEST: urllib.error.URLError('offline')})
        self.assertTrue(data['success'], data)
        self.assertEqual(data['remote_version'], 'v2.0.0')
        self.assertEqual(data['release_notes'], 'real notes')
        self.assertTrue(data['stale'])
        self.assertTrue(data['checked_at'])

    def test_nothing_cached_gives_a_plain_sentence_not_the_raw_error(self):
        data, _ = self._get('/api/mediamtx/version/check', {
            MTX_API: rate_limited(MTX_API), MTX_LATEST: urllib.error.URLError('offline')})
        self.assertFalse(data['success'])
        self.assertIn('limiting version checks', data['error'])
        self.assertIn('Try again in about', data['error'])
        self.assertNotIn('HTTP Error 403', data['error'])

    def test_fresh_answer_is_reused_so_page_loads_do_not_spend_the_limit(self):
        gh = FakeGitHub({MTX_API: lambda: api_release('v2.0.0')})
        with mock.patch.object(urllib.request, 'urlopen', gh):
            for _ in range(5):
                self.client.get('/api/mediamtx/version/check')
        self.assertEqual(gh.calls.count(MTX_API), 1)

    def test_after_a_403_the_api_is_left_alone_until_the_reset(self):
        gh = FakeGitHub({MTX_API: rate_limited(MTX_API),
                         MTX_LATEST: lambda: RedirectResponse('https://github.com/bluenviron/mediamtx/releases/tag/v9.9.9')})
        with mock.patch.object(urllib.request, 'urlopen', gh):
            for _ in range(3):
                self.assertTrue(self.client.get('/api/mediamtx/version/check').get_json()['success'])
        self.assertEqual(gh.calls.count(MTX_API), 1, 'kept calling a rate limited API')

    def test_last_good_answer_survives_a_console_restart(self):
        self._get('/api/mediamtx/version/check', {MTX_API: api_release('v2.0.0', 'kept notes')})
        self.assertTrue(os.path.exists(self.mod.RELEASE_CACHE_FILE))
        # A new process: no memory, only the file. Age the file entry so it is stale.
        with open(self.mod.RELEASE_CACHE_FILE) as f:
            saved = json.load(f)
        saved['bluenviron/mediamtx']['fetched_at'] -= 3600
        with open(self.mod.RELEASE_CACHE_FILE, 'w') as f:
            json.dump(saved, f)
        self.mod._gh_mem_cache.clear()
        data, _ = self._get('/api/mediamtx/version/check', {
            MTX_API: rate_limited(MTX_API), MTX_LATEST: urllib.error.URLError('offline')})
        self.assertEqual(data['release_notes'], 'kept notes')

    def test_upgrade_works_while_the_api_is_rate_limited(self):
        """The Upgrade button needs the download address and the checksum file, not only the tag."""
        arch = self.mod.MEDIAMTX_ARCH
        name = f'mediamtx_v9.9.9_linux_{arch}.tar.gz'
        base = 'https://github.com/bluenviron/mediamtx/releases/download/v9.9.9/'
        gh = FakeGitHub({
            MTX_API: rate_limited(MTX_API),
            MTX_LATEST: RedirectResponse('https://github.com/bluenviron/mediamtx/releases/tag/v9.9.9'),
            base + name: FakeResponse(GOOD),
            base + 'checksums.sha256': FakeResponse(f'{sha(GOOD)} *{name}\n'.encode())})
        reached = []

        def fake_tar_open(*a, **kw):
            reached.append(True)
            raise RuntimeError('reached-extract')

        self.mod.mtx_priv_mode = lambda: 'root'
        with mock.patch.object(urllib.request, 'urlopen', gh), mock.patch.object(tarfile, 'open', fake_tar_open):
            resp = self.client.post('/api/mediamtx/version/upgrade')
        self.assertTrue(reached, resp.get_json())
        self.assertIn('reached-extract', resp.get_json()['error'])

    def test_a_download_with_a_wrong_checksum_is_still_refused_in_fallback_mode(self):
        arch = self.mod.MEDIAMTX_ARCH
        name = f'mediamtx_v9.9.9_linux_{arch}.tar.gz'
        base = 'https://github.com/bluenviron/mediamtx/releases/download/v9.9.9/'
        gh = FakeGitHub({
            MTX_API: rate_limited(MTX_API),
            MTX_LATEST: RedirectResponse('https://github.com/bluenviron/mediamtx/releases/tag/v9.9.9'),
            base + name: FakeResponse(b'tampered'),
            base + 'checksums.sha256': FakeResponse(f'{sha(GOOD)} *{name}\n'.encode())})
        self.mod.mtx_priv_mode = lambda: 'root'
        with mock.patch.object(urllib.request, 'urlopen', gh):
            resp = self.client.post('/api/mediamtx/version/upgrade')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Checksum mismatch', resp.get_json()['error'])

    def test_a_plain_403_that_is_not_a_rate_limit_does_not_block_the_api(self):
        hdrs = email.message.Message()
        hdrs['X-RateLimit-Remaining'] = '40'
        err = urllib.error.HTTPError(MTX_API, 403, 'forbidden', hdrs, None)
        gh = FakeGitHub({MTX_API: err,
                         MTX_LATEST: lambda: RedirectResponse('https://github.com/bluenviron/mediamtx/releases/tag/v9.9.9')})
        with mock.patch.object(urllib.request, 'urlopen', gh):
            self.client.get('/api/mediamtx/version/check')
        self.assertEqual(self.mod._GH_BLOCKED_UNTIL, 0.0)


if __name__ == '__main__':
    unittest.main()
