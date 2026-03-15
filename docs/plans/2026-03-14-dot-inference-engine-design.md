# DoT Inference Engine Design

## Goal

Implement exact-match DoT (Damage over Time) tracking for Project Ares, producing ACT-compatible type 24 log lines that can be uploaded to FFLogs. This closes the ~28% damage gap between Ares and FFLogs.

## Context

FFXIV does not send individual DoT tick packets. ACT infers DoT damage by monitoring target HP changes between direct damage events and attributing unexplained HP decreases to active debuffs. ACT's type 24 lines confirm this: `buff_id=0` in many cases, meaning ACT attributes by source rather than specific buff.

Ares currently captures direct damage (ActionEffect) within 0.8% of ACT. The missing ~28% is entirely DoT/tick damage.

## Approach: HP Delta Method (ACT's Approach)

### Data Sources

Three packet streams feed the engine:

1. **ActionEffect (0x00B6)** -- already parsed. Provides:
   - Direct damage events (used to subtract from HP deltas)
   - Status effect applications (effect type 0x1B = "status add" in effect slots, containing buff_id and duration)
   - Tells us when a DoT debuff is applied to a target

2. **StatusEffectList (0x0178)** -- NEW handler needed. Periodically broadcast with full list of active buffs on an entity:
   - buff_id, duration remaining, source_actor for each status
   - Authoritative source for "what debuffs are on this target right now"
   - Handles buff refreshes, removals, and multi-source scenarios

3. **UpdateHpMpTp (0x00E7)** -- NEW handler needed. Fires on entity HP/MP changes:
   - Current HP of targets after each change
   - Compared against expected HP (after direct damage) to detect DoT ticks

### Core Algorithm

```
For each target being tracked:
  1. Record HP from UpdateHpMpTp
  2. When HP decreases:
     a. Check if any ActionEffect was delivered in this server tick (~50ms window)
     b. If yes: HP_delta = direct_damage (already logged, skip)
     c. If no: HP_delta = DoT tick damage
  3. Attribute DoT damage to the source who applied the active debuff
     - Use StatusEffectList to know which debuffs are active and who applied them
     - If multiple DoTs active, use server tick timing (3s intervals) to correlate
  4. Write ACT-compatible type 24 log line
```

### Debuff Tracker Component

New module: `ares/state/debuffs.py`

```
DebuffTracker:
  - Maintains dict: target_id -> list[ActiveDebuff]
  - ActiveDebuff: buff_id, source_id, applied_time, duration
  - Updated from:
    - ActionEffect status add entries (effect type 0x1B)
    - StatusEffectList packets (full refresh)
    - StatusRemove/expiry (debuff falls off)
  - Query: get_active_dots(target_id) -> list of (buff_id, source_id)
```

### HP Monitor Component

New module: `ares/state/hp_tracker.py`

```
HPTracker:
  - Maintains dict: entity_id -> HPState(current_hp, max_hp, last_update_time)
  - Updated from UpdateHpMpTp packets
  - Tracks direct damage dealt per server tick window
  - When HP delta detected without corresponding ActionEffect:
    -> Emits DoT tick event with (target_id, damage, timestamp)
    -> DebuffTracker resolves source attribution
```

### DoT Tick Emitter

Integrates HP deltas with debuff tracking to produce log lines:

```
on_hp_change(target_id, old_hp, new_hp, timestamp):
  damage = old_hp - new_hp
  if damage <= 0: return  # heal or no change

  direct_damage_this_tick = get_recent_direct_damage(target_id, window=100ms)
  dot_damage = damage - direct_damage_this_tick
  if dot_damage <= 0: return  # fully explained by direct damage

  active_dots = debuff_tracker.get_active_dots(target_id)
  if not active_dots: return  # no DoTs to attribute to

  # Attribute to source (ACT uses first active DoT source)
  source_id = active_dots[0].source_id
  buff_id = active_dots[0].buff_id

  write type 24 log line:
    24|timestamp|target_id|target_name|DoT|buff_id|damage|cur_hp|max_hp|...|source_id|source_name|...

  feed into encounter_manager.on_action_effect(source_id, target_id, dot_damage, timestamp)
```

### New Packet Handlers

**StatusEffectListHandler** (opcode 0x0178):
- Parse the full status list from the 296-byte packet
- Update DebuffTracker with current buffs on the target
- Struct layout needs live capture verification (similar process to ActionEffect)

**UpdateHpMpTpHandler** (opcode 0x00E7):
- Parse entity HP/MP values
- Feed into HPTracker
- Trigger DoT inference when HP decreases

### Server Tick Alignment

FFXIV server ticks every ~3 seconds for DoT/HoT processing. DoT ticks align to this clock. The engine should:
- Detect server tick boundaries from DoT tick timing patterns
- Only attribute DoT damage at tick boundaries
- Handle multiple DoTs ticking simultaneously on the same target

### Integration Points

- **main.py**: Register StatusEffectListHandler and UpdateHpMpTpHandler
- **encounter.py**: DoT damage feeds into existing on_action_effect (already counts toward DPS)
- **log/writer.py**: Type 24 lines already supported
- **Dashboard**: DoT damage automatically included in DPS via encounter manager

### Testing Strategy

- Unit tests with mock HP sequences and debuff states
- Integration test: simulate ActionEffect -> debuff apply -> HP decrease -> verify type 24 line
- Live validation: compare Ares type 24 output against ACT type 24 for same encounter

### Packet Struct Discovery

StatusEffectList (0x0178) and UpdateHpMpTp (0x00E7) payload layouts need live capture verification, same process used for ActionEffect:
1. Capture raw payloads with hex dump
2. Cross-reference with ACT log values
3. Map struct offsets

### File Changes Summary

| File | Change |
|------|--------|
| NEW `ares/state/debuffs.py` | DebuffTracker class |
| NEW `ares/state/hp_tracker.py` | HPTracker + DoT tick emitter |
| NEW `ares/parser/handlers.py` | StatusEffectListHandler, UpdateHpMpTpHandler |
| `main.py` | Register new handlers, wire debuff/HP trackers |
| `ares/parser/handlers.py` | Extract status add entries from ActionEffect |
| `tests/` | New test files for debuff tracker, HP tracker, DoT inference |

### Dependencies

- Requires Deucalion pipe (via ACT for now, standalone injection is a separate project)
- StatusEffectList and UpdateHpMpTp opcode verification needed before implementation
- No new Python packages required

### Success Criteria

- Ares type 24 log lines match ACT type 24 within 5% on damage values
- Total DPS (direct + DoT) matches FFLogs within 2%
- No phantom DoT ticks (false positives from heals or other HP changes)
- Works for all jobs with DoTs (DRG Chaotic Spring, DRK Salted Earth, etc.)

*The Anthiam Co.*
