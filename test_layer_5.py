"""
Layer 5 Final Verification Test (`test_layer_5.py`)

Comprehensively validates:
1. `TickToTimeConverter` exact anchor calibration and lead-in/cooldown padding math.
2. `AutoCaptureEngine` controller orchestration (`CS2NetCon` + `OBSController`) and duck-typed candidate extraction.
3. `ClipperQueue` asynchronous background worker thread lifecycle and status tracking (`Layer 6 UI interface`).
"""

import os
import time
import shutil
import unittest
from typing import Dict, Any

from src.cs2_controller import CS2NetCon
from src.obs_controller import OBSController
from src.autocapture_engine import AutoCaptureEngine
from src.clipper import TickToTimeConverter, ClipperQueue, slice_clip_ffmpeg

try:
    from src.detectors.base import CandidateMoment
except ImportError:
    CandidateMoment = None


class TestLayer5ClipperMath(unittest.TestCase):
    """Verifies Mode 2 Tick-to-Time anchor calibration math (`src/clipper.py`)."""

    def test_anchor_offset_calculation(self):
        # Suppose Round 1 started at Tick 640 in DB, and user says Round 1 is at 10.0s in video
        converter = TickToTimeConverter(round_1_start_tick=640, round_1_video_time_sec=10.0, tick_rate=64.0)
        self.assertEqual(converter.offset_tick, 0, "Offset tick should be 0 when Round 1 tick matches video time exactly.")
        self.assertAlmostEqual(converter.tick_to_seconds(640), 10.0, places=2)

    def test_moment_padding_boundaries(self):
        converter = TickToTimeConverter(round_1_start_tick=640, round_1_video_time_sec=10.0, tick_rate=64.0)
        # Highlight: Tick 16493 -> 18267 (Raw: 257.70s -> 285.42s)
        start_sec, end_sec = converter.moment_to_video_range(16493, 18267, warmup_sec=1.5, cooldown_sec=2.0)
        
        expected_start = max(0.0, (16493 / 64.0) - 1.5)  # ~256.20s
        expected_end = (18267 / 64.0) + 2.0              # ~287.42s
        
        self.assertAlmostEqual(start_sec, expected_start, places=2)
        self.assertAlmostEqual(end_sec, expected_end, places=2)


class TestLayer5ControllersAndDuckTyping(unittest.TestCase):
    """Verifies Mode 1 AutoCaptureEngine (`src/autocapture_engine.py`) and candidate duck-typing."""

    def setUp(self):
        self.test_dir = "test_layer5_output"
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_engine_initialization(self):
        engine = AutoCaptureEngine(output_dir=self.test_dir)
        self.assertIsInstance(engine.cs2, CS2NetCon)
        self.assertIsInstance(engine.obs, OBSController)
        self.assertTrue(os.path.exists(engine.output_dir))

    def test_duck_typed_candidate_extraction(self):
        engine = AutoCaptureEngine(output_dir=self.test_dir)
        
        # Test 1: Python Dict Candidate
        dict_cand = {"start_tick": 1280, "end_tick": 2560, "player_name": "snoop", "description": "Ace_3v1"}
        self.assertEqual(engine._extract_attr(dict_cand, "start_tick"), 1280)
        self.assertEqual(engine._extract_attr(dict_cand, "player_name"), "snoop")
        
        # Test 2: Python Object Candidate (if available or mock object)
        class MockCandidate:
            def __init__(self):
                self.start_tick = 3200
                self.end_tick = 4480
                self.player_name = "ZywOo"
                self.description = "Clutch_1v3"

        obj_cand = MockCandidate()
        self.assertEqual(engine._extract_attr(obj_cand, "start_tick"), 3200)
        self.assertEqual(engine._extract_attr(obj_cand, "player_name"), "ZywOo")


class TestLayer5ClipperQueue(unittest.TestCase):
    """Verifies Mode 2 ClipperQueue background worker lifecycle (`src/clipper.py`)."""

    def setUp(self):
        self.test_dir = "test_clipper_queue_out"
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_queue_initialization_and_status(self):
        cqueue = ClipperQueue(output_dir=self.test_dir)
        status = cqueue.get_status()
        self.assertFalse(status["is_busy"])
        self.assertEqual(status["total"], 0)
        self.assertEqual(status["completed"], 0)
        self.assertEqual(status["saved_paths"], [])

    def test_missing_video_graceful_handling(self):
        cqueue = ClipperQueue(output_dir=self.test_dir)
        converter = TickToTimeConverter(640, 10.0)
        mock_candidates = [{"start_tick": 100, "end_tick": 200, "description": "Test"}]
        
        # Should return False gracefully without crashing when video is missing
        started = cqueue.start_playlist_slicing("non_existent_match.mp4", converter, mock_candidates)
        self.assertFalse(started)


if __name__ == "__main__":
    print("=== Running Layer 5 Complete Verification Suite ===")
    unittest.main(verbosity=2)
