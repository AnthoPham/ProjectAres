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
from ares.parser.handlers import ActionEffectHandler, DeathHandler, DoTHoTHandler
from ares.parser.router import PacketRouter
from ares.server.app import create_app
from ares.state.session import Session


def build_router(cfg: Config, writer: LogWriter, memory: MemoryReader,
                 session: Session, socketio) -> PacketRouter:
    router = PacketRouter(cfg)
    enc_mgr = session.encounter_mgr

    def make_ae_handler(opcode: int, target_count: int):
        h = ActionEffectHandler(
            opcode=opcode,
            log_writer=writer,
            combatant_manager=memory,
            target_count=target_count
        )
        def handle(header):
            h(header)
            # Feed into encounter state
            enc_mgr.on_action_effect(
                source_id=0, target_id=0, damage=0, timestamp=header.timestamp
            )
        return handle

    for variant, count in [(1, 1), (8, 8), (16, 16), (24, 24), (32, 32)]:
        opcode = cfg.opcode(f'ActionEffect{variant}')
        if opcode:
            router.register(opcode, make_ae_handler(opcode, count))

    death_handler = DeathHandler(log_writer=writer, combatant_manager=memory)
    death_opcode = cfg.opcode('ActorControl')
    if death_opcode:
        router.register(death_opcode, death_handler)

    dot_handler = DoTHoTHandler(log_writer=writer, combatant_manager=memory)
    dot_opcode = cfg.opcode('DoTList')
    if dot_opcode:
        router.register(dot_opcode, dot_handler)

    return router


def broadcast_loop(socketio, session: Session):
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
                combatants.append({
                    'name': s.name or f"{s.actor_id:08X}",
                    'job': s.job,
                    'dps': round(dps),
                    'pct': round(pct, 1),
                })
            party_dps = total_dmg / duration if duration > 0 else 0
            payload = {
                'active': True,
                'pull_number': enc.pull_id,
                'duration': round(duration),
                'zone': enc.zone,
                'boss_hp_pct': enc._current_boss_hp_pct,
                'party_dps': round(party_dps),
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

    cfg = Config()
    log.info(f"Loaded config for patch {cfg.patch}")

    session = Session(log_dir='logs')
    writer = LogWriter(log_dir='logs')
    writer.open_session(datetime.now(timezone.utc))
    memory = MemoryReader(cfg)

    deucalion = DeucalionManager(dll_path='bin/deucalion.dll', allow_inject=args.inject)
    app, socketio = create_app(session=session, deucalion_mgr=deucalion)

    # Register encounter callbacks to broadcast over WebSocket
    def on_encounter_event(event, data):
        socketio.emit(event, data)
    session.encounter_mgr.register_callback(on_encounter_event)

    router = build_router(cfg, writer, memory, session, socketio)
    deucalion.on_frame(router.dispatch)

    # Start background services
    deucalion.start()
    memory.start()

    # Broadcast loop in background thread
    t = threading.Thread(target=broadcast_loop, args=(socketio, session), daemon=True)
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
