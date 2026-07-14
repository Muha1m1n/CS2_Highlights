import pandas as pd
from typing import List
from src.detectors.base import CandidateMoment
from src.detectors.multikill import MultiKillDetector
from src.detectors.clutch import ClutchDetector
from src.detectors.skill import SkillDetector

class CS2DetectorEngine:
    """
    Main orchestration engine that runs all highlight detectors, enriches moments with bonuses,
    de-duplicates overlapping windows, and sorts them by final score.
    """
    def __init__(self):
        self.multikill_detector = MultiKillDetector()
        self.clutch_detector = ClutchDetector()
        self.skill_detector = SkillDetector()

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

        # 4. De-duplicate and merge overlapping windows for the same player in the same round
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
                # If they are duplicates of the same type, keep single name
                if current.highlight_type == next_mom.highlight_type:
                    combined_type = current.highlight_type
                
                combined_desc = f"{current.description} and {next_mom.highlight_type}"
                if current.highlight_type == next_mom.highlight_type:
                    combined_desc = current.description
                    
                # Score merging: max of total scores, then assign base and skill
                max_score = max(current.total_score, next_mom.total_score)
                # Keep the base score of the higher one, adjust skill bonus to match
                if current.total_score >= next_mom.total_score:
                    merged_base = current.base_score
                    merged_skill = max_score - merged_base
                else:
                    merged_base = next_mom.base_score
                    merged_skill = max_score - merged_base

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
                    skill_bonus=round(merged_skill, 2),
                    description=combined_desc,
                    metadata=merged_meta
                )
            else:
                merged_moments.append(current)
                current = next_mom
                
        merged_moments.append(current)

        # 5. Sort final highlights descending by total score (highest quality first)
        merged_moments.sort(key=lambda m: m.total_score, reverse=True)

        return merged_moments
