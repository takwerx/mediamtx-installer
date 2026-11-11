"""A share link opens its own stream's HLS files and nothing else.

The /shared-hls/ proxy fetches from MediaMTX with the console's own viewer
credential, so the path check is the only thing that keeps a link for one stream
from opening another. Run from the repo root:

    python3 -m unittest discover -s config-editor/tests -v

Needs flask, ruamel.yaml, psutil and requests. Every /opt/ and /usr/local/ path
in the source is moved into a temp folder before it runs, as the
verify-console-ui skill does, so no MediaMTX install is needed.
"""
import os
import sys
import tempfile
import time
import types
import unittest

EDITOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mediamtx_config_editor.py')


def load_editor():
    sandbox = tempfile.mkdtemp(prefix='mtx_share_test_')
    with open(EDITOR) as f:
        src = f.read()
    src = src.replace('/usr/local/', sandbox + '/usr/local/').replace('/opt/', sandbox + '/opt/')
    os.makedirs(sandbox + '/usr/local/etc', exist_ok=True)
    os.makedirs(sandbox + '/opt/mediamtx-webeditor', exist_ok=True)
    with open(sandbox + '/usr/local/etc/mediamtx.yml', 'w') as f:
        f.write('logLevel: info\napi: yes\npaths:\n  test-stream:\n    source: publisher\n')
    mod = types.ModuleType('mediamtx_config_editor')
    mod.__file__ = EDITOR
    sys.modules['mediamtx_config_editor'] = mod
    exec(compile(src, EDITOR, 'exec'), mod.__dict__)
    return mod


class ShareLinkScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_editor()

    def allowed(self, stream, subpath):
        return self.mod.share_hls_path_allowed(stream, subpath)

    def test_own_hls_files_are_allowed(self):
        for name in ('index.m3u8', 'stream.m3u8', 'video1_stream.m3u8', 'init.mp4', 'abc123_seg4.mp4'):
            self.assertTrue(self.allowed('cam1', 'cam1/' + name), name)

    def test_nested_stream_name_is_allowed(self):
        self.assertTrue(self.allowed('live/drone1', 'live/drone1/index.m3u8'))

    def test_name_prefix_does_not_open_other_streams(self):
        # The bug: startswith('cam1') let a link for cam1 open all of these.
        for other in ('cam10', 'cam1-private', 'cam1_ops', 'cam1.secret'):
            self.assertFalse(self.allowed('cam1', other + '/index.m3u8'), other)

    def test_parent_link_does_not_open_nested_stream(self):
        self.assertFalse(self.allowed('live', 'live/drone1/index.m3u8'))

    def test_dot_dot_is_refused(self):
        for sub in ('cam1/../cam10/index.m3u8', 'cam1/..', 'cam1/../index.m3u8',
                    'cam1/./index.m3u8', 'cam1//index.m3u8', 'cam1/..%2fcam10'):
            self.assertFalse(self.allowed('cam1', sub), sub)

    def test_odd_paths_are_refused(self):
        for sub in ('', 'cam1', 'cam1/', 'cam1/index.m3u8\n', 'cam1/a b', 'cam1/a\\b', 'cam1/a?b=c'):
            self.assertFalse(self.allowed('cam1', sub), repr(sub))

    def test_bad_stored_stream_name_fails_closed(self):
        for stream in ('', '.', '..', 'cam1/..', '../cam1', 'a b'):
            self.assertFalse(self.allowed(stream, stream + '/index.m3u8'), repr(stream))

    def test_route_enforces_it(self):
        """Through the real route: only the linked stream reaches MediaMTX."""
        mod = self.mod
        fetched = []
        links = {'tok': {'stream': 'cam1', 'expires': time.time() + 3600}}
        saved = (mod.load_share_links, mod.hls_fetch_for_share)
        mod.load_share_links = lambda: links
        mod.hls_fetch_for_share = lambda subpath, qs=None: (fetched.append(subpath) or b'ok', 'text/plain')
        try:
            client = mod.app.test_client()
            self.assertEqual(client.get('/shared-hls/tok/cam1/index.m3u8').status_code, 200)
            for sub in ('cam10/index.m3u8', 'cam1-private/index.m3u8', 'cam1/../cam10/index.m3u8'):
                self.assertEqual(client.get('/shared-hls/tok/' + sub).status_code, 403, sub)
            self.assertEqual(client.get('/shared-hls/nope/cam1/index.m3u8').status_code, 403)
        finally:
            mod.load_share_links, mod.hls_fetch_for_share = saved
        self.assertEqual(fetched, ['cam1/index.m3u8'])


if __name__ == '__main__':
    unittest.main()
