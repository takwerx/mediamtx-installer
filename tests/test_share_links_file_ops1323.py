"""Share links file: an odd file is kept and logged, never silently replaced (ops #1323).

Run: python3 -m pytest tests -q   (needs flask, ruamel.yaml, requests, psutil, pytest)

Found in the v2.1.21 round 2 test (ops #1301). Four things, each with its own test class:
1. A links file that is empty or cut off: a visit to /shared/<anything> by anyone replaced it with {}.
   Now a copy (share_links.json.bad-<time>) is kept, one log line says why, the visit changes nothing.
2. One entry that is not an object (for example "_meta": 2) gave 500 on the list, the page and
   "make a link". Now it is skipped and kept in the file.
3. The 24 hour cap skipped without a log line, and after a skip a never-ending link made on purpose
   was capped at the next start. Now it prints why, and links made by this version carry a stamp
   (limits_version) that the cap never touches.
4. Deleting share_links_capped.json capped links made on purpose. The stamp protects them too.
"""
import contextlib
import glob
import io
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_download_pins import load_editor  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = load_editor(self._tmp.name)
        self.mod.app.config['TESTING'] = True
        self.file = self.mod.SHARE_LINKS_FILE

    def client(self, role=None):
        c = self.mod.app.test_client()
        if role:
            with c.session_transaction() as s:
                s['logged_in'] = True
                s['role'] = role
                s['username'] = role + '-user'
        return c

    def write(self, text):
        with open(self.file, 'w') as f:
            f.write(text)

    def read(self):
        with open(self.file) as f:
            return f.read()

    def bad_copies(self):
        return sorted(glob.glob(self.file + '.bad-*'))

    def logged(self, fn, *a, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*a, **kw)
        return result, buf.getvalue()


class BadFileIsKept(Base):
    """Item 1: empty or cut-off links file."""

    CUT = '{"tok1": {"stream": "cam1", "expires": null, "ttl_la'

    def check_visit_keeps_file(self, text):
        self.write(text)
        r, out = self.logged(self.client().get, '/shared/x')
        self.assertEqual(r.status_code, 404)  # no such link, as before
        self.assertEqual(self.read(), text, 'a visit must not change the links file')
        copies = self.bad_copies()
        self.assertEqual(len(copies), 1)
        with open(copies[0]) as f:
            self.assertEqual(f.read(), text)
        self.assertEqual(len([ln for ln in out.splitlines() if 'share_links.json' in ln]), 1, out)

    def test_empty_file_survives_a_visit(self):
        self.check_visit_keeps_file('')

    def test_cut_off_file_survives_a_visit(self):
        self.check_visit_keeps_file(self.CUT)

    def test_file_that_is_not_an_object_survives_a_visit(self):
        self.check_visit_keeps_file('[1, 2]')

    def test_second_visit_makes_no_second_copy_and_no_second_line(self):
        self.write(self.CUT)
        self.client().get('/shared/x')
        _, out = self.logged(self.client().get, '/shared/y')
        self.assertEqual(len(self.bad_copies()), 1)
        self.assertEqual(out.strip(), '')

    def test_admin_list_and_hls_visits_keep_the_file_too(self):
        self.write(self.CUT)
        self.assertEqual(self.client('admin').get('/api/share-links').status_code, 200)
        self.client().get('/shared-hls/tok1/cam1/index.m3u8')
        self.assertEqual(self.read(), self.CUT)

    def test_an_admin_making_a_link_keeps_the_old_text_in_the_copy(self):
        self.write(self.CUT)
        r = self.client('admin').post('/api/share-links/generate', json={'stream': 'cam1', 'ttl': 0})
        self.assertEqual(r.status_code, 200)
        with open(self.bad_copies()[0]) as f:
            self.assertEqual(f.read(), self.CUT)
        self.assertIn(r.get_json()['token'], json.loads(self.read()))

    def test_good_file_is_still_pruned_and_saved(self):
        self.write(json.dumps({
            'gone': {'stream': 'cam1', 'expires': 1},
            'kept': {'stream': 'cam2', 'expires': None},
        }))
        self.client().get('/shared/kept')
        self.assertEqual(list(json.loads(self.read())), ['kept'])
        self.assertEqual(self.bad_copies(), [])

    def test_missing_file_is_not_a_problem(self):
        r, out = self.logged(self.client().get, '/shared/x')
        self.assertEqual(r.status_code, 404)
        self.assertFalse(os.path.exists(self.file))
        self.assertEqual(out.strip(), '')


