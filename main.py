"""
main.py — Orchestrateur principal de Reachy Care
Gère la boucle principale, les modules de perception et les commandes vocales.

Démarrage :
    python main.py [--debug] [--no-chess] [--no-face]
"""

import argparse
import contextlib
import json
import logging
import logging.handlers
import os
import signal
import sys
import time

import chess

sys.path.insert(0, "/home/pollen/reachy_care")

import requests

from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
import numpy as np

import config
from modules.face_recognizer import FaceRecognizer
from modules.register_face import FaceEnroller
from modules.chess_detector import ChessDetector
from modules.chess_engine import ChessEngine
from modules.fall_detector import FallDetector
from modules.memory_manager import MemoryManager
from modules.sound_detector import SoundDetector
from modules.mode_manager import ModeManager, MODE_ECHECS, MODE_HISTOIRE, MODE_PRO, MODE_NORMAL
from modules.tts import TTSEngine
from modules.wake_word import WakeWordDetector
from conv_app_bridge import bridge

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

CMD_FILE = "/tmp/reachy_care_cmd.json"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Setup du logging
# ---------------------------------------------------------------------------

def setup_logging(debug: bool = False) -> None:
    """Configure les handlers fichier (rotation) et console."""
    level = logging.DEBUG if debug else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    os.makedirs(config.LOGS_DIR, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(fh)
    root.addHandler(ch)


# ---------------------------------------------------------------------------
# Classe principale
# ---------------------------------------------------------------------------

class ReachyCare:
    """Orchestrateur principal de Reachy Care."""

    def __init__(
        self,
        enable_chess: bool = True,
        enable_face: bool = True,
    ) -> None:
        self._stop = False
        self._enable_chess = enable_chess
        self._enable_face = enable_face

        self.mini = None
        self._last_greeted: str | None = None
        self._face_miss_count: int = 0  # frames consécutives sans visage reconnu
        self._chess_board = chess.Board()

        # Pre-initialize module attributes so shutdown() is always safe
        self.tts = None
        self.recognizer = None
        self.enroller = None
        self.chess_det = None
        self.chess_eng = None
        self.fall_det = None
        self.memory = None
        self.mode_manager: ModeManager | None = None
        self.wake_word: WakeWordDetector | None = None
        self.sound_det: SoundDetector | None = None

        # État du module chess
        self._chess_detected_frames = 0
        self._chess_absent_frames = 0
        self._chess_fen_candidate: str | None = None      # FEN en cours de validation
        self._chess_fen_candidate_count: int = 0          # frames consécutives identiques
        self._chess_last_stable_fen: str | None = None    # dernier FEN confirmé
        self._chess_noise_count: int = 0                  # changements illégaux consécutifs
        self._chess_move_count: int = 0                   # coups observés
        self._chess_orientation_flip: bool = False        # orientation échiquier

        # Jeu Reachy joueur
        self._chess_reachy_color = None         # chess.BLACK ou chess.WHITE
        self._chess_game_state = "idle"         # "idle" | "human_turn" | "reachy_turn" | "waiting_execution"
        self._chess_expected_fen: str | None = None  # FEN attendu après coup de Reachy
        self._chess_wins = 0
        self._chess_losses = 0

        # Session tracking pour la génération de résumé en fin de session
        self._session_events: list[str] = []
        self._seen_persons: dict[str, dict] = {}  # name → memory dict

        # Check-in chute — état du check-in en cours
        self._fall_checkin_active: bool = False
        self._fall_checkin_time: float = 0.0
        self._pending_impact_time: float | None = None  # timestamp impact sonore en attente de fusion
        self._last_cry_time: float = 0.0               # cooldown anti-spam détection cri

        # Suivi session OpenAI Realtime (expire à 60min — reconnexion proactive à 55min)
        self._conv_app_start_time: float = time.monotonic()

        # Keepalive bridge — timestamp de la dernière activité envoyée au bridge
        self._last_bridge_activity = time.monotonic()

        # Mémoire de session — ré-injection périodique dans le contexte LLM
        self._last_memory_inject = time.monotonic()

        self._check_daemon()

        # Protection double instance — vérifier si un autre main.py tourne déjà
        if config.PID_FILE.exists():
            try:
                existing_pid = int(config.PID_FILE.read_text().strip())
                os.kill(existing_pid, 0)  # signal 0 = vérif existence seulement
                logger.error(
                    "main.py déjà en cours (PID %d) — arrêt immédiat pour éviter les conflits.",
                    existing_pid,
                )
                sys.exit(1)
            except (ProcessLookupError, ValueError):
                # PID mort ou invalide — fichier obsolète, on continue
                logger.warning("PID_FILE obsolète — nettoyage.")
                config.PID_FILE.unlink(missing_ok=True)

        with open(config.PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        logger.info("PID %d écrit dans %s", os.getpid(), config.PID_FILE)

        self._init_modules()

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _check_daemon(self) -> None:
        """Démarre le daemon HTTP Reachy si nécessaire et vérifie son accessibilité.

        Séquence obligatoire (cf. RESULTATS_TESTS.md — 09/03/2026) :
        1. POST /api/daemon/start?wake_up=false  — démarre le backend (moteurs + caméra)
        2. GET  /api/state/full                  — confirme que le daemon répond
        Sans cette étape, ReachyMini() ne peut pas accéder à la caméra ni aux moteurs.
        """
        start_url = f"{config.REACHY_DAEMON_URL}/api/daemon/start?wake_up=false"
        state_url = f"{config.REACHY_DAEMON_URL}/api/state/full"

        # Étape 1 — démarrer le daemon (idempotent si déjà démarré)
        try:
            resp = requests.post(start_url, timeout=config.REACHY_DAEMON_TIMEOUT)
            resp.raise_for_status()
            logger.info("Daemon HTTP démarré : %s (HTTP %d)", start_url, resp.status_code)
        except Exception as exc:
            logger.warning("Impossible de démarrer le daemon : %s — %s", start_url, exc)
            logger.warning("Poursuite du démarrage — le daemon est peut-être déjà actif.")

        # Étape 2 — vérifier l'accessibilité de l'état complet
        try:
            resp = requests.get(state_url, timeout=config.REACHY_DAEMON_TIMEOUT)
            resp.raise_for_status()
            logger.info("Daemon HTTP accessible : %s (HTTP %d)", state_url, resp.status_code)
        except Exception as exc:
            logger.warning("Daemon HTTP non accessible : %s — %s", state_url, exc)
            logger.warning("Poursuite du démarrage sans confirmation daemon.")

    def _init_modules(self) -> None:
        """Instancie tous les modules de perception et d'action."""

        self.tts = TTSEngine(
            voice=config.TTS_VOICE,
            speed=config.TTS_SPEED,
            amplitude=config.TTS_AMPLITUDE,
            backend=config.TTS_BACKEND,
        )
        logger.info("TTSEngine initialisé.")

        self.memory = MemoryManager(str(config.KNOWN_FACES_DIR))
        logger.info("MemoryManager initialisé.")

        self.mode_manager = ModeManager(
            profiles_dir=str(config.BASE_DIR / "external_profiles" / "reachy_care"),
            bridge=bridge,
        )
        logger.info("ModeManager initialisé.")

        if self._enable_face:
            try:
                self.recognizer = FaceRecognizer(
                    known_faces_dir=str(config.KNOWN_FACES_DIR),
                    models_root=str(config.MODELS_DIR),
                    model_name=config.FACE_MODEL_NAME,
                    det_size=config.FACE_DET_SIZE,
                    threshold=config.FACE_COSINE_THRESHOLD,
                    det_score_min=config.FACE_DET_SCORE_MIN,
                )
                self.enroller = FaceEnroller(
                    face_app=self.recognizer._app,
                    known_faces_dir=str(config.KNOWN_FACES_DIR),
                    registry_path=str(config.KNOWN_FACES_DIR / "registry.json"),
                )
                logger.info("FaceRecognizer et FaceEnroller initialisés.")
            except Exception as exc:
                logger.warning("Module face désactivé : %s", exc)
                self._enable_face = False

        if self._enable_chess:
            try:
                self.chess_det = ChessDetector(
                    model_path=config.CHESS_MODEL_PATH,
                    conf_threshold=config.CHESS_CONF_THRESHOLD,
                    imgsz=config.CHESS_IMGSZ,
                )
                stockfish_path = next(
                    (p for p in config.CHESS_STOCKFISH_PATHS if os.path.isfile(p) and os.access(p, os.X_OK)),
                    None,
                )
                if stockfish_path is None:
                    raise FileNotFoundError(
                        f"Stockfish introuvable dans : {config.CHESS_STOCKFISH_PATHS}"
                    )
                self.chess_eng = ChessEngine(
                    stockfish_path=stockfish_path,
                    think_time=config.CHESS_THINK_TIME,
                )
                logger.info("ChessDetector et ChessEngine initialisés (stockfish=%s).", stockfish_path)
            except Exception as exc:
                logger.warning("Module chess désactivé : %s", exc)
                self._enable_chess = False

        try:
            self.fall_det = FallDetector(
                model_complexity=config.FALL_MODEL_COMPLEXITY,
                detection_confidence=config.FALL_DETECTION_CONF,
                fall_ratio_threshold=config.FALL_RATIO_THRESHOLD,
                sustained_seconds=config.FALL_SUSTAINED_SEC,
                ghost_trigger_seconds=config.FALL_GHOST_TRIGGER_SEC,
                ghost_reset_seconds=config.FALL_GHOST_RESET_SEC,
            )
            logger.info("FallDetector initialisé.")
        except Exception as exc:
            logger.warning("FallDetector désactivé : %s", exc)

        if config.SOUND_DETECTION_ENABLED:
            try:
                self.sound_det = SoundDetector(
                    model_path=str(config.SOUND_MODEL_PATH),
                    on_impact=self._handle_sound_impact,
                    threshold=config.SOUND_IMPACT_THRESHOLD,
                    on_cry=self._handle_cry,
                )
                logger.info("SoundDetector initialisé (disponible=%s).", self.sound_det.available)
            except Exception as exc:
                logger.warning("SoundDetector désactivé : %s", exc)

        if config.WAKE_WORD_ENABLED:
            try:
                self.wake_word = WakeWordDetector(
                    model_path=config.WAKE_WORD_MODEL_PATH,
                    on_wake=self._on_wake_word,
                    threshold=config.WAKE_WORD_THRESHOLD,
                    input_device_index=config.WAKE_WORD_DEVICE_INDEX,
                    fallback_model=config.WAKE_WORD_FALLBACK,
                )
                logger.info("WakeWordDetector initialisé.")
            except Exception as exc:
                logger.warning("WakeWordDetector désactivé : %s", exc)

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Démarre la boucle principale dans le contexte ReachyMini."""
        try:
            with ReachyMini() as mini:
                self.mini = mini

                # Réveil et position neutre
                # wake_up() sort la tête du support (son + mouvement initial)
                mini.wake_up()
                time.sleep(1.5)  # laisser le temps aux moteurs de s'activer après wake_up

                # Activer les moteurs en mode stiff pour maintenir la position cible
                mini.enable_motors()
                time.sleep(1.0)

                mini.goto_target(
                    head=create_head_pose(pitch=config.HEAD_IDLE_PITCH_DEG, degrees=True),
                    duration=2.0,
                )
                logger.info("Reachy en position neutre (pitch=%d°).", config.HEAD_IDLE_PITCH_DEG)
                time.sleep(2.5)  # attendre la fin du mouvement goto_target

                # Salutation initiale
                self.tts.say("Bonjour, je suis Reachy. Je suis là.", blocking=True)

                # Démarrer la détection sonore et le wake word
                if self.sound_det:
                    self.sound_det.start()
                if self.wake_word:
                    self.wake_word.start()

                # Boucle principale avec throttling
                last_face = last_chess = last_fall = 0.0

                while not self._stop:
                    frame = mini.media.get_frame()
                    if frame is None:
                        time.sleep(0.1)
                        continue

                    t = time.monotonic()

                    if self.fall_det and t - last_fall >= config.FALL_INTERVAL_SEC:
                        self._handle_fall(frame)
                        last_fall = t

                    if self._enable_face and t - last_face >= config.FACE_INTERVAL_SEC:
                        self._handle_face(frame)
                        last_face = t

                    if self._enable_chess and t - last_chess >= config.CHESS_INTERVAL_SEC:
                        self._handle_chess(frame)
                        last_chess = t

                    self._check_voice_commands()
                    self._check_fall_checkin_timeout()
                    self._check_conv_app_health()
                    time.sleep(config.FRAME_INTERVAL_SEC)

        finally:
            self.shutdown()

    # ------------------------------------------------------------------
    # Handlers d'événements
    # ------------------------------------------------------------------

    def _handle_face(self, frame: np.ndarray) -> None:
        """Identifie le visage et met à jour le contexte conversationnel."""
        if self.recognizer is None:
            return
        # Ne pas interrompre le mode échecs / histoire / pro avec la reconnaissance faciale
        if self.mode_manager and self.mode_manager.get_current_mode() in (MODE_ECHECS, MODE_HISTOIRE, MODE_PRO):
            return
        try:
            name, score = self.recognizer.identify(frame)
            if name and name != self._last_greeted:
                self._face_miss_count = 0
                logger.info("Personne reconnue: %s (score=%.2f)", name, score)

                # Mémoire persistante
                memory_summary = None
                mem = {}
                if self.memory:
                    mem = self.memory.on_seen(name)
                    memory_summary = mem.get("conversation_summary") or None
                    if name not in self._seen_persons:
                        self._seen_persons[name] = mem
                        self._session_events.append(
                            f"Personne reconnue : {name} (session #{mem['sessions_count']})"
                        )
                        logger.info("Personne reconnue : %s (session #%d)", name, mem["sessions_count"])

                profile = mem.get("profile") or None

                # Contexte mémoire enrichi : 3 dernières sessions + 15 faits récents
                sessions = mem.get("sessions", [])[-3:]
                facts = mem.get("facts", [])[-15:]
                if sessions or facts:
                    sessions_txt = "\n".join(
                        f"- {s.get('date', '?')} : {s.get('summary', '')}" for s in sessions
                    ) or "Première rencontre."
                    facts_txt = "\n".join(
                        f"- [{f.get('category', '?')}] {f.get('fact', '')}" for f in facts
                    ) or "Aucun fait enregistré."
                    meds = ", ".join(profile.get("medications", [])) if profile else ""
                    contact = profile.get("emergency_contact", "") if profile else ""
                    memory_summary = (
                        f"HISTORIQUE RÉCENT ({name}) :\n{sessions_txt}\n\n"
                        f"FAITS CONNUS :\n{facts_txt}\n\n"
                        f"PROFIL :\nMédicaments : {meds or 'non renseigné'}\n"
                        f"Contact urgence : {contact or 'non renseigné'}"
                    )

                bridge.set_context(person=name, memory_summary=memory_summary, profile=profile)
                self.mini.goto_target(antennas=config.ANTENNA_HAPPY, duration=0.5)
                self._last_greeted = name
            elif name:
                # Même personne — réinitialise le compteur de misses
                self._face_miss_count = 0
            else:
                # Aucun visage détecté — attendre N misses consécutives avant de réinitialiser
                self._face_miss_count += 1
                if self._face_miss_count >= config.FACE_MISS_RESET_COUNT:
                    self._last_greeted = None
                    self._face_miss_count = 0
        except Exception as exc:
            logger.debug("_handle_face: %s", exc)

    def _handle_chess(self, frame: np.ndarray) -> None:
        """Reachy joue aux échecs contre le joueur humain."""
        if self.chess_det is None or self.chess_eng is None:
            return
        try:
            import chess as _chess
            grid = self.chess_det.frame_to_grid(frame, flip=self._chess_orientation_flip)

            # --- Pas d'échiquier visible ---
            if not grid:
                self._chess_detected_frames = 0
                self._chess_absent_frames += 1
                if (
                    self._chess_absent_frames >= config.CHESS_ABSENT_FRAMES_EXIT
                    and self.mode_manager
                    and self.mode_manager.get_current_mode() == MODE_ECHECS
                ):
                    self._chess_absent_frames = 0
                    self._reset_chess_state()
                    self.mode_manager.switch_mode(MODE_NORMAL)
                return

            self._chess_absent_frames = 0
            self._chess_detected_frames += 1

            # Pré-incliner la tête dès 3 frames pour faciliter la détection continue
            if (
                config.CHESS_AUTO_DETECT
                and self._chess_detected_frames == 3
                and self.mini
                and self.mode_manager
                and self.mode_manager.get_current_mode() != MODE_ECHECS
            ):
                try:
                    self.mini.goto_target(
                        head=create_head_pose(pitch=15, degrees=True),
                        duration=1.0,
                    )
                except Exception:
                    pass

            # --- Auto-détection → basculer en MODE_ECHECS ---
            if (
                config.CHESS_AUTO_DETECT
                and self._chess_detected_frames >= config.CHESS_DETECTION_FRAMES_TRIGGER
                and self.mode_manager
                and self.mode_manager.get_current_mode() != MODE_ECHECS
            ):
                self._start_chess_game()
                return

            if not self.mode_manager or self.mode_manager.get_current_mode() != MODE_ECHECS:
                return

            # --- FEN depuis la vision ---
            new_fen = self.chess_det.grid_to_fen_pieces(grid)
            if not new_fen:
                return

            # --- Vote de stabilité ---
            if new_fen == self._chess_fen_candidate:
                self._chess_fen_candidate_count += 1
            else:
                self._chess_fen_candidate = new_fen
                self._chess_fen_candidate_count = 1

            if self._chess_fen_candidate_count < config.CHESS_STABILITY_FRAMES:
                return

            stable_fen = new_fen

            # --- Calibration initiale ---
            if self._chess_last_stable_fen is None:
                self._chess_last_stable_fen = stable_fen
                logger.info("Chess: position initiale calibrée : %s", stable_fen)
                return

            if stable_fen == self._chess_last_stable_fen:
                return

            # --- Validation du coup ---
            if self._chess_game_state == "waiting_execution":
                # On attend que le joueur pose la pièce de Reachy
                if stable_fen == self._chess_expected_fen:
                    self._chess_last_stable_fen = stable_fen
                    self._chess_game_state = "human_turn"
                    bridge.confirm_move_executed()
                    self._check_game_over()
                    return
                # Le joueur a posé quelque chose d'autre — on ignore (bruit)
                return

            if self._chess_game_state != "human_turn":
                return

            # --- Détecter le coup humain ---
            move = self.chess_det.detect_move(
                self._chess_last_stable_fen, stable_fen, self._chess_board
            )

            if move is None:
                self._chess_noise_count += 1
                if self._chess_noise_count >= config.CHESS_NOISE_TOLERANCE:
                    logger.warning("Chess: resync forcée.")
                    self._chess_noise_count = 0
                    self._chess_last_stable_fen = stable_fen
                    try:
                        turn_char = 'w' if self._chess_board.turn == _chess.WHITE else 'b'
                        self._chess_board = _chess.Board(f"{stable_fen} {turn_char} - - 0 1")
                    except Exception:
                        pass
                return

            # Coup humain valide
            self._chess_noise_count = 0
            try:
                move_san = self._chess_board.san(move)
            except Exception:
                move_san = move.uci()
            self._chess_board.push(move)
            self._chess_last_stable_fen = stable_fen
            self._chess_move_count += 1
            logger.info("Chess: joueur → %s", move_san)
            bridge.announce_human_chess_move(move_san, self._chess_move_count)

            # Vérifier fin de partie après le coup humain
            if self._check_game_over():
                return

            # --- Tour de Reachy ---
            self._chess_game_state = "reachy_turn"
            self._play_reachy_move()

        except Exception as exc:
            logger.debug("Chess: %s", exc, exc_info=True)

    def _start_chess_game(self) -> None:
        """Initialise une nouvelle partie et bascule en mode échecs."""
        import chess as _chess
        self._reset_chess_state()
        self._chess_reachy_color = _chess.BLACK
        self._chess_game_state = "human_turn"
        # Baisser la tête pour voir l'échiquier sur la table
        if self.mini:
            try:
                self.mini.goto_target(
                    head=create_head_pose(pitch=config.HEAD_CHESS_PITCH_DEG, degrees=True),
                    duration=1.5,
                )
                logger.info("Tête position échecs (pitch=%d°).", config.HEAD_CHESS_PITCH_DEG)
            except Exception as exc:
                logger.warning("goto_target chess pitch échoué : %s", exc)
        if self.mode_manager:
            self.mode_manager.switch_mode(MODE_ECHECS)
        level = config.CHESS_SKILL_LEVEL_INIT
        if self.chess_eng:
            self.chess_eng.set_skill_level(level)
        bridge.announce_chess_game_start(
            reachy_color="Noirs",
            skill_label=self.chess_eng.get_skill_label() if self.chess_eng else "débutant",
        )

    def _play_reachy_move(self) -> None:
        """Calcule et annonce le coup de Reachy, puis attend la confirmation."""
        import chess as _chess
        move = self.chess_eng.best_move(self._chess_board)
        if move is None:
            self._chess_game_state = "human_turn"
            return

        from_sq = _chess.square_name(move.from_square)
        to_sq   = _chess.square_name(move.to_square)
        try:
            move_san = self._chess_board.san(move)
        except Exception:
            move_san = move.uci()

        # Appliquer le coup de Reachy sur le board interne
        self._chess_board.push(move)
        self._chess_move_count += 1
        logger.info("Chess: Reachy → %s (%s → %s)", move_san, from_sq, to_sq)

        # Calculer le FEN attendu après que le joueur pose la pièce
        self._chess_expected_fen = self._chess_board.board_fen()
        self._chess_game_state = "waiting_execution"

        # Analyse position
        analysis = self.chess_eng.evaluate_with_best_reply(self._chess_board)

        bridge.announce_reachy_move(
            move_san=move_san,
            from_sq=from_sq,
            to_sq=to_sq,
            score_cp=analysis.get("score_cp"),
            mate_in=analysis.get("mate_in"),
            move_number=self._chess_move_count,
        )

    def _check_game_over(self) -> bool:
        """Vérifie fin de partie. Retourne True si terminée."""
        import chess as _chess
        board = self._chess_board
        if board.is_checkmate():
            winner = "Reachy" if board.turn != self._chess_reachy_color else "le joueur"
            if winner == "Reachy":
                self._chess_wins += 1
                new_level = min(20, getattr(self.chess_eng, '_skill_level', config.CHESS_SKILL_LEVEL_INIT) + 1) if self.chess_eng else config.CHESS_SKILL_LEVEL_INIT
            else:
                self._chess_losses += 1
                new_level = max(0, getattr(self.chess_eng, '_skill_level', config.CHESS_SKILL_LEVEL_INIT) - 1) if self.chess_eng else config.CHESS_SKILL_LEVEL_INIT
            if self.chess_eng:
                self.chess_eng.set_skill_level(new_level)
            bridge.announce_chess_game_over(
                winner=winner,
                reason="échec et mat",
                new_skill_label=self.chess_eng.get_skill_label() if self.chess_eng else "",
            )
            self._reset_chess_state()
            if self.mode_manager:
                self.mode_manager.switch_mode(MODE_NORMAL)
            return True
        if board.is_stalemate() or board.is_insufficient_material() or board.is_seventyfive_moves():
            bridge.announce_chess_game_over(winner="personne", reason="nulle", new_skill_label="")
            self._reset_chess_state()
            if self.mode_manager:
                self.mode_manager.switch_mode(MODE_NORMAL)
            return True
        return False

    def _reset_chess_state(self) -> None:
        """Remet à zéro l'état du module chess pour une nouvelle partie."""
        import chess as _chess
        self._chess_reachy_color = None
        self._chess_game_state = "idle"
        # Relever la tête en position normale
        if self.mini:
            self.mini.goto_target(
                head=create_head_pose(pitch=config.HEAD_IDLE_PITCH_DEG, degrees=True),
                duration=1.5,
            )
        self._chess_expected_fen = None
        self._chess_board = _chess.Board()
        self._chess_fen_candidate = None
        self._chess_fen_candidate_count = 0
        self._chess_last_stable_fen = None
        self._chess_noise_count = 0
        self._chess_move_count = 0
        self._chess_detected_frames = 0
        self._chess_absent_frames = 0
        logger.info("Chess: état remis à zéro.")

    def _handle_fall(self, frame: np.ndarray) -> None:
        """Détecte une chute et déclenche un check-in vocal avant d'alerter."""
        if self.fall_det is None or self._fall_checkin_active:
            return
        try:
            if self.fall_det.is_fallen(frame):
                logger.warning("Suspicion de chute — check-in LLM déclenché")
                self._session_events.append("Suspicion de chute — check-in en cours")
                self._fall_checkin_active = True
                self._fall_checkin_time = time.monotonic()
                self.mini.goto_target(antennas=config.ANTENNA_ALERT, duration=0.3)
                bridge.trigger_check_in(self._last_greeted)
        except Exception as exc:
            logger.debug("_handle_fall: %s", exc)

    def _handle_sound_impact(self, label: str, score: float) -> None:
        """Appelé par SoundDetector quand un son d'impact (chute possible) est détecté."""
        logger.warning("Impact sonore détecté : %s (score=%.2f)", label, score)
        self._session_events.append(f"Impact sonore : {label}")

        # Fusion audio + vidéo obligatoire : squelette absent depuis > 2s → check-in
        # Un son seul ne suffit pas (chien, objet qui tombe, bruit ambiant)
        if (
            self.fall_det
            and self.fall_det._skeleton_absent_since is not None
            and time.monotonic() - self.fall_det._skeleton_absent_since > 2.0
            and not self._fall_checkin_active
        ):
            logger.warning("Fusion audio+vidéo : impact sonore + squelette absent → check-in")
            self._fall_checkin_active = True
            self._fall_checkin_time = time.monotonic()
            if self.mini:
                self.mini.goto_target(antennas=config.ANTENNA_ALERT, duration=0.3)
            bridge.trigger_check_in(self._last_greeted)
        else:
            # Mémoriser l'impact : si le squelette disparaît dans les 5s → check-in différé
            self._pending_impact_time = time.monotonic()
            logger.info("Impact sonore mémorisé — surveillance squelette pendant 5s (fusion différée)")

    def _handle_cry(self) -> None:
        """Détection de cri par RMS — indépendant de la VAD conv_app (half-duplex).

        Appelé par SoundDetector quand RMS > seuil sur 500ms.
        Interrompt la réponse de Reachy et déclenche un check-in immédiat.
        Cooldown 5s pour éviter le spam.
        """
        now = time.monotonic()
        if now - self._last_cry_time < 5.0:
            return
        if self._fall_checkin_active:
            return
        self._last_cry_time = now
        logger.warning("Cri détecté (RMS) — interruption conv_app + check-in")
        self._session_events.append("Cri ou son fort détecté (RMS)")
        bridge._post("/interrupt", {})
        bridge.trigger_check_in(self._last_greeted)

    def _escalate_fall_alert(self) -> None:
        """Escalade l'alerte chute après un check-in négatif ou sans réponse."""
        self._fall_checkin_active = False
        self._session_events.append("Alerte chute confirmée")
        logger.warning("CHUTE CONFIRMÉE — alerte escaladée")
        bridge.trigger_alert("chute confirmée")
        self._send_fall_telegram(self._last_greeted)
        self._send_fall_email(self._last_greeted)
        if self.fall_det:
            self.fall_det.reset()

    def _check_fall_checkin_timeout(self) -> None:
        """Escalade si le LLM n'a pas rappelé dans les 45 secondes."""
        # Vérification fusion différée : impact récent + squelette vient de disparaître
        if (
            self._pending_impact_time is not None
            and time.monotonic() - self._pending_impact_time < 5.0
            and self.fall_det
            and self.fall_det._skeleton_absent_since is not None
            and not self._fall_checkin_active
        ):
            logger.warning("Fusion différée : squelette absent après impact sonore → check-in")
            self._pending_impact_time = None
            self._fall_checkin_active = True
            self._fall_checkin_time = time.monotonic()
            if self.mini:
                self.mini.goto_target(antennas=config.ANTENNA_ALERT, duration=0.3)
            bridge.trigger_check_in(self._last_greeted)
            return
        # Annuler si impact trop vieux (>5s)
        if self._pending_impact_time is not None and time.monotonic() - self._pending_impact_time >= 5.0:
            self._pending_impact_time = None

        if not self._fall_checkin_active:
            return
        if time.monotonic() - self._fall_checkin_time > 45:
            logger.warning("Check-in chute : timeout 45s — escalade")
            self._escalate_fall_alert()

    def _send_fall_telegram(self, person_name: str | None) -> None:
        """Envoie une alerte Telegram en cas de chute détectée."""
        if not config.TELEGRAM_ENABLED:
            return
        if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
            logger.warning("Alerte Telegram : BOT_TOKEN ou CHAT_ID non configurés.")
            return

        import threading
        from datetime import datetime

        who = person_name.capitalize() if person_name else "une personne inconnue"
        now = datetime.now().strftime("%d/%m/%Y à %Hh%M")
        text = (
            f"⚠️ *Reachy Care — Chute détectée*\n\n"
            f"🕐 {now}\n"
            f"👤 Personne : {who}\n\n"
            f"Reachy a réagi vocalement. Vérifiez la situation."
        )

        def _send():
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
                    timeout=10,
                )
                if resp.ok:
                    logger.info("Alerte Telegram envoyée.")
                else:
                    logger.error("Telegram: %s %s", resp.status_code, resp.text)
            except Exception as exc:
                logger.error("Échec envoi Telegram : %s", exc)

        threading.Thread(target=_send, name="fall-telegram", daemon=True).start()

    def _send_fall_email(self, person_name: str | None) -> None:
        """Envoie une alerte email en cas de chute détectée."""
        if not config.ALERT_EMAIL_ENABLED:
            return
        if not config.ALERT_EMAIL_FROM or not config.ALERT_EMAIL_PASSWORD:
            logger.warning("Alerte email : identifiants non configurés (ALERT_EMAIL_FROM / ALERT_EMAIL_PASSWORD).")
            return

        import smtplib
        import threading
        from email.message import EmailMessage
        from datetime import datetime

        who = person_name.capitalize() if person_name else "une personne inconnue"
        now = datetime.now().strftime("%d/%m/%Y à %Hh%M")

        msg = EmailMessage()
        msg["Subject"] = f"⚠️ Reachy Care — Chute détectée ({who})"
        msg["From"]    = config.ALERT_EMAIL_FROM
        msg["To"]      = config.ALERT_EMAIL_TO
        msg.set_content(
            f"Bonjour,\n\n"
            f"Le robot Reachy a détecté une chute le {now}.\n\n"
            f"Personne concernée : {who}\n\n"
            f"Reachy a immédiatement réagi vocalement. Veuillez vérifier la situation.\n\n"
            f"— Reachy Care"
        )

        def _send():
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
                    smtp.login(config.ALERT_EMAIL_FROM, config.ALERT_EMAIL_PASSWORD)
                    smtp.send_message(msg)
                logger.info("Alerte email chute envoyée à %s.", config.ALERT_EMAIL_TO)
            except Exception as exc:
                logger.error("Échec envoi email alerte : %s", exc)

        # Envoyer dans un thread pour ne pas bloquer la boucle principale
        threading.Thread(target=_send, name="fall-email", daemon=True).start()

    # ------------------------------------------------------------------
    # Enrôlement vocal
    # ------------------------------------------------------------------

    def _capture_enrollment_frames(self, name: str, max_valid: int, timeout: float) -> list:
        """Capture des frames en s'arrêtant dès max_valid visages détectés ou timeout."""
        frames = []
        valid_count = 0
        announced_halfway = False
        t_start = time.monotonic()

        while valid_count < max_valid and (time.monotonic() - t_start) < timeout:
            frame = self.mini.media.get_frame()
            if frame is not None:
                frames.append(frame)
                try:
                    faces = self.recognizer._app.get(frame)
                    if faces:
                        valid_count += 1
                        if not announced_halfway and valid_count >= max_valid // 2:
                            announced_halfway = True
                            self.tts.say("Bien, continuez.", blocking=False)
                except Exception:
                    pass
            time.sleep(0.4)

        logger.info("Capture enrôlement : %d frames, %d visages valides.", len(frames), valid_count)
        return frames

    def _enroll_mode(self, name: str) -> None:
        """Capture des frames et enrôle une nouvelle personne, avec feedback vocal."""
        if self.enroller is None or self.recognizer is None:
            self.tts.say("Le module de reconnaissance faciale n'est pas disponible.", blocking=True)
            return

        MIN_VALID = 5
        MAX_VALID = 12
        TIMEOUT   = 12.0  # secondes max par tentative

        self.tts.say(f"Je vais mémoriser {name}. Regardez-moi bien, ne bougez pas.", blocking=True)
        time.sleep(0.5)

        frames = self._capture_enrollment_frames(name, MAX_VALID, TIMEOUT)
        result = self.enroller.enroll(name, frames, min_valid=MIN_VALID)

        if not result["success"] and result["n_valid"] < MIN_VALID:
            # Une tentative supplémentaire
            self.tts.say(
                f"Je n'ai pas bien vu votre visage. Approchez-vous et regardez-moi encore.",
                blocking=True,
            )
            time.sleep(0.5)
            frames2 = self._capture_enrollment_frames(name, MAX_VALID, TIMEOUT)
            result = self.enroller.enroll(name, frames + frames2, min_valid=MIN_VALID)

        if result["success"]:
            self.recognizer.reload_known_faces()
        self.tts.say(result["message"], blocking=True)
        bridge.enroll_complete(name, result["success"])

    # ------------------------------------------------------------------
    # Commandes vocales (polling fichier)
    # ------------------------------------------------------------------

    def _check_voice_commands(self) -> None:
        """Interroge le fichier de commandes vocales et les exécute."""
        if not os.path.exists(CMD_FILE):
            return
        try:
            with open(CMD_FILE, encoding="utf-8") as f:
                cmd = json.load(f)
            os.remove(CMD_FILE)  # consommer la commande

            command = cmd.get("cmd")

            if command == "enroll":
                name = cmd.get("name", "").strip()
                if name:
                    self._enroll_mode(name)
                else:
                    logger.warning("Commande enroll sans nom.")

            elif command == "list_persons":
                if self.enroller:
                    persons = self.enroller.list_known()
                    names = ", ".join(p["name"] for p in persons) if persons else "personne"
                    self.tts.say(f"Je connais : {names}")
                else:
                    self.tts.say("Le module de reconnaissance n'est pas actif.")

            elif command == "forget":
                name = cmd.get("name", "").strip()
                if name and self.enroller:
                    ok = self.enroller.remove(name)
                    self.tts.say(
                        f"J'ai oublié {name}" if ok else f"Je ne connais pas {name}"
                    )
                elif not name:
                    logger.warning("Commande forget sans nom.")
                else:
                    self.tts.say("Le module de reconnaissance n'est pas actif.")

            elif command == "wellbeing_response":
                status = cmd.get("status", "no_response")
                if status == "ok":
                    logger.info("Check-in : personne OK — reset alerte chute")
                    self._fall_checkin_active = False
                    if self.fall_det:
                        self.fall_det.reset()
                else:
                    logger.warning("Check-in : status=%r — escalade alerte chute", status)
                    self._escalate_fall_alert()

            elif command == "wake":
                self._on_wake_word()
                logger.info("Réveil manuel déclenché.")

            elif command == "switch_mode":
                mode = cmd.get("mode", "").strip()
                topic = cmd.get("topic", "").strip()
                if mode and self.mode_manager:
                    switched = self.mode_manager.switch_mode(mode, context=topic)
                    if not switched:
                        logger.debug("switch_mode ignoré (déjà actif ou throttle).")
                else:
                    logger.warning("Commande switch_mode sans mode ou mode_manager absent.")

            else:
                logger.warning("Commande vocale inconnue : %s", command)

        except Exception as exc:
            logger.warning("Erreur commande vocale: %s", exc)

    # ------------------------------------------------------------------
    # Wake word callback
    # ------------------------------------------------------------------

    def _on_wake_word(self) -> None:
        """Appelé par WakeWordDetector lors d'une détection."""
        logger.info("Wake word détecté — réactivation de la session.")
        bridge.wake()
        self._last_bridge_activity = time.monotonic()

    # ------------------------------------------------------------------
    # Keepalive bridge
    # ------------------------------------------------------------------

    def _check_conv_app_health(self) -> None:
        """Envoie un keepalive bridge si plus de 300 s sans activité.
        Reconnexion proactive à 55min avant l'expiration de la session OpenAI Realtime (60min).
        """
        t = time.monotonic()

        # Reconnexion proactive 5min avant l'expiration des 60min OpenAI Realtime
        if t - self._conv_app_start_time > 3300:  # 55 minutes
            logger.warning("Session OpenAI Realtime proche de l'expiration (55min) — reconnexion proactive")
            bridge._post("/reconnect", {})
            self._conv_app_start_time = t

        if t - self._last_bridge_activity > 300:
            if self._last_greeted:
                # Ré-injecte le contexte face au cas où la conv_app a redémarré
                mem = self.memory.on_seen(self._last_greeted) if self.memory else {}
                bridge.set_context(
                    person=self._last_greeted,
                    memory_summary=mem.get("conversation_summary"),
                    profile=mem.get("profile"),
                )
            else:
                bridge.keepalive()
            self._last_bridge_activity = t
        if t - self._last_memory_inject > 180:
            bridge.inject_memory()
            self._last_memory_inject = t

    # ------------------------------------------------------------------
    # Signal et arrêt propre
    # ------------------------------------------------------------------

    def _signal_handler(self, signum, frame) -> None:
        """Gestionnaire de signal SIGTERM / SIGINT."""
        logger.info("Signal %d reçu — arrêt demandé.", signum)
        self._stop = True

    def _summarize_session(self) -> None:
        """Génère et sauvegarde résumé + faits structurés pour chaque personne vue."""
        if not self._seen_persons or self.memory is None:
            return

        api_key = os.getenv("OPENAI_API_KEY") or self._read_openai_key_from_env_file()
        if not api_key:
            logger.warning("Résumé session ignoré : OPENAI_API_KEY introuvable.")
            return

        from datetime import date
        today = date.today().isoformat()
        events_text = "\n".join(self._session_events) if self._session_events else "Aucun événement notable."

        for name, mem in self._seen_persons.items():
            # --- Appel 1 : résumé narratif ---
            existing = mem.get("conversation_summary", "")
            prompt_summary = (
                f"Tu gères la mémoire d'un robot compagnon pour personnes âgées.\n"
                f"Personne : {name}\n"
                f"Résumé existant : {existing or 'Aucun'}\n"
                f"Événements de cette session :\n{events_text}\n\n"
                "Génère un résumé concis (3 phrases max) de cette session. "
                "Mentionne les activités faites, l'ambiance générale, rien de plus. "
                "Réponds uniquement avec le résumé, sans introduction."
            )
            summary = ""
            try:
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt_summary}],
                        "max_tokens": 150,
                        "temperature": 0.3,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                summary = resp.json()["choices"][0]["message"]["content"].strip()
                logger.info("Résumé session généré pour %s.", name)
            except Exception as exc:
                logger.warning("Résumé session échoué pour %s : %s", name, exc)
                summary = events_text[:200] if events_text else ""

            # Sauvegarde dans l'historique roulant
            self.memory.add_session(name, {
                "date": today,
                "summary": summary,
                "activities": [e for e in self._session_events if "echecs" in e.lower() or "histoire" in e.lower()],
            })

            # --- Appel 2 : extraction de faits structurés ---
            if events_text and events_text != "Aucun événement notable.":
                prompt_facts = (
                    f"Événements d'une session avec {name} :\n{events_text}\n\n"
                    "Extrait les faits importants sous forme de liste JSON. "
                    "Chaque fait est un objet avec les champs 'fact' (string) et 'category' "
                    "(une parmi : santé, famille, préférences, habitudes, activités). "
                    "Exemple : [{\"fact\": \"A mal au genou droit\", \"category\": \"santé\"}]. "
                    "Si aucun fait notable, réponds avec []. "
                    "Réponds UNIQUEMENT avec le JSON valide, sans explication."
                )
                try:
                    resp2 = requests.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": "gpt-4o-mini",
                            "messages": [{"role": "user", "content": prompt_facts}],
                            "max_tokens": 300,
                            "temperature": 0.1,
                        },
                        timeout=15,
                    )
                    resp2.raise_for_status()
                    import json as _json
                    raw = resp2.json()["choices"][0]["message"]["content"].strip()
                    facts = _json.loads(raw)
                    if isinstance(facts, list) and facts:
                        # Ajoute la date à chaque fait
                        for f in facts:
                            if isinstance(f, dict):
                                f.setdefault("date", today)
                                f.setdefault("source", "session")
                        self.memory.add_facts(name, facts)
                        logger.info("Faits extraits pour %s : %d faits.", name, len(facts))
                except Exception as exc:
                    logger.warning("Extraction faits échouée pour %s : %s", name, exc)

    def _read_openai_key_from_env_file(self) -> str | None:
        """Lit OPENAI_API_KEY depuis le .env de reachy_mini_conversation_app."""
        env_path = (
            "/venvs/apps_venv/lib/python3.12/site-packages"
            "/reachy_mini_conversation_app/.env"
        )
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except FileNotFoundError:
            logger.debug("_read_openai_key: fichier .env non trouvé : %s", env_path)
        except Exception as exc:
            logger.warning("_read_openai_key: erreur lecture .env : %s", exc)
        return None

    def shutdown(self) -> None:
        """Libère les ressources et nettoie le fichier PID."""
        logger.info("Arrêt de Reachy Care …")

        self._summarize_session()

        try:
            if self.sound_det is not None:
                self.sound_det.stop()
                logger.info("SoundDetector arrêté.")
        except Exception as exc:
            logger.debug("sound_det.stop(): %s", exc)

        try:
            if self.wake_word is not None:
                self.wake_word.stop()
                logger.info("WakeWordDetector arrêté.")
        except Exception as exc:
            logger.debug("wake_word.stop(): %s", exc)

        try:
            if self.chess_eng is not None:
                self.chess_eng.close()
                logger.info("ChessEngine fermé.")
        except Exception as exc:
            logger.debug("chess_eng.close(): %s", exc)

        try:
            if self.fall_det is not None:
                self.fall_det.close()
                logger.info("FallDetector fermé.")
        except Exception as exc:
            logger.debug("fall_det.close(): %s", exc)

        try:
            if config.PID_FILE.exists():
                config.PID_FILE.unlink()
                logger.info("PID_FILE supprimé : %s", config.PID_FILE)
        except Exception as exc:
            logger.debug("Suppression PID_FILE: %s", exc)

        logger.info("Reachy Care arrêté proprement")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reachy Care — orchestrateur principal")
    parser.add_argument("--debug", action="store_true", help="Active le mode DEBUG")
    parser.add_argument("--no-chess", action="store_true", help="Désactive le module chess")
    parser.add_argument("--no-face", action="store_true", help="Désactive la reconnaissance faciale")
    args = parser.parse_args()

    setup_logging(debug=args.debug)

    app = ReachyCare(
        enable_chess=not args.no_chess,
        enable_face=not args.no_face,
    )
    app.run()
