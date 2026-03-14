# Project Ares - Design Document
*FFXIV Combat Log Parser and ACT Replacement*
*Date: 2026-03-13*

---

## Overview

Project Ares is a standalone ACT (Advanced Combat Tracker) replacement for FFXIV. It captures live combat data via Deucalion DLL injection, parses FFXIV network packets, and produces ACT-compatible log files. It exposes a web dashboard on port 5055 for live DPS tracking, pull history, and progression analysis. Log files are compatible with ACT Log Uploader for FFLogs upload.

Project Ares does **not** replace Project Athena's FFLogs API dependency. It provides a complementary local log source. Individual pulls can be manually exported and analyzed.

---

## Architecture

### Component Overview

```
FFXIV Process
     │
     ▼ (DLL injection)
[Deucalion] ──named pipe──► [Packet Parser]
                                   │
                              opcode routing
                                   │
                             [Combat State]
                            /      │       \
                           ▼       ▼        ▼
                     [Memory   [Log      [WebSocket
                      Reader]   Writer]   Server]
                                   │          │
                              ACT .log    Flask UI
                               files    port 5055
```

### Components

| Component | Responsibility |
|---|---|
| Deucalion Manager | Inject DLL, connect named pipe, handle reconnects |
| Packet Parser | Route opcodes to handlers, unpack binary structs |
| Memory Reader | Read entity list, HP, job IDs via pymem at 100ms |
| Combat State | Track encounters, accumulate DPS/HPS, detect boundaries |
| Log Writer | Write ACT-format log lines to disk |
| WebSocket Server | Broadcast live events, serve web dashboard |
| Config Layer | `opcodes.json` + `offsets.json` - patch-day update targets |

---

## Data Flow

### Startup
1. Deucalion Manager polls for FFXIV process PID
2. Injects `deucalion.dll` into game process
3. Opens named pipe: `\\.\pipe\deucalion`
4. Memory Reader attaches via pymem

### Per-Packet Flow
```
Named pipe message
     │
     ▼
IPC header parse → opcode lookup in opcodes.json
     │
     ▼
Raw binary payload → struct unpack → typed event object
     │
     ├──► Combat State (accumulate stats)
     └──► Log Writer (emit ACT log line immediately)
```

### Memory Polling
- Runs on a separate thread, every **100ms** (matches ACT source behavior, confirmed via decompilation)
- Reads entity table for: actor names, job IDs, HP, party composition
- Enriches events with resolved names where packets only carry actor IDs
- Event-driven where possible (AddCombatant packet triggers immediate read), 100ms poll as fallback

### WebSocket Broadcast
- `combat_event` - emitted on every parsed packet
- `encounter_state` - emitted every 1s during active encounter (DPS, HP%, timers)
- `encounter_end` - emitted on wipe/kill with final stats and pull number
- Browser dashboard and Project Athena both subscribe to the same feed

---

## Log Format

### File Naming
```
Network_YYYYMMDD_HHMM.log
```
One file per session. All pulls within a session write to the same file continuously.

### Line Format
```
{type:02d}|{timestamp}|{fields...}|{hash}
```

Timestamp format: `2026-03-13T20:04:33.1230000-05:00`

### LogMessageType Values (from FFXIV_ACT_Plugin source)

| Code | Type | Code | Type |
|---|---|---|---|
| 0 | ChatLog | 26 | StatusAdd |
| 1 | Territory | 27 | TargetIcon |
| 2 | ChangePrimaryPlayer | 28 | WaymarkMarker |
| 3 | AddCombatant | 29 | SignMarker |
| 4 | RemoveCombatant | 30 | StatusRemove |
| 11 | PartyList | 36 | LimitBreak |
| 12 | PlayerStats | 37 | EffectResult |
| 20 | StartsCasting | 38 | StatusList |
| 21 | ActionEffect (single) | 39 | UpdateHp |
| 22 | AOEActionEffect | 40 | ChangeMap |
| 23 | CancelAction | 249 | Settings |
| 24 | DoTHoT | 251 | Debug |
| 25 | Death | 253 | Version |

### Key Log Line Formats (from decompiled FFXIV_ACT_Plugin.Logfile.dll)

**ActionEffect (21/22):**
```
{sourceId:X2}|{sourceName}|{skillId:X2}|{skillName}|{targetId:X2}|{targetName}|
{effectData1_lo:X1}|{effectData1_hi:X1}|...x8 pairs...|
{targetHP}|{targetMaxHP}|{targetMP}|{targetMaxMP}|{targetX}|{targetY}|{targetZ}|{targetHeading}|
{sourceHP}|{sourceMaxHP}|{sourceMP}|{sourceMaxMP}|{sourceX}|{sourceY}|{sourceZ}|{sourceHeading}|
{sequence:X8}|{targetIndex}|{totalTargets}|{ownerId:X2}|{ownerName}|
{effectDisplayType:X2}|{actionId:X2}|{animationId:X2}|{animationDelay:0.000}|{rotation:X4}
```

