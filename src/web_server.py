"""
Layer 6: ClipperCS2 Local Application (`src/web_server.py`)

A locally-run application (served via FastAPI on localhost) that connects to
your CS2 demo replays folder, lets you parse new matches, browse generated matches,
select players, view ML-ranked highlights or round-by-round kills, and trigger
automated OBS+CS2 recording — all from a premium local interface.

Launch: `python -m src.web_server`
Opens: http://localhost:8000 (auto-launched in your default browser)
"""

import os
import sys
import json
import time
import uuid
import sqlite3
import hashlib
import threading
import webbrowser
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "processed", "test_matches.db")
CLIPS_DIR = os.path.join(PROJECT_ROOT, "clips")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULT_DEMO_FOLDER = r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays"

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="ClipperCS2", version="1.0.0")

# Serve recorded clips as static files
os.makedirs(CLIPS_DIR, exist_ok=True)
app.mount("/clips", StaticFiles(directory=CLIPS_DIR), name="clips")

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
recording_tasks = {}   # task_id -> {status, messages, done}
parsing_tasks = {}     # task_id -> {status, messages, done, demo_name}

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class RecordRequest(BaseModel):
    match_hash: str
    player_name: str
    start_tick: int
    end_tick: int
    description: str = ""
    round_num: int = 0

class ParseRequest(BaseModel):
    demo_path: str

# ---------------------------------------------------------------------------
# Helper: get SQLite connection
# ---------------------------------------------------------------------------
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------------------------------------------------------------------
# API: Scan demo folder for .dem files
# ---------------------------------------------------------------------------
@app.get("/api/demos")
def list_demos(folder: str = ""):
    demo_folder = folder if folder and os.path.isdir(folder) else DEFAULT_DEMO_FOLDER
    if not os.path.isdir(demo_folder):
        return {"folder": demo_folder, "exists": False, "demos": []}
    
    demos = []
    for f in os.listdir(demo_folder):
        if f.lower().endswith(".dem"):
            fpath = os.path.join(demo_folder, f)
            try:
                mtime = os.path.getmtime(fpath)
            except Exception:
                mtime = 0
            size_mb = round(os.path.getsize(fpath) / (1024 * 1024), 1)
            modified = datetime.fromtimestamp(mtime).isoformat()
            demos.append({
                "filename": f,
                "path": fpath,
                "size_mb": size_mb,
                "modified": modified,
                "_mtime": mtime
            })
    
    # Sort by date modified, newest first!
    demos.sort(key=lambda x: x["_mtime"], reverse=True)
    for d in demos:
        d.pop("_mtime", None)
        
    return {"folder": demo_folder, "exists": True, "demos": demos}

# ---------------------------------------------------------------------------
# API: Parse a demo file (background task)
# ---------------------------------------------------------------------------
@app.post("/api/parse")
def parse_demo(req: ParseRequest):
    if not os.path.exists(req.demo_path):
        raise HTTPException(status_code=404, detail=f"Demo file not found: {req.demo_path}")
    
    task_id = str(uuid.uuid4())[:8]
    demo_name = os.path.basename(req.demo_path)
    parsing_tasks[task_id] = {"status": "queued", "messages": [f"Queued: {demo_name}"], "done": False, "demo_name": demo_name}
    
    def _run_parse():
        task = parsing_tasks[task_id]
        try:
            task["status"] = "parsing"
            task["messages"].append(f"[Parser] Loading demo: {demo_name}...")
            
            from src.parser import CS2DemoParser
            from src.database import CS2Database
            
            db = CS2Database(DB_PATH)
            file_hash = db.get_file_hash(req.demo_path)
            
            if db.is_match_cached(file_hash):
                task["messages"].append("[Parser] Match already parsed and cached in database!")
                task["status"] = "done"
                task["done"] = True
                return
            
            task["messages"].append("[Parser] Extracting events from .dem binary...")
            parser = CS2DemoParser()
            meta, rounds_df, kills_df, bomb_df = parser.parse(req.demo_path)
            
            task["messages"].append(f"[Parser] Found {len(kills_df)} kills across {len(rounds_df)} rounds on {meta.get('map_name', 'unknown')}.")
            task["messages"].append("[Database] Saving to SQLite cache...")
            
            db.save_match(file_hash, req.demo_path, meta, rounds_df, kills_df, bomb_df)
            
            task["messages"].append(f"[Database SUCCESS] Match cached: {file_hash[:12]}...")
            task["status"] = "done"
            task["done"] = True
            
        except Exception as e:
            task["status"] = "error"
            task["messages"].append(f"[ERROR] {str(e)}")
            task["done"] = True
    
    thread = threading.Thread(target=_run_parse, daemon=True)
    thread.start()
    
    return {"task_id": task_id}

