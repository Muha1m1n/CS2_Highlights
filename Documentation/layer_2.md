# CS2 Highlight Detector - Layer 2: Database & Caching Documentation

This document explains **Layer 2: Database & Caching** of the CS2 Highlight Detector and Scorer. It details the relational database schema, the caching logic, the ORM configuration, and the performance metrics.

---

## 1. Database Paradigm & Rationale

CS2 replay parsing takes roughly **1.5 to 3 seconds** depending on the demo file size. While this is fast, running it repeatedly when browsing a match dashboard results in a laggy user experience.

- **SQLite Cache**: We store parsed matches, rounds, kills, and bomb plants in a local database file (`matches.db`).
- **ORM (Object-Relational Mapping)**: We use **SQLAlchemy** to interface Python with SQL. This abstracts the raw queries into Python classes and guarantees type safety.
- **Why SQLite?**: Being local-first, it requires no setup, has zero network latency, is stored in a single file (`matches.db`), and is highly performant for concurrent reads.

---

## 2. Relational Database Schema

We define four tables in our database, mapped using SQLAlchemy:

```
┌─────────────────────────────────┐
│             matches             │
├─────────────────────────────────┤
│ sha256 (PK)                     │ ◄───┐
│ map_name                        │     │
│ tick_rate                       │     │
│ demo_path                       │     │
│ parsed_at                       │     │
└─────────────────────────────────┘     │ (Foreign Key match_hash)
                                        │
┌─────────────────────────────────┐     │
│             rounds              │     │
├─────────────────────────────────┤     │
│ id (PK)                         │     │
│ match_hash (FK) ────────────────┼─────┤
│ round_number                    │     │
│ start_tick, end_tick            │     │
│ winner_team, end_reason, message│     │
└─────────────────────────────────┘     │
                                        │
┌─────────────────────────────────┐     │
│              kills              │     │
├─────────────────────────────────┤     │
│ id (PK)                         │     │
│ match_hash (FK) ────────────────┼─────┤
│ round_number, tick              │     │
│ attacker_name, user_name        │     │
│ weapon, headshot, noscope, ...  │     │
└─────────────────────────────────┘     │
                                        │
┌─────────────────────────────────┐     │
│           bomb_events           │     │
├─────────────────────────────────┤     │
│ id (PK)                         │     │
│ match_hash (FK) ────────────────┼─────┘
│ round_number, tick, event_type  │
│ user_name, site                 │
└─────────────────────────────────┘
```

---

## 3. Caching Lifecycle Flow

When the user requests to parse a match file:
1. **Hash Generation**: We calculate the SHA-256 hash of the `.dem` file. This acts as a unique digital signature. Even if the file name changes, the signature remains identical.
2. **Cache Check**: The system queries the SQLite database for a match record matching the SHA-256 hash:
   - **Cache Hit (Instant)**: If the hash is found, we query the SQL tables. We map the round, kill, and bomb event records back into Pandas DataFrames and return them immediately, bypassing the parser.
   - **Cache Miss (Parse & Save)**: If the hash is missing:
     1. We invoke `CS2DemoParser` (Layer 1) to parse the demo file.
     2. We take the resulting metadata and DataFrames, instantiate the corresponding SQLAlchemy models, and perform bulk inserts to write them to SQLite.
     3. Subsequent requests for this match will now trigger a **Cache Hit**.

---

## 4. Code Architecture (`src/database.py`)

- **`MatchModel`, `RoundModel`, `KillModel`, `BombEventModel`**: Declarative database models mapped to SQL tables. Relationships are defined with `cascade="all, delete-orphan"` to clean up child data if a match is re-parsed.
- **`CS2Database`**: The database manager exposing key functions:
  - `get_file_hash(path)`: Fast hashing in chunks to prevent memory overhead on large files.
  - `is_match_cached(hash)`: Returns boolean cache status.
  - `save_match(...)`: Performs transaction-safe database writes. In case of failure, a rollback is executed to keep the database consistent.
  - `get_match_data(hash)`: Reconstructs Pandas DataFrames from database rows, maintaining compatibility with the rest of the application.

---

## 5. Performance Verification

Running the test script `test_database.py` produces the following benchmark metrics:

```text
==================================================
PERFORMANCE RATIO: PARSE VS DATABASE LOAD
==================================================
Parser Time   : 1.6190s
Database Load : 0.0110s
Database Cache is 147.0x FASTER than parsing the raw demo file!
```

### Key Takeaway
- **Parsing** requires reading, decoding, and parsing binary packets (CPU-intensive).
- **Database Loading** is a direct index query to SQLite (Disk/Memory-intensive).
- Bypassing the parser via the database cache yields a **140x+ speedup**, reducing UI wait times from seconds to virtually instantaneous.
