# Patch Day Update Checklist

Run this checklist after every major FFXIV patch.

## 1. Update Opcodes
Source: https://github.com/karashiiro/FFXIVOpcodes

Find the updated opcodes for the new patch version and update `config/opcodes.json`.
Change `_patch` and `_updated` fields. Update all opcode hex values.

## 2. Update Memory Offsets
Source: https://github.com/aers/FFXIVClientStructs

Check for changes to actor table offsets. Update `config/offsets.json`.
Change `_patch` and `_updated` fields.

## 3. Update Deucalion (if needed)
Source: https://github.com/ff14wed/deucalion/releases

If Deucalion releases a new version for the patch, replace `bin/deucalion.dll`.

## 4. Verify
1. Start Project Ares: `"D:/Anaconda3/envs/ProjectClaude/python.exe" main.py`
2. Confirm [Connected] status in dashboard header
3. Enter a duty and do one pull
4. Confirm combat events appear in the log feed panel
5. Confirm log file is written to `logs/`

## Warning Signs
- `[WARN] No combat events received` in dashboard after 30s in a fight -> opcodes wrong
- `[WARN] Could not attach to ffxiv_dx11.exe` -> offsets wrong or game updated
- `[WARN] Could not open Deucalion pipe` -> Deucalion needs updating