# ---------------------------------------------------------------------------
# API: SSE stream for parsing progress
# ---------------------------------------------------------------------------
@app.get("/api/parse/{task_id}/status")
def parse_status_sse(task_id: str):
    if task_id not in parsing_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    def event_stream():
        last_idx = 0
        while True:
            task = parsing_tasks.get(task_id)
            if not task:
                break
            messages = task["messages"]
            if len(messages) > last_idx:
                for msg in messages[last_idx:]:
                    yield f"data: {json.dumps({'status': task['status'], 'message': msg})}\n\n"
                last_idx = len(messages)
            if task["done"]:
                yield f"data: {json.dumps({'status': task['status'], 'message': 'STREAM_END'})}\n\n"
                break
            time.sleep(0.3)
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# API: List all parsed/generated matches
# ---------------------------------------------------------------------------
@app.get("/api/matches")
def list_matches():
    conn = get_db()
    try:
        rows = conn.execute("SELECT sha256, map_name, demo_path, parsed_at FROM matches ORDER BY parsed_at DESC").fetchall()
    except Exception:
        conn.close()
        return []
    conn.close()
    matches = []
    for r in rows:
        demo_path = r["demo_path"] or ""
        matches.append({
            "sha256": r["sha256"],
            "map_name": r["map_name"],
            "demo_path": demo_path,
            "demo_filename": os.path.basename(demo_path),
            "parsed_at": r["parsed_at"]
        })
    return matches

# ---------------------------------------------------------------------------
# API: List all players in a match
# ---------------------------------------------------------------------------
@app.get("/api/matches/{match_hash}/players")
def list_players(match_hash: str):
    conn = get_db()
    
    # 1. Compute match result from rounds table
    try:
        round_rows = conn.execute("""
            SELECT winner_team, COUNT(*) AS score 
            FROM rounds WHERE match_hash = ? AND winner_team IN ('CT', 'T')
            GROUP BY winner_team
        """, (match_hash,)).fetchall()
    except Exception:
        round_rows = []
        
    ct_score, t_score = 0, 0
    for r in round_rows:
        if r["winner_team"] == "CT": ct_score = r["score"]
        elif r["winner_team"] == "T": t_score = r["score"]
        
    match_winner = "CT" if ct_score > t_score else "T" if t_score > ct_score else "Tie"
    score_str = f"CT {ct_score} - {t_score} T"
    
    # 2. Get player kills and primary side
    rows = conn.execute("""
        SELECT attacker_name AS name, attacker_team AS team, COUNT(*) AS kills
        FROM kills WHERE match_hash = ? AND attacker_name IS NOT NULL AND attacker_name != 'None'
        GROUP BY attacker_name, attacker_team ORDER BY kills DESC
    """, (match_hash,)).fetchall()
    
    death_rows = conn.execute("""
        SELECT user_name AS name, COUNT(*) AS deaths
        FROM kills WHERE match_hash = ? AND user_name IS NOT NULL AND user_name != 'None'
        GROUP BY user_name
    """, (match_hash,)).fetchall()
    conn.close()
    
    death_map = {r["name"]: r["deaths"] for r in death_rows}
    player_dict = {}
    for r in rows:
        name = r["name"]
        team = r["team"] or "unknown"
        kills = r["kills"]
        if name not in player_dict:
            player_dict[name] = {"name": name, "team": team, "kills": 0, "deaths": death_map.get(name, 0), "teams": []}
        player_dict[name]["kills"] += kills
        if team in ("CT", "T") and team not in player_dict[name]["teams"]:
            player_dict[name]["teams"].append(team)
            
    players = []
    for name, data in player_dict.items():
        teams_played = data["teams"]
        primary_team = data["team"] if data["team"] in ("CT", "T") else (teams_played[0] if teams_played else "unknown")
        
        if len(teams_played) > 1:
            side_label = "CT & T (Swapped Sides)"
        elif primary_team == "CT":
            side_label = "Counter-Terrorist (CT)"
        elif primary_team == "T":
            side_label = "Terrorist (T)"
        else:
            side_label = "Unknown Side"
            
        if match_winner == "Tie":
            player_result = f"Draw ({ct_score}-{t_score})"
        elif match_winner == primary_team:
            player_result = f"Victory ({max(ct_score, t_score)} - {min(ct_score, t_score)})"
        elif primary_team in ("CT", "T"):
            player_result = f"Defeat ({min(ct_score, t_score)} - {max(ct_score, t_score)})"
        else:
            player_result = f"Final: {score_str}"
            
        kd_ratio = round(data["kills"] / max(data["deaths"], 1), 2)
        
        players.append({
            "name": name,
            "team": primary_team,
            "side_label": side_label,
            "match_result": player_result,
            "kills": data["kills"],
            "deaths": data["deaths"],
            "kd": kd_ratio
        })
        
    players.sort(key=lambda x: x["kills"], reverse=True)
    return {
        "match_info": {
            "ct_score": ct_score,
            "t_score": t_score,
            "winner": match_winner,
            "score_string": score_str
        },
        "players": players
    }

