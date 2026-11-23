"""klv-to-cot.py decodes ST0601 sets the way the standard frames them. Run from the repo root:

    python3 -m unittest discover -s config-editor/tests -v

Standard library only; the script is loaded by path because its file name has a hyphen.
"""
import importlib.util
import os
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'klv-to-cot.py')
spec = importlib.util.spec_from_file_location('klv_to_cot', SCRIPT)
klv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(klv)

KEY = bytes.fromhex('060E2B34020B01010E01030101000000')
TIMESTAMP = bytes.fromhex('0208000459f4a6aa4aa8')
LATITUDE = bytes.fromhex('0d045595b66d')     # 60.176822967
LONGITUDE = bytes.fromhex('0e045b5360c4')    # 128.426759042
VERSION = bytes.fromhex('410113')            # ST0601.19


def packet(*items, bad_checksum=False):
    body = b''.join(items) + b'\x01\x02'
    length = len(body) + 2
    ber = bytes([length]) if length < 128 else bytes([0x81, length])
    head = KEY + ber + body
    total = sum(b << (8 if k % 2 == 0 else 0) for k, b in enumerate(head)) & 0xFFFF
    if bad_checksum:
        total ^= 1
    return head + total.to_bytes(2, 'big')


def decode(data):
    scanner = klv.StreamScanner()
    return [klv._to_sample(tags) for tags in scanner.feed(data)], scanner


class KlvToCotTest(unittest.TestCase):
    def test_two_byte_tag_keeps_the_rest_of_the_set_aligned(self):
        # Take-off Time is tag 131 (0x81 0x03). Read with one-byte tags, '81' becomes tag 129
        # with length 3, and the value bytes '0e 05' then read as a 5-byte "tag 14" that
        # overwrites the real Sensor Longitude.
        take_off = bytes.fromhex('8103') + b'\x08' + bytes.fromhex('00000e0511223344')
        samples, _ = decode(packet(TIMESTAMP, LATITUDE, LONGITUDE, take_off, VERSION))
        self.assertEqual(len(samples), 1)
        self.assertAlmostEqual(samples[0]['platform']['lat'], 60.176823, places=5)
        self.assertAlmostEqual(samples[0]['platform']['lon'], 128.426759, places=5)

    def test_bad_checksum_is_dropped(self):
        samples, scanner = decode(packet(TIMESTAMP, LATITUDE, LONGITUDE, VERSION, bad_checksum=True))
        self.assertEqual(samples, [])
        self.assertEqual(scanner.bad_checksum, 1)

    def test_good_set_still_decodes(self):
        samples, scanner = decode(packet(TIMESTAMP, LATITUDE, LONGITUDE, VERSION))
        self.assertEqual(scanner.bad_checksum, 0)
        self.assertAlmostEqual(samples[0]['platform']['lat'], 60.176823, places=5)


# ffmpeg 6.1.1 (Ubuntu 24.04) hands over every ST0601 set with the first 5 bytes of its 16-byte key
# missing (06 0e 2b 34 02). ffmpeg 4.4, 5.1 and 7.1 give the whole key. ops #1128.
CUT = 5


class FfmpegCutKeyTest(unittest.TestCase):
    def setUp(self):
        self.full = packet(TIMESTAMP, LATITUDE, LONGITUDE, VERSION)
        self.cut = self.full[CUT:]
        self.want, _ = decode(self.full)

    def test_set_with_the_first_5_key_bytes_missing_still_decodes(self):
        samples, scanner = decode(self.cut)
        self.assertEqual(samples, self.want)
        self.assertEqual(len(samples), 1)
        self.assertEqual(scanner.bad_checksum, 0)

    def test_many_cut_sets_in_a_row_all_decode(self):
        samples, _ = decode(self.cut * 7)
        self.assertEqual(samples, self.want * 7)

    def test_cut_and_whole_sets_mixed_in_one_stream(self):
        samples, _ = decode(self.cut + self.full + self.cut)
        self.assertEqual(samples, self.want * 3)

    def test_cut_set_with_a_bad_checksum_is_still_dropped(self):
        bad = packet(TIMESTAMP, LATITUDE, LONGITUDE, VERSION, bad_checksum=True)[CUT:]
        samples, scanner = decode(bad)
        self.assertEqual(samples, [])
        self.assertEqual(scanner.bad_checksum, 1)

    def test_cut_stream_in_any_chunk_size_decodes_every_set(self):
        data = self.cut * 4
        for size in (1, 2, 3, 5, 7, 11, 16, 17, 40):
            scanner = klv.StreamScanner()
            got = []
            for i in range(0, len(data), size):
                got += [klv._to_sample(t) for t in scanner.feed(data[i:i + size])]
            self.assertEqual(got, self.want * 4, 'chunk size %d' % size)

    def test_whole_key_split_at_every_byte_still_decodes(self):
        data = self.full * 3
        for size in (1, 2, 3, 4, 5, 6, 10, 15, 16, 17):
            scanner = klv.StreamScanner()
            got = []
            for i in range(0, len(data), size):
                got += [klv._to_sample(t) for t in scanner.feed(data[i:i + size])]
            self.assertEqual(got, self.want * 3, 'chunk size %d' % size)

    def test_bytes_that_only_look_like_the_tail_of_the_key_are_not_a_set(self):
        # The 11-byte tail of the key with a nonsense length and no valid checksum must ship nothing.
        junk = KEY[CUT:] + bytes([4]) + b'\x00\x01\x02\x03'
        samples, _ = decode(junk + b'\x55' * 20)
        self.assertEqual(samples, [])


if __name__ == '__main__':
    unittest.main()
