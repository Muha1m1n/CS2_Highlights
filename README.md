# 🎬 ClipperCS2: Autonomous Counter-Strike 2 Highlight Detection & Recording Engine

**ClipperCS2** is an end-to-end, esports-grade automated highlight detection, machine-learning scoring, and synchronized video clipping suite for **Counter-Strike 2**. It ingests raw `.dem` replay files, extracts high-dimensional gameplay telemetry, ranks moments using custom algorithms, and automatically records broadcast-quality `1080p60` MP4 video clips without human intervention.

---

## 🌟 Key Features & Architecture Highlights

*   **🛡️ Auto-VAC Shield (`Method 3 Hybrid`)**:
    *   **Direct Binary Execution (`cs2.exe`)**: Scours Windows Registry and Steam's `libraryfolders.vdf` across all installed hard drives (`C:\`, `D:\`, `E:\`) to locate your `cs2.exe` installation. Spawns `cs2.exe -insecure -console -netconport 2121 -steam` directly via `subprocess.Popen`, completely avoiding persistent modifications to Steam's `LaunchOptions` box.
    *   **Automatic `localconfig.vdf` Scrubbing**: Whenever `CS2NetCon` disconnects or your batch finishes, `SteamConfigManager` automatically cleans Steam's `userdata/<ID>/config/localconfig.vdf`, stripping out any `-insecure -console -netconport` flags while keeping your personal performance settings (`-novid -high`) untouched. You can jump right into official Valve VAC-secured matchmaking right after clipping with zero manual effort!
*   **🖱️ Automatic Mouse Cursor Suppression (`OBSController`)**:
    *   Before rolling camera, `OBSController` queries your live **OBS Studio v5** scene and automatically applies `capture_cursor = False` across all sources (`Game Capture`, `Display Capture`, `Window Capture`). Your Windows mouse pointer will never accidentally appear or ruin a recorded highlight clip!
*   **🚫 Continuous Demo UI Scrubber Suppression (`CS2NetCon` & `AutoCaptureEngine`)**:
    *   Counter-Strike 2's Panorama UI occasionally refreshes its spectator menus mid-clip when kills happen or ticks jump, popping up the bottom brown replay timeline bar. Our active maintenance loop runs every **1.5 seconds** during recording to continuously invoke `suppress_demo_ui()` (`demoui_close`, `demoui false`, `demoui 0`, `demo_ui_mode 0`, `r_show_demo_ui 0`, `cl_spec_show_bindings 0`), keeping the timeline scrubber permanently shut while preserving the top-right killfeed and player profile (`cl_draw_only_deathnotices 0`, `cl_drawhud 1`).
*   **🎥 Dual-Mode Video Clipping Pipeline**:
    *   **Mode 1 (Hands-Free OBS + CS2 NetCon Automation)**: Python controls both CS2 (`TCP 2121`) and OBS Studio (`WebSocket 4455`). Replays the exact highlight ticks at `1.0x` speed while OBS captures the screen at `1080p @ 60 FPS`. Produces ~400 MB of pristine highlight clips per match (saving ~95% disk space vs recording full games).
    *   **Mode 2 (Manual Recording & FFmpeg Stream-Copy Slicing)**: For players who already record full games via Shadowplay or OBS while playing. Uses Round 1 anchor calibration formulas to slice clips via `ffmpeg -c copy` in **under 0.5 seconds** with **zero re-encoding or quality loss**.

---

## 🏗️ System Architecture (The 6 Layers)

```
[ .DEM Replay File ] 
        │
        ▼
Layer 1: Binary Parser (`src/parser.py` via `demoparser2`)
        │  extracts player deaths, round boundaries, bomb events, weapon vectors
        ▼
Layer 2: Feature Engineering & Database Cache (`src/database.py`)
        │  builds SQLite schema (`data/processed/cs2_highlights.db`), computes killstreaks & clutch states
        ▼
Layer 3: Machine Learning Scorer & Candidate Ranking (`src/scorer.py`)
        │  ranks moments via multi-factor heuristic/ML scoring (multi-kills, noscope, wallbang, clutches)
        ▼
Layer 4: Match Narrative & Climax Analyzer (`src/narrative.py`)
        │  identifies momentum shifts, eco-breaks, round-15 climaxes, and match turning points
        ▼
Layer 5: Syncing, Auto-VAC Shield & Video Clipper (`src/autocapture_engine.py`, `src/cs2_controller.py`, `src/obs_controller.py`)
        │  orchestrates CS2 NetCon TCP (2121) + OBS Studio WebSocket (4455) for automated 1080p60 recording
        ▼
Layer 6: Interactive Web Dashboard (`src/web_server.py`)
           provides real-time progress bars, WebSocket status updates, and interactive HTML playback cards
```

---

## 📁 Repository Layout