# ---------------------------------------------------------------------------
# API: ML-ranked highlights for a player
# ---------------------------------------------------------------------------
@app.get("/api/matches/{match_hash}/players/{player_name}/highlights")
def get_highlights(match_hash: str, player_name: str):
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE sha256 = ?", (match_hash,)).fetchone()
    if not match:
        conn.close()
        raise HTTPException(status_code=404, detail="Match not found")
    
    tick_rate = match["tick_rate"] or 64

    # Build side and winner maps
    round_rows = conn.execute("SELECT round_number, winner_team FROM rounds WHERE match_hash = ?", (match_hash,)).fetchall()
    round_winner_map = {r["round_number"]: r["winner_team"] for r in round_rows}
    
    kill_side_rows = conn.execute("""
        SELECT round_number, attacker_team, user_team
        FROM kills WHERE match_hash = ? AND (attacker_name LIKE ? OR user_name LIKE ?)
    """, (match_hash, f"%{player_name}%", f"%{player_name}%")).fetchall()
    
    player_side_map = {}
    for r in kill_side_rows:
        rn = r["round_number"]
        if rn not in player_side_map:
            if r["attacker_team"] in ("CT", "T"):
                player_side_map[rn] = r["attacker_team"]
            elif r["user_team"] in ("CT", "T"):
                player_side_map[rn] = r["user_team"]

    # Try ML detector engine
    try:
        import pandas as pd
        from src.database import CS2Database
        from src.detector_engine import CS2DetectorEngine
        
        db = CS2Database(DB_PATH)
        meta, rounds_df, kills_df, bomb_df = db.get_match_data(match_hash)
        engine = CS2DetectorEngine(db_path=DB_PATH)
        all_moments = engine.detect_all(rounds_df, kills_df, bomb_df, tick_rate)
        player_moments = [m for m in all_moments if m.player_name and player_name.lower() in m.player_name.lower()]
        conn.close()
        
        result = []
        for m in player_moments:
            rn = m.round_number
            side = player_side_map.get(rn, "unknown")
            winner = round_winner_map.get(rn, "unknown")
            won = (side == winner) if (side in ("CT", "T") and winner in ("CT", "T")) else None
            result.append({
                "round_number": rn, "start_tick": m.start_tick, "end_tick": m.end_tick,
                "highlight_type": m.highlight_type, "base_score": round(m.base_score, 2),
                "skill_bonus": round(m.skill_bonus, 2), "ml_boost": round(m.ml_boost, 2),
                "total_score": round(m.total_score, 2), "description": m.description,
                "player_name": m.player_name, "metadata": m.metadata,
                "side": side, "round_won": won
            })
        return result
    except Exception as e:
        print(f"[WebServer] ML detector failed ({e}), using DB fallback...")

    # Fallback
    rows = conn.execute("""
        SELECT round_number, MIN(tick) AS first_tick, MAX(tick) AS last_tick, COUNT(*) AS kills,
               SUM(headshot) AS headshots, SUM(noscope) AS noscopes,
               SUM(thrusmoke) AS thrusmokes, SUM(penetrated > 0) AS wallbangs
        FROM kills WHERE match_hash = ? AND attacker_name LIKE ?
        GROUP BY round_number ORDER BY kills DESC
    """, (match_hash, f"%{player_name}%")).fetchall()
    conn.close()

    highlights = []
    for r in rows:
        rn = r["round_number"]
        kills = r["kills"]
        base = kills * 12.0
        skill = (r["headshots"] or 0) * 3.0 + (r["noscopes"] or 0) * 8.0 + (r["thrusmokes"] or 0) * 5.0 + (r["wallbangs"] or 0) * 5.0
        hl_type = "Ace" if kills >= 5 else "4K" if kills >= 4 else "3K" if kills >= 3 else "2K" if kills >= 2 else "Kill"
        if kills >= 5: base += 20
        elif kills >= 4: base += 15
        elif kills >= 3: base += 10
        
        side = player_side_map.get(rn, "unknown")
        winner = round_winner_map.get(rn, "unknown")
        won = (side == winner) if (side in ("CT", "T") and winner in ("CT", "T")) else None
        
        highlights.append({
            "round_number": rn, "start_tick": r["first_tick"], "end_tick": r["last_tick"],
            "highlight_type": hl_type, "base_score": round(base, 2), "skill_bonus": round(skill, 2),
            "ml_boost": 0.0, "total_score": round(base + skill, 2),
            "description": f"{player_name} Round {rn} ({kills}K - {r['headshots'] or 0} HS)",
            "player_name": player_name, "metadata": {"headshots": r["headshots"] or 0},
            "side": side, "round_won": won
        })
    return highlights

