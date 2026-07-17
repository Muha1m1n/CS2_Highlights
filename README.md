# 🎬 ClipperCS2: Autonomous Counter-Strike 2 Highlight Detection & Recording Engine

**ClipperCS2** is an end-to-end, esports-grade automated highlight detection, machine-learning scoring, and synchronized video clipping suite for **Counter-Strike 2**. It ingests raw `.dem` replay files, extracts high-dimensional gameplay telemetry, ranks moments using custom algorithms, and automatically records broadcast-quality `1080p60` MP4 video clips without human intervention.

---

## 🌟 Key Features & Architecture Highlights

*   **🛡️ Auto-VAC Shield (`Method 3 Hybrid`)**:
    *   **Direct Binary Execution (`cs2.exe`)**: Scours Windows Registry and Steam's `libraryfolders.vdf` across all installed hard drives (`C:\`, `D:\`, `E:\`) to locate your `cs2.exe` installation. Spawns `cs2.exe -insecure -console -netconport 2121 -steam` directly via `subprocess.Popen`, completely avoiding persistent modifications to Steam's `LaunchOptions` box.
    *   **Automatic `localconfig.vdf` Scrubbing**: Whenever `CS2NetCon` disconnects or your batch finishes, `SteamConfigManager` automatically cleans Steam's `userdata/<ID>/config/localconfig.vdf`, stripping out any `-insecure -console -netconport` flags while keeping your personal performance settings (`-novid -high`) untouched. You can jump right into official Valve VAC-secured matchmaking right after clipping with zero manual effort!
*   **🖱️ Automatic Mouse Cursor Suppression (`OBSController`)**:
    *   Before rolling camera, `OBSController` queries your live **OBS Studio v5** scene and automatically applies `capture_cursor = False` across all sources (`Game Capture`, `Display Capture`, `Window Capture`). Your Windows mouse pointer will never accidentally appear or ruin a recorded highlight clip!
*   **🖥️ Dynamic Resolution & Aspect Ratio Tracking (`CS2NetCon` & `OBSController`)**:
    *   Uses Win32 `GetClientRect` to query the exact active viewport dimensions (`cs2_w x cs2_h`) of Counter-Strike 2 (`whether 4:3 1280x960, 16:9 1920x1080, or custom windowed modes`). Dynamically sets OBS canvas/output dimensions and enforces `OBS_BOUNDS_STRETCH` to guarantee 100% full-screen edge-to-edge video output with **ZERO black bars (`pillarboxing/letterboxing`)**.
*   **🎯 Pre-Fight Lead-in & Pre-UI Player Locking (`AutoCaptureEngine`)**:
    *   Teleports `10.0 full seconds` (`640 ticks`) before the first kill occurs so the clip captures clean engagement setup. Finds and locks onto the desired player (`spec_player`) FIRST right while the demo UI is still active, waiting `1.2 seconds` for the 1st-person POV camera to settle cleanly onto the player before executing UI suppression (`cl_draw_only_deathnotices 1`, `spec_show_xray 0`, `demoui`).
*   **🎥 Dual-Mode Video Clipping Pipeline**:
    *   **Mode 1 (Hands-Free OBS + CS2 NetCon Automation)**: Python controls both CS2 (`TCP 2121`) and OBS Studio (`WebSocket 4455`). Replays exact highlight ticks with full native resolution tracking at `60 FPS`. Produces ~400 MB of pristine highlight clips per match.
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
Layer 6: Interactive Local Desktop App & SPA Dashboard (`src/desktop_app.py`, `src/web_server.py`)
           provides standalone native OS window (`PyWebView`), dynamic port discovery (`get_free_port`), per-clip Side/Outcome badges, and double-click launchers (`.bat` / `.vbs`)
