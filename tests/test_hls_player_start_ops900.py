"""The live player must start inside the playlist (ops #900).

Run: python3 -I -m unittest discover -s tests -v   (needs flask, ruamel.yaml, psutil)

MediaMTX drops the oldest segment about one segment after the playlist lists it. hls.js
starts liveSyncDurationCount segments from the end, so a count at or above hlsSegmentCount
starts at that oldest segment, and a viewer on a slow link gets 404 and no video.
Measured with hls.js 1.6.16 in Chrome against MediaMTX v1.20.0, 1-second keyframes,
3 x 500ms, 0.4 s added to each answer: 10 of 16 starts played with a count of 4, 16 of 16
with 2.

Like test_download_pins, the console file is loaded with its /opt and /usr/local paths
moved into a temp sandbox.
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_download_pins import load_editor  # noqa: E402


class PlayerStartsInsidePlaylist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ed = load_editor(self.tmp.name)
        self.cfg = os.path.join(self.tmp.name, 'mediamtx.yml')
        self.ed.CONFIG_FILE = self.cfg

    def write(self, text):
        with open(self.cfg, 'w') as f:
            f.write(text)

    def sync(self):
        m = re.search(r'liveSyncDurationCount:(\d+)', self.ed.hls_player_tuning_js())
        self.assertIsNotNone(m, self.ed.hls_player_tuning_js())
        return int(m.group(1))

    def test_three_segment_playlist_starts_one_segment_in(self):
        # The infra-TAK fleet value: hlsSegmentCount 3, hlsSegmentDuration 500ms.
        self.write('hlsVariant: mpegts\nhlsSegmentCount: 3\nhlsSegmentDuration: 500ms\n')
        self.assertEqual(self.sync(), 2)

    def test_start_is_always_inside_the_playlist(self):
        for count in range(3, 11):
            self.write('hlsVariant: mpegts\nhlsSegmentCount: %d\n' % count)
            self.assertLess(self.sync(), count, 'hlsSegmentCount %d' % count)

    def test_default_and_satellite_playlists_keep_five(self):
        self.write('hlsVariant: mpegts\n')               # MediaMTX default is 7 segments
        self.assertEqual(self.sync(), 5)
        self.write('hlsVariant: mpegts\nhlsSegmentCount: 7\nhlsSegmentDuration: 3s\n')
        self.assertEqual(self.sync(), 5)

    def test_unreadable_value_falls_back_to_the_default_playlist(self):
        self.write('hlsVariant: mpegts\nhlsSegmentCount: lots\n')
        self.assertEqual(self.sync(), 5)

    def test_max_latency_stays_above_the_start(self):
        for count in (3, 4, 7):
            self.write('hlsVariant: mpegts\nhlsSegmentCount: %d\n' % count)
            js = self.ed.hls_player_tuning_js()
            self.assertGreater(int(re.search(r'liveMaxLatencyDurationCount:(\d+)', js).group(1)), self.sync())

    def test_low_latency_variant_is_unchanged(self):
        self.write('hlsVariant: lowLatency\nhlsSegmentCount: 3\n')
        js = self.ed.hls_player_tuning_js()
        self.assertIn('lowLatencyMode:true', js)
        self.assertNotIn('liveSyncDurationCount', js)


if __name__ == '__main__':
    unittest.main()