**DoTHoT (24):**
```
{targetId:X4}|{targetName}|{HoT/DoT}|{buffId:X1}|{amount:X1}|
{targetHP...}|{sourceId:X4}|{sourceName}|{damageType:X1}|{sourceHP...}
```

**Death (25):**
```
{targetId:X2}|{targetName}|{sourceId:X2}|{sourceName}
```

**AddCombatant (3):**
```
{CombatantID:X4}|{CombatantName}|{JobID:X2}|{Level:X1}|{OwnerID:X4}|
{WorldID:X2}|{WorldName}|{BNpcNameID}|{BNpcID}|{HP}|{MaxHP}|{MP}|{MaxMP}|
{PosX}|{PosY}|{PosZ}|{Heading}
```

### Ability Variants
FFXIV sends separate opcodes for abilities targeting 1, 8, 16, 24, or 32 targets. All variants are normalized to `ActionEffect` (type 21) or `AOEActionEffect` (type 22) in the log output.

---

## Encounter State Machine

```
OUT_OF_COMBAT
     │ first ActionEffect event
     ▼
IN_COMBAT (active pull)
     │
     ├── wipe: ActorControl wipe signal OR all party dead
     ├── kill: boss HP reaches 0
     └── timeout: no combat events for 5s
     │
     ▼
ENCOUNTER_END
     │ freeze live view 3s, emit encounter_end, append to pull list
     ▼
OUT_OF_COMBAT
```

**Encounter end detection priority:**
1. `ActorControl` packet with wipe flag (immediate, most reliable)
2. All party members dead within 10s window
3. Boss HP = 0 in `UpdateHp` packet (kill)
4. 5s timeout (fallback)

---

## Data Models

```python
@dataclass
class Encounter:
    id: int
    start_time: datetime
    end_time: datetime | None
    duration_secs: float
    zone: str
    outcome: str  # 'active', 'wipe', 'kill'
    boss_hp_pct: float | None  # at time of wipe/kill
    combatants: dict[int, CombatantStats]
    party_dps: float

@dataclass
class CombatantStats:
    actor_id: int
    name: str
    job: str
    total_damage: int
    total_healing: int
    dps: float
    hps: float
    deaths: int

@dataclass
class Session:
    start_time: datetime
    zone: str
    log_file: str
    encounters: list[Encounter]
```

Sessions persist to `logs/session_YYYYMMDD.json` so crash recovery is possible.

---

## Web Dashboard

**Port: 5055**

### Out-of-Combat View (Progression)

```
┌─────────────────────────────────────────────────────┐
│  PROJECT ARES          [●] Connected  P12S Phase 2   │
├──────────────────────────────────────────────────────┤
│  PROGRESSION                                         │
│  Boss HP at wipe                                     │
│  100% ┤                                              │
│   75% ┤ ██                                           │
│   50% ┤ ██ ██                                        │
│   25% ┤ ██ ██ ██ ██                                  │
│    0% ┤ ██ ██ ██ ██ ██ ██ [KILL]                    │
│        P1  P2  P3  P4  P5  P6   P7                  │
│  Avg DPS trend:  ↑ +2,100 over session              │
├──────────────────────────────────────────────────────┤
│  Pull 7  KILL   8:21  ████████████ 0%   [Analyze]   │
│  Pull 6  wipe   7:44  ████████░░░░ 8%   [Analyze]   │
│  Pull 5  wipe   6:12  ███████░░░░░ 22%  [Analyze]   │
└──────────────────────────────────────────────────────┘
```

### In-Combat View (Live)

```
┌─────────────────────────────────────────────────────┐
│  PROJECT ARES          [●] PULL 8 - LIVE   4:23     │
├──────────────────────────────────────────────────────┤
│  BOSS HP    ████████████████████░░░░░░░░  62.4%     │
├──────────────────────────────────────────────────────┤
│  PARTY DPS  183,420                                  │
│                                                      │
│  Vatarris   DRK  ████████████████░░  42,810  23.3%  │
│  Anthiam    WHM  ████████░░░░░░░░░░  18,200   9.9%  │
│  Eryndis    SAM  ███████████████░░░  39,100  21.3%  │
│  Kaelith    SGE  ████████░░░░░░░░░░  16,400   8.9%  │
│  Zorvath    BLM  ████████████████░░  41,200  22.5%  │
│  Mirelis    DNC  ████████░░░░░░░░░░  25,710  14.0%  │
│                                                      │
│  HPS        Anthiam  18,200   Kaelith  14,300       │
├──────────────────────────────────────────────────────┤
│  vs Pull 7 avg:  DPS ↑ +2,100    Boss HP: on pace   │
└──────────────────────────────────────────────────────┘
```

