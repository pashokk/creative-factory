import unittest

from creative_factory.drive import games_from_listing

ROOT = "root"
FOLDERS = {
    "g1": {"id": "g1", "name": "Word Cipher", "parents": [ROOT]},
    "y1": {"id": "y1", "name": "2026", "parents": ["g1"]},
    "c1": {"id": "c1", "name": "Creatives", "parents": ["y1"]},
    "k1": {"id": "k1", "name": "WC[001]_Concept_(22.10.26)", "parents": ["c1"]},
    "g2": {"id": "g2", "name": "Minesweeper", "parents": [ROOT]},
    "v2": {"id": "v2", "name": "Videos", "parents": ["g2"]},
    "x": {"id": "x", "name": "Elsewhere", "parents": ["unknown"]},
}


class GamesFromListing(unittest.TestCase):
    def test_groups_by_top_level_folder(self):
        files = [
            {"name": "WC001_v1_9x16_51s_EN.mp4", "parents": ["k1"]},
            {"name": "WC001_v1_4x5_51s_EN.mp4", "parents": ["k1"]},
            {"name": "MS012_v1_9x16_45s_EN.mp4", "parents": ["v2"]},
        ]
        games = games_from_listing(ROOT, FOLDERS, files)
        self.assertEqual(sorted(games["Word Cipher"]),
                         ["WC001_v1_4x5_51s_EN.mp4", "WC001_v1_9x16_51s_EN.mp4", "WC[001]_Concept_(22.10.26)"])
        self.assertEqual(games["Minesweeper"], ["MS012_v1_9x16_45s_EN.mp4"])

    def test_folder_names_count_even_without_files(self):
        folders = {**FOLDERS, "k2": {"id": "k2", "name": "WC[002]_Other_(23.10.26)", "parents": ["c1"]},
                   "k3": {"id": "k3", "name": "Videos", "parents": ["c1"]}}
        games = games_from_listing(ROOT, folders, [])
        self.assertEqual(sorted(games["Word Cipher"]), ["WC[001]_Concept_(22.10.26)", "WC[002]_Other_(23.10.26)"])

    def test_ignores_unconventional_names_and_orphans(self):
        files = [
            {"name": "Bubble_Blast_1_9x16_23.05.25_EN.mp4", "parents": ["v2"]},
            {"name": "WC002_v1_9x16_51s_EN.mp4", "parents": ["x"]},
            {"name": "WC003_v1_9x16_51s_EN.mp4", "parents": []},
        ]
        # only the conventionally named folder counts; the odd file names and orphans are ignored
        self.assertEqual(games_from_listing(ROOT, FOLDERS, files), {"Word Cipher": ["WC[001]_Concept_(22.10.26)"]})


if __name__ == "__main__":
    unittest.main()
