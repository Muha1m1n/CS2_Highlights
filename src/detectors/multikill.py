import pandas as pd
from typing import List
from src.detectors.base import AbstractDetector, CandidateMoment

class MultiKillDetector(AbstractDetector):
    """
    Detects when a player gets multiple kills in a round within a sliding time window.
    """
    def __init__(self, window_seconds: float = 15.0, pre_roll_seconds: float = 5.0, post_roll_seconds: float = 3.0):
        self.window_seconds = window_seconds
        self.pre_roll_seconds = pre_roll_seconds
        self.post_roll_seconds = post_roll_seconds

    def detect(self, rounds_df: pd.DataFrame, kills_df: pd.DataFrame, bomb_df: pd.DataFrame, tick_rate: int) -> List[CandidateMoment]:
        moments = []
        if kills_df.empty or rounds_df.empty:
            return moments

        window_ticks = int(self.window_seconds * tick_rate)
        pre_roll_ticks = int(self.pre_roll_seconds * tick_rate)
        post_roll_ticks = int(self.post_roll_seconds * tick_rate)

        # Map round start/end ticks for fast lookup
        round_limits = {
            r["round_number"]: (r["start_tick"], r["end_tick"]) 
            for _, r in rounds_df.iterrows()
        }

        # Group kills by round and attacker
        grouped = kills_df.groupby(["round_number", "attacker_name"])

        for (round_num, attacker), group in grouped:
            if not attacker or pd.isna(attacker) or attacker == "None":
                continue

            # Sort kills in the round chronologically
            round_kills = group.sort_values("tick")
            if len(round_kills) < 2:
                continue

            # Group kills into clusters where each kill is within window_ticks of the previous one
            clusters = []
            current_cluster = []

            for _, kill in round_kills.iterrows():
                if not current_cluster:
                    current_cluster.append(kill)
                else:
                    last_kill = current_cluster[-1]
                    if kill["tick"] - last_kill["tick"] <= window_ticks:
                        current_cluster.append(kill)
                    else:
                        if len(current_cluster) >= 2:
                            clusters.append(current_cluster)
                        current_cluster = [kill]

            if len(current_cluster) >= 2:
                clusters.append(current_cluster)

            # Process each cluster into a CandidateMoment
            for cluster in clusters:
                num_kills = len(cluster)
                first_kill_tick = int(cluster[0]["tick"])
                last_kill_tick = int(cluster[-1]["tick"])
                
                # Fetch round boundaries
                r_start, r_end = round_limits.get(round_num, (first_kill_tick, last_kill_tick))

                # Apply pre-roll/post-roll buffers, clamped to round start/end
                start_tick = max(r_start, first_kill_tick - pre_roll_ticks)
                end_tick = min(r_end, last_kill_tick + post_roll_ticks)

                # Determine base score
                if num_kills == 2:
                    base_score = 1.0
                    name_type = "2K"
                elif num_kills == 3:
                    base_score = 3.0
                    name_type = "3K"
                elif num_kills == 4:
                    base_score = 6.0
                    name_type = "4K"
                else:
                    base_score = 10.0
                    name_type = "ACE" if num_kills == 5 else f"{num_kills}K"

                weapons = list(set([k["weapon"] for k in cluster if k["weapon"]]))
                weapon_str = weapons[0] if len(weapons) == 1 else "multiple"
                headshots = sum(1 for k in cluster if k["headshot"])

                description = f"{attacker} Round {round_num} {name_type} ({weapon_str})"
                if headshots > 0:
                    description += f" - {headshots} HS"

                # Capture list of ticks and player details in metadata
                metadata = {
                    "kills": [{
                        "tick": int(k["tick"]),
                        "victim": k["user_name"],
                        "weapon": k["weapon"],
                        "headshot": bool(k["headshot"])
                    } for k in cluster],
                    "attacker_team": cluster[0]["attacker_team"]
                }

                moments.append(CandidateMoment(
                    player_name=attacker,
                    round_number=round_num,
                    start_tick=start_tick,
                    end_tick=end_tick,
                    highlight_type=f"Multi-Kill ({name_type})",
                    base_score=base_score,
                    skill_bonus=0.0,  # Calculated in Layer 3/4 later
                    description=description,
                    metadata=metadata
                ))

        return moments
