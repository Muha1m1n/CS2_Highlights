# CS2 Highlight Detector - Layer 4: Machine Learning & Scoring

This document explains **Layer 4: Machine Learning & Scoring** of the CS2 Highlight Detector and Scorer. It details the game state features, the Random Forest classifier model, fallback math-based heuristics, and the round win-probability swing boost calculation.

---

## 1. Machine Learning Paradigm

While Layer 3 detects highlight actions (such as multi-kills or clutches), it does not understand the tactical impact or narrative significance of those actions. 

- **Tactical Context**: Getting 2 kills in a 5v1 round is easy and low tension. Getting 2 kills in a 2v5 round to defuse the bomb is a dramatic round-saving play.
- **Machine Learning Integration**: Layer 4 uses a **Random Forest Classifier** to estimate the live win probability of the Counter-Terrorist team at any given tick.
- **Win Probability Swing ($\Delta WP$)**: By measuring the change in win probability from just *before* a highlight starts to just *after* it ends, we calculate the highlight's tactical impact. High-swing highlights receive a score boost, ranking them higher in the final playlist.

---

## 2. Feature Engineering & State Snapshots

We construct a training matrix $X$ and outcome vector $y$ by scanning all historical rounds in our SQLite database. For every death event and bomb plant, we record:

### Features ($X$)
1.  **`ct_alive`**: Integer (0 to 5) - Count of Counter-Terrorists alive.
2.  **`t_alive`**: Integer (0 to 5) - Count of Terrorists alive.
3.  **`time_remaining`**: Float (0.0 to 115.0) - Seconds left in the round.
    - If the bomb is planted, this represents the seconds remaining before explosion (0.0 to 40.0).
4.  **`bomb_planted`**: Binary (0 or 1) - `1` if bomb is planted, `0` otherwise.

### Target Label ($y$)
*   **`ct_won`**: Binary (0 or 1) - `1` if the CT team won the round, `0` if the T team won.

---

## 3. Dynamic Model Lifecycle (`src/ml_model.py`)

- **Automatic Training**: Every time the detector engine initializes, it automatically queries SQLite for historical match records. It reconstructs the tick-by-tick round states and trains the Random Forest model on these snapshots.
- **Model Serialization**: The model is saved as a binary file (`win_prob_rf.pkl`) in `data/processed/` using Python's standard `pickle` library, allowing instant load times on future runs.
- **Robust Fallback Heuristic**: If the SQLite database is empty (e.g., when a user runs the app for the first time), the engine automatically falls back to a math-based heuristic formula that models CS2 win probability (CT/T alive ratio adjusted for bomb plant and time pressure). This ensures the app is fully functional out-of-the-box.

---

## 4. Scoring: Hype Boost Calculations

For any Candidate Moment, we look up the CT win probability before ($WP_{\text{before}}$) and after ($WP_{\text{after}}$) the moment's action in the round timeline.

- **CT Player Swing**:
  $$\Delta WP = WP_{\text{after}} - WP_{\text{before}}$$
- **T Player Swing** (since T win chance is $1.0 - WP_{\text{CT}}$):
  $$\Delta WP = WP_{\text{before}} - WP_{\text{after}}$$

We clamp the swing to be at least $0.0$ and calculate the ML Boost:
$$\text{ML Boost} = \text{max}(0.0, \Delta WP) \times 5.0$$

The maximum possible ML boost is **`+5.0` points** (representing a full 100% win probability swing).

---

## 5. Benchmark Performance & Generalization

During the validation run on our test database:
- **Training Dataset**: The model successfully extracted **359 game states** from our two cached matches and trained the Random Forest in under 2 seconds.
- **Evaluation Speed**: Running win probability lookups for all 43 candidate moments took just **`0.085` seconds**, maintaining instant response times.
- **Rank Shift Impact**:
  - `ali`'s 4K in Round 4 swung the win probability from **44% to 2%** in favor of T, receiving a **`+2.15` ML boost** and climbing to **Rank #1** with a total score of **`8.8`**.
  - `Baagad billa`'s 3K in Round 11 swung the win probability from **30% to 97%** in favor of CT, receiving a **`+3.37` ML boost** (Score: `6.4`), successfully outranking standard clutches.
  - `Baagad billa`'s 2K in Round 15 swung the win probability from **79% to 10%** in favor of T, receiving a **`+3.45` ML boost** (Score: `4.7`).
