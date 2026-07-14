import pandas as pd
from typing import List
from src.detectors.base import CandidateMoment
from src.detectors.multikill import MultiKillDetector
from src.detectors.clutch import ClutchDetector
from src.detectors.skill import SkillDetector
from src.ml_model import CS2WinProbabilityModel

class CS2DetectorEngine:
    """
    Main orchestration engine that runs all highlight detectors, applies win-probability
    swing boosts via a Random Forest ML model, de-duplicates overlapping clips,
    and sorts highlights.
    """
    def __init__(self, db_path: str = "data/processed/matches.db"):
        self.multikill_detector = MultiKillDetector()
        self.clutch_detector = ClutchDetector()
        self.skill_detector = SkillDetector()
        self.wp_model = CS2WinProbabilityModel(db_path=db_path)
        
        # Train ML model on startup if database has data
        try:
            self.wp_model.train_from_db()
        except Exception as e:
            print(f"Warning: Could not train Win Probability Model on startup: {e}")

    def detect_all(self, rounds_df: pd.DataFrame, kills_df: pd.DataFrame, bomb_df: pd.DataFrame, tick_rate: int) -> List[CandidateMoment]:
        if rounds_df.empty or kills_df.empty:
            return []

        all_moments: List[CandidateMoment] = []

        # 1. Run all individual detectors
        all_moments.extend(self.multikill_detector.detect(rounds_df, kills_df, bomb_df, tick_rate))
        all_moments.extend(self.clutch_detector.detect(rounds_df, kills_df, bomb_df, tick_rate))
        
        # 2. Apply skill bonuses to the multi-kill and clutch highlights
        self.skill_detector.apply_skill_bonuses(all_moments, kills_df)
        
        # 3. Detect standalone high-difficulty skill shots and add them to list
        all_moments.extend(self.skill_detector.detect(rounds_df, kills_df, bomb_df, tick_rate))

        if not all_moments:
            return []

        # 4. Calculate and apply Machine Learning win-probability swings
        self.apply_ml_swings(all_moments, rounds_df, kills_df, bomb_df, tick_rate)

        # 5. De-duplicate and merge overlapping windows for the same player in the same round
        # Sort by round, player, start_tick
        all_moments.sort(key=lambda m: (m.round_number, m.player_name, m.start_tick))
        
        merged_moments: List[CandidateMoment] = []
        current = all_moments[0]

        for next_mom in all_moments[1:]:
            # Check if they belong to the same player in the same round and overlap
            if (current.round_number == next_mom.round_number and 
                current.player_name == next_mom.player_name and 
                next_mom.start_tick <= current.end_tick):
                
                # Merge windows
                merged_start = min(current.start_tick, next_mom.start_tick)
                merged_end = max(current.end_tick, next_mom.end_tick)
                
                # Merge descriptions & highlight types
                combined_type = f"{current.highlight_type} + {next_mom.highlight_type}"
                if current.highlight_type == next_mom.highlight_type:
                    combined_type = current.highlight_type
                
                combined_desc = f"{current.description} and {next_mom.highlight_type}"
                if current.highlight_type == next_mom.highlight_type:
                    combined_desc = current.description
                    
                # Score merging: max of total scores, then assign base, skill, and ml_boost
                max_score = max(current.total_score, next_mom.total_score)
                merged_ml = max(current.ml_boost, next_mom.ml_boost)
                
                # Keep higher base score, adjust skill bonus to match max_score
                if current.total_score >= next_mom.total_score:
                    merged_base = current.base_score
                    merged_skill = max_score - merged_base - merged_ml
                else:
                    merged_base = next_mom.base_score
                    merged_skill = max_score - merged_base - merged_ml

                # Merge metadata
                merged_meta = {**current.metadata, **next_mom.metadata}
                merged_meta["merged_events"] = [current.highlight_type, next_mom.highlight_type]

                current = CandidateMoment(
                    player_name=current.player_name,
                    round_number=current.round_number,
                    start_tick=merged_start,
                    end_tick=merged_end,
                    highlight_type=combined_type,
                    base_score=merged_base,
                    skill_bonus=round(max(0.0, merged_skill), 2),
                    ml_boost=merged_ml,
                    description=combined_desc,
                    metadata=merged_meta
                )
            else:
                merged_moments.append(current)
                current = next_mom
                
        merged_moments.append(current)

        # 6. Sort final highlights descending by total score (highest quality first)
        merged_moments.sort(key=lambda m: m.total_score, reverse=True)

        return merged_moments

    def apply_ml_swings(self, moments: List[CandidateMoment], rounds_df: pd.DataFrame, kills_df: pd.DataFrame, bomb_df: pd.DataFrame, tick_rate: int):
        """
        Calculates win probability at start vs end of each highlight candidate,
        applying a proportional ML boost score.
        """
        for moment in moments:
            round_num = moment.round_number
            player_team = moment.metadata.get("attacker_team")
            if not player_team:
                player_team = moment.metadata.get("clutch_team")
            if not player_team or player_team == "unknown":
                player_team = "CT"  # default fallback
                
            r_rows = rounds_df[rounds_df["round_number"] == round_num]
            if r_rows.empty:
                continue
            r_row = r_rows.iloc[0]
            r_start = int(r_row["start_tick"])
            r_end = int(r_row["end_tick"])
            
            # Fetch events for this round
            r_kills = kills_df[kills_df["round_number"] == round_num]
            r_bombs = bomb_df[bomb_df["round_number"] == round_num]
            
            # Generate win probability timeline
            timeline = self.wp_model.get_round_timeline_wp(r_start, r_end, tick_rate, r_kills, r_bombs)
            if timeline.empty:
                continue
                
            # Determine highlight active window ticks
            active_start = moment.start_tick
            if "kills" in moment.metadata and moment.metadata["kills"]:
                active_start = moment.metadata["kills"][0]["tick"]
            elif "clutch_start_tick" in moment.metadata:
                active_start = moment.metadata["clutch_start_tick"]
                
            active_end = moment.end_tick
            if "kills" in moment.metadata and moment.metadata["kills"]:
                active_end = moment.metadata["kills"][-1]["tick"]
                
            # State before: closest tick in timeline < active_start
            before_rows = timeline[timeline["tick"] < active_start]
            if not before_rows.empty:
                wp_before = before_rows.iloc[-1]["win_prob"]
            else:
                wp_before = timeline.iloc[0]["win_prob"]
                
            # State after: closest tick in timeline >= active_end
            after_rows = timeline[timeline["tick"] >= active_end]
            if not after_rows.empty:
                wp_after = after_rows.iloc[0]["win_prob"]
            else:
                wp_after = timeline.iloc[-1]["win_prob"]
                
            # Calculate win probability swing for the player's team
            if player_team == "CT":
                swing = wp_after - wp_before
            else:
                swing = wp_before - wp_after
                
            swing = max(0.0, swing)
            ml_boost = round(swing * 5.0, 2)
            
            moment.ml_boost = ml_boost
            moment.metadata["wp_before"] = round(wp_before, 4)
            moment.metadata["wp_after"] = round(wp_after, 4)
            moment.metadata["wp_swing"] = round(swing, 4)
            
            if ml_boost > 0.1:
                moment.description += f" [ML Swing: +{ml_boost} (wp: {int(wp_before*100)}% -> {int(wp_after*100)}%)]"
