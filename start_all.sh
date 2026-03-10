#!/bin/bash
# start_all.sh — Lance conv_app + Reachy Care ensemble en une seule commande
set -e

VENV="/venvs/apps_venv/bin/python"
CARE_DIR="/home/pollen/reachy_care"
LOG_DIR="$CARE_DIR/logs"
CONV_PID_FILE="/tmp/conv_app.pid"

export GST_PLUGIN_PATH=/opt/gst-plugins-rs/lib/aarch64-linux-gnu/gstreamer-1.0
export REACHY_CARE_PATH="$CARE_DIR"
# Outils conv_app sur le PYTHONPATH pour qu'ils soient importables par le conv_app
export PYTHONPATH="${CARE_DIR}/tools_for_conv_app:${PYTHONPATH}"

# Charger les variables depuis le .env de la conv_app
ENV_FILE="/home/pollen/reachy_mini_conversation_app/src/reachy_mini_conversation_app/.env"
if [ -f "$ENV_FILE" ]; then
    set -o allexport
    source "$ENV_FILE"
    set +o allexport
fi

# Profil Reachy Care (priorité sur le .env)
export REACHY_MINI_CUSTOM_PROFILE=reachy_care
export REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY="$CARE_DIR/external_profiles"
export REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY="$CARE_DIR/tools_for_conv_app"
export AUTOLOAD_EXTERNAL_TOOLS=true

mkdir -p "$LOG_DIR"

# ── Volume système au maximum ──────────────────────────────────────────────
amixer -D pulse sset Master 100% unmute 2>/dev/null || amixer sset Master 100% unmute 2>/dev/null || true
pactl set-sink-volume @DEFAULT_SINK@ 100% 2>/dev/null || true
pactl set-sink-mute @DEFAULT_SINK@ false 2>/dev/null || true
echo "[start_all] Volume système configuré au maximum"

# ── 1. Cleanup au Ctrl+C (enregistré tôt pour couvrir toutes les étapes) ──
cleanup() {
    echo ""
    echo "[start_all] Arrêt..."
    if [ -f "$CONV_PID_FILE" ]; then
        kill "$(cat "$CONV_PID_FILE")" 2>/dev/null || true
        rm -f "$CONV_PID_FILE"
    fi
    echo "[start_all] Terminé."
}
trap cleanup EXIT INT TERM

# ── 2. Daemon ──────────────────────────────────────────────────────────────
# Le || true empêche set -e d'interrompre le script si curl échoue
DAEMON_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8000/api/state/full || true)
if [ "$DAEMON_STATUS" != "200" ]; then
    echo "[start_all] Daemon absent — redémarrage..."
    sudo systemctl restart reachy-mini-daemon.service && sleep 8
    curl -s -X POST 'http://localhost:8000/api/daemon/start?wake_up=false' || true
    sleep 5
fi
echo "[start_all] Daemon OK"

# ── 3. Vérifier qu'aucune instance de conv_app ne tourne ──────────────────
if [ -f "$CONV_PID_FILE" ] && kill -0 "$(cat "$CONV_PID_FILE")" 2>/dev/null; then
    echo "[start_all] conv_app déjà en cours (PID=$(cat "$CONV_PID_FILE")). Arrêtez-la d'abord."
    exit 1
fi

# ── 4. Lancer conv_app en arrière-plan ────────────────────────────────────
echo "[start_all] Lancement conv_app..."
/venvs/apps_venv/bin/reachy-mini-conversation-app >> "$LOG_DIR/conv_app.log" 2>&1 &
echo $! > "$CONV_PID_FILE"
echo "[start_all] conv_app PID=$(cat "$CONV_PID_FILE") — log: $LOG_DIR/conv_app.log"
sleep 4

# ── 5. Lancer Reachy Care au premier plan ─────────────────────────────────
echo "[start_all] Lancement Reachy Care..."
"$VENV" "$CARE_DIR/main.py" "$@" 2>&1 | tee -a "$LOG_DIR/reachy_care.log"
