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


if __name__ == '__main__':
    unittest.main()
