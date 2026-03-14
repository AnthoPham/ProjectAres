# Project Ares

FFXIV combat log parser. Captures live combat data via Deucalion DLL injection,
produces ACT-compatible log files, and serves a live dashboard at http://localhost:5055.

## Requirements
- FFXIV running (ffxiv_dx11.exe)
- Python 3.11 (ProjectClaude conda env)
- `bin/deucalion.dll` present (see Setup)
- Run as Administrator (required for DLL injection)

## Setup
1. Download `deucalion.dll` from https://github.com/ff14wed/deucalion/releases
2. Place in `bin/deucalion.dll`
3. Install deps: `"D:/Anaconda3/envs/ProjectClaude/python.exe" -m pip install -r requirements.txt`

## Run
```bash
# Must run as Administrator
"D:/Anaconda3/envs/ProjectClaude/python.exe" main.py
```

Dashboard: http://localhost:5055
Logs: `logs/Network_YYYYMMDD_HHMM.log`

## After a Patch
See `PATCH_DAY.md`.

## Project Athena Integration
Export any pull log via the [Analyze] button in the dashboard.
Use the exported `.log` file with ACT Log Uploader to upload to FFLogs,
then analyze in Project Athena as usual.
