"""
FFmpeg Video Clipper & Tick-to-Time Converter (`src/clipper.py`)

Handles Layer 5 Mode 2 (Manual Recording & FFmpeg Stream Copying).
Provides exact mathematical conversion from CS2 demo ticks to video timestamps using
Round 1 anchor calibration, extracts clips in <0.5 seconds via `ffmpeg -c copy`,
and manages an asynchronous background worker queue to keep UI dashboards responsive.
"""

import os
import time
import queue
import shutil
import threading
import subprocess
from typing import List, Dict, Any, Optional, Tuple, Callable


class TickToTimeConverter:
    """
    Translates game ticks to precise video seconds using Round 1 anchor calibration.
    """

    def __init__(self, round_1_start_tick: int, round_1_video_time_sec: float, tick_rate: float = 64.0):
        """
        Args:
            round_1_start_tick: Exact tick when Round 1 freeze time ended (from Layer 2/3 DB).
            round_1_video_time_sec: Video timestamp in seconds observed by user when Round 1 starts (`00:14 -> 14.0s`).
            tick_rate: Match tick rate (usually 64.0).
        """
        self.round_1_start_tick = int(round_1_start_tick)
        self.round_1_video_time_sec = float(round_1_video_time_sec)
        self.tick_rate = float(tick_rate)

        # Calculate Offset Tick corresponding to 0.0s in the video
        self.offset_tick = self.round_1_start_tick - int(self.round_1_video_time_sec * self.tick_rate)

    def tick_to_seconds(self, tick: int) -> float:
        """Converts any game tick ($T$) into exact video timestamp in seconds ($V$)."""
        return max(0.0, (tick - self.offset_tick) / self.tick_rate)

    def moment_to_video_range(
        self,
        start_tick: int,
        end_tick: int,
        warmup_sec: float = 1.5,
        cooldown_sec: float = 2.0
    ) -> Tuple[float, float]:
        """
        Converts tick boundaries into padded video start and end seconds.
        """
        raw_start_sec = self.tick_to_seconds(start_tick)
        raw_end_sec = self.tick_to_seconds(end_tick)

        start_sec = max(0.0, raw_start_sec - warmup_sec)
        end_sec = raw_end_sec + cooldown_sec
        return (start_sec, end_sec)


