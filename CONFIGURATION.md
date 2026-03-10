# Reachy Care — Guide de configuration

## Prérequis matériel

- Reachy Mini Wireless (firmware ≥ 1.5.1)
- Raspberry Pi 4 intégré, accessible en SSH : `pollen@192.168.1.244` (mdp : `root`)
- Python 3.12 dans `/venvs/apps_venv`
- Stockfish installé : `/usr/games/stockfish`
- Caméra intégrée au robot (GStreamer)

---

## 1. Déploiement des fichiers

Depuis le Mac, synchroniser le dossier entier vers le Pi :

```bash
rsync -av --exclude='__pycache__' --exclude='*.pyc' \
  /Users/alexandre/Galaad-Motokiyo-Ferran/reachy_care/ \
  pollen@192.168.1.244:/home/pollen/reachy_care/
```

---

## 2. Dépendances Python

Sur le Pi, dans le venv des apps :

```bash
ssh pollen@192.168.1.244
source /venvs/apps_venv/bin/activate

# Dépendances Reachy Care
pip install insightface onnxruntime mediapipe chess stockfish \
            "openwakeword>=0.6.0" pyaudio requests

# Dépendance déjà présente normalement
pip install reachy-mini
```

---

## 3. Modèles à télécharger

### InsightFace buffalo_s (reconnaissance faciale)
```bash
# Télécharger automatiquement au premier lancement, ou manuellement :
python3 -c "import insightface; insightface.app.FaceAnalysis('buffalo_s').prepare(ctx_id=0)"
```

### Modèle YOLO chess (détection échiquier)
Télécharger `best_mobile.onnx` depuis HuggingFace (yamero999/chess-piece-detection-yolo11n) :
```bash
wget -O /home/pollen/reachy_care/models/chess_yolo11n.pt \
  "https://huggingface.co/yamero999/chess-piece-detection-yolo11n/resolve/main/best_mobile.onnx"
```

### Wake word (optionnel — fallback automatique sur `hey_jarvis`)
Placer le modèle custom `hey_reachy.onnx` dans :
```
/home/pollen/reachy_care/models/hey_reachy.onnx
```
Si absent, Reachy utilisera automatiquement `hey_jarvis` comme wake word.

---

## 4. Clés API et variables d'environnement

Les clés sont dans le `.env` de `reachy_mini_conversation_app` :
```
/home/pollen/reachy_mini_conversation_app/.env
```

Contenu attendu :
```env
OPENAI_API_KEY=sk-...
BRAVE_API_KEY=REDACTED_BRAVE_KEY
REACHY_MINI_CUSTOM_PROFILE=reachy_care
REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY=/home/pollen/reachy_care/external_profiles
```

---

## 5. Patch de la conv_app (une seule fois)

Cette étape injecte le bridge Reachy Care dans la conv_app.
**À relancer si la conv_app est mise à jour.**

```bash
ssh pollen@192.168.1.244
source /venvs/apps_venv/bin/activate

# Si déjà patché, restaurer le backup avant de relancer
# cp /home/pollen/.../openai_realtime.py.bak /home/pollen/.../openai_realtime.py

python3 /home/pollen/reachy_care/patch_source.py
```

Vérifier la sortie : tous les `✅ Patch appliqué` doivent apparaître.

---

## 6. Lancer le système

```bash
ssh pollen@192.168.1.244
bash /home/pollen/reachy_care/start_all.sh
```

`start_all.sh` :
1. Charge le `.env`
2. Lance `reachy-mini-conversation-app` en arrière-plan
3. Attend 4 secondes (initialisation)
4. Lance `main.py` au premier plan (logs visibles)
5. À l'arrêt (Ctrl+C), stoppe automatiquement la conv_app

---

## 7. Enrôler une personne (reconnaissance faciale)

Écrire dans `/tmp/reachy_care_cmd.json` :

```json
{"cmd": "enroll", "name": "Marie"}
```

Le robot capturera 10 photos et mémorisera le visage.

Commandes disponibles via le fichier CMD :
```json
{"cmd": "enroll",      "name": "Prénom"}
{"cmd": "forget",      "name": "Prénom"}
{"cmd": "list_persons"}
{"cmd": "switch_mode", "mode": "histoire"}
{"cmd": "switch_mode", "mode": "pro", "topic": "les étoiles"}
{"cmd": "switch_mode", "mode": "normal"}
```

---

## 8. Structure des dossiers