### [Analyze] Button Behavior
- Exports the selected pull's log segment as a standalone ACT-compatible `.log` file
- Opens a detail view showing that pull's full combatant breakdown
- Can switch between any pull at any time, including during an active pull

---

## WebSocket Events

```python
# Every combat packet
socket.emit('combat_event', {
    'type': 21,
    'timestamp': '2026-03-13T20:04:33.123',
    'raw_line': '21|...'
})

# Every 1s during active encounter
socket.emit('encounter_state', {
    'active': True,
    'pull_number': 8,
    'duration': 263,
    'zone': 'Anabaseios: The Twelfth Circle (Savage)',
    'boss_hp_pct': 62.4,
    'party_dps': 183420,
    'combatants': [
        {'name': 'Vatarris', 'job': 'DRK', 'dps': 42810, 'pct': 23.3},
    ]
})

# On encounter end
socket.emit('encounter_end', {
    'pull_number': 8,
    'outcome': 'wipe',
    'duration': 263,
    'boss_hp_pct': 8.4,
    'log_file': 'Network_20260313_2004.log',
    'combatants': [...]
})
```

---

## Configuration Files

### config/opcodes.json
```json
{
  "_patch": "7.3",
  "_source": "https://github.com/karashiiro/FFXIVOpcodes",
  "ActionEffect1":    "0x00A3",
  "ActionEffect8":    "0x016C",
  "ActionEffect16":   "0x022B",
  "ActionEffect24":   "0x0119",
  "ActionEffect32":   "0x01D4",
  "ActorControl":     "0x02A4",
  "ActorControlSelf": "0x01F3",
  "AddCombatant":     "0x0357",
  "RemoveCombatant":  "0x0298",
  "UpdateHpMpTp":     "0x030A",
  "StatusEffectList": "0x03A1",
  "DoTList":          "0x026F",
  "CastBar":          "0x01C3",
  "WaymarkPreset":    "0x00B7"
}
```

### config/offsets.json
```json
{
  "_patch": "7.3",
  "_source": "https://github.com/aers/FFXIVClientStructs",
  "actor_table":      "0x1D23A80",
  "actor_table_size": 624,
  "player_id":        "0x1D2FD20",
  "territory_id":     "0x1D27508",
  "server_time":      "0x1D27510"
}
```

---

## Maintenance

### Patch Day Checklist

```
1. Check FFXIVOpcodes repo for new opcode values → update config/opcodes.json
2. Check FFXIVClientStructs for offset changes   → update config/offsets.json
3. Check Deucalion releases for new version      → replace bin/deucalion.dll if needed
4. Start Ares, verify [Connected] status appears
5. Do one test pull, confirm log lines appear in log feed panel
```

### Update Sources

| What | Source | Frequency |
|---|---|---|
| Opcodes | `github.com/karashiiro/FFXIVOpcodes` | Every major patch (~quarterly) |
| Memory offsets | `github.com/aers/FFXIVClientStructs` | Every major patch (~quarterly) |
| Deucalion DLL | `github.com/ff14wed/deucalion/releases` | When Deucalion breaks (less frequent) |
| Job definitions | `Definitions/*.json` in FFXIV_ACT_Plugin repo | Rarely (new jobs/potency changes) |

### Warning System
If opcodes are stale, Ares displays in the log feed panel after 30s in a fight:
```
[WARN] No combat events received - opcodes may need updating for current patch
```

---

## Directory Structure

```
ProjectAres/
├── main.py                  # Entry point
├── config/
│   ├── opcodes.json         # Patch-day update target
│   └── offsets.json         # Patch-day update target
├── bin/
│   └── deucalion.dll        # Deucalion binary (versioned)
├── ares/
│   ├── deucalion/
│   │   └── manager.py       # Injection + named pipe reader
│   ├── parser/
│   │   ├── router.py        # Opcode → handler dispatch
│   │   └── handlers.py      # Per-packet-type parsers
│   ├── memory/
│   │   └── reader.py        # pymem entity table polling
│   ├── state/
│   │   ├── encounter.py     # Encounter state machine
│   │   └── session.py       # Session + pull history
│   ├── log/
│   │   └── writer.py        # ACT log line formatter + file writer
│   └── server/
│       ├── app.py           # Flask + SocketIO
│       └── static/          # Dashboard HTML/CSS/JS
├── logs/                    # Generated log files + session JSON
└── docs/
    └── plans/
        └── 2026-03-13-project-ares-design.md
```

---

*The Anthiam Co.*
