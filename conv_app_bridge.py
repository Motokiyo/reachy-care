"""
Bridge entre Reachy Care et reachy_mini_conversation_app.
Tous les modules Reachy Care utilisent ce singleton pour interagir avec l'IA.

Communication via HTTP IPC : main.py POST les événements au serveur HTTP
que le conv_app démarre sur localhost:8766 au moment de la connexion.
"""
import json
import logging
import threading
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_RC_PREFIX = "[Reachy Care]"
_IPC_BASE  = "http://127.0.0.1:8766"


class ConvAppBridge:
    """Singleton qui envoie les événements Reachy Care au conv_app via HTTP IPC."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Compatibilité ascendante — no-op (l'IPC HTTP ne nécessite plus d'enregistrement)
    # ------------------------------------------------------------------

    def register_handler(self, handler) -> None:
        """No-op conservé pour compatibilité. L'IPC HTTP remplace l'accès direct."""
        logger.debug("ConvAppBridge.register_handler() ignoré — IPC HTTP actif.")

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def set_context(
        self,
        person=None,
        mood=None,
        memory_summary=None,
        profile=None,
    ) -> None:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo
        try:
            import config as _cfg
            tz = ZoneInfo(getattr(_cfg, "TIMEZONE", "Europe/Paris"))
        except Exception:
            tz = None
        now_str = _dt.now(tz).strftime("%A %d %B %Y à %Hh%M")

        if person:
            memory_ctx = f" Contexte mémorisé : {memory_summary}." if memory_summary else ""

            profile_ctx = ""
            if profile:
                parts = []
                if profile.get("medications"):
                    parts.append("Médicaments : " + ", ".join(profile["medications"]))
                if profile.get("schedules"):
                    parts.append("Horaires : " + ", ".join(profile["schedules"]))
                if profile.get("emergency_contact"):
                    parts.append("Contact urgence : " + profile["emergency_contact"])
                if profile.get("notes"):
                    parts.append("Notes : " + profile["notes"])
                if parts:
                    profile_ctx = " Profil : " + " | ".join(parts) + "."

            text = (
                f"{_RC_PREFIX} La personne devant toi s'appelle {person}. "
                f"Nous sommes le {now_str}.{memory_ctx}{profile_ctx} "
                f"Salue-la chaleureusement par son prénom."
            )
            instructions = (
                "Accueille cette personne avec joie et douceur, en une ou deux phrases maximum. "
                "Utilise son prénom."
            )
        else:
            text = (
                f"{_RC_PREFIX} Une personne est devant toi, mais je ne la reconnais pas. "
                f"Nous sommes le {now_str}."
            )
            instructions = (
                "Accueille cette personne avec bienveillance et demande-lui son prénom "
                "en une phrase douce."
            )
        self._post("/event", {"text": text, "instructions": instructions})

    def trigger_check_in(self, person: str | None = None) -> None:
        """Demande au LLM de vérifier si la personne va bien (suspicion de chute).

        Le LLM pose une question douce, attend la réponse, puis appelle le tool
        report_wellbeing pour signaler l'issue à main.py.
        """
        who = person.capitalize() if person else "la personne"
        text = (
            f"{_RC_PREFIX} Suspicion de chute : {who} est immobile depuis plusieurs secondes. "
            "Vérifie doucement si elle va bien."
        )
        instructions = (
            "Pose une question douce et naturelle pour vérifier que la personne va bien. "
            "Exemple : 'Vous êtes confortablement installé ? Tout va bien ?' "
            "Attends sa réponse. "
            "— Si elle répond positivement (oui, ça va, etc.), appelle report_wellbeing(status='ok'). "
            "— Si elle répond négativement ou semble en difficulté, appelle report_wellbeing(status='problem'). "
            "— Si tu n'obtiens pas de réponse après environ 20 secondes, appelle report_wellbeing(status='no_response'). "
            "Ne dramatise pas, reste calme et rassurant."
        )
        self._post("/event", {"text": text, "instructions": instructions})

    def trigger_alert(self, alert_type: str, details: str = "") -> None:
        location_part = f" (lieu : {details})" if details else ""
        text = (
            f"{_RC_PREFIX} URGENT — Alerte de type '{alert_type}' détectée{location_part}. "
            "Une personne pourrait avoir besoin d'aide."
        )
        instructions = (
            "Réponds immédiatement de façon très rassurante, en maximum 2 phrases courtes. "
            "Vérifie si la personne va bien. Ne dramatise pas mais montre que tu es là. "
            "Si elle ne répond pas, propose d'appeler un proche."
        )
        self._post("/event", {"text": text, "instructions": instructions})

    def announce_chess_move(
        self,
        move: str,
        player: str = "",
        score_cp: int | None = None,
        best_reply: str | None = None,
        mate_in: int | None = None,
        move_number: int = 0,
        commentary: str = "",
    ) -> None:
        """Appelé par le module chess pour faire commenter un coup humain observé."""
        parts = []
        if player:
            parts.append(f"Les {player} ont joué {move}")
        else:
            parts.append(f"Le coup '{move}' vient d'être joué")
        if move_number:
            parts[0] += f" (coup n°{move_number})"

        eval_part = ""
        if mate_in is not None:
            plural = "s" if abs(mate_in) > 1 else ""
            eval_part = f" Mat en {abs(mate_in)} coup{plural}."
        elif score_cp is not None:
            if abs(score_cp) < 50:
                eval_part = " Position équilibrée."
            elif score_cp >= 150:
                eval_part = " Avantage clair des Blancs."
            elif score_cp > 0:
                eval_part = f" Légère avance des Blancs ({score_cp} centipions)."
            elif score_cp <= -150:
                eval_part = " Avantage clair des Noirs."
            else:
                eval_part = f" Légère avance des Noirs ({abs(score_cp)} centipions)."

        reply_part = f" Meilleure réponse suggérée : {best_reply}." if best_reply else ""
        if commentary:
            reply_part += f" {commentary}"

        text = f"{_RC_PREFIX} {'. '.join(parts)}.{eval_part}{reply_part}"
        instructions = (
            "Commente ce coup d'échecs en 1 à 2 phrases, avec enthousiasme et bienveillance. "
            "Adopte le ton d'un coach sympa pour personnes âgées. "
            "N'utilise pas le jargon technique — traduis les notations en mots simples. "
            "Encourage le joueur."
        )
        self._post("/event", {"text": text, "instructions": instructions})

    def announce_chess_game_start(self, reachy_color: str, skill_label: str) -> None:
        """Annonce le début d'une partie — Reachy explique les règles du jeu."""
        text = (
            f"{_RC_PREFIX} Nouvelle partie d'échecs. "
            f"Je joue les {reachy_color}. Niveau : {skill_label}. "
            "Le joueur humain joue les Blancs et commence."
        )
        instructions = (
            "Annonce joyeusement le début de la partie. "
            "Dis que tu joues les Noirs, que c'est au joueur de commencer, "
            "et que tu vas adapter ton niveau. "
            "Sois enthousiaste, 2 phrases max."
        )
        self._post("/event", {"text": text, "instructions": instructions})

    def announce_human_chess_move(self, move_san: str, move_number: int) -> None:
        """Confirme le coup humain et annonce que Reachy réfléchit."""
        text = (
            f"{_RC_PREFIX} Le joueur humain vient de jouer {move_san} "
            f"(coup n°{move_number}). Je réfléchis à ma réponse."
        )
        instructions = (
            "Confirme le coup du joueur en le traduisant en langage naturel (évite la notation algébrique brute). "
            "Dis que tu réfléchis. 1-2 phrases, ton de joueur concentré."
        )
        self._post("/event", {"text": text, "instructions": instructions})

    def announce_reachy_move(
        self,
        move_san: str,
        from_sq: str,
        to_sq: str,
        score_cp: int | None = None,
        mate_in: int | None = None,
        move_number: int = 0,
    ) -> None:
        """Reachy annonce son propre coup et demande au joueur de le placer."""
        eval_hint = ""
        if mate_in is not None and mate_in > 0:
            eval_hint = f" Je vois un mat en {mate_in}."
        elif score_cp is not None and score_cp > 150:
            eval_hint = " J'ai un bon avantage."
        elif score_cp is not None and score_cp < -150:
            eval_hint = " Tu as un bon avantage — je dois me défendre."

        text = (
            f"{_RC_PREFIX} Mon coup (Reachy, coup n°{move_number}) : {move_san}. "
            f"Déplacez ma pièce de {from_sq} vers {to_sq}.{eval_hint}"
        )
        instructions = (
            f"Annonce ton coup d'échecs '{move_san}' en language naturel. "
            f"Dis clairement au joueur de déplacer ta pièce de la case {from_sq} vers {to_sq}. "
            "Sois précis et direct — le joueur doit savoir exactement quoi faire. "
            "Tu peux ajouter un bref commentaire stratégique en 1 phrase. 2-3 phrases max."
        )
        self._post("/event", {"text": text, "instructions": instructions})

    def confirm_move_executed(self) -> None:
        """Confirme que le joueur a bien placé la pièce de Reachy."""
        text = f"{_RC_PREFIX} Le joueur a bien placé ma pièce. À ton tour !"
        instructions = (
            "Remercie le joueur d'avoir placé ta pièce et encourage-le pour son prochain coup. "
            "1 phrase courte et enthousiaste."
        )
        self._post("/event", {"text": text, "instructions": instructions})

    def announce_chess_game_over(self, winner: str, reason: str, new_skill_label: str) -> None:
        """Annonce la fin de partie et l'ajustement de niveau."""
        level_msg = f" J'ajuste mon niveau : {new_skill_label}." if new_skill_label else ""
        text = (
            f"{_RC_PREFIX} Fin de partie ! Vainqueur : {winner} ({reason}).{level_msg}"
        )
        if winner == "Reachy":
            instructions = (
                "Annonce ta victoire avec joie mais sans te vanter. "
                "Félicite le joueur pour la partie. "
                f"Dis que tu vas jouer un peu plus fort la prochaine fois ({new_skill_label}). "
                "Propose une revanche. 2-3 phrases."
            )
        elif winner == "le joueur":
            instructions = (
                "Félicite chaleureusement le joueur pour sa victoire ! "
                "Sois bon perdant et enthousiaste. "
                f"Dis que tu vas jouer un peu moins fort la prochaine fois ({new_skill_label}). "
                "Propose une revanche. 2-3 phrases."
            )
        else:
            instructions = (
                "Annonce la nulle avec bonne humeur. "
                "C'est une belle partie équilibrée. Propose une revanche. 1-2 phrases."
            )
        self._post("/event", {"text": text, "instructions": instructions})

    def enroll_complete(self, name: str, success: bool) -> None:
        if success:
            text = f"{_RC_PREFIX} Enrôlement réussi pour '{name}'. J'ai bien mémorisé ce visage."
            instructions = (
                f"Dis à {name} que tu l'as bien mémorisé(e) et que tu le/la reconnaîtras "
                "désormais. Sois chaleureux(se), en une phrase."
            )
        else:
            text = f"{_RC_PREFIX} L'enrôlement de '{name}' a échoué. Je n'ai pas pu mémoriser ce visage."
            instructions = (
                f"Explique gentiment à {name} que tu n'as pas pu mémoriser son visage "
                "et propose de réessayer. Reste encourageant(e), en une ou deux phrases."
            )
        self._post("/event", {"text": text, "instructions": instructions})

    def update_session_instructions(self, instructions: str) -> None:
        self._post("/session_update", {"instructions": instructions})

    def announce_mode_switch(self, announce_text: str) -> None:
        instructions = "Confirme oralement le changement de mode en une phrase enthousiaste et courte."
        self._post("/event", {"text": announce_text, "instructions": instructions})

    def inject_memory(self) -> None:
        """Relit la mémoire de session et la ré-injecte dans le contexte LLM.

        À appeler périodiquement pour que le LLM ne perde pas le fil
        quand la fenêtre de contexte OpenAI Realtime se remplit.
        """
        import json
        from pathlib import Path
        memory_file = Path("/tmp/reachy_session_memory.json")
        try:
            data = json.loads(memory_file.read_text(encoding="utf-8"))
        except Exception:
            return  # Pas de mémoire — rien à injecter

        # Filtrer les clés internes
        items = {k: v for k, v in data.items() if not k.startswith("_")}
        if not items:
            return

        lines = "\n".join(f"- {k} : {v}" for k, v in items.items())
        text = f"{_RC_PREFIX} Rappel de contexte (mémoire de session) :\n{lines}"
        instructions = (
            "Prends note de ce rappel de contexte et poursuis naturellement "
            "ce que tu faisais, sans le mentionner explicitement."
        )
        self._post("/event", {"text": text, "instructions": instructions})
        logger.debug("ConvAppBridge.inject_memory() : %d clés injectées", len(items))

    def keepalive(self) -> None:
        text = f"{_RC_PREFIX} Vérification de présence — tout va bien ?"
        instructions = "Dis une courte phrase douce pour vérifier que la personne va bien. Maximum une phrase."
        self._post("/event", {"text": text, "instructions": instructions})

    def wake(self) -> None:
        """Wake word détecté — réinitialise l'état idle sans faire parler Reachy."""
        self._post("/wake", {})

    # ------------------------------------------------------------------
    # Méthode interne HTTP
    # ------------------------------------------------------------------

    def _post(self, path: str, data: dict) -> None:
        try:
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                f"{_IPC_BASE}{path}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                resp.read()
            logger.debug("ConvAppBridge IPC %s : OK", path)
        except urllib.error.URLError as exc:
            logger.warning(
                "ConvAppBridge IPC %s : conv_app non disponible (normal si pas encore connecté) : %s",
                path, exc,
            )
        except Exception as exc:
            logger.error("ConvAppBridge IPC %s : %s", path, exc)


bridge = ConvAppBridge()
