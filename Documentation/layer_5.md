# CS2 Highlight Detector - Layer 5: Syncing & Video Clipper

This document explains **Layer 5: Syncing & Video Clipper** of the CS2 Highlight Detector and Scorer. It covers the tick-to-video mathematical synchronization formulas, the automated dual-mode clipping architecture, cinematic in-game UI configuration, and the asynchronous video processing pipeline.

---

## 1. Architectural Overview & Dual-Mode Paradigm

Up to Layer 4, every detected highlight is defined strictly in terms of **game ticks** (e.g., `start_tick=16493`, `end_tick=18267`). Layer 5 bridges the gap between raw analytical data and visual media by translating these tick intervals into actual `.mp4` video clips.

To support both advanced automated setups and universal recording workflows, Layer 5 is designed around a **Dual-Mode Architecture**:

1. **Mode 1: Automated OBS & CS2 Capture (Hands-Free Pipeline)**
   - Python directly controls the Counter-Strike 2 game engine and OBS Studio.
   - The game automatically replays the highlight ticks while OBS records the screen.
   - **0% In-Game Performance Hit**: Players do not record while playing competitively, maximizing FPS and minimizing input lag.
   - **Massive Storage Savings**: Only the exact 15–25 second highlights are recorded (~400 MB total per match vs. 5–8 GB for full recordings).

2. **Mode 2: Manual Recording & FFmpeg Slicing (Universal Pipeline)**
   - For users who record full matches via Nvidia GeForce Shadowplay, Medal, or OBS while playing.
   - Uses anchor-point synchronization formulas to align timestamps and extracts clips using lightning-fast FFmpeg stream copying.

---

## 2. Tick-to-Video Synchronization (The Math)

When slicing an existing video recording (`Mode 2`), the video timeline (measured in seconds) must be precisely aligned with the game timeline (measured in ticks). Because video recordings rarely begin exactly at tick `0` of the demo file due to menu loading or warmup delays, an alignment formula is required.

```
Demo File Ticks:   0 ───────► T_offset ───► T_highlight_start ───────────────► End
                              │            │
                              ▼            ▼
Video Seconds:                0.0s ──────► V_highlight_start ────────────────► End
```

### The Synchronization Formula
To convert any game tick ($T$) into its corresponding video timestamp in seconds ($V_{\text{time}}$), we determine the **Offset Tick** ($T_{\text{offset}}$)—the exact demo tick that corresponds to video second `0.0s`:

$$V_{\text{time}} = \frac{T - T_{\text{offset}}}{R}$$

Where $R$ represents the match tick rate (typically `64.0` ticks/second for standard CS2 demos).

### Calibrating $T_{\text{offset}}$ via Anchor Points
To find $T_{\text{offset}}$ without requiring manual calculation from the user, the dashboard requests a single **Anchor Point**:
* **Anchor Question**: *"At what video timestamp (`MM:SS`) does Round 1 officially start?"*
* Suppose the user enters $V_{\text{anchor}} = 14.0\text{ seconds}$, and our SQLite database indicates that Round 1 freeze-time ended at $T_{\text{round\_1\_start}} = 65$.
* The system computes the exact offset:
  $$T_{\text{offset}} = T_{\text{round\_1\_start}} - (V_{\text{anchor}} \times R) = 65 - (14.0 \times 64.0) = -831$$

Once calibrated, every candidate highlight's `start_tick` and `end_tick` across the entire match maps to the exact video second with millisecond precision.

---

## 3. Mode 1: Automated OBS & CS2 Capture Engine

The automated pipeline synchronizes two standalone applications using local network protocols: **NetCon** for CS2 and **WebSockets** for OBS Studio.

### Step 1: Python Dependencies & Verification (`test_obs_connection.py`)
- Uses `obs-websocket-py` (OBS WebSocket v5 API) and `psutil` (process monitoring).
- Connects to OBS Studio on port `4455` to verify authentication and check active recording status (`requests.GetRecordStatus()`).

### Step 2: CS2 NetCon Controller (`src/cs2_controller.py`)

Counter-Strike 2 supports a local TCP console interface when launched with the flag `-netconport 2121`. Python establishes a socket connection to `localhost:2121` to execute game commands and automate playback in real time.

We implemented the `CS2NetCon` class inside `src/cs2_controller.py` with the following core capabilities:

#### 1. Process Management & Automatic Game Launching
* **`is_cs2_running()`**: Checks `psutil` process list to see if `cs2.exe` is currently running.
* **`launch_cs2_if_needed(wait_seconds=15)`**: If CS2 is not open, automatically launches it using the Steam protocol (`steam://run/730//-netconport 2121`) and waits for the game engine TCP port to open.