```
ClipperCS2/
├── data/
│   ├── raw/                 # Raw match videos (.mp4) and demos (.dem)
│   └── processed/           # SQLite database cache (`cs2_highlights.db`) and parsing logs
├── clips/                   # Output directory for finished 1080p60 MP4 highlights (`.gitignore`d)
├── src/
│   ├── parser.py            # Layer 1: Rust-backed demoparser2 wrapper & event standardization
│   ├── database.py          # Layer 2: SQLite schema, match indexing, and event caching
│   ├── scorer.py            # Layer 3: Multi-factor highlight scoring & ranking logic
│   ├── narrative.py         # Layer 4: Match narrative context and climax detection
│   ├── steam_config_manager.py # Layer 5: Method 3 Auto-VAC Shield (direct binary boot + VDF scrubbing)
│   ├── cs2_controller.py    # Layer 5: CS2 NetCon TCP (port 2121) command interface & HUD cleanup
│   ├── obs_controller.py    # Layer 5: OBS Studio WebSocket (port 4455) controller & cursor suppression
│   ├── autocapture_engine.py # Layer 5: Master orchestration loop connecting CS2 and OBS
│   └── clipper.py           # Layer 5: FFmpeg stream-copy video slicer & async worker queue
├── Documentation/
│   ├── layer_1.md           # Technical specs for Layer 1 parser and round-pairing algorithms
│   ├── layer_2.md           # Technical specs for Layer 2 SQLite database and feature extraction
│   ├── layer_3.md           # Technical specs for Layer 3 machine learning scorer & candidate filters
│   ├── layer_4.md           # Technical specs for Layer 4 narrative context analyzer
│   └── layer_5.md           # Technical specs for Layer 5 Auto-VAC Shield, NetCon, OBS, and FFmpeg
├── test_steam_config_manager.py # Unit test suite verifying VDF scrubbing and cs2.exe discovery
├── test_layer_5.py          # Unit test suite verifying ClipperQueue, math offsets, and duck-typing
└── requirements.txt         # Python project dependencies (`demoparser2`, `obswebsocket`, `psutil`)
```

---

## 🚀 Quickstart Guide

### 1. Requirements
* **Operating System**: Windows 10 / 11 (64-bit)
* **Python**: Python 3.10+ (`uv` or `pip` recommended)
* **Counter-Strike 2**: Installed via Steam (`cs2.exe`)
* **OBS Studio**: Version 28.0+ (`WebSocket v5` enabled on port `4455`)

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/yourusername/ClipperCS2.git
cd ClipperCS2

# Install dependencies
pip install -r requirements.txt
```

### 3. Running Automated Highlight Capture (Mode 1)
Make sure OBS Studio is open in the background (with `Desktop Audio` or `Game Capture` configured). You do **not** need to manually launch CS2 or configure `-insecure` launch options; **ClipperCS2 handles it automatically**:

```powershell
# Capture the #1 highest scoring highlight for player "log1c" from a demo file
python -m src.autocapture_engine --demo "C:\Path\To\Match.dem" --player "log1c" --top 1
```

**What Happens Behind the Scenes**:
1. `SteamConfigManager` discovers `cs2.exe` and launches it cleanly with `-insecure -console -netconport 2121 -steam`.
2. `AutoCaptureEngine` connects to CS2 NetCon (`localhost:2121`) and OBS WebSocket (`localhost:4455`).
3. `OBSController` enforces `1080p @ 60 FPS` and sets `capture_cursor = False` across all scene capture sources.
4. CS2 teleports (`demo_goto`) to the highlight tick with a `1.0s` warmup buffer and pauses.
5. `setup_cinematic_hud()` locks camera to your exact 1st-person POV (`spec_player "log1c"`), disables X-Ray wallhacks (`spec_show_xray 0`), and enables your player profile (`cl_draw_only_deathnotices 0`).
6. OBS starts recording while CS2 resumes playback (`demo_resume`) at `1.0x` speed.
7. During the exact duration of the highlight, our active maintenance loop pulses every `1.5 seconds`, sending `demoui_close` and `demoui false` to guarantee the replay scrubber never pops open.
8. OBS stops recording, pauses CS2, and moves the finished `1080p60` MP4 directly into the `clips/` directory.
9. Upon completion, `SteamConfigManager().clean_cs2_launch_options()` scrubs `localconfig.vdf` so your CS2 installation is instantly ready for VAC-secured competitive matchmaking!

---

## 🧪 Testing & Verification
All unit tests are completely self-contained and run in under `0.05 seconds`:
```powershell
# Verify Auto-VAC Shield and localconfig.vdf scrubbing
python test_steam_config_manager.py

# Verify Layer 5 queue math, duck-typing, and anchor synchronization
python test_layer_5.py
```

---

## 📄 License & Contributing
ClipperCS2 is built for educational and personal esports analysis. Pull requests and feature suggestions for custom scoring models or overlay components (`Layer 6`) are welcome!
