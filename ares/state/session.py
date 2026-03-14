# ares/state/session.py
import json
import logging
import os
from datetime import datetime, timezone
from ares.state.encounter import EncounterManager

log = logging.getLogger(__name__)


class Session:
    def __init__(self, log_dir: str = 'logs'):
        self._log_dir = log_dir
        self._start = datetime.now(timezone.utc)
        self._session_file = os.path.join(
            log_dir, f"session_{self._start.strftime('%Y%m%d_%H%M')}.json"
        )
        os.makedirs(log_dir, exist_ok=True)
        self.encounter_mgr = EncounterManager()
        self.encounter_mgr.register_callback(self._on_event)

    def _on_event(self, event: str, data: dict):
        if event == 'encounter_end':
            self._persist()

    def _persist(self):
        data = {
            'session_start': self._start.isoformat(),
            'pulls': self.encounter_mgr.progression_summary()
        }
        with open(self._session_file, 'w') as f:
            json.dump(data, f, indent=2)
