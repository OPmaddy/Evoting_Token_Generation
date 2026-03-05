import sqlite3
import pandas as pd
import os

DB_PATH = "voters.db"
ELECTORAL_ROLL_PATH = "./Electoral_Roll.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS voters (
    Entry_Number TEXT PRIMARY KEY,
    Name TEXT,
    EID_Vector TEXT,
    Token_Timestamp TEXT,
    TokenID TEXT,
    Image1Path TEXT,
    Image2Path TEXT,
    Booth_Number TEXT
);
"""


class VoterDB:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self):
        first_time = not os.path.exists(self.db_path)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(SCHEMA)
        
        # Migration: Ensure Booth_Number column exists
        try:
            cur.execute("ALTER TABLE voters ADD COLUMN Booth_Number TEXT")
        except sqlite3.OperationalError:
            # Column likely already exists
            pass

        conn.commit()

        if first_time:
            self._import_electoral_roll(conn)

        conn.close()

    def _import_electoral_roll(self, conn):
        df = pd.read_csv(ELECTORAL_ROLL_PATH)

        cur = conn.cursor()
        for _, r in df.iterrows():
            cur.execute(
                """
                INSERT OR IGNORE INTO voters
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL)
                """,
                (
                    str(r["Entry_Number"]).strip(),
                    r["Name"],
                    r["Vector of which Elections he is elidgible for"]
                )
            )
        conn.commit()

    def get_voter(self, entry_number: str):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM voters WHERE lower(Entry_Number)=?",
            (entry_number.lower(),)
        )

        row = cur.fetchone()
        conn.close()

        if not row:
            return None

        # Determine keys dynamically or hardcode based on schema
        # Current Schema order: Entry, Name, EID, Timestamp, TokenID, Img1, Img2, Booth
        keys = [
            "Entry_Number",
            "Name",
            "EID_Vector",
            "Token_Timestamp",
            "TokenID",
            "Image1Path",
            "Image2Path",
            "Booth_Number"
        ]
        
        # Handle case where row might have fewer fields if migration failed (unlikely but safe)
        if len(row) != len(keys):
             # Fallback if DB structure doesn't match keys exactly (should not happen with migration)
             pass 

        return dict(zip(keys, row))

    def has_token(self, voter: dict) -> bool:
        return voter["TokenID"] is not None
    
    def stage_token(
        self,
        entry_number,
        token_id,
        issued_at,
        img1,
        img2,
        booth
    ):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
    
        cur.execute(
            """
            UPDATE voters
            SET TokenID=?,
                Token_Timestamp=?,
                Image1Path=?,
                Image2Path=?,
                Booth_Number=?
            WHERE Entry_Number=?
            """,
            (token_id, issued_at, img1, img2, str(booth), entry_number)
        )
    
        conn.commit()
        conn.close()
