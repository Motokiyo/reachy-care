"""
report_wellbeing.py — Outil de retour de vérification de bien-être.

Appelé par le LLM après avoir posé une question de check-in (suite à une
suspicion de chute). Écrit le résultat dans /tmp/reachy_care_cmd.json,
lu par main.py pour décider d'escalader ou non l'alerte.
"""

import json
import logging
from typing import Any

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

_CMD_FILE = "/tmp/reachy_care_cmd.json"


class ReportWellbeing(Tool):
    """Signale l'issue d'une vérification de bien-être après suspicion de chute."""

    name = "report_wellbeing"
    description = (
        "À appeler UNIQUEMENT après avoir posé une question de vérification de bien-être "
        "(suite à une suspicion de chute détectée par la vision). "
        "Signale si la personne va bien, a besoin d'aide, ou n'a pas répondu."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ok", "problem", "no_response"],
                "description": (
                    "'ok' si la personne confirme qu'elle va bien, "
                    "'problem' si elle indique avoir besoin d'aide, "
                    "'no_response' si elle n'a pas répondu après ~20 secondes."
                ),
            },
        },
        "required": ["status"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        raw = kwargs.get("status", "")
        status = raw.strip() if isinstance(raw, str) else ""
        if status not in {"ok", "problem", "no_response"}:
            status = "no_response"

        cmd = {"cmd": "wellbeing_response", "status": status}

        try:
            with open(_CMD_FILE, "w", encoding="utf-8") as f:
                json.dump(cmd, f)
            logger.info("report_wellbeing: status=%r écrit dans cmd file", status)
            return {"acknowledged": True, "status": status}
        except Exception as exc:
            logger.error("report_wellbeing: impossible d'écrire la commande : %s", exc)
            return {"error": "Impossible de transmettre le résultat."}
