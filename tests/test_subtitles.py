import re
import unittest

from creative_factory import subtitles as sub

WORDS = [("Think", 0.0, 0.22), ("you're", 0.24, 0.4), ("good", 0.42, 0.53), ("at", 0.57, 0.61),
         ("puzzles?", 0.86, 1.38), ("Crack", 1.71, 1.95), ("it.", 2.0, 2.2)]


class Words(unittest.TestCase):
    def test_alignment_to_words(self):
        chars = list("hi you")
        starts = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
        ends = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        self.assertEqual(sub.words_from_alignment(chars, starts, ends), [("hi", 0.0, 0.2), ("you", 0.3, 0.6)])

    def test_estimate_covers_the_audio(self):
        words = sub.estimate_words("one two three", 3.0)
        self.assertEqual([w[0] for w in words], ["one", "two", "three"])
        self.assertLessEqual(words[-1][2], 3.0)
        self.assertEqual(words[0][1], 0.0)

    def test_chunks_break_on_sentence_end_and_size(self):
        groups = sub.chunk(WORDS, 3)
        self.assertEqual([[w[0] for w in g] for g in groups],
                         [["Think", "you're", "good"], ["at", "puzzles?"], ["Crack", "it."]])


class Ass(unittest.TestCase):
    def events(self, style):
        doc = sub.ass_document(WORDS, style)
        out = []
        for m in re.finditer(r"Dialogue: 0,(\d+):(\d\d):(\d\d)\.(\d\d),(\d+):(\d\d):(\d\d)\.(\d\d),Cap,,0,0,0,,(.*)", doc):
            g = m.groups()
            out.append((int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 100,
                        int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 100, g[8]))
        return doc, out

    def test_pop_highlights_one_word_per_event_in_uppercase(self):
        doc, events = self.events("pop")
        self.assertEqual(len(events), len(WORDS))
        self.assertIn("THINK", events[0][2])
        self.assertEqual(events[0][2].count(sub.HIGHLIGHT), 1)
        self.assertIn("PlayResY: 1920", doc)

    def test_clean_keeps_case_and_one_event_per_chunk(self):
        _, events = self.events("clean")
        self.assertIn("Think you're good at", events[0][2])
        self.assertNotIn(sub.HIGHLIGHT, events[0][2])

    def test_events_never_overlap(self):
        for style in ("pop", "clean"):
            _, events = self.events(style)
            for (s1, e1, _), (s2, e2, _) in zip(events, events[1:]):
                self.assertLessEqual(e1, s2 + 0.001, style)
                self.assertGreater(e1, s1)

    def test_override_braces_in_text_are_neutralised(self):
        doc = sub.ass_document([("{\\an8}hi", 0, 1)], "clean")
        self.assertNotIn("{\\an8}", doc)

    def test_unknown_style(self):
        with self.assertRaises(ValueError):
            sub.ass_document(WORDS, "fancy")


if __name__ == "__main__":
    unittest.main()
