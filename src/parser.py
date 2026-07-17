import os
import pandas as pd
from demoparser2 import DemoParser

class CS2DemoParser:
    """
    Wrapper for demoparser2 to parse CS2 demo files (.dem) and extract
    normalized game event structures (rounds, kills, bomb events).
    """
    def __init__(self, demo_path: str = None):
        self.demo_path = demo_path
        self.parser = DemoParser(demo_path) if demo_path and os.path.exists(demo_path) else None
        self.header = None
        self.tick_rate = 64  # Default fallback
        self.map_name = "unknown"
        if demo_path and not os.path.exists(demo_path):
            raise FileNotFoundError(f"Demo file not found: {demo_path}")
        
    def parse_metadata(self) -> dict:
        """
        Parses demo header metadata.
        """
        try:
            self.header = self.parser.parse_header()
            self.tick_rate = int(self.header.get("tick_rate", 64))
            # If tick_rate is invalid or 0, default to 64
            if self.tick_rate <= 0:
                self.tick_rate = 64
            self.map_name = self.header.get("map_name", "unknown")
            return {
                "map_name": self.map_name,
                "tick_rate": self.tick_rate,
                "snapshot_rate": self.header.get("snapshot_rate", 64),
                "client_name": self.header.get("client_name", "unknown"),
                "game_directory": self.header.get("game_directory", "unknown")
            }
        except Exception as e:
            print(f"Error parsing header: {e}")
            # Fallback values
            self.tick_rate = 64
            self.map_name = "unknown"
            return {"map_name": "unknown", "tick_rate": 64}

    def parse_rounds(self) -> pd.DataFrame:
        """
        Extracts round boundaries by pairing round_end events with the
        most recent round_start events.
        """
        try:
            # Parse round start and end events
            start_events = self.parser.parse_event("round_start")
            end_events = self.parser.parse_event("round_end")
        except Exception as e:
            print(f"Error reading round events from demoparser2: {e}")
            return pd.DataFrame()

        if start_events.empty or end_events.empty:
            return pd.DataFrame()

        # Convert to pandas if they are in polars/other formats
        if not isinstance(start_events, pd.DataFrame):
            start_events = pd.DataFrame(start_events)
        if not isinstance(end_events, pd.DataFrame):
            end_events = pd.DataFrame(end_events)

        # Sort events by tick
        start_ticks = sorted(start_events["tick"].tolist())
        
        rounds_list = []
        # We loop through end events and pair them with the most recent start event
        for _, end_row in end_events.sort_values("tick").iterrows():
            end_tick = end_row["tick"]
            
            # Find the most recent start_tick before this end_tick
            matching_starts = [t for t in start_ticks if t < end_tick]
            if not matching_starts:
                continue
                
            start_tick = matching_starts[-1]
            
            winner = end_row.get("winner")
            winner = str(winner) if not pd.isna(winner) else ""
            
            reason = end_row.get("reason")
            if not pd.isna(reason):
                try:
                    reason = int(reason)
                except (ValueError, TypeError):
                    reason = str(reason)
            else:
                reason = ""
                
            message = end_row.get("message")
            message = str(message) if not pd.isna(message) else ""
            
            rounds_list.append({
                "start_tick": start_tick,
                "end_tick": end_tick,
                "winner_team": winner,
                "end_reason": reason,
                "message": message
            })
            
        # Sort combined rounds by tick
        rounds_df = pd.DataFrame(rounds_list).sort_values("start_tick").reset_index(drop=True)
        
        # Filter out warmup rounds. In CS2 matchmaking/pro demos, warmup rounds end with reasons
        # that occur before the match officially restarts.
        # A simple, effective heuristic: the match starts, and scores reset.
        # We assign round_number sequentially for all rounds. We will refine this in Layer 2/3.
        rounds_df["round_number"] = rounds_df.index + 1
        
        return rounds_df

    def parse_kills(self, rounds_df: pd.DataFrame) -> pd.DataFrame:
        """
        Extracts kill events and associates them with round numbers and team names.
        """
        try:
            # Query custom player property team_num (2 = T, 3 = CT)
            kills_df = self.parser.parse_event("player_death", player=["team_num"])
        except Exception as e:
            print(f"Error parsing kill events: {e}")
            return pd.DataFrame()

        if kills_df.empty:
            return pd.DataFrame()

        if not isinstance(kills_df, pd.DataFrame):
            kills_df = pd.DataFrame(kills_df)

        # Map team numbers to T/CT strings
        if "attacker_team_num" in kills_df.columns:
            kills_df["attacker_team"] = kills_df["attacker_team_num"].map({2: "T", 3: "CT"}).fillna("unknown")
        else:
            kills_df["attacker_team"] = "unknown"

        if "user_team_num" in kills_df.columns:
            kills_df["user_team"] = kills_df["user_team_num"].map({2: "T", 3: "CT"}).fillna("unknown")
        else:
            kills_df["user_team"] = "unknown"

        # Ensure essential columns are present
        required_cols = ["tick", "attacker_name", "user_name", "weapon"]
        for col in required_cols:
            if col not in kills_df.columns:
                if col == "user_name" and "victim_name" in kills_df.columns:
                    kills_df["user_name"] = kills_df["victim_name"]
                else:
                    kills_df[col] = None

        # Add round numbers by matching kills to round tick ranges
        kills_df["round_number"] = None
        for _, r_row in rounds_df.iterrows():
            mask = (kills_df["tick"] >= r_row["start_tick"]) & (kills_df["tick"] <= r_row["end_tick"])
            kills_df.loc[mask, "round_number"] = r_row["round_number"]
            
        # Filter out kills that did not happen during active rounds
        kills_df = kills_df.dropna(subset=["round_number"]).copy()
        kills_df["round_number"] = kills_df["round_number"].astype(int)
        
        # Standardize flags
        for flag in ["headshot", "noscope", "thrusmoke"]:
            if flag not in kills_df.columns:
                kills_df[flag] = False
            else:
                kills_df[flag] = kills_df[flag].fillna(False).astype(bool)
                
        if "penetrated" not in kills_df.columns:
            kills_df["penetrated"] = 0
        else:
            kills_df["penetrated"] = kills_df["penetrated"].fillna(0).astype(int)

        return kills_df

    def parse_bomb_events(self, rounds_df: pd.DataFrame) -> pd.DataFrame:
        """
        Extracts bomb events (plant, defuse, explode) and associates them with rounds and teams.
        """
        bomb_dfs = []
        event_types = {
            "bomb_planted": ("plant", "T"),
            "bomb_defused": ("defuse", "CT"),
            "bomb_exploded": ("explode", "T")
        }
        
        for event_name, (event_label, team) in event_types.items():
            try:
                df = self.parser.parse_event(event_name)
                if not df.empty:
                    if not isinstance(df, pd.DataFrame):
                        df = pd.DataFrame(df)
                    df["event_type"] = event_label
                    df["user_team"] = team
                    
                    # Ensure site and user_name are present (explode might not contain them)
                    if "site" not in df.columns:
                        df["site"] = None
                    if "user_name" not in df.columns:
                        df["user_name"] = None
                        
                    bomb_dfs.append(df[["tick", "event_type", "user_name", "user_team", "site"]])
            except Exception:
                continue
                
        if not bomb_dfs:
            return pd.DataFrame(columns=["tick", "event_type", "user_name", "user_team", "site", "round_number"])
            
        bomb_df = pd.concat(bomb_dfs, ignore_index=True).sort_values("tick").reset_index(drop=True)
        
        # Map rounds
        bomb_df["round_number"] = None
        for _, r_row in rounds_df.iterrows():
            mask = (bomb_df["tick"] >= r_row["start_tick"]) & (bomb_df["tick"] <= r_row["end_tick"])
            bomb_df.loc[mask, "round_number"] = r_row["round_number"]
            
        bomb_df = bomb_df.dropna(subset=["round_number"]).copy()
        bomb_df["round_number"] = bomb_df["round_number"].astype(int)
        
        return bomb_df

    def parse(self, demo_path: str = None):
        """
        Master method that runs full extraction on a .dem file:
        Returns: (metadata_dict, rounds_df, kills_df, bomb_df)
        """
        if demo_path:
            if not os.path.exists(demo_path):
                raise FileNotFoundError(f"Demo file not found: {demo_path}")
            self.demo_path = demo_path
            self.parser = DemoParser(demo_path)
        elif not self.parser or not self.demo_path:
            raise ValueError("No valid demo_path provided to CS2DemoParser.")
            
        meta = self.parse_metadata()
        rounds_df = self.parse_rounds()
        kills_df = self.parse_kills(rounds_df)
        bomb_df = self.parse_bomb_events(rounds_df)
        return meta, rounds_df, kills_df, bomb_df
