"""
convert_voters.py
-----------------
Converts a list of voter JSON records (each with name, voter_id, election_id)
into a CSV Electoral Roll with format:

  Entry_Number, Name, Vector of which Elections he is eligible for

Usage:
  Option A - Load from a JSON file:
    1. Save your JSON array to voters_input.json
    2. Set INPUT_JSON_FILE = "voters_input.json"
    3. Run: python convert_voters.py

  Option B - Paste JSON directly into INPUT_JSON_DATA below.
"""

import json
import csv
import sys
import os
from collections import defaultdict

# ─── Configuration ───────────────────────────────────────────────────────────

# Path to an input JSON file (set to None to use inline data below)
INPUT_JSON_FILE = "voters.json"   # e.g. "voters_input.json" or None

# If INPUT_JSON_FILE is None, paste your JSON array here:
INPUT_JSON_DATA = """
[
  {"name": "Voter 0001", "voter_id": "V0001", "election_id": 1},
  {"name": "Voter 0002", "voter_id": "V0002", "election_id": 1}
]
"""

OUTPUT_CSV_FILE = "Electoral_Roll_1.csv"

# ─── Load data ───────────────────────────────────────────────────────────────

if INPUT_JSON_FILE and os.path.exists(INPUT_JSON_FILE):
    print(f"Loading from file: {INPUT_JSON_FILE}")
    with open(INPUT_JSON_FILE, "r", encoding="utf-8") as f:
        voters = json.load(f)
elif INPUT_JSON_FILE and not os.path.exists(INPUT_JSON_FILE):
    print(f"ERROR: File '{INPUT_JSON_FILE}' not found.", file=sys.stderr)
    print("Either create the file or set INPUT_JSON_FILE = None and paste data inline.", file=sys.stderr)
    sys.exit(1)
else:
    print("Loading from inline INPUT_JSON_DATA...")
    voters = json.loads(INPUT_JSON_DATA)

print(f"Loaded {len(voters)} voter records.")

# ─── Group elections per voter (handles voters in multiple elections) ─────────

voter_elections = defaultdict(lambda: {"name": "", "elections": set()})

for v in voters:
    vid = v["voter_id"]
    voter_elections[vid]["name"] = v["name"]
    voter_elections[vid]["elections"].add(int(v["election_id"]))

# ─── Write CSV ───────────────────────────────────────────────────────────────

with open(OUTPUT_CSV_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Entry_Number", "Name", "Vector"])

    for entry_num, (voter_id, info) in enumerate(voter_elections.items(), start=1):
        elections_vector = ";".join(f"E{eid}" for eid in sorted(info["elections"]))
        writer.writerow([entry_num, info["name"], elections_vector])

print(f"Done! Written {len(voter_elections)} unique voters to '{OUTPUT_CSV_FILE}'.")
