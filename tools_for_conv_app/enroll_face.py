"""
enroll_face.py — Outil d'enrôlement facial pour reachy_mini_conversation_app.

Déclenché par l'IA quand l'utilisateur demande à être mémorisé.
Écrit une commande dans /tmp/reachy_care_cmd.json, lu par main.py.
L'enrôlement dure ~3 secondes (10 photos automatiques) puis s'arrête seul.
"""

import json
import logging
from typing import Any

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

_CMD_FILE = "/tmp/reachy_care_cmd.json"


class EnrollFace(Tool):
    """Mémorise le visage d'une personne pour la reconnaître dans le futur."""

    name = "enroll_face"
    description = (
        "Mémorise le visage de la personne devant Reachy pour la reconnaître lors des prochaines visites. "
        "IMPORTANT : n'utilise cet outil QUE si la personne te demande EXPLICITEMENT d'être mémorisée "
        "(ex: 'mémorise mon visage', 'enregistre-moi', 'souviens-toi de moi'). "
        "Ne l'appelle JAMAIS suite à un événement [Reachy Care] de reconnaissance faciale, "
        "ni de ta propre initiative. En cas de doute : ne pas enrôler. "
        "L'enrôlement dure environ 3 secondes — dis à la personne de rester face à la caméra."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Prénom de la personne à mémoriser. Exemple : 'Alexandre', 'Marie'.",
            },
        },
        "required": ["name"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        name = (kwargs.get("name") or "").strip()

        if not name:
            return {"error": "Je n'ai pas compris le prénom. Peux-tu le répéter ?"}

        cmd = {"cmd": "enroll", "name": name}

        try:
            with open(_CMD_FILE, "w", encoding="utf-8") as f:
                json.dump(cmd, f)
            logger.info("enroll_face: commande écrite → name=%r", name)
            return {"status": "ok", "name": name}
        except Exception as exc:
            logger.error("enroll_face: impossible d'écrire la commande : %s", exc)
            return {"error": "Impossible de lancer l'enrôlement."}
