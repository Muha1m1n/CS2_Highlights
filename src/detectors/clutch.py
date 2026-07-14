import pandas as pd
from typing import List, Dict, Set
from src.detectors.base import AbstractDetector, CandidateMoment

class ClutchDetector(AbstractDetector):
    """
    Detects when a player is the last survivor on their team and successfully wins the round.
    """
    def __init__(self, pre_roll_seconds: float = 3.0, post_roll_seconds: float = 3.0):
        self.pre_roll_seconds = pre_roll_seconds
        self.post_roll_seconds = post_roll_seconds

    def detect(self, rounds_df: pd.DataFrame, kills_df: pd.DataFrame, bomb_df: pd.DataFrame, tick_rate: int) -> List[CandidateMoment]:
        moments = []
        if kills_df.empty or rounds_df.empty:
            return moments

        pre_roll_ticks = int(self.pre_roll_seconds * tick_rate)
        post_roll_ticks = int(self.post_roll_seconds * tick_rate)

        # 1. Build a match-wide player-to-team lookup map from the kills data
        player_teams: Dict[str, str] = {}
        for _, row in kills_df.iterrows():
            att = row["attacker_name"]
            vic = row["user_name"]
            att_team = row["attacker_team"]
            vic_team = row["user_team"]
            
            if att and att != "None" and att_team and att_team != "unknown":
                player_teams[att] = att_team
            if vic and vic != "None" and vic_team and vic_team != "unknown":
                player_teams[vic] = vic_team

        # 2. Iterate through each round to find clutches
        for _, r_row in rounds_df.iterrows():
            round_num = int(r_row["round_number"])
            r_start = int(r_row["start_tick"])
            r_end = int(r_row["end_tick"])
            winner = r_row["winner_team"]  # 'CT' or 'T'
            
            if not winner or winner == "":
                continue

            # Find all kills in this round, sorted chronologically
            round_kills = kills_df[kills_df["round_number"] == round_num].sort_values("tick")
            if round_kills.empty:
                continue

            # Determine who actively participated in this round
            round_players = set()
            for _, k in round_kills.iterrows():
                if k["attacker_name"] and k["attacker_name"] != "None":
                    round_players.add(k["attacker_name"])
                if k["user_name"] and k["user_name"] != "None":
                    round_players.add(k["user_name"])

            # Split them into CT and T rosters
            ct_roster = {p for p in round_players if player_teams.get(p) == "CT"}
            t_roster = {p for p in round_players if player_teams.get(p) == "T"}

            if not ct_roster or not t_roster:
                continue

            # Track who has died
            dead_players: Set[str] = set()
            clutch_opportunities = [] # Stores (player, clutch_start_tick, opponent_count)

            # Trace the kills tick-by-tick
            for _, kill in round_kills.iterrows():
                victim = kill["user_name"]
                tick = int(kill["tick"])
                
                if not victim or victim == "None":
                    continue
                    
                dead_players.add(victim)

                # Check CT team alive count
                ct_alive = ct_roster - dead_players
                t_alive = t_roster - dead_players

                # Scenario A: Only 1 CT alive, T has N >= 1 alive
                if len(ct_alive) == 1 and len(t_alive) >= 1:
                    clutch_player = list(ct_alive)[0]
                    # Only record if we haven't already marked this clutch_player in this round
                    if not any(co[0] == clutch_player for co in clutch_opportunities):
                        clutch_opportunities.append((clutch_player, tick, len(t_alive), "CT"))

                # Scenario B: Only 1 T alive, CT has N >= 1 alive
                if len(t_alive) == 1 and len(ct_alive) >= 1:
                    clutch_player = list(t_alive)[0]
                    if not any(co[0] == clutch_player for co in clutch_opportunities):
                        clutch_opportunities.append((clutch_player, tick, len(ct_alive), "T"))

            # Evaluate if any clutch opportunity succeeded
            for clutch_player, start_tick, opponent_count, player_team in clutch_opportunities:
                # Did the clutch player's team win the round?
                if player_team == winner:
                    # Determine base score based on opponent count (1vN)
                    if opponent_count == 1:
                        base_score = 2.0
                    elif opponent_count == 2:
                        base_score = 4.0
                    elif opponent_count == 3:
                        base_score = 7.0
                    elif opponent_count == 4:
                        base_score = 10.0
                    else:
                        base_score = 15.0

                    description = f"{clutch_player} Round {round_num} 1v{opponent_count} Clutch"
                    
                    # Buffer timestamps, clamping to round limits
                    clutch_start = max(r_start, start_tick - pre_roll_ticks)
                    clutch_end = min(r_end, r_end + post_roll_ticks)  # Clutches end at round end

                    metadata = {
                        "clutch_player": clutch_player,
                        "clutch_team": player_team,
                        "opponents_count": opponent_count,
                        "clutch_start_tick": start_tick
                    }

                    moments.append(CandidateMoment(
                        player_name=clutch_player,
                        round_number=round_num,
                        start_tick=clutch_start,
                        end_tick=clutch_end,
                        highlight_type=f"Clutch (1v{opponent_count})",
                        base_score=base_score,
                        skill_bonus=0.0,
                        description=description,
                        metadata=metadata
                    ))

        return moments
