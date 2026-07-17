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

#### 1. Process Management & Auto-VAC Shield (`src/steam_config_manager.py`)
To prevent VAC risks from permanently modifying Steam's global `LaunchOptions` while ensuring reliable automation, Layer 5 uses a **Method 3 Hybrid Auto-VAC Shield**:
* **Direct Binary Discovery (`cs2.exe`)**: `SteamConfigManager` queries the Windows Registry and parses `libraryfolders.vdf` across all hard drives (`C:\`, `D:\`, `E:\`) to locate `cs2.exe`. Spawns `cs2.exe -insecure -console -netconport 2121 -steam` directly via `subprocess.Popen`, completely avoiding persistent modifications to Steam's launch options box.
* **Automatic `localconfig.vdf` Scrubbing (`clean_cs2_launch_options`)**: Whenever `CS2NetCon` disconnects or an application exits, `SteamConfigManager` automatically scans `userdata/<ID>/config/localconfig.vdf` and strips out any `-insecure`, `-console`, or `-netconport` flags while preserving user performance options (`-novid -high`).

#### 2. Socket Connection & Command Execution (`src/cs2_controller.py`)
* **`connect(max_retries=5, retry_delay=2.0)`**: Opens `socket.SOCK_STREAM` to `127.0.0.1:2121` with retry logic.
* **`disconnect()`**: Cleanly closes the TCP socket and triggers VDF launch option scrubbing.
* **`send_command(command, read_response=False)`**: Sends raw UTF-8 encoded console commands (`command + "\n"`), handling socket shutdown errors gracefully without raising tracebacks.

#### 3. Demo Playback & Navigation API
* **`play_demo(demo_path)`**: Converts absolute paths to forward slashes and sends `playdemo "<path>"`.
* **`goto_tick(tick, relative=False)`**: Teleports demo playback to exact ticks via `demo_goto <tick>`.
* **`pause_demo()` / `resume_demo()`**: Controls play/pause states (`demo_pause`, `demo_resume`).
* **`set_timescale(scale=1.0)`**: Sets `demo_timescale <scale>` (`1.0` for real-time video capture, `10.0` for fast-forward).

#### 4. Cinematic UI & Continuous Demo UI Scrubber Suppression (`setup_cinematic_hud` & `suppress_demo_ui`)
To ensure clean, esports-grade video highlights without visual clutter, `setup_cinematic_hud(player_name)` sends the following exact command sequence right before recording starts:

```python
commands = [
    "sv_cheats 1",                   # Required for offline demo UI adjustments
    "cl_draw_only_deathnotices 0",   # Keeps player profile, ammo, health, weapon & avatars VISIBLE
    "cl_drawhud 1",                  # Ensures HUD panels are enabled
    "spec_show_xray 0",              # Disables X-Ray wallhacks for an authentic live-gameplay feel
    "demo_timescale 1.0",            # Guarantees exact 1.0x playback speed
]
```
* **`suppress_demo_ui()`**: Counter-Strike 2's Panorama UI occasionally re-displays the bottom brown demo timeline scrubber bar (`Replay UI`) when teleports or kills trigger spectator updates. `suppress_demo_ui()` sends the complete battery of closing commands (`demoui_close`, `demoui false`, `demoui 0`, `demo_ui_mode 0`, `r_show_demo_ui 0`, `cl_spec_show_bindings 0`).
* **`lock_camera_to_player(player_name)`**: Pulses `spec_player` across 6 iterations while invoking `suppress_demo_ui()` on every pulse to ensure exact POV lock without opening the replay timeline.
* **`restore_normal_hud()`**: Sends `cl_draw_only_deathnotices 0`, `spec_show_xray 1`, `r_show_demo_ui 1` to restore standard spectator UI once recording concludes.

### Step 3: OBS Studio Controller (`src/obs_controller.py`)

To control video recording precisely when CS2 demo playback reaches a highlight interval, we built the `OBSController` class wrapping the `obswebsocket` WebSocket v5 API (`localhost:4455`).

#### Core Methods & Capabilities:
* **`connect(max_retries=3)`**: Connects via WebSocket to OBS Studio and retrieves version info (`requests.GetVersion()`).
* **`set_1080p_60fps()`**: Programmatically forces OBS base and output resolution to `1920x1080` at `60 FPS`.
* **`disable_mouse_cursor_capture()`**: Right before recording starts, scans all inputs inside your OBS Studio scene (`Game Capture`, `Display Capture`, `Window Capture`) via WebSocket (`SetInputSettings`) and sets `capture_cursor = False`. Your Windows mouse pointer will never accidentally appear or ruin a recorded highlight clip!
* **`get_record_status()` / `get_record_directory()`**: Checks active recording states and retrieves video output folders.
* **`start_recording()` / `stop_recording()`**: Controls OBS video capture, polling `output_active` with a file-flush buffer window to prevent `PermissionError` when moving files.
* **`find_latest_recording()`**: Automatically locates the exact `.mp4` video file just produced by OBS Studio.

### Step 4: Master Automated Loop (`src/autocapture_engine.py`)

To synchronize Counter-Strike 2 demo playback (`CS2NetCon` on port 2121) and OBS Studio screen capture (`OBSController` on port 4455) into a single, fully automated pipeline, we built the `AutoCaptureEngine` class inside `src/autocapture_engine.py`.

#### Core Methods & Lifecycle:
* **`connect_all(launch_cs2_if_closed=True)`**: Connects to both OBS WebSocket and CS2 NetCon TCP. If `cs2.exe` is closed, spawns the game directly via `SteamConfigManager` (`cs2.exe -insecure -console -netconport 2121 -steam`).
* **`disconnect_all()`**: Safely closes both controller connections upon batch completion and triggers `localconfig.vdf` launch option scrubbing.
* **`capture_highlight(...)`**:
  Executes the precise, synchronized recording workflow for a single candidate highlight:
  1. **Demo Load Check**: Issues `playdemo "<path>"` and allows a Source 2 entity loading window.
  2. **Warmup Teleport (`10-Second Lead-In`)**: Issues `demo_goto <actual_start>` where `actual_start` is calculated `640 ticks` (`10.0 full seconds`) ahead of the first kill, ensuring clean movement and engagement buildup before any fighting begins.
  3. **Dynamic Resolution & Zero Black Bars (`GetClientRect + OBS_BOUNDS_STRETCH`)**: Focuses Counter-Strike 2, queries its exact running viewport width and height (`cs2_w x cs2_h`), dynamically sets OBS canvas/output dimensions to match natively (`whether 4:3 or 16:9`), and enforces `OBS_BOUNDS_STRETCH` so the game capture fills 100% of the screen from edge to edge with **zero black bars**.
  4. **Pre-UI Player Lock & Camera Settling**: Finds and locks the camera onto the target player (`spec_player "<player>"`) right while the demo UI is still active, waiting `1.2 seconds` for the 1st-person POV camera to settle cleanly onto the target.
  5. **UI Suppression & Camera Trigger**: Executes `suppress_demo_ui()` (`cl_draw_only_deathnotices 1`, `spec_show_xray 0`, `demoui`) right before triggering `self.obs.start_recording()`.
  6. **Finalize & Sanitize**: Rolls the camera cleanly for the engagement duration, stops recording, and moves the clip to `clips/{safe_description}.mp4`.
* **`capture_playlist(...)`**: Iterates over a ranked list of candidate moments, reporting real-time progress to callbacks while ensuring graceful HUD cleanup and VAC scrubbing upon completion.

---

## 4. Mode 2: Manual Recording & FFmpeg Slicing (`src/clipper.py` - Step 5)

For users who have an existing match recording (`match.mp4`) generated manually via NVIDIA GeForce Shadowplay, Medal, or OBS Studio, Layer 5 provides `src/clipper.py` to extract highlights without re-launching CS2.

### Step 5 Implementation Classes:

#### 1. `TickToTimeConverter`
Translates CS2 demo ticks (`start_tick`, `end_tick`) into exact video timestamps in seconds (`start_sec`, `end_sec`) using Round 1 anchor calibration:
* **`__init__(round_1_start_tick, round_1_video_time_sec, tick_rate=64.0)`**: Calculates the tick offset $T_{\text{offset}} = T_{\text{round\_1\_start}} - \text{int}(V_{\text{round\_1\_start}} \times 64.0)$.
* **`tick_to_seconds(tick)`**: Converts any game tick $T$ into video timestamp $V = \max(0, \frac{T - T_{\text{offset}}}{64.0})$.
* **`moment_to_video_range(...)`**: Returns padded `(start_sec, end_sec)` window adjusted for video lead-in and clutch aftermath.

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
| `test_obs_connection.py` | ✅ **Complete** | Verification script for OBS WebSocket connectivity and authentication. | `obs-websocket-py`, `psutil` |
| `src/steam_config_manager.py` | ✅ **Complete** | Method 3 Auto-VAC Shield: direct `cs2.exe` boot + `localconfig.vdf` scrubbing. | `subprocess`, `psutil`, `winreg` |
| `src/cs2_controller.py` | ✅ **Complete** | TCP socket client for CS2 NetCon (`port 2121`), POV lock, and `suppress_demo_ui()`. | `socket`, `time` |
| `src/obs_controller.py` | ✅ **Complete** | OBS Studio controller for 1080p60 recording and mouse cursor suppression. | `obs-websocket-py` |
| `src/autocapture_engine.py` | ✅ **Complete** | Master coordinator loop automating CS2 playback and active HUD maintenance loop. | `CS2NetCon`, `OBSController` |
| `src/clipper.py` | ✅ **Complete** | FFmpeg stream-copy clipper and asynchronous background task queue. | `subprocess`, `threading`, `queue` |
| `test_steam_config_manager.py` | ✅ **Complete** | Unit test suite verifying VDF scrubbing and cs2.exe binary discovery. | `unittest` |
| `test_layer_5.py` | ✅ **Complete** | Comprehensive unit test suite verifying anchor calibration, duck-typing, and queue lifecycle. | `unittest` |

---

## 6. Clean HUD Setup (`cl_draw_only_deathnotices 0`) & Telemetry/TrueView Suppression

To ensure broadcast-grade recordings with clear player information (`Player Health, Armor, Ammo, Equipped Weapon, and Killfeed`) while suppressing unwanted engine telemetry overlays, Layer 5 enforces the following precise sequence in `src/cs2_controller.py` and `src/autocapture_engine.py` during pre-record setup:

### 1. Enabling Full Player HUD
Instead of stripping the entire UI (`cl_draw_only_deathnotices 1`), the engine explicitly sets:
* **`cl_draw_only_deathnotices 0`**: Keeps bottom-left Health/Armor bar, bottom-right Weapon (`Autumn` / Glock / AK-47) and Ammo panels, plus top-right Killfeed active during recording.
* **`cl_drawhud 1`**: Guarantees core viewport HUD rendering is enabled.

### 2. Disabling Top-Right Telemetry & Replay Overlays
To eliminate text overlays (`Max 9.4ms | Avg 177FPS`, `TrueView Disabled - old demo`), the following commands are dispatched via NetCon before rolling camera:
```c
cl_showfps 0                                    // Hides traditional frame rate counter
cq_netgraph 0                                   // Hides Source 2 network graph
cl_hud_telemetry_frametime_show 0               // Hides frame timing telemetry
cl_hud_telemetry_ping_show 0                    // Hides latency/ping overlay
cl_hud_telemetry_net_misdelivery_show 0         // Hides packet loss telemetry
cl_hud_telemetry_serverrecvmargin_graph_show 0  // Hides server margin graph
spec_show_trueview 0                            // Hides spectator TrueView / demo info overlay
tv_nochat 1                                     // Hides spectator chat overlays
cl_spec_show_bindings 0                         // Hides binding shortcut hints
r_show_demo_ui 0                                // Hides bottom demo timeline bar
demo_ui_mode 0
```
