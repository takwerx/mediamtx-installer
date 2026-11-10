"""Test-video upload must keep files inside the test video folder, and be admin only.

Run: python3 -m unittest discover -s tests -v   (needs flask, ruamel.yaml, psutil, requests)

The editor has import-time side effects on /opt and /usr/local, so (like the
verify-console-ui skill) every such path in the source is rewritten into a temp
sandbox before it runs.
"""
import io
import os
import sys
import tempfile
import types
import unittest

EDITOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config-editor', 'mediamtx_config_editor.py')


def import_editor(sandbox):
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


class UploadTestVideo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='mtx_upload_')
        cls.mod = import_editor(cls.tmp.name)
        cls.video_dir = cls.mod.TEST_VIDEO_DIR

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def client(self, role):
        c = self.mod.app.test_client()
        with c.session_transaction() as s:
            s['logged_in'] = True
            s['role'] = role
            s['username'] = 'tester'
        return c

    def post(self, client, name):
        return client.post('/api/test/upload', data={'test_file': (io.BytesIO(b'ts-bytes'), name)},
                           content_type='multipart/form-data')

    def test_dotdot_name_stays_inside_folder(self):
        # The folder two levels up is where a raw '../../x.ts' would land.
        outside = os.path.normpath(os.path.join(self.video_dir, '..', '..', 'x.ts'))
        outside_one = os.path.normpath(os.path.join(self.video_dir, '..', 'x.ts'))
        for name in ('../x.ts', '../../x.ts', '..\\..\\x.ts'):
            r = self.post(self.client('admin'), name)
            self.assertEqual(r.status_code, 200, (name, r.get_data(as_text=True)))
            self.assertEqual(r.get_json()['filename'], 'x.ts')
        self.assertTrue(os.path.isfile(os.path.join(self.video_dir, 'x.ts')))
        self.assertFalse(os.path.exists(outside))
        self.assertFalse(os.path.exists(outside_one))

    def test_absolute_path_name_stays_inside_folder(self):
        target = os.path.join(self.tmp.name, 'abs_target.ts')
        r = self.post(self.client('admin'), target)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        saved = r.get_json()['filename']
        self.assertNotIn('/', saved)
        self.assertTrue(os.path.isfile(os.path.join(self.video_dir, saved)))
        self.assertFalse(os.path.exists(target))

    def test_name_with_nothing_left_is_refused(self):
        for name in ('../.ts', '..', '/'):
            r = self.post(self.client('admin'), name)
            self.assertEqual(r.status_code, 400, name)

    def test_non_ts_still_refused(self):
        r = self.post(self.client('admin'), 'movie.mp4')
        self.assertEqual(r.status_code, 400)

    def test_plain_name_still_works(self):
        r = self.post(self.client('admin'), 'clip.ts')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(os.path.isfile(os.path.join(self.video_dir, 'clip.ts')))

    def test_viewer_cannot_upload(self):
        r = self.post(self.client('viewer'), 'viewer_clip.ts')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(os.path.exists(os.path.join(self.video_dir, 'viewer_clip.ts')))


if __name__ == '__main__':
    unittest.main()