def slice_clip_ffmpeg(
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
    use_stream_copy: bool = True
) -> bool:
    """
    Slices a video interval (`start_sec` -> `end_sec`) using FFmpeg.
    
    If `use_stream_copy` is True, uses `-c copy` for lightning-fast (<0.5s) sub-second extraction
    without re-encoding. Falls back to fast re-encoding if stream copy fails or if requested.
    """
    if not os.path.exists(video_path):
        print(f"[Clipper ERROR] Source video file not found: `{video_path}`")
        return False

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # 1. Attempt Stream Copy (`-c copy`) for speed
    if use_stream_copy:
        cmd_copy = [
            "ffmpeg", "-y",
            "-ss", f"{start_sec:.3f}",
            "-to", f"{end_sec:.3f}",
            "-i", video_path,
            "-c", "copy",
            output_path
        ]
        try:
            res = subprocess.run(cmd_copy, capture_output=True, text=True)
            if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return True
            else:
                print(f"[Clipper WARNING] Stream copy failed or produced invalid clip (returncode={res.returncode}). Falling back to fast re-encode...")
        except Exception as e:
            print(f"[Clipper WARNING] FFmpeg execution error during stream copy: {e}. Falling back to re-encode...")

    # 2. Fallback: Fast Re-encode (`libx264 -preset fast`)
    cmd_encode = [
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}",
        "-to", f"{end_sec:.3f}",
        "-i", video_path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "aac",
        output_path
    ]
    try:
        res = subprocess.run(cmd_encode, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return True
        else:
            print(f"[Clipper ERROR] FFmpeg re-encode failed:\n{res.stderr}")
            return False
    except Exception as e:
        print(f"[Clipper ERROR] Fatal FFmpeg execution error: {e}")
        return False


class ClipperQueue:
    """
    Asynchronous background worker queue (`threading.Thread` + `queue.Queue`).
    Slices multiple candidate clips in the background without blocking UI dashboards (`Layer 6`).
    """

    def __init__(self, output_dir: str = "clips"):
        self.output_dir = os.path.abspath(output_dir)
        self.task_queue: queue.Queue = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.is_busy = False
        self.stop_requested = False

        # Status tracking for UI
        self.total_clips = 0
        self.completed_clips = 0
        self.current_clip_name = ""
        self.saved_clip_paths: List[str] = []
        self.errors: List[str] = []
        self.progress_callback: Optional[Callable] = None

        os.makedirs(self.output_dir, exist_ok=True)

    def _worker_loop(self):
        """Background thread loop that pulls tasks and executes FFmpeg commands."""
        self.is_busy = True
        while not self.stop_requested:
            try:
                task = self.task_queue.get(timeout=0.5)
            except queue.Empty:
                if self.task_queue.empty():
                    break
                continue

            video_path, start_sec, end_sec, target_filename, desc = task
            self.current_clip_name = desc
            target_abspath = os.path.join(self.output_dir, target_filename)

            # Prevent overwriting by appending UNIX timestamp if name exists
            if os.path.exists(target_abspath):
                base, ext = os.path.splitext(target_filename)
                target_abspath = os.path.join(self.output_dir, f"{base}_{int(time.time())}{ext}")

            print(f"[ClipperQueue] Slicing: {desc} ({start_sec:.1f}s -> {end_sec:.1f}s)...")
            success = slice_clip_ffmpeg(
                video_path=video_path,
                start_sec=start_sec,
                end_sec=end_sec,
                output_path=target_abspath,
                use_stream_copy=True
            )

            if success:
                self.completed_clips += 1
                self.saved_clip_paths.append(target_abspath)
                print(f"[ClipperQueue SUCCESS] Saved -> {target_abspath}")
            else:
                self.errors.append(f"Failed to slice: {desc}")
                print(f"[ClipperQueue ERROR] Failed to slice clip: {desc}")

            if self.progress_callback and callable(self.progress_callback):
                try:
                    self.progress_callback(self.completed_clips, self.total_clips, target_abspath if success else None)
                except Exception:
                    pass

            self.task_queue.task_done()

        self.is_busy = False
        self.current_clip_name = "Done"
        print(f"\n[ClipperQueue SUMMARY] Completed batch slicing. Saved {self.completed_clips}/{self.total_clips} clips into `{self.output_dir}`!")

    def start_playlist_slicing(
        self,
        video_path: str,
        converter: TickToTimeConverter,
        candidates: List[Any],
        match_title: str = "Match",
        progress_callback: Optional[Callable] = None
    ) -> bool:
        """
        Enqueues a list of candidates and starts the background worker thread.
        """
        if self.is_busy:
            print("[ClipperQueue WARNING] Queue is currently busy processing another job.")
            return False

        if not os.path.exists(video_path):
            print(f"[ClipperQueue ERROR] Video file not found: `{video_path}`")
            return False

        self.stop_requested = False
        self.total_clips = len(candidates)
        self.completed_clips = 0
        self.saved_clip_paths = []
        self.errors = []
        self.progress_callback = progress_callback

        for idx, candidate in enumerate(candidates, start=1):
            # Extract attributes dynamically (supports dataclass or dict)
            start_tick = int(getattr(candidate, "start_tick", candidate.get("start_tick", 0) if isinstance(candidate, dict) else 0))
            end_tick = int(getattr(candidate, "end_tick", candidate.get("end_tick", start_tick + 640) if isinstance(candidate, dict) else start_tick + 640))
            desc = str(getattr(candidate, "description", candidate.get("description", "Highlight") if isinstance(candidate, dict) else "Highlight"))

            start_sec, end_sec = converter.moment_to_video_range(start_tick, end_tick, warmup_sec=1.5, cooldown_sec=2.0)

            safe_desc = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in desc).strip('_')
            safe_match = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in match_title).strip('_')
            target_filename = f"{safe_match}_Clip_{idx:02d}_{safe_desc}.mp4"

            self.task_queue.put((video_path, start_sec, end_sec, target_filename, desc))

        print(f"[ClipperQueue] Enqueued {self.total_clips} highlight tasks. Starting worker thread...")
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        return True

    def get_status(self) -> Dict[str, Any]:
        """Returns real-time queue status for UI dashboard progress bars."""
        return {
            "is_busy": self.is_busy,
            "total": self.total_clips,
            "completed": self.completed_clips,
            "current_clip": self.current_clip_name,
            "saved_paths": self.saved_clip_paths,
            "errors": self.errors
        }


if __name__ == "__main__":
    print("=== FFmpeg Clipper & TickToTimeConverter Standalone Test ===")
    
    # Test converter math
    # Suppose Round 1 started at Tick 640 in database, and user says Round 1 is at 10.0s in video
    converter = TickToTimeConverter(round_1_start_tick=640, round_1_video_time_sec=10.0, tick_rate=64.0)
    print(f" -> Offset Tick: {converter.offset_tick} (Tick 0 = {converter.tick_to_seconds(0):.2f}s)")
    
    # Suppose Highlight happens at Tick 16493 -> 18267
    s_sec, e_sec = converter.moment_to_video_range(16493, 18267)
    print(f" -> Highlight Ticks (16493->18267) mapped to Video Range: {s_sec:.2f}s to {e_sec:.2f}s")
    
    # Check if ffmpeg is installed on system
    try:
        ver = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if ver.returncode == 0:
            print("[SUCCESS] FFmpeg command-line tool is installed and accessible on system PATH!")
        else:
            print("[WARNING] FFmpeg returned non-zero exit code.")
    except FileNotFoundError:
        print("[WARNING] `ffmpeg` executable not found on system PATH.")
        print(" -> To slice existing `.mp4` videos, install FFmpeg (`winget install -e --id Gyan.FFmpeg`).")
