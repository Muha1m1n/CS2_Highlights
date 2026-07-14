import os
import pickle
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from src.database import CS2Database

class CS2WinProbabilityModel:
    """
    Random Forest win-probability predictor for Counter-Strike 2 rounds.
    Includes a math-based heuristic fallback if the database has insufficient training data.
    """
    def __init__(self, db_path: str = "data/processed/matches.db", model_path: str = "data/processed/win_prob_rf.pkl"):
        self.db_path = db_path
        self.model_path = model_path
        self.model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
        self.trained = False
        
        # Load model if it exists
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, "rb") as f:
                    self.model = pickle.load(f)
                self.trained = True
                print("Loaded trained Win Probability Random Forest model.")
            except Exception as e:
                print(f"Could not load saved model, defaulting to fallback: {e}")

    def train_from_db(self) -> bool:
        """
        Gathers all matches in the database, extracts game state snapshots,
        trains the Random Forest, and serializes it.
        """
        if not os.path.exists(self.db_path):
            print("Database file does not exist. Cannot train.")
            return False
            
        db = CS2Database(self.db_path)
        session = db.Session()
        
        # Get all matches
        from src.database import MatchModel
        matches = session.query(MatchModel).all()
        session.close()
        
        if not matches:
            print("No matches in database to train on.")
            return False
            
        X = []
        y = []
        
        print(f"Extracting training features from {len(matches)} matches...")
        for match in matches:
            try:
                _, rounds_df, kills_df, bomb_df = db.get_match_data(match.sha256)
                if rounds_df.empty:
                    continue
                    
                tick_rate = match.tick_rate
                
                # Process round by round
                for _, r_row in rounds_df.iterrows():
                    round_num = int(r_row["round_number"])
                    r_start = int(r_row["start_tick"])
                    r_end = int(r_row["end_tick"])
                    winner = r_row["winner_team"]
                    
                    if winner not in ["CT", "T"]:
                        continue
                        
                    ct_won = 1 if winner == "CT" else 0
                    
                    # Fetch all events in this round
                    r_kills = kills_df[kills_df["round_number"] == round_num].sort_values("tick")
                    r_bombs = bomb_df[bomb_df["round_number"] == round_num].sort_values("tick")
                    
                    # Track states
                    ct_alive = 5
                    t_alive = 5
                    bomb_planted = False
                    bomb_plant_tick = None
                    
                    # Let's create a timeline of all events sorted by tick
                    events = []
                    for _, k in r_kills.iterrows():
                        events.append({
                            "tick": int(k["tick"]),
                            "type": "kill",
                            "victim_team": k["user_team"]
                        })
                    for _, b in r_bombs.iterrows():
                        events.append({
                            "tick": int(b["tick"]),
                            "type": "bomb",
                            "event_type": b["event_type"]
                        })
                        
                    events.sort(key=lambda e: e["tick"])
                    
                    # Initial state at round start
                    time_left = 115.0 # standard round time
                    X.append([ct_alive, t_alive, time_left, 0]) # 0 for not planted
                    y.append(ct_won)
                    
                    # Process tick timeline
                    for ev in events:
                        t = ev["tick"]
                        
                        # Calculate time left
                        if not bomb_planted:
                            time_left = max(0.0, 115.0 - (t - r_start) / tick_rate)
                        else:
                            time_left = max(0.0, 40.0 - (t - bomb_plant_tick) / tick_rate)
                            
                        # Capture state before event takes place
                        X.append([ct_alive, t_alive, time_left, 1 if bomb_planted else 0])
                        y.append(ct_won)
                        
                        # Apply event
                        if ev["type"] == "kill":
                            if ev["victim_team"] == "CT":
                                ct_alive = max(0, ct_alive - 1)
                            elif ev["victim_team"] == "T":
                                t_alive = max(0, t_alive - 1)
                        elif ev["type"] == "bomb":
                            if ev["event_type"] == "plant":
                                bomb_planted = True
                                bomb_plant_tick = t
                            elif ev["event_type"] == "defuse":
                                # CT won immediately
                                ct_alive = ct_alive # no change
                            elif ev["event_type"] == "explode":
                                # T won immediately
                                t_alive = t_alive
                                
                        # Capture state after event takes place
                        if not bomb_planted:
                            time_left = max(0.0, 115.0 - (t - r_start) / tick_rate)
                        else:
                            time_left = max(0.0, 40.0 - (t - bomb_plant_tick) / tick_rate)
                            
                        X.append([ct_alive, t_alive, time_left, 1 if bomb_planted else 0])
                        y.append(ct_won)
            except Exception as e:
                print(f"Skipping match {match.sha256} due to feature extraction error: {e}")
                continue
                
        if len(X) < 20:
            print(f"Not enough training states collected ({len(X)} states). Fallback will be used.")
            return False
            
        # Train Random Forest Model
        print(f"Training Random Forest on {len(X)} game states...")
        self.model.fit(np.array(X), np.array(y))
        self.trained = True
        
        # Save model
        model_dir = os.path.dirname(self.model_path)
        if model_dir and not os.path.exists(model_dir):
            os.makedirs(model_dir, exist_ok=True)
            
        with open(self.model_path, "wb") as f:
            pickle.dump(self.model, f)
            
        print(f"Random Forest model successfully trained and saved to {self.model_path}.")
        return True

    def predict_win_probability(self, ct_alive: int, t_alive: int, time_left: float, bomb_planted: bool) -> float:
        """
        Predicts win probability of CT team. Falls back to mathematical heuristics
        if model has not been trained.
        """
        if self.trained:
            # Predict probability using Random Forest
            try:
                features = np.array([[ct_alive, t_alive, time_left, 1 if bomb_planted else 0]])
                # predict_proba returns [prob_T_win, prob_CT_win]
                prob_ct = self.model.predict_proba(features)[0][1]
                return float(prob_ct)
            except Exception as e:
                # In case of prediction error, fall back to heuristic
                pass
                
        # Heuristic fallback
        if ct_alive == 0:
            return 0.0
        if t_alive == 0:
            if not bomb_planted:
                return 1.0
            else:
                # If Ts are all dead but bomb is planted, CTs must defuse.
                # Standard defuse takes 5s (with kit) or 10s (without).
                return 0.95 if time_left >= 5.0 else 0.02
                
        # Base alive ratio
        ratio = ct_alive / (ct_alive + t_alive)
        
        if bomb_planted:
            # Bomb favors T (team 2). CT has time pressure.
            # As time_left decreases, CT chance drops drastically
            time_factor = min(1.0, max(0.0, time_left / 40.0))
            prob = ratio * 0.4 * (0.2 + 0.8 * time_factor)
        else:
            # Standard round. As time_left decreases, pressure rises on Ts to plant, favoring CTs
            time_factor = min(1.0, max(0.0, time_left / 115.0))
            # If time is running out and bomb is not planted, CTs are favored
            prob = ratio * (1.0 - 0.25 * time_factor)
            
        return float(np.clip(prob, 0.01, 0.99))

    def get_round_timeline_wp(self, round_start: int, round_end: int, tick_rate: int, r_kills: pd.DataFrame, r_bombs: pd.DataFrame) -> pd.DataFrame:
        """
        Generates tick-by-tick win-probability updates for a specific round,
        resolving alive counts and bomb plant status chronologically.
        """
        timeline = []
        
        # Initial state
        ct_alive = 5
        t_alive = 5
        bomb_planted = False
        bomb_plant_tick = None
        
        # Sort and merge events
        events = []
        for _, k in r_kills.iterrows():
            events.append({
                "tick": int(k["tick"]),
                "type": "kill",
                "team": k["user_team"],
                "desc": f"{k['attacker_name']} killed {k['user_name']} ({k['weapon']})"
            })
        for _, b in r_bombs.iterrows():
            events.append({
                "tick": int(b["tick"]),
                "type": "bomb",
                "event_type": b["event_type"],
                "desc": f"Bomb {b['event_type']}ed by {b['user_name']}"
            })
        events.sort(key=lambda e: e["tick"])
        
        # Insert start tick
        wp = self.predict_win_probability(ct_alive, t_alive, 115.0, False)
        timeline.append({
            "tick": round_start,
            "ct_alive": ct_alive,
            "t_alive": t_alive,
            "time_left": 115.0,
            "bomb_planted": False,
            "win_prob": wp,
            "event_desc": "Round Started"
        })
        
        last_tick = round_start
        
        for ev in events:
            t = ev["tick"]
            # Fill intermediate ticks with time decaying steps (optional for drawing smooth lines,
            # but reporting event-based updates is sufficient and cleaner for graphs)
            if not bomb_planted:
                time_left = max(0.0, 115.0 - (t - round_start) / tick_rate)
            else:
                time_left = max(0.0, 40.0 - (t - bomb_plant_tick) / tick_rate)
                
            # Update alive counts
            if ev["type"] == "kill":
                if ev["team"] == "CT":
                    ct_alive = max(0, ct_alive - 1)
                elif ev["team"] == "T":
                    t_alive = max(0, t_alive - 1)
            elif ev["type"] == "bomb":
                if ev["event_type"] == "plant":
                    bomb_planted = True
                    bomb_plant_tick = t
                    
            wp = self.predict_win_probability(ct_alive, t_alive, time_left, bomb_planted)
            timeline.append({
                "tick": t,
                "ct_alive": ct_alive,
                "t_alive": t_alive,
                "time_left": time_left,
                "bomb_planted": bomb_planted,
                "win_prob": wp,
                "event_desc": ev["desc"]
            })
            
            last_tick = t
            
        # Add final tick
        if last_tick < round_end:
            time_left = 0.0 if not bomb_planted else max(0.0, 40.0 - (round_end - bomb_plant_tick) / tick_rate)
            wp = self.predict_win_probability(ct_alive, t_alive, time_left, bomb_planted)
            timeline.append({
                "tick": round_end,
                "ct_alive": ct_alive,
                "t_alive": t_alive,
                "time_left": time_left,
                "bomb_planted": bomb_planted,
                "win_prob": wp,
                "event_desc": "Round Ended"
            })
            
        return pd.DataFrame(timeline)
