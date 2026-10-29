import json
import os
import tempfile
import threading
import unittest

from creative_factory.registry import Registry

DRIVE = {"My Little Spa": ["SP032_v1_9x16_45s_EN.mp4", "SP033_v1_9x16_45s_EN.mp4"],
         "Brain Wash": ["BW001_v1_9x16_59s_EN.mp4"]}


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "registry.json")
        self.now = 1000.0
        self.scans = 0

    def tearDown(self):
        self.dir.cleanup()

    def scan(self):
        self.scans += 1
        return DRIVE

    def reg(self, scan=True):
        return Registry(self.path, self.scan if scan else None, clock=lambda: self.now)

    def test_new_game_starts_at_one(self):
        self.assertEqual(self.reg(scan=False).reserve("Word Cipher"), ("WC", 1))

    def test_continues_from_drive_ids(self):
        r = self.reg()
        self.assertEqual(r.reserve("My Little Spa"), ("SP", 34))
        self.assertEqual(r.reserve("Brain Wash"), ("BW", 2))

    def test_reservation_is_recorded_immediately(self):
        r = self.reg()
        self.assertEqual(r.reserve("Word Cipher")[1], 1)
        self.assertEqual(r.reserve("Word Cipher")[1], 2)
        with open(self.path) as f:
            self.assertEqual(json.load(f)["ids"]["WC"], [1, 2])

    def test_collision_gets_a_digit(self):
        r = self.reg()
        self.assertEqual(r.reserve("Bear Wood"), ("BW1", 1))

    def test_scan_runs_weekly_not_every_time(self):
        r = self.reg()
        r.reserve("Word Cipher")
        r.reserve("Word Cipher")
        self.assertEqual(self.scans, 1)
        self.now += 8 * 24 * 3600
        r.reserve("Word Cipher")
        self.assertEqual(self.scans, 2)

    def test_rescan_keeps_local_reservations(self):
        r = self.reg()
        r.reserve("Word Cipher")
        self.now += 8 * 24 * 3600
        self.assertEqual(r.reserve("Word Cipher"), ("WC", 2))

    def test_force_refresh(self):
        r = self.reg()
        r.refresh()
        r.refresh()
        self.assertEqual(self.scans, 1)
        r.refresh(force=True)
        self.assertEqual(self.scans, 2)

    def test_concurrent_reservations_never_collide(self):
        got = []
        def work():
            got.append(self.reg(scan=False).reserve("Word Cipher")[1])
        threads = [threading.Thread(target=work) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sorted(got), list(range(1, 21)))

    def test_questionable_name_needs_manual_prefix(self):
        r = self.reg(scan=False)
        with self.assertRaises(ValueError):
            r.reserve("Outrun")
        self.assertEqual(r.reserve("Outrun", manual_prefix="OR"), ("OR", 1))


if __name__ == "__main__":
    unittest.main()
