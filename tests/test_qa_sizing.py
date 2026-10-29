import unittest

from creative_factory import qa, sizing


def info(**kw):
    base = dict(duration_s=59.4, width=1080, height=1920, size_bytes=29_000_000, has_audio=True)
    base.update(kw)
    return qa.MediaInfo(**base)


class Sizing(unittest.TestCase):
    def test_budget_at_59s(self):
        self.assertAlmostEqual(sizing.total_bitrate(59, 30) / 1e6, 3.96, delta=0.05)
        self.assertAlmostEqual(sizing.total_bitrate(59, 40) / 1e6, 5.28, delta=0.05)

    def test_budget_keeps_file_under_limit(self):
        for limit in (30, 40):
            for dur in (30, 45, 59):
                size = (sizing.total_bitrate(dur, limit) / 8) * dur
                self.assertLess(size, limit * sizing.MB)

    def test_video_bitrate_reserves_audio(self):
        self.assertEqual(
            sizing.video_bitrate(50, 30, audio_bps=100_000),
            sizing.total_bitrate(50, 30) - 100_000,
        )


class Checks(unittest.TestCase):
    def test_good_file_passes(self):
        self.assertTrue(qa.run_checks("BW001_v1_9x16_59s_EN.mp4", info()).ok)

    def test_duration_window(self):
        self.assertIsNone(qa.check_duration(30.0))
        self.assertIsNone(qa.check_duration(59.9))
        self.assertIsNotNone(qa.check_duration(60.0))
        self.assertIsNotNone(qa.check_duration(29.9))

    def test_size_limit(self):
        self.assertIsNotNone(qa.check_size(31_000_000, 30))
        self.assertIsNone(qa.check_size(31_000_000, 40))

    def test_ratio_and_substitute(self):
        self.assertIsNone(qa.check_ratio("4x5"))
        self.assertIsNotNone(qa.check_ratio("1x1"))
        self.assertIsNone(qa.check_ratio("1x1", allow_substitute=True))

    def test_name_must_match_video(self):
        r = qa.run_checks("BW001_v1_16x9_40s_EN.mp4", info())
        self.assertFalse(r.ok)
        self.assertEqual(len(r.problems), 2)

    def test_bad_name_and_no_audio(self):
        r = qa.run_checks("final.mp4", info(has_audio=False))
        self.assertEqual(len(r.problems), 2)


if __name__ == "__main__":
    unittest.main()