class OddEntries(Base):
    """Item 2: an entry that is not an object."""

    def setUp(self):
        super().setUp()
        self.write(json.dumps({
            '_meta': 2,
            'listnull': None,
            'good': {'stream': 'cam1', 'created': '2026-11-01T00:00:00Z', 'created_by': 'a',
                     'expires': None, 'ttl_label': 'Until revoked'},
        }))

    def test_admin_list_answers_200_with_only_the_real_link(self):
        r = self.client('admin').get('/api/share-links')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x['token'] for x in r.get_json()['links']], ['good'])

    def test_make_a_link_answers_200(self):
        r = self.client('admin').post('/api/share-links/generate', json={'stream': 'cam2', 'ttl': 3600})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_pages_for_odd_entries_are_the_expired_page_not_500(self):
        for tok in ('_meta', 'listnull'):
            self.assertEqual(self.client().get('/shared/' + tok).status_code, 404, tok)
            self.assertEqual(self.client().get('/shared-hls/%s/cam1/index.m3u8' % tok).status_code, 403, tok)

    def test_the_webrtc_routes_refuse_odd_entries_with_403_not_500(self):
        for path in ('/shared/_meta/whep', '/shared-whep/_meta', '/shared/listnull/whep'):
            self.assertEqual(self.client().post(path, data='v=0').status_code, 403, path)

    def test_the_real_link_page_still_works(self):
        self.assertEqual(self.client().get('/shared/good').status_code, 200)

    def test_odd_entries_stay_in_the_file_after_every_save(self):
        self.client('admin').get('/api/share-links')
        self.client().get('/shared/good')
        self.client('admin').post('/api/share-links/generate', json={'stream': 'cam2', 'ttl': 3600})
        saved = json.loads(self.read())
        self.assertEqual(saved['_meta'], 2)
        self.assertIn('listnull', saved)
        self.assertIn('good', saved)
        self.assertEqual(len(saved), 4)

    def test_revoke_removes_the_link_and_keeps_the_odd_entries(self):
        r = self.client('admin').post('/api/share-links/revoke', json={'token': 'good'})
        self.assertEqual(r.status_code, 200)
        saved = json.loads(self.read())
        self.assertNotIn('good', saved)
        self.assertEqual(saved['_meta'], 2)
        self.assertIn('listnull', saved)

    def test_a_meta_that_is_an_object_is_fine(self):
        self.write(json.dumps({'_meta': {'v': 3}, 'good': {'stream': 'cam1', 'expires': None}}))
        r = self.client('admin').get('/api/share-links')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x['token'] for x in r.get_json()['links']], ['good'])  # an object with no stream is not a link
        self.assertEqual(self.client().get('/shared/_meta').status_code, 404)
        self.assertEqual(self.client().get('/shared/good').status_code, 200)

    def test_cap_does_not_touch_an_object_entry_that_is_not_a_link(self):
        self.write(json.dumps({'_future': {'schema': 3}, 'good': {'stream': 'cam1', 'expires': None}}))
        self.assertEqual(self.mod.cap_never_ending_share_links(now=1700000000), 1)
        saved = json.loads(self.read())
        self.assertEqual(saved['_future'], {'schema': 3})
        self.assertEqual(saved['good']['expires'], 1700000000 + 86400)

    def test_cap_skips_odd_entries_and_keeps_them(self):
        self.assertEqual(self.mod.cap_never_ending_share_links(now=1700000000), 1)
        saved = json.loads(self.read())
        self.assertEqual(saved['_meta'], 2)
        self.assertEqual(saved['good']['expires'], 1700000000 + 86400)