#### 2. Socket Connection & Command Execution
* **`connect(max_retries=5, retry_delay=2.0)`**: Opens `socket.SOCK_STREAM` to `127.0.0.1:2121` with retry logic.
* **`disconnect()`**: Cleanly closes the TCP socket when recording finishes.
* **`send_command(command, read_response=False)`**: Sends raw UTF-8 encoded console commands (`command + "\n"`).

#### 3. Demo Playback & Navigation API
* **`play_demo(demo_path)`**: Converts absolute paths to forward slashes and sends `playdemo "<path>"`.
* **`goto_tick(tick, relative=False)`**: Teleports demo playback to exact ticks via `demo_goto <tick>`.
* **`pause_demo()` / `resume_demo()`**: Controls play/pause states (`demo_pause`, `demo_resume`).
* **`set_timescale(scale=1.0)`**: Sets `demo_timescale <scale>` (`1.0` for real-time video capture, `10.0` for fast-forward).

#### 4. Cinematic UI & HUD Configuration (`setup_cinematic_hud`)
To ensure clean, esports-grade video highlights without visual clutter, `setup_cinematic_hud(player_name)` sends the following exact command sequence right before recording starts:

```python
commands = [
    "sv_cheats 1",                   # Required for offline demo UI adjustments
    "cl_draw_only_deathnotices 1",   # Hides radar, inventory, health bars; keeps ONLY top-right killfeed
    "spec_show_xray 0",              # Disables X-Ray wallhacks for an authentic live-gameplay feel
    "r_show_demo_ui 0",              # Hides the bottom demo scrubber menu bar (Shift + F2 UI)
    "demo_timescale 1.0",            # Guarantees exact 1.0x playback speed
]
if player_name:
    commands.append("spec_mode 1")                         # Locks to 1st-person camera
    commands.append(f'spec_player_by_name "{player_name}"') # Locks view directly to target player
```
* **`restore_normal_hud()`**: Sends `cl_draw_only_deathnotices 0`, `spec_show_xray 1`, `r_show_demo_ui 1` to restore standard spectator UI once recording concludes.

### Step 3: OBS Studio Controller (`src/obs_controller.py`)

To control video recording precisely when CS2 demo playback reaches a highlight interval, we built the `OBSController` class wrapping the `obswebsocket` WebSocket v5 API (`localhost:4455`).

#### Core Methods & Capabilities:
* **`connect(max_retries=3)`**: Connects via WebSocket to OBS Studio and retrieves version info (`requests.GetVersion()`).
* **`get_record_status()`**: Calls `requests.GetRecordStatus()` to check `{"is_recording": bool, "is_paused": bool, "timecode": str}`.
* **`get_record_directory()`**: Calls `requests.GetRecordDirectory()` to find the absolute path where OBS saves video output (e.g., `C:\Users\snoop\Videos`).
* **`start_recording()`**: Sends `requests.StartRecord()` and verifies that `output_active` becomes `True`.
* **`stop_recording(wait_for_file_flush=True, timeout=10.0)`**:
  Commands OBS to `StopRecord()`. If `wait_for_file_flush` is enabled, polls OBS status until `output_active` turns `False` and allows a 1-second filesystem release window. This prevents `PermissionError` when moving or renaming the file immediately after recording stops.
* **`find_latest_recording(extensions=('mp4', 'mkv', 'mov'))`**: Scans `get_record_directory()` using `glob` and `os.path.getmtime` to automatically locate the exact `.mp4` video file just produced by OBS Studio so the automated loop can rename it cleanly.

### Step 4: Master Automated Loop (`src/autocapture_engine.py`)

To synchronize Counter-Strike 2 demo playback (`CS2NetCon` on port 2121) and OBS Studio screen capture (`OBSController` on port 4455) into a single, fully automated pipeline, we built the `AutoCaptureEngine` class inside `src/autocapture_engine.py`.

#### Core Methods & Lifecycle:
* **`connect_all(launch_cs2_if_closed=True)`**: Connects to both OBS WebSocket and CS2 NetCon TCP. If `launch_cs2_if_closed` is active and `cs2.exe` is closed, automatically boots the game via Steam and waits for the socket to accept connections.
* **`disconnect_all()`**: Safely closes both controller connections upon batch completion.
* **`capture_highlight(demo_path, candidate, match_title, clip_index, warmup_ticks=64, cooldown_ticks=128)`**:
  Executes the precise, synchronized recording workflow for a single candidate highlight (supports both `CandidateMoment` dataclasses and dictionaries):
  1. **Demo Load Check**: If `demo_path` differs from `current_loaded_demo`, issues `playdemo "<path>"` and allows a 6-second Source 2 entity loading window.
  2. **Warmup Teleport**: Calculates `actual_start = max(0, start_tick - warmup_ticks)` (default 1.0s buffer) to ensure models and textures are rendered before recording. Issues `demo_goto <actual_start>` and `demo_pause`.
  3. **Cinematic HUD**: Invokes `setup_cinematic_hud(player_name)` (`cl_draw_only_deathnotices 1`, `spec_show_xray 0`, 1st-person camera lock).
  4. **Camera Trigger**: Issues `self.obs.start_recording()`.
  5. **Playback**: Issues `self.cs2.resume_demo()` at normal 1.0x speed and sleeps for exact clip duration $D = (actual\_end - actual\_start) / 64.0$.
  6. **Finalize & Sanitize**: Pauses CS2, issues `self.obs.stop_recording(wait_for_file_flush=True)`, locates the freshly generated raw clip via `find_latest_recording()`, and renames/moves it to `clips/{match_title}_Clip_{index:02d}_{safe_description}.mp4` (handling file collisions automatically by appending UNIX timestamps).
