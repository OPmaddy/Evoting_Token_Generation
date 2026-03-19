"""
One-time script to import the Electoral Roll CSV into MongoDB.

Usage:
    python db_init.py                                      # uses default CSV path
    python db_init.py --csv /path/to/Electoral_Roll.csv    # custom CSV path
    python db_init.py --drop                               # drop existing collection first
"""

import argparse
import csv
import sys

from pymongo import MongoClient
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION, ELECTORAL_ROLL_CSV


def import_electoral_roll(csv_path: str, drop_existing: bool = False):
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    collection = db[MONGO_COLLECTION]

    if drop_existing:
        print(f"Dropping existing collection '{MONGO_COLLECTION}' ...")
        collection.drop()

    # Ensure unique index
    collection.create_index("entry_number", unique=True)

    # Read CSV
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print(f"ERROR: CSV file not found at '{csv_path}'")
        sys.exit(1)

    if not rows:
        print("WARNING: CSV file is empty, nothing to import.")
        return

    inserted = 0
    skipped = 0

    for row in rows:
        entry_number = row.get("Entry_Number", "").strip()
        name = row.get("Name", "").strip()
        eid_vector = row.get("Vector of which Elections he is elidgible for", "").strip()

        if not entry_number:
            continue

        doc = {
            "entry_number": entry_number,
            "name": name,
            "eid_vector": eid_vector,
            "status": "not_generated",
            "device_id": None,
            "token_id": None,
            "token_timestamp": None,
            "booth_number": None,
            "requested_at": None,
            "generated_at": None,
        }

        try:
            collection.insert_one(doc)
            inserted += 1
            print(f"  ✓ {entry_number} — {name}")
        except Exception:
            # Likely duplicate key
            skipped += 1
            print(f"  ⊘ {entry_number} — already exists, skipped")

    print(f"\nDone. Inserted: {inserted}, Skipped (duplicates): {skipped}")
    print(f"Total voters in collection: {collection.count_documents({})}")

    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import Electoral Roll into MongoDB")
    parser.add_argument(
        "--csv",
        default=ELECTORAL_ROLL_CSV,
        help=f"Path to Electoral_Roll.csv (default: {ELECTORAL_ROLL_CSV})",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop the existing collection before importing",
    )
    args = parser.parse_args()

    print(f"Importing from: {args.csv}")
    print(f"MongoDB: {MONGO_URI} → {MONGO_DB_NAME}.{MONGO_COLLECTION}")
    print()

    import_electoral_roll(args.csv, drop_existing=args.drop)
