"""
Automated Capture Engine (`src/autocapture_engine.py`)

Master coordinator for Layer 5 Mode 1 (OBS & CS2 Auto-Capture).
Links `CS2NetCon` (port 2121) and `OBSController` (port 4455) together to automatically
record candidate highlights from a `.dem` replay file into crisp, cinematic `.mp4` video clips.
"""

import os
import time
import shutil
from typing import List, Dict, Any, Optional, Union

try:
    from src.cs2_controller import CS2NetCon
    from src.obs_controller import OBSController
    from src.detectors.base import CandidateMoment
except ImportError:
    # Handle relative imports if run from inside `src/` or tests
    from cs2_controller import CS2NetCon
    from obs_controller import OBSController
    CandidateMoment = None


class AutoCaptureEngine:
    """
    Orchestrates Counter-Strike 2 demo playback and OBS Studio screen recording
    to automatically slice and save top-ranked highlight clips.
    """

    def __init__(
        self,
        cs2_host: str = "127.0.0.1",
        cs2_port: int = 2121,
        obs_host: str = "localhost",
        obs_port: int = 4455,
        obs_password: str = "",
        output_dir: str = "clips",
        tick_rate: float = 64.0
    ):
        self.cs2 = CS2NetCon(host=cs2_host, port=cs2_port)
        self.obs = OBSController(host=obs_host, port=obs_port, password=obs_password)
        self.output_dir = os.path.abspath(output_dir)
        self.tick_rate = tick_rate
        self.current_loaded_demo: Optional[str] = None

        os.makedirs(self.output_dir, exist_ok=True)

    def connect_all(self, launch_cs2_if_closed: bool = True) -> bool:
        """
        Verifies and establishes connections to both OBS Studio and CS2 NetCon.
        If OBS Studio or CS2 is closed, boots them automatically via subprocess/Steam.
        """
        print("[AutoCaptureEngine] Verifying OBS Studio WebSocket connection...")
        if not self.obs.connect(max_retries=1):
            print("[AutoCaptureEngine] OBS Studio not detected. Attempting to launch `obs64.exe`...")
            obs_path = r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"
            obs_dir = r"C:\Program Files\obs-studio\bin\64bit"
            if os.path.exists(obs_path):
                try:
                    import subprocess, shutil
                    sentinel_dir = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "obs-studio", ".sentinel")
                    if os.path.exists(sentinel_dir):
                        shutil.rmtree(sentinel_dir, ignore_errors=True)
                        print("[AutoCaptureEngine] Scrubbed OBS `.sentinel` crash directory to guarantee clean startup.")
                    subprocess.Popen([obs_path, "--always-normal-mode", "--disable-shutdown-check", "--disable-safe-mode"], cwd=obs_dir)
                    print("[AutoCaptureEngine] Launched `obs64.exe` (Always Normal Mode & Safe Mode bypass enabled). Waiting for WebSocket server to initialize...")
                    time.sleep(8.0)
                except Exception as e:
                    print(f"[AutoCaptureEngine ERROR] Could not launch OBS: {e}")
            if not self.obs.connect(max_retries=10, retry_delay=2.0):
                print("[AutoCaptureEngine ERROR] Cannot start capture: OBS Studio is not connected.")
                return False

        print("[AutoCaptureEngine] Verifying CS2 NetCon TCP connection...")
        if not self.cs2.connect(max_retries=2):
            if launch_cs2_if_closed:
                print("[AutoCaptureEngine] Attempting to boot CS2 via Steam...")
                if self.cs2.launch_cs2_if_needed(wait_seconds=30):
                    time.sleep(3.0)  # Extra buffer for TCP console to open
                    if not self.cs2.connect(max_retries=15, retry_delay=2.0):
                        return False
                else:
                    return False
            else:
                return False

        print("[AutoCaptureEngine SUCCESS] Both CS2 and OBS Studio are connected and ready!")
        return True

    def disconnect_all(self):
        """Cleanly disconnects both controllers."""
        self.cs2.disconnect()
        self.obs.disconnect()
        print("[AutoCaptureEngine] Disconnected from all controllers.")

    def disconnect(self):
        """Alias for disconnect_all()."""
        self.disconnect_all()

    def close_all_apps(self):
        """
        Gracefully shuts down both Counter-Strike 2 (`cs2.exe`) and OBS Studio (`obs64.exe`).
        Automatically scrubs any remaining VAC launch options before exiting.
        """
        print("\n[AutoCaptureEngine] Shutting down both Counter-Strike 2 and OBS Studio applications...")
        self.cs2.close_cs2()
        self.obs.close_obs()
        print("[AutoCaptureEngine SUCCESS] All recording applications closed and launch options scrubbed.")

    def _extract_attr(self, item: Any, attr_name: str, default: Any = None) -> Any:
        """Helper to extract attribute from either CandidateMoment object or dict."""
        if isinstance(item, dict):
            return item.get(attr_name, default)
        return getattr(item, attr_name, default)

    def _set_mouse_lock(self, locked: bool):
        """
        Locks hardware mouse input via Windows BlockInput and parks cursor at bottom-right corner.
        Requires Administrator privileges for BlockInput; parking always succeeds.
        """
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.BlockInput(1 if locked else 0)
            if locked:
                user32.SetCursorPos(1920, 1080)
        except Exception:
            pass

    def capture_highlight(
        self,
        demo_path: str,
        candidate: Any,
        match_title: str = "Match",
        clip_index: int = 1,
        warmup_ticks: int = 256,  # 4.0s lead-in
        cooldown_ticks: int = 32  # 0.5s cooldown
    ) -> Optional[str]:
        """
        Records a single candidate highlight clip from a demo file.
        
        Args:
            demo_path: Absolute or relative path to the `.dem` file.
            candidate: `CandidateMoment` or dict with `start_tick`, `end_tick`, `player_name`, `description`.
            match_title: Prefix name for the match (e.g. "Match730").
            clip_index: Ordering rank number (`Highlight_1`).
            warmup_ticks: Lead-in ticks before `start_tick` (default 256 = 4.0 seconds).
            cooldown_ticks: Cooldown ticks after `end_tick` (default 32 = 0.5 seconds for instant cutoff).
            
        Returns:
            Absolute file path of the saved and renamed `.mp4` clip, or None if failed.
        """
        if not self.cs2.connected or not self.obs.connected:
            if not self.connect_all():
                return None

        # 1. Extract moment properties
        start_tick = int(self._extract_attr(candidate, "start_tick", 0))
        end_tick = int(self._extract_attr(candidate, "end_tick", start_tick + 640))
        player_name = str(self._extract_attr(candidate, "player_name", ""))
        desc = str(self._extract_attr(candidate, "description", "Highlight"))
        
        # Calculate padded tick boundaries
        actual_start = max(0, start_tick - warmup_ticks)
        actual_end = end_tick + cooldown_ticks
        duration_ticks = actual_end - actual_start
        duration_sec = duration_ticks / 64.0  # 64 tick rate standard

        print(f"\n=======================================================")
        print(f"[AutoCaptureEngine] Capturing Clip #{clip_index}: {desc}")
        print(f" -> Target Player: {player_name if player_name else 'All / Default'}")
        print(f" -> Ticks: {actual_start} to {actual_end} (~{duration_sec:.1f}s)")
        print(f"=======================================================")

        # 2. Load demo file if changed
        clean_demo_path = os.path.abspath(demo_path)
        if self.current_loaded_demo != clean_demo_path:
            self.cs2.play_demo(clean_demo_path)
            self.current_loaded_demo = clean_demo_path
            print("[AutoCaptureEngine] Waiting for Source 2 demo level (`levelload`) to finish loading...")
            for _ in range(25):
                time.sleep(1.0)
                st = self.cs2.send_command("status", read_response=True)
                if st and "levelload" not in st and ("map" in st or "DEMO" in st or "game" in st):
                    break
            time.sleep(2.0)  # Buffer after level settle before teleporting

        # 3. Teleport demo to exact start tick and let it play for 0.5s so entities load cleanly
        print(f"[AutoCaptureEngine] Teleporting demo to pre-fight tick {actual_start}...")
        self.cs2.goto_tick(actual_start)
        self.cs2.resume_demo()
        time.sleep(0.5)

        # 4. Bring CS2 to foreground, detect its exact running resolution (4:3, 16:9, etc.), and configure OBS canvas dynamically!
        self.cs2.focus_cs2_window()
        time.sleep(0.3)
        cs2_w, cs2_h = self.cs2.get_window_resolution()
        print(f"[AutoCaptureEngine] Configuring OBS to match detected CS2 player resolution: {cs2_w}x{cs2_h}...")
        self.obs.set_recording_resolution(width=cs2_w, height=cs2_h, fps=60)
        
        if player_name:
            print(f"[AutoCaptureEngine] Finding and locking camera onto desired player `{player_name}` FIRST before hiding UI...")
            self.cs2.lock_camera_to_player(player_name)
        
        # 5. Wait some time before hiding UI so the camera settles cleanly onto target player
        print("[AutoCaptureEngine] Waiting 1.2s for camera to settle cleanly on player before hiding UI...")
        time.sleep(1.2)
        
        # 6. Now hide demo UI right before recording starts and pause demo at clean lead-in tick
        print("[AutoCaptureEngine] Hiding demo UI (cl_draw_only_deathnotices 1, spec_show_xray 0, demoui)...")
        self.cs2.suppress_demo_ui()
        self.cs2.send_command("cl_draw_only_deathnotices 1")
        self.cs2.send_command("cl_drawhud 1")
        self.cs2.send_command("spec_show_xray 0")
        self.cs2.pause_demo()
        time.sleep(1.0)

        # 7. Now Start Recording (Frame #1 captures the clean pre-fight lead-in at least 5+ seconds before shooting starts!)
        print("[AutoCaptureEngine] Rolling camera (Start OBS Recording)...")
        if not self.obs.start_recording():
            print("[AutoCaptureEngine ERROR] Failed to trigger OBS recording.")
            return None

        print("[AutoCaptureEngine] Allowing 1.5s while paused for OBS encoder pipeline to fully initialize and capture clean lead-in frames...")
        time.sleep(1.5)

        self._set_mouse_lock(True)
        try:
            # 6. Now Resume Demo & record the clean highlight without missing any action
            print(f"[AutoCaptureEngine] Resuming game playback for {duration_sec:.1f} seconds (mouse input disabled)...")
            self.cs2.resume_demo()
            time.sleep(duration_sec)
        finally:
            self._set_mouse_lock(False)

        # 7. Stop Recording & Pause Demo
        print("[AutoCaptureEngine] Highlight finished! Stopping OBS camera...")
        self.cs2.pause_demo()
        raw_clip_path = self.obs.stop_recording(wait_for_file_flush=True, timeout=12.0)

        if not raw_clip_path or not os.path.exists(raw_clip_path):
            print("[AutoCaptureEngine ERROR] OBS stopped, but raw video clip could not be located on disk.")
            return None

        # 8. Sanitize description & move file to output folder
        safe_desc = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in desc).strip('_')
        safe_match = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in match_title).strip('_')
        target_filename = f"{safe_match}_Clip_{clip_index:02d}_{safe_desc}.mp4"
        target_abspath = os.path.join(self.output_dir, target_filename)

        try:
            # If target exists, overwrite or append counter
            if os.path.exists(target_abspath):
                target_abspath = os.path.join(self.output_dir, f"{safe_match}_Clip_{clip_index:02d}_{safe_desc}_{int(time.time())}.mp4")

            shutil.move(raw_clip_path, target_abspath)
            print(f"[AutoCaptureEngine SUCCESS] Clip successfully saved -> {target_abspath}")
            return target_abspath
        except Exception as e:
            print(f"[AutoCaptureEngine ERROR] Failed to move clip from `{raw_clip_path}` to `{target_abspath}`: {e}")
            return raw_clip_path

    def capture_playlist(
        self,
        demo_path: str,
        candidates: List[Any],
        match_title: str = "Match",
        progress_callback: Optional[Any] = None,
        close_apps_when_done: bool = True
    ) -> List[str]:
        """
        Sequentially captures a full playlist of candidate highlights.
        
        Args:
            demo_path: Absolute path to the `.dem` file.
            candidates: List of `CandidateMoment` objects sorted by priority/score.
            match_title: Title prefix for output clips.
            progress_callback: Optional callback function `fn(current_idx, total_clips, latest_clip_path)`
                               for updating UI progress bars.
            close_apps_when_done: If True, automatically closes CS2 and OBS Studio when recording concludes.
                               
        Returns:
            List of absolute paths to all successfully recorded `.mp4` clips.
        """
        saved_clips = []
        total = len(candidates)
        print(f"\n[AutoCaptureEngine] Starting batch capture of {total} highlights from `{os.path.basename(demo_path)}`...")

        if not self.connect_all():
            return []

        try:
            for idx, candidate in enumerate(candidates, start=1):
                clip_path = self.capture_highlight(
                    demo_path=demo_path,
                    candidate=candidate,
                    match_title=match_title,
                    clip_index=idx
                )
                if clip_path:
                    saved_clips.append(clip_path)

                if progress_callback and callable(progress_callback):
                    try:
                        progress_callback(idx, total, clip_path)
                    except Exception:
                        pass

                # Short 1.5s breather between highlights
                time.sleep(1.5)
        finally:
            # Always restore normal HUD before disconnecting or closing
            print("\n[AutoCaptureEngine] Batch complete. Restoring normal spectator HUD...")
            try:
                self.cs2.restore_normal_hud()
            except Exception:
                pass

            if close_apps_when_done:
                self.close_all_apps()
            else:
                self.disconnect_all()

        print(f"\n[AutoCaptureEngine SUMMARY] Successfully captured {len(saved_clips)}/{total} clips into `{self.output_dir}`!")
        return saved_clips


