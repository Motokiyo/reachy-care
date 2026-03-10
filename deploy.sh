#!/bin/bash
# deploy.sh — synchronise le code Mac vers la Pi
PI_HOST="pollen@reachy-mini.local"
PI_PATH="/home/pollen/reachy_care/"
LOCAL_PATH="$(dirname "$0")/"

rsync -avz --progress \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='models/' \
    --exclude='known_faces/' \
    --exclude='logs/' \
    --exclude='*.npy' \
    --exclude='RESULTATS_TESTS.md' \
    --exclude='QUESTIONS-COWORK.md' \
    --exclude='INSTRUCTIONS_CLAUDE_CODE.md' \
    --exclude='phase1_chess_vision/' \
    --exclude='resources/' \
    --exclude='docs/' \
    "$LOCAL_PATH" "$PI_HOST:$PI_PATH"

echo "✅ Deploy OK"
