# Layer 6: Interactive Local Desktop Application & Dashboard (`src/desktop_app.py` & `src/web_server.py`)

Layer 6 provides the user-facing local application experience for **ClipperCS2**. It packages the backend data engine (`FastAPI + SQLite`) and frontend Single Page Application (`SPA`) into a native Windows desktop window using `PyWebView`, complete with standalone double-click launchers (`Launch_ClipperCS2.bat` / `.vbs`) and dynamic port discovery.

---

## 1. Native Desktop Architecture (`src/desktop_app.py`)

To deliver a locally tuned, zero-browser-dependence experience, `src/desktop_app.py` boots a background daemon thread running `uvicorn` and spawns a native OS window container via `webview.create_window`.

### Key Capabilities:
* **Dynamic Port Discovery (`get_free_port`)**:
  Prevents `[WinError 10048] address already in use` by dynamically testing `127.0.0.1:8000` through `8050` using `socket.socket(socket.AF_INET, socket.SOCK_STREAM).bind()`. If a previous server instance or background task is still active on `8000`, the app automatically selects `8001` or any open port on localhost.
* **Native PyWebView Container**:
  Creates a responsive desktop window (`1280x820` initial, minimum `1024x640`) rendering the local dashboard without external browser tabs or URL bars.
* **Fallback Auto-Launch**:
  If native webview dependencies are unavailable, safely falls back to `webbrowser.open(f"http://127.0.0.1:{port}")` while keeping the backend thread alive.

---

## 2. Standalone Windows Launchers (`bat` & `vbs`)

To allow instant double-click startup directly from the desktop or repository root:

1. **`Launch_ClipperCS2.bat`**:
   Standard Windows Command Script that locates `python.exe` and executes `python src/desktop_app.py` cleanly.
2. **`Launch_ClipperCS2_Silent.vbs`**:
   VBScript wrapper using `WScript.Shell.Run "cmd.exe /c Launch_ClipperCS2.bat", 0, True`. Launches the complete application totally silently without spawning or flashing any background command prompt (`CMD`) terminal windows.

---

## 3. SPA Dashboard Features (`src/static/app.js`, `index.html`, `style.css`)

The frontend is built with high-performance Vanilla JS and sleek, esports-dark glassmorphism CSS (`#0d1117` / `#161b22`).

### Core Navigation Flow:
1. **Home Screen (`#homeScreen`)**:
   Provides quick entry cards to either **Generate New Match** (scan `.dem` folder) or **View Generated Matches** (browse already parsed database highlights).
2. **Generate New Match Screen (`#generateScreen`)**:
   Connects to your local CS2 replay folder (`defaulting to C:\Program Files (x86)\Steam\...\replays`). Scans all `.dem` files via `/api/demos` and displays them sorted by date (`newest first`). Clicking **Generate Match** triggers background parsing via `demoparser2` (`Layer 1`).
3. **Match Details & Player Selector (`#detailScreen`)**:
   Displays all active players in the match as interactive chips. Selecting any player (`e.g., log1c`) dynamically filters and renders two primary tabs:
   * **Best Highlights (`#tabHighlights`)**: Displays top ML-ranked clips (`4K`, `Ace`, `Clutch`, `Double Kill`).
   * **By Round (`#tabRounds`)**: Lists all 24+ rounds in chronological order with individual kill breakdown cards.

---

## 4. Per-Clip Side (`CT/T`) & Round Outcome (`Won/Lost`) Badges

To give immediate tactical context before launching CS2 or slicing clips, every single highlight and round card now embeds contextual badges queried from `src/web_server.py`:

### On Every Highlight Card (`Best Highlights` Tab):
Right next to the highlight badge (`e.g., 4K`), the header displays:
* **Side Badge**: `[🛡️ CT Side]` (`#4da6ff` blue) or `[🗡️ T Side]` (`#ff9933` orange).
* **Round Outcome Badge**: `[🏆 Round Won]` (`#2ea043` green) or `[❌ Round Lost]` (`#f85149` red).
* **Round Status Label**: Provides human-readable summaries such as `[CT Won Round (Defused)]` or `[T Won Round (Bomb Exploded)]`.

### On Every Round Header (`By Round` Tab):
Every round card header displays full side and outcome context:
> `Round 3` **`[🛡️ CT Side]`** **`[🏆 Round Won]`** `— 4 Kills`

---

## 5. Summary of Implemented Layer 6 Files

| File | Status | Purpose | Key Dependencies |
| :--- | :---: | :--- | :--- |
| `src/desktop_app.py` | ✅ **Complete** | Native PyWebView desktop container with `get_free_port()` dynamic binding. | `pywebview`, `uvicorn`, `socket` |
| `src/web_server.py` | ✅ **Complete** | FastAPI backend serving `/api/demos`, `/api/matches`, and per-clip side/outcome data. | `fastapi`, `sqlite3`, `pydantic` |
| `src/static/index.html` | ✅ **Complete** | Single-page UI layout covering Home, Generate, Matches, and Player Detail views. | Vanilla HTML5 |
| `src/static/style.css` | ✅ **Complete** | Modern dark-mode styling, glassmorphism cards, and badge indicators. | CSS3 Variables |
| `src/static/app.js` | ✅ **Complete** | State management, dynamic sorting (`newest first`), and per-clip badge rendering. | Vanilla ES6+ JS |
| `Launch_ClipperCS2.bat` | ✅ **Complete** | Instant Windows double-click batch launcher. | `cmd.exe` |
| `Launch_ClipperCS2_Silent.vbs` | ✅ **Complete** | Zero-window silent launcher script. | `wscript.exe` |
