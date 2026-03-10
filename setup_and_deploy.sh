#!/bin/bash
# setup_and_deploy.sh — À lancer depuis ton Mac dans ton terminal
# Lance : bash /Users/alexandre/Galaad-Motokiyo-Ferran/reachy_care/setup_and_deploy.sh

set -e
PI="pollen@192.168.1.244"
PASS="root"
LOCAL="/Users/alexandre/Galaad-Motokiyo-Ferran/reachy_care/"
REMOTE="/home/pollen/reachy_care/"

SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no"
SCP="sshpass -p $PASS rsync -avz --progress"

echo "======================================"
echo " REACHY CARE — Setup & Deploy"
echo "======================================"

# ── 1. DEPLOY CODE ─────────────────────────────────────────────
echo ""
echo "▶ 1/6 — Deploy du code sur la Pi..."
$SCP \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='models/' \
    --exclude='known_faces/*.npy' \
    --exclude='logs/' \
    --exclude='RESULTATS_TESTS.md' \
    --exclude='QUESTIONS-COWORK.md' \
    --exclude='INSTRUCTIONS_CLAUDE_CODE.md' \
    --exclude='phase1_chess_vision/' \
    --exclude='resources/' \
    --exclude='docs/' \
    "$LOCAL" "$PI:$REMOTE"
echo "✅ Code déployé"

# ── 2. INSTALL DÉPENDANCES ─────────────────────────────────────
echo ""
echo "▶ 2/6 — Installation dépendances Pi..."
$SSH $PI "bash -s" << 'REMOTE_INSTALL'
set -e
echo "→ apt : stockfish + espeak-ng..."
sudo apt-get install -y stockfish espeak-ng --quiet 2>&1 | tail -3

echo "→ pip : chess + mediapipe + huggingface_hub..."
source /venvs/apps_venv/bin/activate
pip install chess==1.11.2 mediapipe==0.10.14 huggingface_hub --quiet 2>&1 | tail -5

echo "→ Vérification dépendances..."
python3 -c "
import chess, mediapipe, insightface, onnxruntime, cv2
print(f'  chess={chess.__version__}')
print(f'  mediapipe={mediapipe.__version__}')
print(f'  insightface={insightface.__version__}')
print(f'  onnxruntime={onnxruntime.__version__}')
print(f'  opencv={cv2.__version__}')
"
REMOTE_INSTALL
echo "✅ Dépendances OK"

# ── 3. STRUCTURE DOSSIERS ──────────────────────────────────────
echo ""
echo "▶ 3/6 — Création structure dossiers..."
$SSH $PI "mkdir -p /home/pollen/reachy_care/{models,known_faces,logs,external_profiles}"
echo "✅ Dossiers OK"

# ── 4. PATCH CONV_APP ──────────────────────────────────────────
echo ""
echo "▶ 4/6 — Patch reachy_mini_conversation_app..."
$SSH $PI "bash -s" << 'REMOTE_PATCH'
source /venvs/apps_venv/bin/activate
if [ -f /home/pollen/reachy_care/conv_app_patch.py ]; then
    python3 /home/pollen/reachy_care/conv_app_patch.py
else
    echo "⚠ conv_app_patch.py absent — skip patch"
fi
REMOTE_PATCH
echo "✅ Patch conv_app OK"

# ── 5. CONFIG .ENV ─────────────────────────────────────────────
echo ""
echo "▶ 5/6 — Configuration profil Reachy Care..."
$SSH $PI "bash -s" << 'REMOTE_ENV'
CONV_APP_DIR=$(find /home/pollen -name "app.py" -path "*/conversation*" 2>/dev/null | head -1 | xargs dirname 2>/dev/null || echo "")
if [ -n "$CONV_APP_DIR" ] && [ ! -f "$CONV_APP_DIR/.env" ]; then
    echo "→ Création .env dans $CONV_APP_DIR"
    cat > "$CONV_APP_DIR/.env" << EOF
REACHY_MINI_CUSTOM_PROFILE=reachy_care
REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=/home/pollen/reachy_care/external_profiles
# OPENAI_API_KEY=sk-VOTRE_CLE_ICI
EOF
    echo "⚠ Pense à remplir OPENAI_API_KEY dans $CONV_APP_DIR/.env"
else
    echo "→ .env déjà présent ou conv_app non trouvée"
fi
REMOTE_ENV

# ── 6. TESTS ───────────────────────────────────────────────────
echo ""
echo "▶ 6/6 — Tests de validation..."
$SSH $PI "bash -s" << 'REMOTE_TEST'
source /venvs/apps_venv/bin/activate
cd /home/pollen/reachy_care

echo "→ Test imports modules..."
python3 -c "
import sys
sys.path.insert(0, '/home/pollen/reachy_care')
from modules.face_recognizer import FaceRecognizer
from modules.register_face import FaceEnroller
from modules.chess_engine import ChessEngine
from modules.fall_detector import FallDetector
from modules.tts import TTSEngine
from conv_app_bridge import bridge
import config
print('✅ Tous les imports OK')
print(f'   KNOWN_FACES_DIR = {config.KNOWN_FACES_DIR}')
print(f'   CHESS_STOCKFISH_PATHS = {config.CHESS_STOCKFISH_PATHS}')
"

echo "→ Test stockfish..."
python3 -c "
from pathlib import Path
paths = ['/usr/games/stockfish', '/usr/local/bin/stockfish', '/usr/bin/stockfish']
found = next((p for p in paths if Path(p).exists()), None)
if found: print(f'✅ Stockfish : {found}')
else: print('❌ Stockfish introuvable')
"

echo "→ Test daemon HTTP..."
curl -s --max-time 3 http://localhost:8000/api/state/full > /dev/null && echo "✅ Daemon HTTP OK" || echo "⚠ Daemon non démarré (normal si robot en veille)"

echo "→ Test TTS..."
python3 -c "
from modules.tts import TTSEngine
tts = TTSEngine()
print(f'✅ TTS backend: {tts._backend}')
"

echo ""
echo "======================================"
echo " RÉSUMÉ"
echo "======================================"
df -h / | tail -1 | awk '{print "Disque : " $3 " utilisé / " $2 " total (" $5 ")"}'
free -h | grep Mem | awk '{print "RAM    : " $3 " utilisée / " $2 " total"}'
ls /home/pollen/reachy_care/modules/*.py | wc -l | xargs -I{} echo "Modules : {} fichiers Python"
REMOTE_TEST

echo ""
echo "======================================"
echo "✅ SETUP TERMINÉ"
echo ""
echo "Pour lancer Reachy Care :"
echo "  ssh pollen@192.168.1.244"
echo "  bash /home/pollen/reachy_care/start.sh"
echo "======================================"
