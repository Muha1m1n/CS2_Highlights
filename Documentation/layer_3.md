# CS2 Highlight Detector - Layer 3: Rules-Based Moment Detection

This document explains **Layer 3: Rules-Based Moment Detection** of the CS2 Highlight Detector and Scorer. It details the modular highlight detectors, time clustering, de-duplication merging algorithms, and the rules-based scoring mechanics.

---

## 1. Modular Architecture

Layer 3 uses an abstract plugin architecture to make it easy to extend highlight detection. We define:

1. **`CandidateMoment`**: A data class holding metadata, time ranges (ticks), highlight description, and scores.
2. **`AbstractDetector`**: An interface requiring a `detect` function that returns a list of candidate moments.
3. **`CS2DetectorEngine`**: The central orchestrator that runs all detectors, applies skill modifiers, merges overlapping tick windows, and ranks candidates.

```
                  ┌─────────────────────────────────────┐
                  │          SQLite Database            │
                  └──────────────────┬──────────────────┘
                                     │
                 ┌───────────────────┼───────────────────┐
                 ▼                   ▼                   ▼
      ┌─────────────────────┐ ┌─────────────┐ ┌─────────────────────┐
      │  MultiKillDetector  │ │  Clutch     │ │    SkillDetector    │
      │  (15s Time Window)  │ │  Detector   │ │ (Stand-alone shots│
      │                     │ │  (1vN State)│ │  & bonus applier)  │
      └──────────┬──────────┘ └──────┬──────┘ └──────────┬──────────┘
                 │                   │                   │
                 └───────────────────┼───────────────────┘
                                     ▼
                  ┌─────────────────────────────────────┐
                  │         De-duplication Merger       │
                  │  (Combines overlapping tick ranges) │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │    Sorted Highlights List Output    │
                  └─────────────────────────────────────┘
```

---

## 2. Highlight Detection Logic

### A. Multi-Kill Detector (`multikill.py`)
- **Concept**: Finds rounds where a single player gets multiple kills.
- **Window Clustering**: Kills can be spread out. We cluster consecutive kills by the same player in a round if they happen within **15 seconds** of each other:
  $$\Delta t = t_i - t_{i-1} \le 15\text{s}$$
- **Tick Buffers**: To make sure clips are clean, highlights are padded with a **5-second pre-roll** (before the first kill) and a **3-second post-roll** (after the last kill), clamped to round boundaries.
- **Base Heuristic Scores**:
  - **2 Kills**: 1.0
  - **3 Kills**: 3.0
  - **4 Kills**: 6.0
  - **5+ Kills (Ace)**: 10.0

### B. Clutch Detector (`clutch.py`)
- **Concept**: Detects successful 1vN rounds where the last surviving player wins the round for their team.
- **Dynamic Roster Tracing**: To handle disconnections and varying game formats (e.g. 5v5 vs 2v2), the detector dynamically resolves active rosters in each round by unioning attackers and victims.
- **State Tracing**: Scans death events chronologically. The clutch state triggers at tick $T_c$ when teammate count drops to exactly `1` while enemies alive count is $N \ge 1$.
- **Outcome Check**: If the round winner matches the clutch player's team, the clutch is flagged as successful.
- **Base Heuristic Scores**:
  - **1v1**: 2.0 | **1v2**: 4.0 | **1v3**: 7.0 | **1v4**: 10.0 | **1v5**: 15.0

### C. Skill Flair Detector (`skill.py`)
- **Concept**: Scans for mechanical skill modifiers (Headshot, No-scope, Through Smoke, Wallbang, Knife/Zeus kills).
- **Dual-Purpose Design**:
  1. **Stand-alone Highlights**: Registers single rare kills (like knife kills, Zeus kills, or no-scopes) if their score exceeds a threshold ($\ge 1.5$).
  2. **Bonus Enricher**: Modifies existing multi-kill and clutch highlights, adding bonus points for headshots or wallbangs that occurred within their tick ranges:
     - **Headshot**: $+0.2$
     - **Wallbang (Penetrated)**: $+1.0 \times \text{walls}$
     - **Through Smoke**: $+1.2$
     - **No-Scope Sniper**: $+1.5$
     - **Knife Kill**: $+3.0$
     - **Zeus / Taser**: $+2.5$

---

## 3. De-duplication Merging Algorithm

If a player gets a 3-kill round and one of those kills secure a 1v2 clutch, they will trigger both the Clutch and Multi-Kill detectors. This results in overlapping clip windows.

- **Overlapping Merge**: The engine sorts moments by round, player, and start tick. If the start tick of a moment is less than or equal to the end tick of the previous moment, they are merged.
- **Merged Fields**:
  - **Ticks**: $\text{start\_tick} = \min(s_1, s_2)$ and $\text{end\_tick} = \max(e_1, e_2)$
  - **Scores**: Combined score = $\max(\text{score}_1, \text{score}_2)$
  - **Label**: Combined type, e.g. `Multi-Kill (2K) + Clutch (1v1)`

---

## 4. Benchmark Validation (`test_detectors.py`)

Running the detector engine on our 21-round competitive match (149 total kills) returned the following metrics:
- **Duration**: Highlight detection takes **`0.08` seconds** from SQLite cache data.
- **Highlights Discovered**: 43 distinct highlight candidates.
- **Top Highlights Ranked**:
  1. Round 3: `Baagad billa` 1v3 Clutch (Score: `7.0`)
  2. Round 7: `BabaYaga` 1v3 Clutch (Score: `7.0`)
  3. Round 4: `ali` 4K with AK-47 including 3 Headshots (Score: `6.6`)
  4. Round 16: `Gagalusconi` 2K with AWP + AWP Through Smoke (Score: `2.4`)
  5. Round 21: `Gagalusconi` AWP Wallbang kill (Score: `2.0`)