```

---

## 📁 Repository Layout

```
ClipperCS2/
├── data/
│   ├── raw/                 # Raw match videos (.mp4) and demos (.dem)
│   └── processed/           # SQLite database cache (`cs2_highlights.db`) and parsing logs
├── clips/                   # Output directory for finished 1080p60 MP4 highlights (`.gitignore`d)
├── Launch_ClipperCS2.bat    # Standalone double-click Windows batch launcher
├── Launch_ClipperCS2_Silent.vbs # Zero-terminal silent double-click launcher
├── src/
│   ├── parser.py            # Layer 1: Rust-backed demoparser2 wrapper & event standardization
│   ├── database.py          # Layer 2: SQLite schema, match indexing, and event caching
│   ├── scorer.py            # Layer 3: Multi-factor highlight scoring & ranking logic
│   ├── narrative.py         # Layer 4: Match narrative context and climax detection
│   ├── steam_config_manager.py # Layer 5: Method 3 Auto-VAC Shield (direct binary boot + VDF scrubbing)
│   ├── cs2_controller.py    # Layer 5: CS2 NetCon TCP (port 2121) command interface & HUD cleanup
│   ├── obs_controller.py    # Layer 5: OBS Studio WebSocket (port 4455) controller & cursor suppression
│   ├── autocapture_engine.py # Layer 5: Master orchestration loop connecting CS2 and OBS
│   ├── clipper.py           # Layer 5: FFmpeg stream-copy video slicer & async worker queue
│   ├── desktop_app.py       # Layer 6: PyWebView native desktop window container & port auto-discovery
│   ├── web_server.py        # Layer 6: FastAPI server handling demo scanning and per-clip badge data
│   └── static/              # Layer 6: Dark-mode SPA (`index.html`, `style.css`, `app.js`)
├── Documentation/
│   ├── layer_1.md           # Technical specs for Layer 1 parser and round-pairing algorithms
│   ├── layer_2.md           # Technical specs for Layer 2 SQLite database and feature extraction
│   ├── layer_3.md           # Technical specs for Layer 3 machine learning scorer & candidate filters
│   ├── layer_4.md           # Technical specs for Layer 4 narrative context analyzer
│   ├── layer_5.md           # Technical specs for Layer 5 Auto-VAC Shield, NetCon, OBS, and FFmpeg
│   └── layer_6.md           # Technical specs for Layer 6 Native Desktop Application & SPA Dashboard
├── test_steam_config_manager.py # Unit test suite verifying VDF scrubbing and cs2.exe discovery
├── test_layer_5.py          # Unit test suite verifying ClipperQueue, math offsets, and duck-typing
└── requirements.txt         # Python project dependencies (`demoparser2`, `obs-websocket-py`, `psutil`, `pywebview`)
```

---

## 🚀 Quickstart Guide

### 1. Requirements
* **Operating System**: Windows 10 / 11 (64-bit)
* **Python**: Python 3.10+ (`uv` or `pip` recommended)
* **Counter-Strike 2**: Installed via Steam (`cs2.exe`)
* **OBS Studio**: Version 28.0+ (`WebSocket v5` enabled on port `4455`)

### 2. Installation & Quickstart (1-Click Setup)

#### Method A: 1-Click All-in-One Installer & Launcher (Recommended for New Users)
Simply double-click **`Install_and_Run.bat`** directly inside the `ClipperCS2` folder!
* **Checks Python**: Automatically detects if Python 3.10+ is installed (`if not, opens the official installer directly`).
* **Creates Virtual Environment**: Automatically creates a clean `.venv` directory and installs all dependencies (`demoparser2`, `pywebview`, `fastapi`, `obswebsocket`).
* **Creates Desktop Shortcut**: Automatically places a `ClipperCS2` shortcut icon on your Windows Desktop pointing to `Launch_ClipperCS2_Silent.vbs`.
* **Launches App Immediately**: Boots the native desktop application right away (`and anytime later via the desktop icon or Launch_ClipperCS2_Silent.vbs`)!

#### Method B: Manual Command-Line Installation
```powershell
# Clone the repository
git clone https://github.com/yourusername/ClipperCS2.git
cd ClipperCS2

# Install dependencies
pip install -r requirements.txt

# Launch Desktop App
python -m src.desktop_app
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
