# main.py
"""
Project Ares - FFXIV Combat Log Parser
Run with: "D:/Anaconda3/envs/ProjectClaude/python.exe" main.py
Access dashboard at: http://localhost:5055

By default, connects to an existing Deucalion pipe (from ACT/Machina).
Use --inject to self-inject the DLL (requires Administrator).
"""
import argparse
import logging
import os
import threading
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
log = logging.getLogger('ares')

from ares.config import Config
from ares.deucalion.manager import DeucalionManager
from ares.log.writer import LogWriter, LogMessageType
from ares.memory.reader import MemoryReader
from ares.parser.handlers import ActionEffectHandler, ActorControlHandler, ActorControlSelfHandler
from ares.parser.router import PacketRouter
from ares.server.app import create_app
from ares.state.session import Session


def build_router(cfg: Config, writer: LogWriter, memory: MemoryReader,
                 session: Session, socketio) -> PacketRouter:
    router = PacketRouter(cfg)
    enc_mgr = session.encounter_mgr

    # Track party members -- any player (0x10xxxxxx) who hits an NPC (0x40xxxxxx)
    # is considered a party member. This auto-detects your party during combat.
    party_members = set()

    def is_party_action(source_id: int, target_id: int) -> bool:
        """Check if this action is from a party member hitting an enemy."""
        is_player = (source_id & 0xFF000000) == 0x10000000
        is_enemy_target = (target_id & 0xFF000000) == 0x40000000
        if is_player and is_enemy_target:
            if source_id not in party_members:
                party_members.add(source_id)
                log.info(f"Detected party member: {source_id:08X} ({len(party_members)} total)")
            return True
        # Also accept if source is a known party member (e.g. self-buffs)
        return source_id in party_members

    def make_ae_handler(opcode: int, target_count: int):
        h = ActionEffectHandler(
            opcode=opcode,
            log_writer=writer,
            combatant_manager=memory,
            target_count=target_count
        )
        def handle(header):
            h(header)
            if not is_party_action(h.last_source_id, h.last_target_id):
                return
            enc_mgr.on_action_effect(
                source_id=h.last_source_id,
                target_id=h.last_target_id,
                damage=h.last_damage,
                timestamp=header.timestamp
            )
        return handle

    for variant, count in [(1, 1), (8, 8), (16, 16), (24, 24), (32, 32)]:
        opcode = cfg.opcode(f'ActionEffect{variant}')
        if opcode:
            router.register(opcode, make_ae_handler(opcode, count))

    # ActorControl (0x020B) - handles death events and combat state
    ac_handler = ActorControlHandler(
        log_writer=writer, combatant_manager=memory, encounter_manager=enc_mgr
    )
    ac_opcode = cfg.opcode('ActorControl')
    if ac_opcode:
        router.register(ac_opcode, ac_handler)

    # ActorControlSelf (0x0217) - handles DoT/HoT ticks
    acs_handler = ActorControlSelfHandler(
        log_writer=writer, combatant_manager=memory, encounter_manager=None
    )
    def handle_acs(header):
        acs_handler(header)
        # Only feed DoT damage into encounter if source is a party member
        if acs_handler.last_damage > 0 and acs_handler.last_source_id in party_members:
            enc_mgr.on_action_effect(
                source_id=acs_handler.last_source_id,
                target_id=acs_handler.last_target_id,
                damage=acs_handler.last_damage,
                timestamp=header.timestamp
            )
    acs_opcode = cfg.opcode('ActorControlSelf')
    if acs_opcode:
        router.register(acs_opcode, handle_acs)

    return router


def broadcast_loop(socketio, session: Session, memory: MemoryReader):
    """Emit encounter_state every 1 second during active encounter."""
    while True:
        enc = session.encounter_mgr.current
        if enc:
            duration = enc.duration_secs
            combatants = []
            total_dmg = sum(s.total_damage for s in enc.combatant_stats.values())
            for s in sorted(enc.combatant_stats.values(), key=lambda x: -x.total_damage):
                dps = s.total_damage / duration if duration > 0 else 0
                pct = (s.total_damage / total_dmg * 100) if total_dmg > 0 else 0
                # Resolve name from memory reader if available
                combatant = memory.get_by_id(s.actor_id)
                name = combatant.name if combatant else s.name or f"{s.actor_id:08X}"
                combatants.append({
                    'name': name,
                    'job': s.job,
                    'dps': round(dps),
                    'pct': round(pct, 1),
                    'total_damage': s.total_damage,
                })
            party_dps = total_dmg / duration if duration > 0 else 0
            payload = {
                'active': True,
                'pull_number': enc.pull_id,
                'duration': round(duration),
                'zone': enc.zone,
                'boss_hp_pct': enc._current_boss_hp_pct,
                'party_dps': round(party_dps),
                'total_damage': total_dmg,
                'combatants': combatants,
            }
            socketio.emit('encounter_state', payload)
        time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description='Project Ares - FFXIV Combat Log Parser')
    parser.add_argument('--inject', action='store_true',
                        help='Self-inject Deucalion DLL (requires Admin). '
                             'Default: connect to existing pipe from ACT/Machina.')
    parser.add_argument('--port', type=int, default=5055, help='Dashboard port (default: 5055)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("Project Ares starting...")
    if not args.inject:
        log.info("Passive mode: will connect to existing Deucalion pipe. "
                 "Use --inject to self-inject.")

    project_dir = os.path.dirname(os.path.abspath(__file__))

    cfg = Config()
    log.info(f"Loaded config for patch {cfg.patch}")

    log_dir = os.path.join(project_dir, 'logs')
    session = Session(log_dir=log_dir)
    writer = LogWriter(log_dir=log_dir)
    writer.open_session(datetime.now(timezone.utc))
    memory = MemoryReader(cfg)
    if memory.attach():
        memory.start()
        log.info("Memory reader attached - combatant names available")
    else:
        log.info("Memory reader not attached - using hex IDs (run as admin for name resolution)")

    dll_path = os.path.join(project_dir, 'bin', 'deucalion.dll')
    deucalion = DeucalionManager(dll_path=dll_path, allow_inject=args.inject)
    app, socketio = create_app(session=session, deucalion_mgr=deucalion)

    # Register encounter callbacks to broadcast over WebSocket
    def on_encounter_event(event, data):
        socketio.emit(event, data)
    session.encounter_mgr.register_callback(on_encounter_event)

    router = build_router(cfg, writer, memory, session, socketio)
    deucalion.on_frame(router.dispatch)

    # Start background services
    deucalion.start()

    # Broadcast loop in background thread
    t = threading.Thread(target=broadcast_loop, args=(socketio, session, memory), daemon=True)
    t.start()

    # Ticker thread for encounter timeout detection
    def tick_loop():
        while True:
            session.encounter_mgr.tick(datetime.now(timezone.utc))
            time.sleep(1.0)
    threading.Thread(target=tick_loop, daemon=True).start()

    log.info(f"Dashboard available at http://localhost:{args.port}")
    socketio.run(app, host='0.0.0.0', port=args.port)


if __name__ == '__main__':
    main()