# ---------------------------------------------------------------------------
# API: Rounds with kills for a player
# ---------------------------------------------------------------------------
@app.get("/api/matches/{match_hash}/players/{player_name}/rounds")
def get_rounds(match_hash: str, player_name: str):
    conn = get_db()
    
    round_rows = conn.execute("SELECT round_number, winner_team FROM rounds WHERE match_hash = ?", (match_hash,)).fetchall()
    round_winner_map = {r["round_number"]: r["winner_team"] for r in round_rows}
    
    kills_rows = conn.execute("""
        SELECT round_number, tick, user_name AS victim, weapon, headshot, noscope, thrusmoke, penetrated, attacker_team
        FROM kills WHERE match_hash = ? AND attacker_name LIKE ?
        ORDER BY round_number ASC, tick ASC
    """, (match_hash, f"%{player_name}%")).fetchall()
    
    death_rows = conn.execute("""
        SELECT round_number, MIN(tick) AS death_tick
        FROM kills WHERE match_hash = ? AND user_name LIKE ?
        GROUP BY round_number
    """, (match_hash, f"%{player_name}%")).fetchall()
    conn.close()

    death_map = {r["round_number"]: r["death_tick"] for r in death_rows}
    rounds = {}
    for r in kills_rows:
        rn = r["round_number"]
        team = r["attacker_team"] if r["attacker_team"] in ("CT", "T") else "unknown"
        if rn not in rounds:
            rounds[rn] = {
                "round_number": rn, "kills": [], "total_kills": 0,
                "first_kill_tick": None, "last_kill_tick": None,
                "side": team,
                "round_won": (team == round_winner_map.get(rn)) if team in ("CT", "T") and round_winner_map.get(rn) in ("CT", "T") else None
            }
        rounds[rn]["kills"].append({
            "tick": r["tick"], "victim": r["victim"], "weapon": r["weapon"],
            "headshot": bool(r["headshot"]), "noscope": bool(r["noscope"]),
            "thrusmoke": bool(r["thrusmoke"]), "penetrated": r["penetrated"] > 0 if r["penetrated"] else False
        })
        rounds[rn]["total_kills"] += 1
        if rounds[rn]["first_kill_tick"] is None: rounds[rn]["first_kill_tick"] = r["tick"]
        rounds[rn]["last_kill_tick"] = r["tick"]

    for rn, data in rounds.items():
        data["player_death_tick"] = death_map.get(rn)
    return sorted(rounds.values(), key=lambda x: x["round_number"])

