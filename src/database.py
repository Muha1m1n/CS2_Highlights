import os
import hashlib
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

Base = declarative_base()

class MatchModel(Base):
    __tablename__ = "matches"
    
    sha256 = Column(String(64), primary_key=True)
    map_name = Column(String(64), nullable=False)
    tick_rate = Column(Integer, nullable=False)
    demo_path = Column(String(512), nullable=False)
    parsed_at = Column(DateTime, default=datetime.utcnow)
    
    rounds = relationship("RoundModel", back_populates="match", cascade="all, delete-orphan")
    kills = relationship("KillModel", back_populates="match", cascade="all, delete-orphan")
    bomb_events = relationship("BombEventModel", back_populates="match", cascade="all, delete-orphan")

class RoundModel(Base):
    __tablename__ = "rounds"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_hash = Column(String(64), ForeignKey("matches.sha256"), nullable=False)
    round_number = Column(Integer, nullable=False)
    start_tick = Column(Integer, nullable=False)
    end_tick = Column(Integer, nullable=False)
    winner_team = Column(String(10), nullable=False)
    end_reason = Column(String(64), nullable=False)
    message = Column(String(256), nullable=False)
    
    match = relationship("MatchModel", back_populates="rounds")

class KillModel(Base):
    __tablename__ = "kills"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_hash = Column(String(64), ForeignKey("matches.sha256"), nullable=False)
    round_number = Column(Integer, nullable=False)
    tick = Column(Integer, nullable=False)
    attacker_name = Column(String(128), nullable=True)
    attacker_team = Column(String(10), nullable=True)  # 'CT' or 'T'
    user_name = Column(String(128), nullable=True)       # Victim name
    user_team = Column(String(10), nullable=True)      # Victim team ('CT' or 'T')
    weapon = Column(String(64), nullable=True)
    headshot = Column(Boolean, default=False)
    noscope = Column(Boolean, default=False)
    thrusmoke = Column(Boolean, default=False)
    penetrated = Column(Integer, default=0)
    
    match = relationship("MatchModel", back_populates="kills")

class BombEventModel(Base):
    __tablename__ = "bomb_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_hash = Column(String(64), ForeignKey("matches.sha256"), nullable=False)
    round_number = Column(Integer, nullable=False)
    tick = Column(Integer, nullable=False)
    event_type = Column(String(32), nullable=False)    # plant, defuse, explode
    user_name = Column(String(128), nullable=True)
    user_team = Column(String(10), nullable=True)      # 'CT' or 'T'
    site = Column(String(32), nullable=True)
    
    match = relationship("MatchModel", back_populates="bomb_events")


