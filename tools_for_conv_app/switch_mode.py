"""
switch_mode.py — Outil de changement de mode pour reachy_mini_conversation_app.

Appelé par l'IA quand elle détecte une intention de changement de mode.

Deux actions en parallèle :
  1. Met à jour la session OpenAI Realtime DIRECTEMENT via await (synchrone avant
     de retourner le résultat au LLM, pour que les nouvelles instructions soient
     actives dès la prochaine réponse).
  2. Écrit /tmp/reachy_care_cmd.json pour que main.py mette à jour son état interne.
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

_CMD_FILE = "/tmp/reachy_care_cmd.json"

_INSTRUCTIONS_FILES = {
    "normal":   "instructions.txt",
    "histoire": "instructions_histoire.txt",
    "pro":      "instructions_pro.txt",
    "echecs":   "instructions_echecs.txt",
}

_SEPARATOR = "=" * 60


# ---------------------------------------------------------------------------
# Helpers — instructions
# ---------------------------------------------------------------------------

def _get_profiles_dir() -> Path | None:
    base = os.environ.get("REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY", "")
    profile = os.environ.get("REACHY_MINI_CUSTOM_PROFILE", "reachy_care")
    if base:
        d = Path(base) / profile
        if d.exists():
            return d
    fallback = Path("/home/pollen/reachy_care/external_profiles/reachy_care")
    return fallback if fallback.exists() else None


def _load_file(profiles_dir: Path, mode: str) -> str | None:
    filename = _INSTRUCTIONS_FILES.get(mode)
    if not filename:
        return None
    path = profiles_dir / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("switch_mode: fichier instructions manquant : %s", path)
    return None


def _get_config():
    care_path = os.environ.get("REACHY_CARE_PATH", "/home/pollen/reachy_care")
    try:
        if care_path not in sys.path:
            sys.path.insert(0, care_path)
        import config as _rc_config  # noqa: PLC0415
        return _rc_config
    except Exception:
        return None


def _build_instructions(mode: str, topic: str = "") -> str | None:
    """Construit les instructions fusionnées base + mode-spécifique."""
    profiles_dir = _get_profiles_dir()
    if not profiles_dir:
        logger.error("switch_mode: répertoire de profils introuvable.")
        return None

    mode_txt = _load_file(profiles_dir, mode)
    if not mode_txt:
        return None

    if mode == "normal":
        instructions = mode_txt
    else:
        base = _load_file(profiles_dir, "normal") or ""
        if base:
            instructions = (
                _SEPARATOR
                + "\n## MODE ACTIF : " + mode.upper() + "\n"
                + "Les regles de ce bloc ont PRIORITE ABSOLUE sur tout ce qui suit.\n"
                + _SEPARATOR
                + "\n\n"
                + mode_txt
                + "\n\n"
                + _SEPARATOR
                + "\n## REGLES GENERALES (s appliquent sauf si contredites ci-dessus)\n"
                + _SEPARATOR
                + "\n\n"
                + base
            )
        else:
            instructions = mode_txt

    if mode == "pro" and topic:
        instructions += f"\n\nSujet demandé : {topic}"

    cfg = _get_config()
    location = getattr(cfg, "LOCATION", "Paris, France") if cfg else "Paris, France"
    timezone_str = getattr(cfg, "TIMEZONE", "Europe/Paris") if cfg else "Europe/Paris"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone_str)
    except Exception:
        tz = None
    now_str = datetime.now(tz).strftime("%A %d %B %Y, %Hh%M")
    instructions = instructions.replace("{LOCATION}", location)
    instructions = instructions.replace("{DATETIME}", now_str)
    return instructions


# ---------------------------------------------------------------------------
# Helper — handler direct access
# ---------------------------------------------------------------------------

def _get_handler():
    """Récupère le handler OpenAI Realtime depuis le module patché."""
    for mod in sys.modules.values():
        if hasattr(mod, "_reachy_care_handler") and getattr(mod, "_reachy_care_handler") is not None:
            return mod._reachy_care_handler
    return None


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class SwitchMode(Tool):
    """Change le mode de comportement de Reachy."""

    name = "switch_mode"
    description = (
        "Change le mode de comportement de Reachy. "
        "Utilise 'histoire' pour lire un livre du domaine public, "
        "'pro' pour faire un exposé sur un sujet, "
        "'echecs' pour jouer aux échecs, "
        "'normal' pour revenir à la conversation habituelle."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["normal", "histoire", "pro", "echecs"],
                "description": "Mode cible.",
            },
            "topic": {
                "type": "string",
                "description": "Sujet pour le mode exposé. Exemple : 'les étoiles', 'la Tour Eiffel'.",
            },
        },
        "required": ["mode"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        mode = (kwargs.get("mode") or "").strip()
        topic = (kwargs.get("topic") or "").strip()

        if mode not in {"normal", "histoire", "pro", "echecs"}:
            return {"error": f"Mode inconnu : {mode}"}

        # 1. Construire les instructions fusionnées
        instructions = _build_instructions(mode, topic)

        # 2. Mettre à jour la session DIRECTEMENT (avant de retourner le résultat au LLM)
        #    → le LLM génère sa première réponse avec les nouvelles instructions déjà actives
        if instructions:
            handler = _get_handler()
            if handler and hasattr(handler, "schedule_session_update"):
                try:
                    await handler.schedule_session_update(instructions)
                    logger.info(
                        "switch_mode: session update direct OK (mode=%s, %d chars)",
                        mode, len(instructions),
                    )
                except Exception as exc:
                    logger.warning("switch_mode: session update direct échoué : %s", exc)
            else:
                logger.warning(
                    "switch_mode: handler non disponible — session update ignoré "
                    "(conv_app pas encore connecté ?)"
                )
        else:
            logger.warning("switch_mode: instructions introuvables pour mode=%s", mode)

        # 3. Écrire la commande pour main.py (mise à jour de l'état interne Reachy Care)
        cmd: dict[str, Any] = {"cmd": "switch_mode", "mode": mode}
        if topic:
            cmd["topic"] = topic
        try:
            with open(_CMD_FILE, "w", encoding="utf-8") as f:
                json.dump(cmd, f)
            logger.info("switch_mode: commande main.py écrite → mode=%s", mode)
        except Exception as exc:
            logger.warning("switch_mode: impossible d'écrire la commande : %s", exc)

        return {"status": "ok", "mode": mode}
