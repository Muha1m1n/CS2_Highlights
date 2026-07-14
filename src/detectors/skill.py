import pandas as pd
from typing import List
from src.detectors.base import AbstractDetector, CandidateMoment

class SkillDetector(AbstractDetector):
    """
    Detects standalone mechanical flair highlights (e.g. knife/Zeus kills, wallbangs, no-scopes)
    and provides utility to enrich other highlights (multi-kills, clutches) with skill bonuses.
    """
    def __init__(self, score_threshold: float = 1.5, pre_roll_seconds: float = 4.0, post_roll_seconds: float = 2.0):
        self.score_threshold = score_threshold
        self.pre_roll_seconds = pre_roll_seconds
        self.post_roll_seconds = post_roll_seconds

    @staticmethod
    def calculate_kill_bonus(kill: pd.Series) -> float:
        """
        Calculates the skill bonus score for a single kill event based on flags.
        """
        bonus = 0.0
        
        # 1. Headshot
        if bool(kill.get("headshot", False)):
            bonus += 0.2
            
        # 2. No-scope
        if bool(kill.get("noscope", False)):
            bonus += 1.5
            
        # 3. Through smoke
        if bool(kill.get("thrusmoke", False)):
            bonus += 1.2
            
        # 4. Wallbang (penetrated count)
        penetrations = int(kill.get("penetrated", 0))
        if penetrations > 0:
            bonus += 1.0 * penetrations
            
        # 5. Exotic weapon choices
        weapon = str(kill.get("weapon", "")).lower()
        if "knife" in weapon or "bayonet" in weapon or "dagger" in weapon:
            bonus += 3.0
        elif "zeus" in weapon or "taser" in weapon:
            bonus += 2.5
            
        return bonus

    def detect(self, rounds_df: pd.DataFrame, kills_df: pd.DataFrame, bomb_df: pd.DataFrame, tick_rate: int) -> List[CandidateMoment]:
        moments = []
        if kills_df.empty or rounds_df.empty:
            return moments

        pre_roll_ticks = int(self.pre_roll_seconds * tick_rate)
        post_roll_ticks = int(self.post_roll_seconds * tick_rate)

        # Map round limits
        round_limits = {
            r["round_number"]: (r["start_tick"], r["end_tick"]) 
            for _, r in rounds_df.iterrows()
        }

        # Scan all kills in the match for high-difficulty single kills
        for _, kill in kills_df.iterrows():
            attacker = kill["attacker_name"]
            round_num = kill["round_number"]
            tick = int(kill["tick"])
            weapon = kill["weapon"]
            
            if not attacker or attacker == "None":
                continue

            # Compute skill bonus
            skill_bonus = self.calculate_kill_bonus(kill)
            
            # Base score for a single kill is 0.5
            base_score = 0.5
            total_score = base_score + skill_bonus

            # If it exceeds the threshold (e.g. 1.5), register as standalone highlight
            if total_score >= self.score_threshold:
                r_start, r_end = round_limits.get(round_num, (tick, tick))
                start_tick = max(r_start, tick - pre_roll_ticks)
                end_tick = min(r_end, tick + post_roll_ticks)

                # Build descriptive label
                flairs = []
                if "knife" in str(weapon).lower():
                    flairs.append("Knife Kill")
                elif "zeus" in str(weapon).lower():
                    flairs.append("Zeus Kill")
                else:
                    if kill["noscope"]:
                        flairs.append("No-Scope")
                    if kill["thrusmoke"]:
                        flairs.append("Thru-Smoke")
                    if kill["penetrated"] > 0:
                        flairs.append("Wallbang")

                flair_str = " + ".join(flairs) if flairs else "Skill Shot"
                description = f"{attacker} Round {round_num} - {flair_str} ({weapon})"
                
                metadata = {
                    "weapon": weapon,
                    "headshot": bool(kill["headshot"]),
                    "noscope": bool(kill["noscope"]),
                    "thrusmoke": bool(kill["thrusmoke"]),
                    "penetrated": int(kill["penetrated"]),
                    "attacker_team": kill["attacker_team"]
                }

                moments.append(CandidateMoment(
                    player_name=attacker,
                    round_number=int(round_num),
                    start_tick=start_tick,
                    end_tick=end_tick,
                    highlight_type=f"Skill Shot ({flair_str})",
                    base_score=base_score,
                    skill_bonus=skill_bonus,
                    description=description,
                    metadata=metadata
                ))

        return moments

    def apply_skill_bonuses(self, moments: List[CandidateMoment], kills_df: pd.DataFrame):
        """
        Enriches existing CandidateMoments with skill bonuses based on the kills that occurred
        within their tick windows.
        """
        if kills_df.empty:
            return

        for moment in moments:
            # Only apply if it's not already a single Skill Shot (which has its bonus pre-computed)
            if moment.highlight_type.startswith("Skill Shot"):
                continue

            # Find all kills by this player in this round during this highlight tick window
            matching_kills = kills_df[
                (kills_df["round_number"] == moment.round_number) &
                (kills_df["attacker_name"] == moment.player_name) &
                (kills_df["tick"] >= moment.start_tick) &
                (kills_df["tick"] <= moment.end_tick)
            ]

            total_bonus = 0.0
            for _, kill in matching_kills.iterrows():
                total_bonus += self.calculate_kill_bonus(kill)
            
            moment.skill_bonus = round(total_bonus, 2)
            
            # Append bonus keywords to description if present
            bonuses = []
            has_hs = matching_kills["headshot"].any()
            has_ns = matching_kills["noscope"].any()
            has_wb = (matching_kills["penetrated"] > 0).any()
            
            if has_hs:
                bonuses.append("HS")
            if has_ns:
                bonuses.append("NoScope")
            if has_wb:
                bonuses.append("Wallbang")
                
            if bonuses:
                moment.description += f" [+{', '.join(bonuses)}]"