class CS2Database:
    """
    SQLAlchemy database wrapper for managing SQLite caching of parsed CS2 demo files.
    """
    def __init__(self, db_path: str = "data/processed/matches.db"):
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        
    @staticmethod
    def get_file_hash(file_path: str) -> str:
        """
        Computes SHA-256 hash of a file.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
            
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256.update(byte_block)
        return sha256.hexdigest()
        
    def is_match_cached(self, file_hash: str) -> bool:
        """
        Checks if the match is already cached in the database.
        """
        session = self.Session()
        try:
            match_exists = session.query(MatchModel).filter_by(sha256=file_hash).first() is not None
            return match_exists
        finally:
            session.close()
            
    def save_match(self, file_hash: str, demo_path: str, meta: dict, rounds_df: pd.DataFrame, kills_df: pd.DataFrame, bomb_df: pd.DataFrame):
        """
        Saves parsed match, rounds, kills, and bomb event records into SQLite.
        """
        session = self.Session()
        try:
            # Delete match if it already exists to avoid duplicate constraint errors
            existing_match = session.query(MatchModel).filter_by(sha256=file_hash).first()
            if existing_match:
                session.delete(existing_match)
                session.commit()
                
            # Create Match Entry
            match_record = MatchModel(
                sha256=file_hash,
                map_name=meta.get("map_name", "unknown"),
                tick_rate=meta.get("tick_rate", 64),
                demo_path=demo_path
            )
            session.add(match_record)
            session.flush()
            
            # 1. Rounds
            round_records = []
            if not rounds_df.empty:
                for _, row in rounds_df.iterrows():
                    round_records.append(RoundModel(
                        match_hash=file_hash,
                        round_number=int(row["round_number"]),
                        start_tick=int(row["start_tick"]),
                        end_tick=int(row["end_tick"]),
                        winner_team=str(row["winner_team"]),
                        end_reason=str(row["end_reason"]),
                        message=str(row["message"])
                    ))
                session.bulk_save_objects(round_records)
                
            # 2. Kills
            kill_records = []
            if not kills_df.empty:
                for _, row in kills_df.iterrows():
                    kill_records.append(KillModel(
                        match_hash=file_hash,
                        round_number=int(row["round_number"]),
                        tick=int(row["tick"]),
                        attacker_name=str(row["attacker_name"]) if not pd.isna(row["attacker_name"]) else None,
                        attacker_team=str(row["attacker_team"]) if not pd.isna(row["attacker_team"]) else None,
                        user_name=str(row["user_name"]) if not pd.isna(row["user_name"]) else None,
                        user_team=str(row["user_team"]) if not pd.isna(row["user_team"]) else None,
                        weapon=str(row["weapon"]) if not pd.isna(row["weapon"]) else None,
                        headshot=bool(row["headshot"]),
                        noscope=bool(row["noscope"]),
                        thrusmoke=bool(row["thrusmoke"]),
                        penetrated=int(row["penetrated"])
                    ))
                session.bulk_save_objects(kill_records)
                
            # 3. Bomb Events
            bomb_records = []
            if not bomb_df.empty:
                for _, row in bomb_df.iterrows():
                    bomb_records.append(BombEventModel(
                        match_hash=file_hash,
                        round_number=int(row["round_number"]),
                        tick=int(row["tick"]),
                        event_type=str(row["event_type"]),
                        user_name=str(row["user_name"]) if not pd.isna(row["user_name"]) else None,
                        user_team=str(row["user_team"]) if not pd.isna(row["user_team"]) else None,
                        site=str(row["site"]) if not pd.isna(row["site"]) else None
                    ))
                session.bulk_save_objects(bomb_records)
                
            session.commit()
            print(f"Successfully cached match {file_hash} to database.")
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
            
    def get_match_data(self, file_hash: str) -> tuple:
        """
        Retrieves cached match tables and parses them back into pandas DataFrames.
        """
        session = self.Session()
        try:
            match = session.query(MatchModel).filter_by(sha256=file_hash).first()
            if not match:
                raise KeyError(f"Match with hash {file_hash} not found in database.")
                
            meta = {
                "map_name": match.map_name,
                "tick_rate": match.tick_rate,
                "demo_path": match.demo_path
            }
            
            # Reconstruct Rounds DataFrame
            rounds = session.query(RoundModel).filter_by(match_hash=file_hash).order_by(RoundModel.round_number).all()
            rounds_list = [{
                "round_number": r.round_number,
                "start_tick": r.start_tick,
                "end_tick": r.end_tick,
                "winner_team": r.winner_team,
                "end_reason": r.end_reason,
                "message": r.message
            } for r in rounds]
            rounds_df = pd.DataFrame(rounds_list)
            
            # Reconstruct Kills DataFrame
            kills = session.query(KillModel).filter_by(match_hash=file_hash).order_by(KillModel.tick).all()
            kills_list = [{
                "tick": k.tick,
                "round_number": k.round_number,
                "attacker_name": k.attacker_name,
                "attacker_team": k.attacker_team,
                "user_name": k.user_name,
                "user_team": k.user_team,
                "weapon": k.weapon,
                "headshot": k.headshot,
                "noscope": k.noscope,
                "thrusmoke": k.thrusmoke,
                "penetrated": k.penetrated
            } for k in kills]
            kills_df = pd.DataFrame(kills_list)
            
            # Reconstruct Bomb Events DataFrame
            bombs = session.query(BombEventModel).filter_by(match_hash=file_hash).order_by(BombEventModel.tick).all()
            bombs_list = [{
                "tick": b.tick,
                "round_number": b.round_number,
                "event_type": b.event_type,
                "user_name": b.user_name,
                "user_team": b.user_team,
                "site": b.site
            } for b in bombs]
            bomb_df = pd.DataFrame(bombs_list)
            if bomb_df.empty:
                bomb_df = pd.DataFrame(columns=["tick", "round_number", "event_type", "user_name", "user_team", "site"])
                
            return meta, rounds_df, kills_df, bomb_df
        finally:
            session.close()