* **`capture_playlist(demo_path, candidates, match_title, progress_callback=None)`**:
  Iterates over a ranked list of candidate moments (`Layer 3 / 4`), capturing each highlight sequentially. Triggers `progress_callback(idx, total, clip_path)` after each clip for real-time frontend dashboard progress bars (`Layer 6`), and guarantees `restore_normal_hud()` is called upon batch conclusion.

---

## 4. Mode 2: Manual Recording & FFmpeg Slicing (`src/clipper.py` - Step 5)

For users who have an existing match recording (`match.mp4`) generated manually via NVIDIA GeForce Shadowplay, Medal, or OBS Studio, Layer 5 provides `src/clipper.py` to extract highlights without re-launching CS2.

### Step 5 Implementation Classes:

#### 1. `TickToTimeConverter`
Translates CS2 demo ticks (`start_tick`, `end_tick`) into exact video timestamps in seconds (`start_sec`, `end_sec`) using Round 1 anchor calibration:
* **`__init__(round_1_start_tick, round_1_video_time_sec, tick_rate=64.0)`**: Calculates the tick offset $T_{\text{offset}} = T_{\text{round\_1\_start}} - \text{int}(V_{\text{round\_1\_start}} \times 64.0)$.
* **`tick_to_seconds(tick)`**: Converts any game tick $T$ into video timestamp $V = \max(0, \frac{T - T_{\text{offset}}}{64.0})$.
* **`moment_to_video_range(start_tick, end_tick, warmup_sec=1.5, cooldown_sec=2.0)`**: Returns padded `(start_sec, end_sec)` window adjusted for video lead-in and clutch aftermath.

#### 2. `slice_clip_ffmpeg(video_path, start_sec, end_sec, output_path, use_stream_copy=True)`
Extracts a video slice via subprocess `ffmpeg`:
* **Stream Copying (`-c copy`)**: Executes `ffmpeg -y -ss [start] -to [end] -i [video] -c copy [output]`. Cuts a 30-second 1080p/4K clip in **under 0.5 seconds** with **zero quality loss** and minimal CPU overhead.
* **Automatic Fallback (`-c:v libx264 -preset veryfast`)**: If stream copying fails due to non-keyframe alignment or corrupted timestamps (`returncode != 0`), automatically falls back to high-speed re-encoding (`-crf 22`).

#### 3. `ClipperQueue`
Asynchronous background worker queue (`threading.Thread` + `queue.Queue`) designed for high-throughput batch slicing in the Layer 6 web dashboard:
* **Non-Blocking UI Integration**: When `start_playlist_slicing()` is called with 10–15 candidate highlights, all extraction tasks are pushed to a dedicated daemon worker loop (`_worker_loop`).
* **Real-Time Progress Tracking**: Invokes `progress_callback(completed, total, clip_path)` upon each completion and exposes `get_status()` (`is_busy`, `current_clip`, `saved_paths`, `errors`) so the frontend can display live progress bars while allowing the user to browse stats or watch finished clips simultaneously.

---

## 5. Summary of Implemented Layer 5 Files

| File | Status | Purpose | Key Dependencies |
| :--- | :---: | :--- | :--- |
| `test_obs_connection.py` | ✅ **Complete** | Verification script for OBS WebSocket connectivity and authentication. | `obswebsocket`, `psutil` |
| `src/cs2_controller.py` | ✅ **Complete** | TCP socket client for CS2 NetCon (`port 2121`) + cinematic HUD commands. | `socket`, `time` |
| `src/obs_controller.py` | ✅ **Complete** | OBS Studio controller for starting/stopping recordings and checking paths. | `obswebsocket` |
| `src/autocapture_engine.py` | ✅ **Complete** | Master coordinator loop automating CS2 playback and OBS capture. | `CS2NetCon`, `OBSController` |
| `src/clipper.py` | ✅ **Complete** | FFmpeg stream-copy clipper and asynchronous background task queue. | `subprocess`, `threading`, `queue` |
| `test_layer_5.py` | ✅ **Complete** | Comprehensive unit test suite verifying anchor calibration, duck-typing, and queue lifecycle. | `unittest` |
