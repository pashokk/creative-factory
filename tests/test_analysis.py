import os
import shutil
import subprocess
import tempfile
import unittest

from creative_factory import analysis

RAW = {"trim_start": 5, "trim_len": 40, "crop_top_pct": 4, "crop_bottom_pct": 6, "hook": " Can you crack\nthe phrase? ",
       "lines": [{"at": 20, "text": "Second."}, {"at": 0.3, "text": "First."}, {"at": 5, "text": "  "}],
       "music_prompt": "soft piano", "rationale": "Starts on the first word."}


class Normalize(unittest.TestCase):
    def test_orders_lines_drops_empty_and_strips(self):
        out = analysis.normalize(RAW, 60)
        self.assertEqual([l["text"] for l in out["lines"]], ["First.", "Second."])
        self.assertEqual(out["hook"], "Can you crack\nthe phrase?")

    def test_clamps_length_start_and_crop(self):
        out = analysis.normalize({**RAW, "trim_start": 50, "trim_len": 90, "crop_top_pct": 40, "crop_bottom_pct": -3}, 60)
        self.assertEqual(out["trim_len"], analysis.MAX_GAMEPLAY_S)
        self.assertEqual(out["trim_start"], 60 - analysis.MAX_GAMEPLAY_S)
        self.assertEqual((out["crop_top_pct"], out["crop_bottom_pct"]), (15.0, 0.0))

    def test_never_runs_past_the_footage(self):
        out = analysis.normalize({**RAW, "trim_start": 30, "trim_len": 45}, 40)
        self.assertLessEqual(out["trim_start"] + out["trim_len"], 40)

    def test_short_footage_is_an_error(self):
        with self.assertRaises(analysis.AnalysisError):
            analysis.normalize(RAW, 20)

    def test_line_start_cannot_fall_after_the_end_card_begins_ending(self):
        out = analysis.normalize({**RAW, "lines": [{"at": 999, "text": "Late."}]}, 60)
        self.assertLessEqual(out["lines"][0]["start"], out["trim_len"] + 4.0)


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class Suggest(unittest.TestCase):
    def test_request_shape_and_result(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=270x540:rate=10", "-t", "30",
                            "-pix_fmt", "yuv420p", video], check=True)
            seen = {}

            def fake_post(payload, key):
                seen["payload"] = payload
                return {"content": [{"type": "tool_use", "name": "propose_edit", "input": RAW}]}

            out = analysis.suggest(video, d, "Word Cipher", "relaxing", 30.0, post=fake_post)
        payload = seen["payload"]
        self.assertEqual(payload["tool_choice"], {"type": "tool", "name": "propose_edit"})
        content = payload["messages"][0]["content"]
        self.assertGreaterEqual(sum(1 for b in content if b["type"] == "image"), 10)
        self.assertIn("Word Cipher", content[0]["text"])
        self.assertIn("relaxing", content[0]["text"])
        self.assertLessEqual(out["trim_start"] + out["trim_len"], 30.0)

    def test_missing_tool_call_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=270x540:rate=10", "-t", "30",
                            "-pix_fmt", "yuv420p", video], check=True)
            with self.assertRaises(analysis.AnalysisError):
                analysis.suggest(video, d, "G", "", 30.0, post=lambda p, k: {"content": [{"type": "text", "text": "hi"}]})


if __name__ == "__main__":
    unittest.main()
