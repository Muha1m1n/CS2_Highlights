import os
import sys
import io
import time
from src.parser import CS2DemoParser
from src.database import CS2Database

# Force sys.stdout to write in UTF-8 to prevent Windows terminal UnicodeEncodeErrors
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def main():
    demo_path = r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo\replays\match730_003830814863983116618_0173473800_161.dem"
    db_path = "data/processed/test_matches.db"
    
    # Ensure test clean state: delete test db if exists
    if os.path.exists(db_path):
        os.remove(db_path)
        print("Cleared previous test database.")
        
    print(f"Initializing database at: {db_path}")
    db = CS2Database(db_path)
    
    print("\n--- Step 1: Calculating Replay Hash ---")
    start_hash = time.time()
    file_hash = db.get_file_hash(demo_path)
    hash_time = time.time() - start_hash
    print(f"SHA-256 Hash: {file_hash}")
    print(f"Hashing took : {hash_time:.4f} seconds")
    
    print("\n--- Step 2: Caching Check (Should be False) ---")
    is_cached = db.is_match_cached(file_hash)
    print(f"Is match cached? {is_cached}")
    assert not is_cached, "Error: match should not be cached yet!"
    
    print("\n--- Step 3: Parsing Demo File (Layer 1) ---")
    start_parse = time.time()
    parser = CS2DemoParser(demo_path)
    meta = parser.parse_metadata()
    rounds_df = parser.parse_rounds()
    kills_df = parser.parse_kills(rounds_df)
    bomb_df = parser.parse_bomb_events(rounds_df)
    parse_time = time.time() - start_parse
    print(f"Parsing completed in: {parse_time:.4f} seconds")
    print(f"Parsed {len(rounds_df)} rounds, {len(kills_df)} kills, {len(bomb_df)} bomb events.")
    
    print("\n--- Step 4: Storing Match in Database (Layer 2) ---")
    start_save = time.time()
    db.save_match(file_hash, demo_path, meta, rounds_df, kills_df, bomb_df)
    save_time = time.time() - start_save
    print(f"Saving match took  : {save_time:.4f} seconds")
    
    print("\n--- Step 5: Caching Check (Should be True) ---")
    is_cached = db.is_match_cached(file_hash)
    print(f"Is match cached? {is_cached}")
    assert is_cached, "Error: match should now be cached!"
    
    print("\n--- Step 6: Loading Match from Database (Cache Retrieve) ---")
    start_load = time.time()
    cache_meta, cache_rounds, cache_kills, cache_bombs = db.get_match_data(file_hash)
    load_time = time.time() - start_load
    print(f"Database load took : {load_time:.4f} seconds")
    
    print("\n--- Step 7: Verifying Data Consistency ---")
    print(f"Metadata matches?  : {cache_meta['map_name'] == meta['map_name'] and cache_meta['tick_rate'] == meta['tick_rate']}")
    print(f"Rounds match size? : {len(cache_rounds) == len(rounds_df)}")
    print(f"Kills match size?  : {len(cache_kills) == len(kills_df)}")
    print(f"Bombs match size?  : {len(cache_bombs) == len(bomb_df)}")
    
    # Quick sanity check on reloaded structures
    print("\n=== Reloaded Rounds Timeline ===")
    print(cache_rounds.to_string(index=False))
    print("\n=== Reloaded Kills Details (First 5) ===")
    print(cache_kills[["tick", "round_number", "attacker_name", "attacker_team", "user_name", "user_team", "weapon", "headshot"]].head(5).to_string(index=False))
    
    print("\n==================================================")
    print("PERFORMANCE RATIO: PARSE VS DATABASE LOAD")
    print("==================================================")
    speedup = parse_time / load_time
    print(f"Parser Time   : {parse_time:.4f}s")
    print(f"Database Load : {load_time:.4f}s")
    print(f"Database Cache is {speedup:.1f}x FASTER than parsing the raw demo file!")
    
if __name__ == "__main__":
    main()
