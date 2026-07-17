from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any
import pandas as pd

@dataclass
class CandidateMoment:
    player_name: str
    round_number: int
    start_tick: int
    end_tick: int
    highlight_type: str
    base_score: float
    skill_bonus: float
    description: str
    ml_boost: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_score(self) -> float:
        return self.base_score + self.skill_bonus + self.ml_boost

    @property
    def kill_count(self) -> int:
        """
        Returns the exact number of kills in this highlight moment for strict kill-tier ranking
        (Ace/5K+ = 5, 4K = 4, 3K = 3, 2K = 2, 1K/Clutch = 1).
        """
        kills = self.metadata.get("kills", [])
        if isinstance(kills, list) and len(kills) > 0:
            return len(kills)
            
        # Fallback string parsing from highlight_type or description
        text = f"{self.highlight_type} {self.description}".upper()
        if any(token in text for token in ("ACE", "5K", "6K", "7K")):
            return 5
        if "4K" in text:
            return 4
        if "3K" in text:
            return 3
        if "2K" in text:
            return 2
        return 1

class AbstractDetector(ABC):
    """
    Abstract Base Class for all highlight detectors.
    """
    @abstractmethod
    def detect(self, rounds_df: pd.DataFrame, kills_df: pd.DataFrame, bomb_df: pd.DataFrame, tick_rate: int) -> List[CandidateMoment]:
        """
        Scans match event dataframes and extracts candidate highlights.
        """
        pass
