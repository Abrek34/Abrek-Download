"""Doğrudan indirici parça planlama testleri."""

from __future__ import annotations

import os
import unittest

os.environ["ABREK_LANG"] = "tr"

from core.direct import plan_segments


class PlanSegmentsTests(unittest.TestCase):
    def test_single_segment(self):
        self.assertEqual(plan_segments(100, 1), [{"start": 0, "end": 99}])

    def test_even_split_covers_all_bytes(self):
        segments = plan_segments(100, 4)
        self.assertEqual(
            segments,
            [
                {"start": 0, "end": 24},
                {"start": 25, "end": 49},
                {"start": 50, "end": 74},
                {"start": 75, "end": 99},
            ],
        )
        covered = sum(segment["end"] - segment["start"] + 1 for segment in segments)
        self.assertEqual(covered, 100)
        for previous, current in zip(segments, segments[1:]):
            self.assertEqual(previous["end"] + 1, current["start"])

    def test_uneven_split_still_covers_all_bytes(self):
        segments = plan_segments(10, 3)
        self.assertEqual(segments[0]["start"], 0)
        self.assertEqual(segments[-1]["end"], 9)
        for segment in segments:
            self.assertGreaterEqual(segment["end"], segment["start"])
        covered = sum(segment["end"] - segment["start"] + 1 for segment in segments)
        self.assertEqual(covered, 10)

    def test_more_parts_than_bytes_are_clamped(self):
        segments = plan_segments(3, 10)
        self.assertEqual(len(segments), 3)
        self.assertTrue(all(segment["start"] == segment["end"] for segment in segments))

    def test_zero_and_negative_total(self):
        self.assertEqual(plan_segments(0, 4), [{"start": 0, "end": -1}])
        self.assertEqual(plan_segments(-5, 4), [{"start": 0, "end": -1}])

    def test_zero_parts_falls_back_to_one(self):
        self.assertEqual(plan_segments(50, 0), [{"start": 0, "end": 49}])


if __name__ == "__main__":
    unittest.main()
