import os
import sys
import io
import time
import pandas as pd
from src.parser import CS2DemoParser
from src.database import CS2Database
from src.detector_engine import CS2DetectorEngine

# Force sys.stdout to write in UTF-8 to prevent Windows terminal UnicodeEncodeErrors
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def main():
    demo_path = r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays\match730_003831047039177720673_1229901627_382.dem"
    db_path = "data/processed/test_matches.db"
    
    print(f"Loading database cache from: {db_path}")
    db = CS2Database(db_path)
    
    file_hash = db.get_file_hash(demo_path)
    print(f"Match Hash: {file_hash}")
    
    if not db.is_match_cached(file_hash):
        print("Match not in cache. Parsing raw demo file first (Layer 1)...")
        start = time.time()
        parser = CS2DemoParser(demo_path)
        meta = parser.parse_metadata()
        rounds_df = parser.parse_rounds()
        kills_df = parser.parse_kills(rounds_df)
        bomb_df = parser.parse_bomb_events(rounds_df)
        print(f"Parsing complete in {time.time() - start:.2f} seconds.")
        
        # Save to database (Layer 2)
        db.save_match(file_hash, demo_path, meta, rounds_df, kills_df, bomb_df)
    else:
        print("Match found in cache! Loading tables from SQLite...")
        
    start_load = time.time()
    meta, rounds_df, kills_df, bomb_df = db.get_match_data(file_hash)
    print(f"Loaded match data in {time.time() - start_load:.4f} seconds.")
    
    print(f"Match Map  : {meta['map_name']}")
    print(f"Tick Rate  : {meta['tick_rate']} ticks/sec")
    print(f"Kills Count: {len(kills_df)}")
    
    # Run Detector Engine (Layer 3)
    print("\n--- Running Highlight Detection Engine (Layer 3) ---")
    detector = CS2DetectorEngine(db_path=db_path)
    start_detect = time.time()
    moments = detector.detect_all(rounds_df, kills_df, bomb_df, meta["tick_rate"])
    detect_time = time.time() - start_detect
    print(f"Moment detection took: {detect_time:.4f} seconds.")
    print(f"Found {len(moments)} total highlight candidate moments.")
    
    print("\n==========================================================================================")
    print("DETECTOR RUN SUMMARY: TOP HIGHLIGHTS DETECTED (SORTED BY SCORE)")
    print("==========================================================================================")
    
    headers = ["Rank", "Score", "Player", "Round", "Type", "Ticks (Duration)", "Description"]
    print(f"{headers[0]:<5} | {headers[1]:<6} | {headers[2]:<12} | {headers[3]:<5} | {headers[4]:<25} | {headers[5]:<18} | {headers[6]}")
    print("-" * 105)
    
    for i, m in enumerate(moments):
        duration_sec = (m.end_tick - m.start_tick) / meta["tick_rate"]
        tick_range = f"{m.start_tick}-{m.end_tick} ({duration_sec:.1f}s)"
        score_str = f"{m.total_score:.1f}"
        
        # Truncate player name for formatting
        player = m.player_name
        if len(player) > 12:
            player = player[:10] + ".."
            
        print(f"#{i+1:<4} | {score_str:<6} | {player:<12} | {m.round_number:<5} | {m.highlight_type:<25} | {tick_range:<18} | {m.description}")
        
if __name__ == "__main__":
    main()
