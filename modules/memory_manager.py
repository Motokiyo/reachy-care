"""
memory_manager.py — Mémoire persistante par personne pour Reachy Care.

Chaque personne connue a un fichier <nom>_memory.json dans known_faces/.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = {
    "name": "",
    "last_seen": "",
    "sessions_count": 0,
    "conversation_summary": "",
    "preferences": {},
    "health_signals": [],
    "family": {},
    "profile": {
        "medications": [],      # ex: ["Doliprane 500mg matin et soir", "Kardégic 75mg à jeun"]
        "schedules": [],        # ex: ["petit-déjeuner 8h", "déjeuner 12h30", "dîner 19h"]
        "emergency_contact": "", # ex: "Fille Marie : 06 12 34 56 78"
        "notes": "",            # informations libres
    },
}


class MemoryManager:
    """Charge, met à jour et sauvegarde la mémoire persistante par personne."""

    def __init__(self, known_faces_dir: str) -> None:
        self._dir = Path(known_faces_dir)

    # ------------------------------------------------------------------
    # I/O JSON
    # ------------------------------------------------------------------

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}_memory.json"

    def load(self, name: str) -> dict:
        path = self._path(name)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for k, v in _SCHEMA.items():
                    data.setdefault(k, v)
                return data
            except Exception as exc:
                logger.warning("MemoryManager: lecture %s échouée : %s", path, exc)
        return {**_SCHEMA, "name": name}

    def save(self, data: dict) -> None:
        name = data.get("name", "unknown")
        try:
            self._path(name).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("MemoryManager: mémoire sauvegardée pour %s", name)
        except Exception as exc:
            logger.warning("MemoryManager: sauvegarde %s échouée : %s", name, exc)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def on_seen(self, name: str) -> dict:
        """Met à jour last_seen et sessions_count. Retourne le dict mémoire."""
        data = self.load(name)
        data["name"] = name
        data["last_seen"] = datetime.now().isoformat(timespec="seconds")
        data["sessions_count"] += 1
        self.save(data)
        return data

    def update_summary(self, name: str, summary: str) -> None:
        data = self.load(name)
        data["conversation_summary"] = summary
        self.save(data)

    def update_profile(self, name: str, field: str, value) -> None:
        """Met à jour un champ du profil d'une personne."""
        data = self.load(name)
        if "profile" not in data:
            data["profile"] = {
                "medications": [],
                "schedules": [],
                "emergency_contact": "",
                "notes": "",
            }
        # Champs liste : découper par virgule
        if field in ("medications", "schedules") and isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        data["profile"][field] = value
        self.save(data)

    def list_persons(self) -> list[str]:
        return [p.stem.replace("_memory", "") for p in self._dir.glob("*_memory.json")]