```
/home/pollen/reachy_care/
├── main.py                          # Orchestrateur principal
├── config.py                        # Toute la configuration
├── conv_app_bridge.py               # Bridge thread-safe vers la conv_app
├── patch_source.py                  # Script de patch (une seule fois)
├── start_all.sh                     # Script de lancement
├── modules/
│   ├── face_recognizer.py           # Reconnaissance faciale InsightFace
│   ├── register_face.py             # Enrôlement de nouveaux visages
│   ├── chess_detector.py            # Détection échiquier YOLO
│   ├── chess_engine.py              # Moteur d'échecs Stockfish
│   ├── fall_detector.py             # Détection de chute MediaPipe
│   ├── memory_manager.py            # Mémoire persistante par personne (JSON)
│   ├── mode_manager.py              # Gestionnaire de modes
│   ├── tts.py                       # Synthèse vocale (espeak)
│   └── wake_word.py                 # Détection wake word (openWakeWord)
├── tools_for_conv_app/
│   ├── search.py                    # Outil Brave Search
│   ├── switch_mode.py               # Outil changement de mode
│   └── gutenberg.py                 # Outil lecture Project Gutenberg
├── external_profiles/reachy_care/
│   ├── instructions.txt             # Prompt MODE_NORMAL
│   ├── instructions_histoire.txt    # Prompt MODE_HISTOIRE
│   ├── instructions_pro.txt         # Prompt MODE_PRO
│   ├── instructions_echecs.txt      # Prompt MODE_ECHECS
│   ├── tools.txt                    # Liste des outils activés
│   └── voice.txt                    # Voix OpenAI (cedar)
├── models/
│   ├── chess_yolo11n.pt             # Modèle YOLO détection pièces
│   └── hey_reachy.onnx              # Wake word custom (optionnel)
├── known_faces/                     # Visages enrôlés + mémoire JSON
└── logs/
    └── reachy_care.log              # Logs rotatifs (10 MB × 3)
```

---

## 9. Modes de comportement

| Mode | Déclenchement | Comportement |
|------|---------------|--------------|
| `normal` | Défaut au démarrage | Conversation libre, bienveillante |
| `histoire` | Vocal : "mode histoire" / "raconte-moi" | Lit des textes Project Gutenberg |
| `pro` | Vocal : "mode pro" / "parle-moi de X" | Exposé structuré avec recherche Brave |
| `echecs` | Auto : échiquier détecté 3 frames | Coaching d'échecs, conserve l'état de la partie |

---

## 10. Variables de configuration (config.py)

| Variable | Valeur | Description |
|----------|--------|-------------|
| `FACE_COSINE_THRESHOLD` | 0.40 | Seuil similarité faciale (↑ = plus strict) |
| `FACE_INTERVAL_SEC` | 2.0 | Fréquence reconnaissance faciale |
| `CHESS_DETECTION_FRAMES_TRIGGER` | 3 | Frames avant activation mode échecs |
| `CHESS_ABSENT_FRAMES_EXIT` | 10 | Frames avant désactivation mode échecs |
| `WAKE_WORD_THRESHOLD` | 0.5 | Sensibilité wake word (↑ = moins sensible) |
| `FALL_RATIO_THRESHOLD` | 0.15 | Seuil détection chute |
| `FALL_SUSTAINED_SEC` | 3.0 | Durée minimale pour confirmer une chute |
| `HEAD_IDLE_PITCH_DEG` | -10 | Angle tête au repos (°) |

---

## 11. Ajouter des images à la conversation (approche future)

L'API OpenAI Realtime supporte l'envoi d'images via `input_image`. Pour que Reachy "voie" la caméra en temps réel :

**Ce qui existe déjà :** l'outil `camera` dans la conv_app permet à l'IA de demander une capture quand l'utilisateur dit "regarde" ou "qu'est-ce que tu vois".

**Pour aller plus loin (proactif) :** ajouter dans `conv_app_bridge.py` une méthode `send_image(frame)` qui :
1. Encode le frame NumPy en JPEG base64
2. L'injecte via `connection.conversation.item.create` avec `content_type: "input_image"`

```python
# Exemple d'injection dans patch openai_realtime.py
await self.connection.conversation.item.create(item={
    "type": "message",
    "role": "user",
    "content": [
        {"type": "input_image", "image": base64_jpeg},
        {"type": "input_text", "text": "[Reachy Care] Voici ce que je vois."}
    ]
})
```

Cas d'usage concrets :
- Envoyer une image quand une personne inconnue est détectée → l'IA voit le visage
- Envoyer une photo de l'échiquier au début d'une partie → l'IA confirme la position initiale
- Déclencher manuellement via commande vocale "analyse ce que tu vois"
