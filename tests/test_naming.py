import unittest
from datetime import date

from creative_factory import naming


class DerivePrefix(unittest.TestCase):
    def test_two_words(self):
        self.assertEqual(naming.derive_prefix("Brain Wash"), "BW")

    def test_first_two_words_of_three(self):
        self.assertEqual(naming.derive_prefix("My Little Spa"), "ML")

    def test_questionable_names_return_none(self):
        # a single word like Outrun (OR) cannot be derived: ask for a manual abbreviation
        for name in ["Outrun", "2048 Merge", "Word2", "The Sims", "Игра Слов", "", "X"]:
            self.assertIsNone(naming.derive_prefix(name), name)

    def test_suggestion_for_manual_prompt(self):
        self.assertEqual(naming.suggest_prefix("Outrun"), "OU")
        self.assertEqual(naming.suggest_prefix("2048 Merge"), "ME")
        self.assertIsNone(naming.suggest_prefix("X"))


class ParseFilename(unittest.TestCase):
    def test_plain(self):
        p = naming.parse_filename("BW001_v1_9x16_59s_EN.mp4")
        self.assertEqual((p.prefix, p.id, p.version, p.ratio, p.duration, p.lang),
                         ("BW", 1, 1, "9x16", 59, "EN"))

    def test_collision_digit_is_part_of_prefix(self):
        p = naming.parse_filename("BW1001_v2_4x5_45s_EN.mp4")
        self.assertEqual((p.prefix, p.id), ("BW1", 1))

    def test_designer_suffix(self):
        p = naming.parse_filename("SP006_v2_9x16_52s_EN_ZP.mp4")
        self.assertEqual((p.prefix, p.id, p.suffix), ("SP", 6, "ZP"))

    def test_rejects_other_names(self):
        self.assertIsNone(naming.parse_filename("v2.mp4"))
        self.assertIsNone(naming.parse_filename("BW01_v1_9x16_59s_EN.mp4"))


class AssignPrefix(unittest.TestCase):
    def test_free_prefix(self):
        self.assertEqual(naming.assign_prefix("Brain Wash", {}), "BW")

    def test_collision_gets_digit(self):
        m = {"BW": "business world"}
        self.assertEqual(naming.assign_prefix("Brain Wash", m), "BW1")
        m["BW1"] = "brain wash"
        self.assertEqual(naming.assign_prefix("Brain Wash", m), "BW1")
        self.assertEqual(naming.assign_prefix("Bubble Walk", m), "BW2")

    def test_same_game_reuses_its_prefix(self):
        self.assertEqual(naming.assign_prefix("Brain  Wash", {"BW": "brain wash"}), "BW")

    def test_override(self):
        self.assertEqual(naming.assign_prefix("My Little Spa", {}), "SP")

    def test_manual_abbreviation(self):
        self.assertEqual(naming.assign_prefix("2048 Merge", {}, manual="mg"), "MG")
        self.assertEqual(naming.assign_prefix("2048 Merge", {"MG": "other"}, manual="mg"), "MG1")

    def test_questionable_name_needs_manual(self):
        with self.assertRaises(ValueError):
            naming.assign_prefix("2048 Merge", {})

    def test_bad_manual(self):
        with self.assertRaises(ValueError):
            naming.assign_prefix("Brain Wash", {}, manual="B1")

    def test_prefix_map_from_drive_listing(self):
        m = naming.build_prefix_map({
            "My Little Spa": ["SP033_v1_9x16_59s_EN.mp4", "notes.txt"],
            "Business World": ["BW002_v1_9x16_40s_EN.mp4"],
        })
        self.assertEqual(m, {"SP": "my little spa", "BW": "business world"})


class Ids(unittest.TestCase):
    def test_new_game_starts_at_one(self):
        self.assertEqual(naming.next_id([]), 1)

    def test_gaps_are_not_reused(self):
        self.assertEqual(naming.next_id([6, 27, 33]), 34)

    def test_runs_out_at_999(self):
        with self.assertRaises(ValueError):
            naming.next_id([999])


class Names(unittest.TestCase):
    def test_file_name_round_trips(self):
        name = naming.file_name("BW1", 12, 2, "4x5", 45)
        self.assertEqual(name, "BW1012_v2_4x5_45s_EN.mp4")
        p = naming.parse_filename(name)
        self.assertEqual((p.prefix, p.id), ("BW1", 12))

    def test_folder_name(self):
        self.assertEqual(
            naming.folder_name("SP", 33, "No Break", date(2026, 10, 22)),
            "SP[033]_No_Break_(22.10.26)",
        )

    def test_ratio_label(self):
        self.assertEqual(naming.ratio_label(1080, 1920), "9x16")
        self.assertEqual(naming.ratio_label(1080, 1350), "4x5")


if __name__ == "__main__":
    unittest.main()
