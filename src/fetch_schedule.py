import argparse
import csv
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

API_BASE = "https://api.football-data.org/v4"
COMPETITION_CODE = "PL"  # Premier League


def iso_date(d: str) -> str:
    # Accept YYYY-MM-DD and return ISO date
    try:
        return datetime.fromisoformat(d).date().isoformat()
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Invalid date: {d}. Use YYYY-MM-DD") from e


def fetch_matches(start_date: str, end_date: str, token: str) -> Dict[str, Any]:
    url = f"{API_BASE}/competitions/{COMPETITION_CODE}/matches"
    headers = {"X-Auth-Token": token}
    params = {
        "dateFrom": start_date,
        "dateTo": end_date,
    }
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def normalize_match(m: Dict[str, Any]) -> Dict[str, Any]:
    utc_date = m.get("utcDate")
    # Convert to date/time strings
    kick_iso = None
    if utc_date:
        try:
            kick_iso = datetime.fromisoformat(utc_date.replace("Z", "+00:00")).isoformat()
        except Exception:
            kick_iso = utc_date
    score = m.get("score", {})
    full_time = score.get("fullTime", {})

    return {
        "id": m.get("id"),
        "status": m.get("status"),
        "matchday": m.get("matchday"),
        "utcDate": kick_iso,
        "homeTeam": (m.get("homeTeam") or {}).get("name"),
        "awayTeam": (m.get("awayTeam") or {}).get("name"),
        "homeScore": full_time.get("home"),
        "awayScore": full_time.get("away"),
        "referees": ", ".join([r.get("name", "") for r in m.get("referees", []) if r.get("name")]),
        "venue": m.get("area", {}).get("name"),
        "competition": (m.get("competition") or {}).get("name"),
        "stage": m.get("stage"),
        "group": m.get("group"),
        "link": m.get("id") and f"https://www.football-data.org/match/{m['id']}" or None,
    }


def save_csv(matches: List[Dict[str, Any]], out_path: str) -> None:
    if not matches:
        # Write header only
        fields = [
            "id",
            "status",
            "matchday",
            "utcDate",
            "homeTeam",
            "awayTeam",
            "homeScore",
            "awayScore",
            "referees",
            "venue",
            "competition",
            "stage",
            "group",
            "link",
        ]
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
        return
    fields = list(matches[0].keys())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(matches)


def save_json(matches: List[Dict[str, Any]], out_path: str) -> None:
    import json

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Fetch Premier League fixtures in a date range and save to CSV/JSON")
    parser.add_argument("--start-date", required=True, type=iso_date, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--end-date", required=True, type=iso_date, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("-o", "--output", required=True, help="Output file path (.csv or .json)")
    args = parser.parse_args()

    load_dotenv()
    token = os.getenv("FOOTBALL_DATA_API_TOKEN")
    if not token:
        raise SystemExit("Missing FOOTBALL_DATA_API_TOKEN in environment (.env)")

    data = fetch_matches(args.start_date, args.end_date, token)
    matches_raw = data.get("matches", [])
    matches = [normalize_match(m) for m in matches_raw]

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    ext = os.path.splitext(args.output)[1].lower()
    if ext == ".csv":
        save_csv(matches, args.output)
    elif ext == ".json":
        save_json(matches, args.output)
    else:
        raise SystemExit("Output must end with .csv or .json")

    print(f"Saved {len(matches)} matches to {args.output}")


if __name__ == "__main__":
    main()