# ---------------------------------------------------------------------------
# API: Trigger recording
# ---------------------------------------------------------------------------
@app.post("/api/record")
def start_recording(req: RecordRequest):
    task_id = str(uuid.uuid4())[:8]
    recording_tasks[task_id] = {"status": "queued", "messages": ["Recording queued..."], "done": False}
    
    conn = get_db()
    match = conn.execute("SELECT demo_path FROM matches WHERE sha256 = ?", (req.match_hash,)).fetchone()
    conn.close()
    if not match: raise HTTPException(status_code=404, detail="Match not found")
    demo_path = match["demo_path"]

    def _run_recording():
        task = recording_tasks[task_id]
        try:
            task["status"] = "starting"
            task["messages"].append("Connecting to OBS Studio & CS2...")
            from src.autocapture_engine import AutoCaptureEngine
            engine = AutoCaptureEngine(output_dir=CLIPS_DIR)
            task["status"] = "connecting"
            task["messages"].append("Booting CS2 and OBS Studio...")
            engine.connect_all(launch_cs2_if_closed=True)
            
            final_tick = req.end_tick
            try:
                db_conn = sqlite3.connect(DB_PATH)
                death_row = db_conn.execute(
                    "SELECT MIN(tick) FROM kills WHERE user_name LIKE ? AND round_number = ? AND match_hash = ?",
                    (f"%{req.player_name}%", req.round_num, req.match_hash)).fetchone()
                if death_row and death_row[0]: final_tick = min(final_tick, death_row[0] + 16)
                db_conn.close()
            except Exception: pass
            
            candidate = {
                "start_tick": req.start_tick, "end_tick": final_tick,
                "player_name": req.player_name,
                "description": req.description or f"{req.player_name} Round {req.round_num}",
                "round_num": req.round_num
            }
            task["status"] = "recording"
            task["messages"].append(f"Recording: {candidate['description']}...")
            engine.capture_playlist(demo_path=demo_path, candidates=[candidate], match_title=f"{req.player_name}_Clip")
            task["status"] = "done"
            task["messages"].append("Clip recorded and saved!")
            task["done"] = True
        except Exception as e:
            task["status"] = "error"
            task["messages"].append(f"Error: {str(e)}")
            task["done"] = True

    threading.Thread(target=_run_recording, daemon=True).start()
    return {"task_id": task_id}

# ---------------------------------------------------------------------------
# API: SSE recording status
# ---------------------------------------------------------------------------
@app.get("/api/record/{task_id}/status")
def recording_status_sse(task_id: str):
    if task_id not in recording_tasks: raise HTTPException(status_code=404, detail="Task not found")
    def event_stream():
        last_idx = 0
        while True:
            task = recording_tasks.get(task_id)
            if not task: break
            messages = task["messages"]
            if len(messages) > last_idx:
                for msg in messages[last_idx:]: yield f"data: {json.dumps({'status': task['status'], 'message': msg})}\n\n"
                last_idx = len(messages)
            if task["done"]:
                yield f"data: {json.dumps({'status': task['status'], 'message': 'STREAM_END'})}\n\n"
                break
            time.sleep(0.5)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# API: List recorded clips
# ---------------------------------------------------------------------------
@app.get("/api/clips")
def list_clips():
    if not os.path.isdir(CLIPS_DIR): return []
    clips = []
    for f in sorted(os.listdir(CLIPS_DIR), reverse=True):
        if f.lower().endswith(".mp4"):
            fpath = os.path.join(CLIPS_DIR, f)
            clips.append({"filename": f, "size_mb": round(os.path.getsize(fpath) / (1024*1024), 1),
                          "created_at": datetime.fromtimestamp(os.path.getctime(fpath)).isoformat()})
    return clips

# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------
@app.get("/")
def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path): return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend not found")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# CLI Entry Point — Auto-opens browser
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  ClipperCS2 - Layer 6 Local App")
    print("  http://localhost:8000")
    print("=" * 60)
    
    # Auto-open browser after 1.5s delay
    def _open_browser():
        time.sleep(1.5)
        webbrowser.open("http://localhost:8000")
    threading.Thread(target=_open_browser, daemon=True).start()
    
    uvicorn.run(app, host="127.0.0.1", port=8000)
