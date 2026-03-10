"""
mode_manager.py — Gestionnaire de modes pour Reachy Care.

Modes :
    MODE_NORMAL   : conversation libre (défaut)
    MODE_HISTOIRE : lecture de livres domaine public (Project Gutenberg)
    MODE_PRO      : monologue structuré avec recherche internet
    MODE_ECHECS   : coaching vocal d'échecs (auto-déclenché par vision)
"""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config

logger = logging.getLogger(__name__)

MODE_NORMAL   = "normal"
MODE_HISTOIRE = "histoire"
MODE_PRO      = "pro"
MODE_ECHECS   = "echecs"

VALID_MODES = {MODE_NORMAL, MODE_HISTOIRE, MODE_PRO, MODE_ECHECS}

# Délai minimum entre deux switches (anti-spam)
_SWITCH_THROTTLE_SEC = 5.0

# Fichiers d'instructions par mode (dans profiles_dir)
_INSTRUCTIONS_FILES = {
    MODE_NORMAL:   "instructions.txt",
    MODE_HISTOIRE: "instructions_histoire.txt",
    MODE_PRO:      "instructions_pro.txt",
    MODE_ECHECS:   "instructions_echecs.txt",
}

# Message injecté dans la conversation au moment du switch
_ANNOUNCE_MESSAGES = {
    MODE_HISTOIRE: (
        "[Reachy Care] MODE LECTURE activé. "
        "Tu entres en mode lecture de livres du domaine public. "
        "Propose de choisir un type d'histoire."
    ),
    MODE_PRO: (
        "[Reachy Care] MODE EXPOSÉ activé. "
        "Tu entres en mode exposé. "
        "Demande sur quel sujet faire l'exposé si non précisé."
    ),
    MODE_ECHECS: (
        "[Reachy Care] MODE ÉCHECS activé. "
        "Un échiquier est devant toi. Adopte le rôle de coach d'échecs bienveillant."
    ),
    MODE_NORMAL: (
        "[Reachy Care] MODE NORMAL activé. "
        "Reviens à ta personnalité de compagnon bienveillant habituelle."
    ),
}


class ModeManager:
    """Gestionnaire thread-safe des modes de comportement de Reachy."""

    def __init__(self, profiles_dir: str, bridge) -> None:
        self._profiles_dir = Path(profiles_dir)
        self._bridge = bridge
        self._lock = threading.Lock()
        self._current_mode = MODE_NORMAL
        self._last_switch_time = 0.0
        self._instructions_cache: dict[str, str] = {}
        self._preload_instructions()

    def _preload_instructions(self) -> None:
        for mode, filename in _INSTRUCTIONS_FILES.items():
            path = self._profiles_dir / filename
            if path.exists():
                self._instructions_cache[mode] = path.read_text(encoding="utf-8")
                logger.info(
                    "Instructions mode '%s' chargées (%d chars).", mode,
                    len(self._instructions_cache[mode]),
                )
            else:
                logger.warning("Fichier instructions manquant pour mode '%s' : %s", mode, path)

    def get_current_mode(self) -> str:
        with self._lock:
            return self._current_mode

    def switch_mode(self, mode: str, context: str = "") -> bool:
        """
        Change le mode actif.

        Returns True si le switch a eu lieu, False si ignoré
        (mode identique, throttle, ou mode inconnu).
        """
        if mode not in VALID_MODES:
            logger.warning("Mode inconnu : '%s'", mode)
            return False

        now = time.monotonic()
        with self._lock:
            if self._current_mode == mode:
                return False
            if now - self._last_switch_time < _SWITCH_THROTTLE_SEC:
                logger.debug("Switch trop rapide ignoré.")
                return False
            previous = self._current_mode
            self._current_mode = mode
            self._last_switch_time = now

        logger.info("Switch mode : %s → %s (context=%r)", previous, mode, context)
        self._apply_mode(mode, context)
        return True

    def _apply_mode(self, mode: str, context: str = "") -> None:
        try:
            tz = ZoneInfo(getattr(config, "TIMEZONE", "Europe/Paris"))
        except Exception:
            tz = None
        now_str = datetime.now(tz).strftime("%A %d %B %Y, %Hh%M")

        mode_instructions = self._instructions_cache.get(mode)
        if not mode_instructions:
            logger.error("Instructions manquantes pour mode '%s' — switch annulé.", mode)
            return

        # Construire les instructions complètes :
        # base (normal) + override mode-spécifique si mode != normal
        base_instructions = self._instructions_cache.get(MODE_NORMAL, "")
        if mode == MODE_NORMAL or not base_instructions:
            instructions = mode_instructions
        else:
            instructions = (
                base_instructions
                + "\n\n"
                + "=" * 60
                + f"\n## MODE ACTIF : {mode.upper()}\n"
                + "Les règles ci-dessous REMPLACENT les règles générales en cas de conflit.\n"
                + "=" * 60
                + "\n\n"
                + mode_instructions
            )

        if mode == MODE_PRO and context:
            instructions = instructions + f"\n\nSujet demandé : {context}"

        # Injection LOCATION et DATETIME
        instructions = instructions.replace("{LOCATION}", config.LOCATION)
        instructions = instructions.replace("{DATETIME}", now_str)

        # 1. Mettre à jour les instructions de session (persistant)
        self._bridge.update_session_instructions(instructions)

        # 2. Injecter un message d'amorçage avec le contexte si disponible
        announce_text = _ANNOUNCE_MESSAGES.get(mode, "")
        if mode == MODE_PRO and context:
            announce_text += f" Sujet : {context}."
        elif mode == MODE_ECHECS and context:
            announce_text += f" Position actuelle de la partie (FEN) : {context}."

        self._bridge.announce_mode_switch(announce_text)
