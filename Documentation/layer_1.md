# CS2 Highlight Detector - Layer 1: Parsing & Ingestion Documentation

This document explains **Layer 1: Parsing & Ingestion** of the Counter-Strike 2 (CS2) Highlight Detector and Scorer. It covers the technical concepts of replays, the library we use, the code architecture of `src/parser.py`, and the validation process.

---

## 1. What is a CS2 Replay (.dem)?

A CS2 replay file (ending in `.dem`) is **not a video file**. It is a packet-by-packet recording of all the data exchanged between the game server and the players during a match. It contains:
- **Ticks**: Replays are recorded in snapshots called "ticks." A standard CS2 match runs at **64 ticks per second** (or 128 ticks for custom servers). A 45-minute match can contain over 170,000 ticks.
- **Events**: The game engine logs specific milestones as "game events" (e.g., player deaths, round starts, bomb plants, grenade throws).
- **Entities**: The positions $(X, Y, Z)$, health, armor, inventory, and viewing angles of all 10 players at every tick.

To extract this raw binary data into a readable format for Python, we use **`demoparser2`**, a high-performance parser compiled in Rust that translates binary replays into structured dataframes (Tables) in milliseconds.

---

## 2. Ingestion Code Architecture (`src/parser.py`)

Our parsing engine is written inside `src/parser.py`. It is structured as a class called `CS2DemoParser`. Here is a detailed breakdown of its properties and methods:

### Class Initialization
```python
def __init__(self, demo_path: str):
    self.demo_path = demo_path
    self.parser = DemoParser(demo_path)  # The Rust parser instance
    self.header = None
    self.tick_rate = 64                  # Default fallback
    self.map_name = "unknown"
```
When instantiated, it checks if the file exists and initializes the underlying Rust `DemoParser`.

---

### Core Methods & Logic

#### 1. `parse_metadata()`
Reads the header block of the demo file to extract match metadata:
- **Map Name**: The map played (e.g. `de_ancient`, `de_mirage`).
- **Tick Rate**: The frequency of ticks. Crucial because it translates demo ticks into seconds:
  $$\text{Seconds} = \frac{\text{Tick}}{\text{Tick Rate}}$$
  If the tick rate is missing or invalid, we default to `64`.

#### 2. `parse_rounds()`
CS2 demos do not have a built-in table of rounds. Instead, they record a stream of events like `round_start` and `round_end`. We reconstruct the rounds using an **Event Pairing Algorithm**:

```
[Start Event] Tick 100 ────► Active Round Gameplay ────► [End Event] Tick 8400
      │                                                         │
      └────────────────── Reconstructed Round 1 ────────────────┘
```

- **The Algorithm**:
  1. We parse all `round_start` ticks and sort them.
  2. We parse all `round_end` ticks.
  3. For every `round_end` event, we search backward to find the **most recent** `round_start` tick that occurred before it.
  4. This pairs them together into a round segment spanning `[start_tick, end_tick]`.
- **Warmups & Restarts**: By always matching a round end to the *most recent* round start, we automatically filter out aborted rounds or restarts (which have no matching `round_end` event in the main gameplay stream).
- **Data Extracted**:
  - `winner_team`: Who won the round (`"T"` or `"CT"`).
  - `end_reason`: Why the round ended (e.g. `ct_killed`, `t_killed`, `bomb_defused`, `target_bombed`, `ct_surrender`).
  - `message`: Game log end message.

#### 3. `parse_kills(rounds_df)`
Extracts the detailed kill feed (`player_death` events) and maps them to their respective round numbers.
- **Round Mapping**: We loop through our reconstructed rounds. If a kill's `tick` falls between a round's `start_tick` and `end_tick`, we tag that kill with that `round_number`. Kills occurring during warmup or after the match ends are discarded.
- **Flag Standardization**:
  - **`headshot`**: Hit target in the head (boolean).
  - **`noscope`**: Fired a sniper rifle without scoping (boolean).
  - **`thrusmoke`**: Shot passed through a smoke grenade (boolean).
  - **`penetrated`**: Number of objects or walls the bullet penetrated before killing the target (integer).

#### 4. `parse_bomb_events(rounds_df)`
Extracts objective events: `bomb_planted` (plant), `bomb_defused` (defuse), and `bomb_exploded` (explode).
- We merge these three separate event lists into a single chronological timeline.
- We map them to their correct round number using tick boundaries.
- We extract the player name who performed the action and the site (e.g. site ID `172`, which maps to Site A or B).

---

## 3. Data Flow Diagram

This diagram visualizes how data flows from the binary demo file to our structured Python tables:

```
┌─────────────────────────────────┐
│     Raw Replay (.dem File)      │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│          demoparser2            │  (Rust Engine)
└────────────────┬────────────────┘
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
     [Starts]  [Ends]  [Deaths]      (Raw Event Data)
        │        │        │
        └────┬───┘        │
             ▼            │
      [Round Pairing]     │
             │            │
             ▼            ▼
         [Rounds] ───► [Kills]       (Round-mapped Dataframes)
```

---

## 4. Verification Test (`test_parser.py`)

To verify Layer 1 is working, we created a test script called `test_parser.py` which:
1. Locates the sample demo `match730_003830814863983116618_0173473800_161.dem` in the `Demo_Data` folder.
2. Initializes `CS2DemoParser`.
3. Prints parsed metadata, rounds, kills, and bomb plants.

### Example Console Output
If you run `python test_parser.py`, you will see:
```text
Testing parser on: Demo_Data\match730_003830814863983116618_0173473800_161.dem

--- Parsing Metadata ---
{'map_name': 'de_ancient', 'tick_rate': 64, 'snapshot_rate': 64, ...}

--- Parsing Rounds ---
Parsed 2 rounds.
   start_tick  end_tick winner_team    end_reason message  round_number
0          65      6737           T     ct_killed                     1
1        7185      7955           T  ct_surrender                     2

--- Parsing Kills ---
Parsed 5 kills.
   tick  round_number attacker_name       user_name        weapon  headshot
0  3007             1        Mahyar       Shigaraki         glock     False
1  3717             1        Mahyar          Artexl         glock     False
...
```
This output proves that the parsing, round pairing, and kill mapping logic is fully functioning and ready to feed into our database caching layer (Layer 2).
