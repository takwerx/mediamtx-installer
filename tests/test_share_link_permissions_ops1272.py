"""Share links: who may list them and how long a link made by a viewer lasts (ops #1272).

Run: python3 -m pytest tests -q   (needs flask, ruamel.yaml, requests, psutil, pytest)

The console file is loaded with its /opt and /usr/local paths moved into a temp sandbox,
like test_download_pins. A signed-in viewer does not list links, and a link a viewer makes
ends within 24 hours (4 hours when no lifetime is given). An admin keeps both.
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_download_pins import load_editor  # noqa: E402


class SharePermissions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = load_editor(self._tmp.name)
        self.mod.app.config['TESTING'] = True

    def client(self, role):
        c = self.mod.app.test_client()
        with c.session_transaction() as s:
            s['logged_in'] = True
            s['role'] = role
            s['username'] = role + '-user'
        return c

    def make(self, role, **body):
        body.setdefault('stream', 'cam1')
        return self.client(role).post('/api/share-links/generate', json=body)

    def stored(self):
        return self.mod.load_share_links()

    def test_viewer_does_not_get_the_list(self):
        self.make('admin', ttl=3600)
        r = self.client('viewer').get('/api/share-links')
        self.assertEqual(r.status_code, 403)
        self.assertNotIn('token', r.get_data(as_text=True))

    def test_admin_gets_the_list(self):
        self.make('admin', ttl=3600)
        r = self.client('admin').get('/api/share-links')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()['links']), 1)

    def test_viewer_link_without_a_lifetime_lasts_4_hours(self):
        for body in ({}, {'ttl': 0}, {'ttl': None}):
            r = self.make('viewer', **body)
            self.assertEqual(r.status_code, 200, body)
            exp = self.stored()[r.get_json()['token']]['expires']
            self.assertIsNotNone(exp, body)
            self.assertAlmostEqual(exp - time.time(), 14400, delta=5)
            self.assertEqual(r.get_json()['ttl_label'], '4 hours')

    def test_viewer_link_is_cut_to_24_hours(self):
        r = self.make('viewer', ttl=10 * 86400)
        exp = self.stored()[r.get_json()['token']]['expires']
        self.assertAlmostEqual(exp - time.time(), 86400, delta=5)

    def test_viewer_link_with_a_lifetime_in_range_is_kept(self):
        r = self.make('viewer', ttl=3600)
        exp = self.stored()[r.get_json()['token']]['expires']
        self.assertAlmostEqual(exp - time.time(), 3600, delta=5)

    def test_admin_can_still_make_a_link_that_never_ends(self):
        r = self.make('admin', ttl=0)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self.stored()[r.get_json()['token']]['expires'])
        self.assertEqual(r.get_json()['ttl_label'], 'Until revoked')

    def test_bad_lifetime_or_stream_name_is_refused(self):
        for role in ('viewer', 'admin'):
            for body in ({'ttl': 'soon'}, {'ttl': -1}, {'ttl': [1]}, {'stream': 'a/../b'},
                         {'stream': 'a b'}, {'stream': '<x>'}):
                self.assertEqual(self.make(role, **body).status_code, 400, (role, body))
        self.assertEqual(self.stored(), {})


class OldNeverEndingLinks(unittest.TestCase):
    """Links made before the update that never end end 24 hours after the update, once (ops #1272)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = load_editor(self._tmp.name)
        self.mod.app.config['TESTING'] = True

    def old_links(self):
        self.mod.save_share_links({
            'oldA': {'stream': 'cam1', 'created_by': 'x', 'expires': None, 'ttl_label': 'Until revoked'},
            'oldB': {'stream': 'cam2', 'created_by': 'x', 'ttl_label': 'Until revoked'},
            'timed': {'stream': 'cam3', 'expires': 2000000000, 'ttl_label': '4 hours'},
        })

    def test_never_ending_links_end_24_hours_after_the_update(self):
        self.old_links()
        now = 1700000000
        self.assertEqual(self.mod.cap_never_ending_share_links(now=now), 2)
        links = self.mod.load_share_links()
        self.assertEqual(links['oldA']['expires'], now + 86400)
        self.assertEqual(links['oldB']['expires'], now + 86400)
        self.assertEqual(links['timed']['expires'], 2000000000)  # a link with an end time is left alone
        self.assertEqual(links['oldA']['stream'], 'cam1')

    def test_it_runs_once_so_a_later_admin_link_that_never_ends_is_kept(self):
        self.old_links()
        self.mod.cap_never_ending_share_links()
        admin = self.mod.app.test_client()
        with admin.session_transaction() as s:
            s['logged_in'] = True
            s['role'] = 'admin'
            s['username'] = 'admin'
        tok = admin.post('/api/share-links/generate', json={'stream': 'cam1', 'ttl': 0}).get_json()['token']
        self.assertEqual(self.mod.cap_never_ending_share_links(), 0)  # second start: nothing to do
        self.assertIsNone(self.mod.load_share_links()[tok]['expires'])

    def test_a_box_with_no_links_still_gets_the_marker(self):
        self.assertEqual(self.mod.cap_never_ending_share_links(), 0)
        self.assertTrue(os.path.exists(self.mod.SHARE_LINKS_CAP_MARKER_FILE))
        self.mod.save_share_links({'a': {'stream': 'cam1', 'expires': None}})
        self.assertEqual(self.mod.cap_never_ending_share_links(), 0)  # made after the update: kept
        self.assertIsNone(self.mod.load_share_links()['a']['expires'])

    def test_an_unreadable_links_file_is_never_written_over(self):
        with open(self.mod.SHARE_LINKS_FILE, 'w') as f:
            f.write('{not json')
        self.assertIsNone(self.mod.cap_never_ending_share_links())
        with open(self.mod.SHARE_LINKS_FILE) as f:
            self.assertEqual(f.read(), '{not json')
        self.assertFalse(os.path.exists(self.mod.SHARE_LINKS_CAP_MARKER_FILE))

    def test_a_capped_link_stops_working_when_its_time_is_up(self):
        self.old_links()
        self.mod.cap_never_ending_share_links(now=time.time() - 2 * 86400)
        c = self.mod.app.test_client()
        self.assertEqual(c.get('/shared/oldA').status_code, 404)


if __name__ == '__main__':
    unittest.main()
