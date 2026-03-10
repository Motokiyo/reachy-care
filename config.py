from pathlib import Path

# Chemins
BASE_DIR          = Path("/home/pollen/reachy_care")
MODELS_DIR        = BASE_DIR / "models"
KNOWN_FACES_DIR   = BASE_DIR / "known_faces"
LOGS_DIR          = BASE_DIR / "logs"
LOG_FILE          = LOGS_DIR / "reachy_care.log"
PID_FILE          = Path("/tmp/reachy_care.pid")

# Module 1A — Face Recognition
FACE_MODEL_NAME         = "buffalo_s"
FACE_DET_SIZE           = (320, 320)
FACE_COSINE_THRESHOLD   = 0.40
FACE_DET_SCORE_MIN      = 0.70
FACE_INTERVAL_SEC       = 2.0
FACE_MAX_PERSONS        = 5       # max personnes enrôlées
FACE_ENROLL_PHOTOS      = 10      # photos par enrôlement
FACE_MISS_RESET_COUNT   = 8       # misses consécutives avant de réinitialiser _last_greeted (8×2s=16s)

# Module 1B — Chess
CHESS_MODEL_PATH        = str(MODELS_DIR / "chess_yolo11n.pt")
CHESS_CONF_THRESHOLD    = 0.65
CHESS_IMGSZ             = 416
CHESS_STOCKFISH_PATHS   = ["/usr/games/stockfish", "/usr/local/bin/stockfish", "/usr/bin/stockfish"]
CHESS_THINK_TIME        = 2.0
CHESS_INTERVAL_SEC      = 3.0

# Module 1D — Fall Detection
FALL_MODEL_COMPLEXITY   = 0
FALL_DETECTION_CONF     = 0.50
FALL_RATIO_THRESHOLD    = 0.15
FALL_SUSTAINED_SEC      = 3.0
FALL_INTERVAL_SEC       = 0.5
FALL_GHOST_TRIGGER_SEC  = 5.0   # Algo B : secondes sans squelette avant alerte (5.0 = moins de faux positifs sur sorties de pièce)
FALL_GHOST_RESET_SEC    = 45.0  # Algo B : secondes sans squelette → personne sortie (reset)

# Module 1E — Sound Detection (YAMNet TFLite)
SOUND_DETECTION_ENABLED  = True
SOUND_MODEL_PATH         = MODELS_DIR / "yamnet.tflite"
SOUND_IMPACT_THRESHOLD   = 0.45    # score min pour déclencher suspicion de chute

# Boucle principale
FRAME_INTERVAL_SEC      = 0.1     # 10 Hz

# TTS
TTS_VOICE               = "fr"
TTS_SPEED               = 140
TTS_AMPLITUDE           = 200     # Volume espeak-ng : 0-200 (défaut système : 100)
TTS_BACKEND             = "espeak"

# Reachy SDK
REACHY_DAEMON_URL       = "http://localhost:8000"
REACHY_DAEMON_TIMEOUT   = 5

# Localisation
LOCATION                = "Paris, France"   # ville pour les recherches météo
TIMEZONE                = "Europe/Paris"    # fuseau horaire (IANA, ex: "America/New_York", "Asia/Tokyo")

# Alertes Telegram (recommandé — plus simple que l'email)
TELEGRAM_BOT_TOKEN      = "REDACTED_TELEGRAM_TOKEN"
TELEGRAM_CHAT_ID        = "REDACTED_CHAT_ID"
TELEGRAM_ENABLED        = True

# Alertes email (alternatif)
ALERT_EMAIL_TO          = ""             # adresse de destination des alertes email
ALERT_EMAIL_FROM        = ""         # ex: "reachy.alerts@gmail.com"
ALERT_EMAIL_PASSWORD    = ""         # mot de passe d'application Gmail
ALERT_EMAIL_ENABLED     = False      # passer à True une fois les identifiants configurés

# Comportements
HEAD_IDLE_PITCH_DEG     = -10
HEAD_CHESS_PITCH_DEG    = 30   # tête baissée vers la table pour voir l'échiquier
ANTENNA_HAPPY           = [0.5, 0.5]
ANTENNA_ALERT           = [-1.0, -1.0]

# Modes
CHESS_AUTO_DETECT              = True  # re-activer auto-détection
CHESS_DETECTION_FRAMES_TRIGGER = 10   # (si CHESS_AUTO_DETECT) frames consécutives → MODE_ECHECS
CHESS_ABSENT_FRAMES_EXIT       = 60   # frames consécutives sans échiquier → MODE_NORMAL (~2 min)
CHESS_STABILITY_FRAMES         = 3     # frames identiques pour valider un coup
CHESS_NOISE_TOLERANCE          = 3     # changements illégaux consécutifs → resync board
CHESS_SKILL_LEVEL_INIT         = 3     # niveau Stockfish initial (0=débutant, 20=expert)

# Wake Word
WAKE_WORD_ENABLED       = True
WAKE_WORD_MODEL_PATH    = MODELS_DIR / "hey_Reatchy.onnx"  # modèle custom entraîné
WAKE_WORD_TFLITE_PATH   = MODELS_DIR / "hey_Reatchy.tflite"  # fallback tflite
WAKE_WORD_FALLBACK      = "hey_jarvis"  # fallback built-in si les deux absents
WAKE_WORD_THRESHOLD     = 0.5
WAKE_WORD_DEVICE_INDEX  = None   # None = device par défaut (PulseAudio)

# Overrides locaux (gitignored) — pour les credentials sur le Pi
# Créer /home/pollen/reachy_care/config_local.py avec les valeurs à surcharger
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
