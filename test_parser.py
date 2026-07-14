import os
import sys
import io
import pandas as pd
from src.parser import CS2DemoParser

# Force sys.stdout to write in UTF-8 to prevent Windows terminal UnicodeEncodeErrors
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def main():
    if len(sys.argv) > 1:
        demo_path = sys.argv[1]
    else:
        demo_dir = "Demo_Data"
        if not os.path.exists(demo_dir):
            print(f"Directory {demo_dir} does not exist.")
            sys.exit(1)
            
        dem_files = [f for f in os.listdir(demo_dir) if f.endswith(".dem")]
        if not dem_files:
            print("No .dem files found in Demo_Data. Please copy a demo file first.")
            sys.exit(0)
            
        demo_path = os.path.join(demo_dir, dem_files[0])
        
    print(f"Testing parser on: {demo_path}")
    
    if not os.path.exists(demo_path):
        print(f"File not found: {demo_path}")
        sys.exit(1)
        
    parser = CS2DemoParser(demo_path)
    
    print("\n==================================================")
    print("MATCH METADATA")
    print("==================================================")
    meta = parser.parse_metadata()
    for k, v in meta.items():
        print(f"{k.upper():<20}: {v}")
    
    print("\n==================================================")
    print("ROUNDS TIMELINE (ALL ROUNDS)")
    print("==================================================")
    rounds_df = parser.parse_rounds()
    if rounds_df.empty:
        print("No rounds parsed.")
        sys.exit(1)
    
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(rounds_df.to_string(index=False))
        
    print("\n==================================================")
    print("ROUND-BY-ROUND STATISTICS")
    print("==================================================")
    kills_df = parser.parse_kills(rounds_df)
    bomb_df = parser.parse_bomb_events(rounds_df)
    
    stats = []
    for _, r_row in rounds_df.iterrows():
        r_num = r_row["round_number"]
        r_kills = len(kills_df[kills_df["round_number"] == r_num])
        r_bombs = bomb_df[bomb_df["round_number"] == r_num]
        
        bomb_action = "None"
        if not r_bombs.empty:
            actions = []
            for _, b_row in r_bombs.iterrows():
                actions.append(f"{b_row['event_type']} by {b_row['user_name']} (Site {b_row['site']})")
            bomb_action = " -> ".join(actions)
            
        stats.append({
            "Round": r_num,
            "Winner": r_row["winner_team"],
            "Reason": r_row["end_reason"],
            "Kills": r_kills,
            "Bomb Action": bomb_action
        })
    stats_df = pd.DataFrame(stats)
    print(stats_df.to_string(index=False))

    print("\n==================================================")
    print("KILL FEED DETAIL: WHO KILLED WHO (FIRST 40 KILLS)")
    print("==================================================")
    if kills_df.empty:
        print("No kills parsed.")
    else:
        kills_detail = kills_df[["tick", "round_number", "attacker_name", "user_name", "weapon", "headshot"]].copy()
        kills_detail = kills_detail.rename(columns={"user_name": "victim_name"})
        print(kills_detail.head(40).to_string(index=False))

    print("\n==================================================")
    print("BOMB OBJECTIVES IN DETAIL (ALL)")
    print("==================================================")
    if bomb_df.empty:
        print("No bomb events parsed.")
    else:
        print(bomb_df.to_string(index=False))

if __name__ == "__main__":
    main()