class CapSafety(Base):
    """Items 3 and 4: the 24 hour cap says why it skipped, and never hits a link made on purpose."""

    def make_forever(self):
        r = self.client('admin').post('/api/share-links/generate', json={'stream': 'cam1', 'ttl': 0})
        self.assertEqual(r.status_code, 200)
        return r.get_json()['token']

    def old_links(self):
        self.mod.save_share_links({
            'old': {'stream': 'cam1', 'created_by': 'x', 'expires': None, 'ttl_label': 'Until revoked'},
        })

    def test_cap_that_cannot_read_the_file_prints_one_line(self):
        self.write('')
        result, out = self.logged(self.mod.cap_never_ending_share_links)
        self.assertIsNone(result)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, out)
        self.assertIn('not capped', lines[0])
        self.assertIn('share_links.json', lines[0])

    def test_cap_that_cannot_write_prints_one_line(self):
        self.old_links()
        real_open = open

        def refuse(path, mode='r', *a, **kw):
            if 'w' in mode and str(path).startswith(os.path.dirname(self.file)):
                raise PermissionError(13, 'Permission denied', str(path))
            return real_open(path, mode, *a, **kw)

        from unittest import mock
        with mock.patch('builtins.open', refuse):
            result, out = self.logged(self.mod.cap_never_ending_share_links)
        self.assertIsNone(result)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, out)
        self.assertIn('not capped', lines[0])
        self.assertIn('Permission denied', lines[0])

    def test_empty_file_at_the_update_then_a_never_ending_link_then_restart(self):
        self.write('')
        self.assertIsNone(self.mod.cap_never_ending_share_links())  # the update: cannot run
        tok = self.make_forever()  # admin makes a link on purpose
        self.assertEqual(self.mod.cap_never_ending_share_links(), 0)  # the next restart
        self.assertIsNone(self.mod.load_share_links()[tok]['expires'])

    def test_cap_that_could_not_write_leaves_a_later_link_alone_too(self):
        from unittest import mock
        self.old_links()
        real_open = open

        def refuse_marker(path, mode='r', *a, **kw):
            if 'w' in mode and str(path) == self.mod.SHARE_LINKS_CAP_MARKER_FILE:
                raise PermissionError(13, 'Permission denied', str(path))
            return real_open(path, mode, *a, **kw)

        # the cap runs but the marker cannot be made; the box runs; an admin makes a link; restart
        with mock.patch('builtins.open', refuse_marker):
            self.assertIsNone(self.logged(self.mod.cap_never_ending_share_links)[0])
        tok = self.make_forever()
        self.mod.cap_never_ending_share_links()
        links = self.mod.load_share_links()
        self.assertIsNone(links[tok]['expires'])  # made on purpose: stays never-ending
        self.assertIsNotNone(links['old']['expires'])  # the old link got its end

    def test_deleted_marker_does_not_cap_a_link_made_on_purpose(self):
        self.old_links()
        self.mod.cap_never_ending_share_links()
        tok = self.make_forever()
        os.remove(self.mod.SHARE_LINKS_CAP_MARKER_FILE)  # someone deletes the marker by hand
        self.mod.cap_never_ending_share_links()
        self.assertIsNone(self.mod.load_share_links()[tok]['expires'])

    def test_deleted_marker_does_not_extend_or_recap_an_old_capped_link(self):
        self.old_links()
        self.mod.cap_never_ending_share_links(now=1700000000)
        os.remove(self.mod.SHARE_LINKS_CAP_MARKER_FILE)
        self.mod.cap_never_ending_share_links(now=1800000000)
        self.assertEqual(self.mod.load_share_links()['old']['expires'], 1700000000 + 86400)

    def test_link_with_no_stamp_is_an_old_link_and_gets_the_cap(self):
        # What a link with no stamp (and no created) gets: made before this version, so it is capped.
        self.mod.save_share_links({'a': {'stream': 'cam1', 'expires': None}})
        self.assertEqual(self.mod.cap_never_ending_share_links(now=1700000000), 1)
        self.assertEqual(self.mod.load_share_links()['a']['expires'], 1700000000 + 86400)

    def test_new_links_carry_the_stamp_and_old_ones_do_not(self):
        tok = self.make_forever()
        self.assertEqual(self.mod.load_share_links()[tok].get('limits_version'), 1)

    def test_update_twice_changes_nothing_the_second_time(self):
        self.old_links()
        self.mod.cap_never_ending_share_links(now=1700000000)
        before = self.read()
        self.assertEqual(self.mod.cap_never_ending_share_links(now=1700099999), 0)
        self.assertEqual(self.read(), before)

    def test_file_from_a_newer_version_keeps_its_own_fields(self):
        self.write(json.dumps({
            '_meta': 2,
            'new': {'stream': 'cam1', 'expires': None, 'limits_version': 2, 'extra': {'a': 1}},
            'old': {'stream': 'cam2', 'expires': None},
        }))
        self.assertEqual(self.mod.cap_never_ending_share_links(now=1700000000), 1)
        saved = json.loads(self.read())
        self.assertIsNone(saved['new']['expires'])
        self.assertEqual(saved['new']['extra'], {'a': 1})
        self.assertEqual(saved['_meta'], 2)
        self.assertEqual(saved['old']['expires'], 1700000000 + 86400)


class InfraTakPatchNames(unittest.TestCase):
    """infra-TAK patches the deployed editor by function name (its app.py, "Fix duplicate endpoints"):
    it finds each def below and the @app.route line above it. Keep all five, once each, with the same route."""

    ROUTES = {
        'shared_stream_page': "@app.route('/shared/<token>')",
        'shared_hls_proxy': "@app.route('/shared-hls/<token>/<path:subpath>')",
        'api_share_links_list': "@app.route('/api/share-links')",
        'api_share_links_generate': "@app.route('/api/share-links/generate', methods=['POST'])",
        'api_share_links_revoke': "@app.route('/api/share-links/revoke', methods=['POST'])",
    }

    def test_names_and_route_lines_are_unchanged(self):
        from test_download_pins import EDITOR
        with open(EDITOR, encoding='utf-8') as f:
            lines = f.read().splitlines()
        for name, route in self.ROUTES.items():
            idx = [i for i, ln in enumerate(lines) if ln.startswith('def %s(' % name)]
            self.assertEqual(len(idx), 1, name)
            block = []
            j = idx[0] - 1
            while j >= 0 and lines[j].startswith('@'):
                block.append(lines[j])
                j -= 1
            self.assertIn(route, block, name)


if __name__ == '__main__':
    unittest.main()
