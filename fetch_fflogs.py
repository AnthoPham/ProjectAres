"""Fetch FFLogs report data for ntDRNFcZpMABQqPa (last fight)."""

import os
import requests
import time

# Credentials
CLIENT_ID = "9da2020d-abe7-43da-ac33-14dd375338f8"
CLIENT_SECRET = "XzkxPBxaCUu8fYbNDoFjmQIFe1p88K40jowTpsd9"

TOKEN_URL = "https://www.fflogs.com/oauth/token"
API_URL = "https://www.fflogs.com/api/v2/client"
REPORT_CODE = "ntDRNFcZpMABQqPa"


def get_token():
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def gql(token, query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(API_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    result = resp.json()
    if "errors" in result:
        raise Exception(f"GraphQL errors: {result['errors']}")
    return result.get("data", {})


def main():
    print("Authenticating with FFLogs...")
    token = get_token()
    print("Authenticated successfully.\n")

    # Step 1: Get report fights to find the last one
    print(f"Fetching report {REPORT_CODE}...")
    fights_query = """
    query GetReport($code: String!) {
        reportData {
            report(code: $code) {
                title
                fights {
                    id
                    startTime
                    endTime
                    name
                    encounterID
                    kill
                    difficulty
                    bossPercentage
                }
                masterData(translate: true) {
                    actors(type: "Player") {
                        id
                        name
                        type
                        subType
                    }
                }
            }
        }
    }
    """
    data = gql(token, fights_query, {"code": REPORT_CODE})
    report = data["reportData"]["report"]

    print(f"Report Title: {report['title']}")
    fights = report["fights"]
    print(f"Total fights in report: {len(fights)}\n")

    # Get last fight
    last_fight = fights[-1]
    fight_id = last_fight["id"]
    fight_name = last_fight["name"]
    encounter_id = last_fight["encounterID"]
    kill = last_fight.get("kill", False)
    duration_ms = last_fight["endTime"] - last_fight["startTime"]
    duration_s = duration_ms / 1000
    minutes = int(duration_s // 60)
    seconds = duration_s % 60
    boss_pct = last_fight.get("bossPercentage", None)

    print("=" * 70)
    print(f"LAST FIGHT (Fight #{fight_id})")
    print("=" * 70)
    print(f"  Encounter:    {fight_name}")
    print(f"  Encounter ID: {encounter_id}")
    print(f"  Result:       {'KILL' if kill else 'WIPE'}", end="")
    if boss_pct is not None and not kill:
        print(f" (Boss at {boss_pct / 100:.1f}%)")
    else:
        print()
    print(f"  Duration:     {minutes}m {seconds:.1f}s ({duration_ms:,} ms)")
    print()

    # Step 2: Get damage done table for the fight
    print("Fetching damage data...")
    table_query = f"""
    query GetTable($code: String!) {{
        reportData {{
            report(code: $code) {{
                table(fightIDs: [{fight_id}], dataType: DamageDone, startTime: {last_fight['startTime']}, endTime: {last_fight['endTime']})
            }}
        }}
    }}
    """
    table_data = gql(token, table_query, {"code": REPORT_CODE})
    table = table_data["reportData"]["report"]["table"]

    # Handle nested data structure
    if "data" in table:
        table = table["data"]

    entries = table.get("entries", [])
    total_time_s = table.get("totalTime", duration_ms) / 1000

    # Step 3: Get player details for job info
    details_query = """
    query GetPlayerDetails($code: String!, $fightID: Int!) {
        reportData {
            report(code: $code) {
                playerDetails(fightIDs: [$fightID])
            }
        }
    }
    """
    details_data = gql(token, details_query, {"code": REPORT_CODE, "fightID": fight_id})
    player_details_raw = details_data["reportData"]["report"]["playerDetails"]
    if "data" in player_details_raw:
        player_details_raw = player_details_raw["data"]
    if "playerDetails" in player_details_raw:
        player_details_raw = player_details_raw["playerDetails"]

    # Build name->job map
    name_to_job = {}
    for role in ["tanks", "healers", "dps"]:
        for p in player_details_raw.get(role, []):
            name_to_job[p["name"]] = p.get("type", "Unknown")

    # Filter to player entries only (exclude pets, limit breaks, etc.)
    # Players have type "Player" or their name appears in playerDetails
    player_entries = []
    for entry in entries:
        name = entry.get("name", "")
        entry_type = entry.get("type", "")
        # Include if it's a known player or type is a job name
        if name in name_to_job or entry_type in name_to_job.values():
            player_entries.append(entry)

    # Sort by total damage descending
    player_entries.sort(key=lambda e: e.get("total", 0), reverse=True)

    print()
    print("-" * 70)
    print(f"{'#':<4}{'Player':<22}{'Job':<15}{'Total Damage':>14}{'DPS':>10}")
    print("-" * 70)

    total_damage = 0
    total_rdps = 0
    for i, entry in enumerate(player_entries, 1):
        name = entry.get("name", "Unknown")
        job = name_to_job.get(name, entry.get("type", "Unknown"))
        damage = entry.get("total", 0)
        # Calculate DPS from fight duration
        dps = damage / total_time_s if total_time_s > 0 else 0
        total_damage += damage
        total_rdps += dps

        print(f"{i:<4}{name:<22}{job:<15}{damage:>14,}{dps:>10,.1f}")

    print("-" * 70)
    print(f"{'':4}{'TOTAL':<22}{'':<15}{total_damage:>14,}{total_rdps:>10,.1f}")
    print("-" * 70)

    # Step 4: Try to get rankings/parse data
    print("\nFetching parse rankings...")
    try:
        rankings_query = f"""
        query GetRankings($code: String!, $fightID: Int!) {{
            reportData {{
                report(code: $code) {{
                    rankings(fightIDs: [$fightID], playerMetric: rdps)
                }}
            }}
        }}
        """
        rankings_data = gql(token, rankings_query, {"code": REPORT_CODE, "fightID": fight_id})
        rankings = rankings_data["reportData"]["report"]["rankings"]

        if "data" in rankings:
            rankings_list = rankings["data"]
        else:
            rankings_list = rankings

        if rankings_list:
            print()
            print("-" * 70)
            print(f"{'Player':<22}{'Job':<15}{'rDPS':>10}{'Parse %':>10}")
            print("-" * 70)

            # Rankings can be nested differently
            if isinstance(rankings_list, list):
                for r in rankings_list:
                    roles = r.get("roles", {})
                    for role_name, role_data in roles.items():
                        for char in role_data.get("characters", []):
                            name = char.get("name", "Unknown")
                            job = char.get("class", "Unknown")
                            rdps = char.get("amount", 0)
                            parse_pct = char.get("rankPercent", 0)
                            print(f"{name:<22}{job:<15}{rdps:>10,.1f}{parse_pct:>9.1f}%")
            print("-" * 70)
        else:
            print("  No ranking data available (fight may not be a ranked encounter).")

    except Exception as e:
        print(f"  Could not fetch rankings: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
