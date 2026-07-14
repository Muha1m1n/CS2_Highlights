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
Counter-Strike 2 supports a local TCP console interface when launched with the flag `-netconport 2121`. Python establishes a socket connection to `localhost:2121` to execute game commands in real time:
- `playdemo <path_to_demo>`: Loads the target `.dem` file.
- `demo_goto <tick>`: Teleports the demo engine to a specific tick.
- `demo_pause` / `demo_resume`: Controls playback flow.
- `demo_timescale 1.0`: Ensures normal `1.0x` speed during recording.

### Step 3: Cinematic UI Configuration
To ensure clean, esports-grade video highlights without visual clutter, Python sends the following console commands right before recording begins:

```bash
# 1. Hide radar, weapon inventory, health/ammo bars; keep ONLY top-right killfeed
cl_draw_only_deathnotices 1

# 2. Lock camera to First-Person View of the active highlight player
spec_mode 1
spec_player_by_name "<player_name>"

# 3. Disable X-Ray (wallhacks) for authentic live-gameplay feel
spec_show_xray 0

# 4. Hide the bottom demo scrubber menu (Shift + F2 UI)
r_show_demo_ui 0
```

### Step 4: Master Automated Loop (`src/autocapture_engine.py`)
When the user clicks *"Automated Capture"* for a playlist of highlights:
1. **Pre-roll Warmup**: Python sends `demo_goto <start_tick - 64>` (1 second prior) to allow textures and character models to fully render.
2. **Pause & Prep**: Sends `demo_pause` and applies the cinematic UI settings.
3. **Trigger Recording**: Tells OBS via WebSocket to `StartRecord`.
4. **Playback**: Sends `demo_goto <start_tick>` followed immediately by `demo_resume`.
5. **Sleep**: Python calculates exact clip duration $D = (end\_tick - start\_tick) / 64.0$ and sleeps for exactly $D$ seconds.
6. **Stop & Organize**: Tells OBS to `StopRecord`, pauses CS2, and renames the generated output video to `clips/Match_1_Highlight_1_Clutch_3v1.mp4`.

---

## 4. Mode 2: Manual Recording & FFmpeg Slicing (`src/clipper.py`)

For users who already have a full match video file (`match.mp4`), Layer 5 uses **FFmpeg** to extract clips.

### Stream Copying (`-c copy`)
Instead of re-encoding every frame (which is slow and CPU-intensive), the system uses stream copying when cutting:
```bash
ffmpeg -ss [start_seconds] -to [end_seconds] -i full_match.mp4 -c copy output_clip.mp4
```
* **Performance**: Slices a 20-second clip in under **0.5 seconds** with zero loss of quality.
* **Keyframe Alignment**: If a clip boundary does not land on an exact video keyframe, the engine automatically adjusts the lead-in buffer by $-1.5\text{s}$ to ensure clean cuts without video freezing.

### Asynchronous Background Queue
Slicing multiple clips sequentially in the web interface could block the main UI thread. 
- All FFmpeg slicing tasks are pushed to a background `queue.Queue` managed by a dedicated worker (`threading.Thread`).
- The frontend receives real-time progress updates (`Clipping highlight 3 of 10...`), allowing the user to continue browsing stats or watching completed clips while background work finishes.

---

## 5. Summary of Layer 5 Files to be Implemented

| File | Purpose | Key Dependencies |
| :--- | :--- | :--- |
| `test_obs_connection.py` | Verification script for OBS WebSocket connectivity and authentication. | `obswebsocket`, `psutil` |
| `src/cs2_controller.py` | TCP socket client for CS2 NetCon (`port 2121`) + cinematic HUD commands. | `socket`, `time` |
| `src/obs_controller.py` | OBS Studio controller for starting/stopping recordings and checking paths. | `obswebsocket` |
| `src/autocapture_engine.py` | Master coordinator loop automating CS2 playback and OBS capture. | `CS2NetCon`, `OBSController` |
| `src/clipper.py` | FFmpeg stream-copy clipper and asynchronous background task queue. | `subprocess`, `threading`, `queue` |