if __name__ == "__main__":
    import argparse
    import sqlite3

    parser = argparse.ArgumentParser(description="AutoCaptureEngine CLI - Record CS2 Highlights")
    parser.add_argument("--demo", default=r"C:/Program Files (x86)/Steam/steamapps/common/Counter-Strike Global Offensive/game/csgo/replays/match730_003831047039177720673_1229901627_382.dem", help="Path to demo file")
    parser.add_argument("--player", default="log1c", help="Target player substring to record")
    parser.add_argument("--top", type=int, default=1, help="Number of top scoring clips to capture")
    parser.add_argument("--output", default="clips", help="Output directory for MP4 clips")
    args = parser.parse_args()

    print(f"=== AutoCaptureEngine CLI: Capturing Top {args.top} clip(s) for `{args.player}` ===")
    
    # Check database or create candidate candidate dictionary
    # We query all candidate moments matching player_name or fall back to high score check
    try:
        from src.detectors.base import CandidateMoment
        from src.database import CS2Database
        from src.detectors.multikill import MultiKillDetector
        from src.detectors.clutch import ClutchDetector
        from src.detectors.skill import SkillDetector
        from src.ml_model import CS2WinProbabilityModel

        db = CS2Database("data/processed/test_matches.db")
        match_data = db.load_match_data("8c3d49085e289a2513a7c211962af8f98864ed8388d5552659a77554b0a8972b")
        
        detectors = [MultiKillDetector(), ClutchDetector(), SkillDetector()]
        all_candidates = []
        for d in detectors:
            all_candidates.extend(d.detect(match_data))
            
        model = CS2WinProbabilityModel()
        model.load_model("data/processed/win_prob_rf.pkl")
        all_candidates = model.rank_moments(all_candidates, match_data)
        
        # Filter for our target player
        player_cands = [c for c in all_candidates if args.player.lower() in c.player_name.lower()]
        print(f" -> Found {len(player_cands)} detected moments for `{args.player}` in match.")
    except Exception as e:
        print(f"[CLI fallback] Could not run ML ranking: {e}. Using direct DB query...")
        player_cands = []

    if not player_cands:
        # Direct DB high score fallback if no ranked objects found
        conn = sqlite3.connect("data/processed/test_matches.db")
        c = conn.cursor()
        match_hash_clause = ""
        params = [f"%{args.player}%"]
        file_hash = None
        if args.demo and os.path.exists(args.demo):
            try:
                from src.database import CS2Database
                file_hash = CS2Database.get_file_hash(args.demo)
                match_hash_clause = " AND match_hash = ?"
                params.append(file_hash)
            except Exception:
                pass

        row = c.execute(f"""
            SELECT round_number, min(tick), max(tick), count(*) as kills
            FROM kills WHERE attacker_name LIKE ?{match_hash_clause} GROUP BY round_number ORDER BY kills DESC LIMIT 1
        """, params).fetchone()
        if row:
            # Exact user request: stop instantly when kills complete or player dies
            death_params = [f"%{args.player}%", row[0]]
            if match_hash_clause:
                death_params.append(file_hash)
            death_row = c.execute(f"SELECT min(tick) FROM kills WHERE user_name LIKE ? AND round_number = ?{match_hash_clause}", death_params).fetchone()
            final_tick = row[2]
            if death_row and death_row[0]:
                final_tick = min(final_tick, death_row[0] + 16) # Include death tick plus 16 ticks (~0.25s) for instant cut
            conn.close()
            player_cands = [{
                "start_tick": row[1] - 384,  # 6.0s before 1st kill + 4.0s warmup_ticks = 10.0s total lead-in before 1st kill!
                "end_tick": final_tick + 32, # Stop instantly after final kill or death!
                "player_name": args.player,
                "description": f"{args.player} Round {row[0]} ({row[3]} Kills High Score)",
                "round_num": row[0]
            }]

    if not player_cands:
        print(f"[ERROR] No highlights or kills found for player `{args.player}`.")
        sys.exit(1)

    top_clips = player_cands[:args.top]
    engine = AutoCaptureEngine(output_dir=args.output)
    engine.capture_playlist(demo_path=args.demo, candidates=top_clips, match_title=f"{args.player}_Best")
    print(f" -> CS2 Host: {engine.cs2.host}:{engine.cs2.port}")
    print(f" -> OBS Host: {engine.obs.host}:{engine.obs.port}")
    print("To run a live capture test, ensure OBS Studio is open and call `engine.capture_playlist()`.")
