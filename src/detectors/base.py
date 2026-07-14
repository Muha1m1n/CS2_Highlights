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
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_score(self) -> float:
        return self.base_score + self.skill_bonus

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
