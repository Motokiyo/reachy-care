# Reachy Care — État d'avancement

## Vue d'ensemble du projet

Reachy Care est un système de compagnon robotique pour personnes âgées basé sur le robot Reachy Mini Wireless de Pollen Robotics. Il augmente la conv_app officielle (reachy_mini_conversation_app) avec des capacités de perception et de mémoire.

## Architecture globale

Deux processus coexistent :
- **reachy_mini_conversation_app** (conv_app) : gère la conversation voix via OpenAI Realtime API
- **main.py (Reachy Care)** : orchestre les modules de perception, communique via un bridge thread-safe

Communication : `ConvAppBridge` (singleton) → `asyncio.run_coroutine_threadsafe()` → `schedule_external_event()` injecté dans la conv_app via `patch_source.py`

## Modules implémentés

### ✅ Module 1A — Reconnaissance faciale
- Fichier : `modules/face_recognizer.py`
- Technologie : InsightFace buffalo_s, cosine similarity
- Fonctionnement : identifie les personnes enrôlées toutes les 2s, déclenche une salutation personnalisée via le bridge

### ✅ Module 1B — Détection échiquier
- Fichiers : `modules/chess_detector.py`, `modules/chess_engine.py`
- Technologie : YOLO11n ONNX (best_mobile.onnx), Stockfish
- Fonctionnement : détecte l'échiquier via la caméra, calcule le meilleur coup, l'annonce via le bridge
- Auto-switch : active MODE_ECHECS après 3 détections consécutives, retour MODE_NORMAL après 10 frames sans échiquier

### ✅ Module 1D — Détection de chute
- Fichier : `modules/fall_detector.py`
- Technologie : MediaPipe Pose (complexity 0)
- Fonctionnement : surveille le ratio hauteur/largeur du squelette, alerte si chute soutenue pendant 3s

### ✅ Module — Mémoire persistante
- Fichier : `modules/memory_manager.py`
- Format : JSON par personne dans `known_faces/`
- Fonctionnement : enregistre `last_seen`, `sessions_count`, `conversation_summary`
- Résumé de session : GPT-4o-mini génère un résumé des interactions à chaque arrêt propre

### ✅ Module — TTS
- Fichier : `modules/tts.py`
- Backend : espeak (fr, 140 wpm)
- Utilisé pour : salutations initiales, confirmations d'enrôlement, alertes chute

### ✅ Module — Wake Word
- Fichier : `modules/wake_word.py`
- Technologie : openWakeWord (ONNX), PyAudio 16kHz
- Fonctionnement : détecte "Hey Reachy" (ou fallback `hey_jarvis` si modèle absent), appelle `bridge.keepalive()` pour réactiver la session
- Cooldown : 3s entre deux détections

### ✅ Module — Enrôlement facial
- Fichier : `modules/register_face.py`
- Fonctionnement : capture 10 photos, extrait les embeddings, sauvegarde dans `known_faces/`

### ✅ Module — Gestionnaire de modes
- Fichier : `modules/mode_manager.py`
- Modes : MODE_NORMAL, MODE_HISTOIRE, MODE_PRO, MODE_ECHECS
- Fonctionnement : charge les instructions du mode, appelle `connection.session.update()` via bridge pour changer les instructions de session OpenAI Realtime, thread-safe avec throttle 5s

## Bridge et communication

### ✅ conv_app_bridge.py

Méthodes exposées :

| Méthode | Description |
|---|---|
| `register_handler(handler)` | Appelé par main.py de la conv_app au démarrage |
| `set_context(person, mood, memory_summary)` | Salutation personnalisée |
| `trigger_alert(type, details)` | Alerte chute/urgence |
| `announce_chess_move(move, commentary)` | Annonce d'un coup |
| `enroll_complete(name, success)` | Confirmation d'enrôlement |
| `keepalive()` | Maintient la session active (appelé par wake word ou timer 300s) |
| `update_session_instructions(instructions)` | Change les instructions de session (modes) |
| `announce_mode_switch(text)` | Injecte le message d'annonce de changement de mode |

### ✅ patch_source.py

Injecte dans `openai_realtime.py` de la conv_app :
- `_external_events: asyncio.Queue` + `_asyncio_loop`
- Tâche asyncio `_process_external_events()`
- Méthode `schedule_external_event(text, instructions)`
- Méthode `schedule_session_update(instructions)` (changement de mode)
- Idle adapté personnes âgées : message calme, timeout 60s (au lieu de 15s)

### ✅ Outils pour la conv_app
- `tools_for_conv_app/search.py` : Brave Search (clé API configurée)
- `tools_for_conv_app/switch_mode.py` : changement de mode (écrit dans `/tmp/reachy_care_cmd.json`)
- `tools_for_conv_app/gutenberg.py` : récupération textes Project Gutenberg (via Gutendex, sans clé)

## Profil reachy_care (conv_app)

| Fichier | Rôle |
|---|---|
| `external_profiles/reachy_care/instructions.txt` | MODE_NORMAL |
| `external_profiles/reachy_care/instructions_histoire.txt` | MODE_HISTOIRE (lecture Gutenberg) |
| `external_profiles/reachy_care/instructions_pro.txt` | MODE_PRO (exposé structuré) |
| `external_profiles/reachy_care/instructions_echecs.txt` | MODE_ECHECS (coaching, conserve la partie en cours) |
| `external_profiles/reachy_care/tools.txt` | dance, stop_dance, play_emotion, stop_emotion, camera, do_nothing, head_tracking, move_head, search, switch_mode, gutenberg |
| `external_profiles/reachy_care/voice.txt` | cedar |

## Infrastructure

- `start_all.sh` : lance conv_app + main.py, charge le .env, cleanup automatique
- `config.py` : toutes les constantes centralisées
- `logs/reachy_care.log` : logs rotatifs (10 MB × 3)
- `/tmp/reachy_care_cmd.json` : canal de commandes (enroll, forget, list_persons, switch_mode)

## Ce qui reste à faire

### Priorité 1 — Déploiement et tests

- 🔲 Déployer tous les fichiers sur le Pi (rsync depuis le Mac)
- 🔲 Installer les dépendances : `pip install "openwakeword>=0.6.0" pyaudio`
- 🔲 Réappliquer `patch_source.py` (restaurer les .bak d'abord si déjà patché)
- 🔲 Tester la reconnaissance faciale avec buffalo_s téléchargé
- 🔲 Tester le mode échecs avec le modèle YOLO
- 🔲 Tester le wake word (fallback hey_jarvis)
- 🔲 Tester les modes histoire/pro/echecs en conditions réelles

### Priorité 2 — Wake word custom

- 🔲 Entraîner un modèle ONNX "Hey Reachy" via Google Colab (openWakeWord training notebook)
- 🔲 Placer le modèle dans `models/hey_reachy.onnx`

### Priorité 3 — Images proactives (vision enrichie)

- 🔲 Ajouter `send_image(frame)` dans `conv_app_bridge.py`
- 🔲 Injecter via `input_image` content type dans l'API OpenAI Realtime
- 🔲 Cas d'usage : personne inconnue → l'IA voit le visage, début de partie → l'IA voit l'échiquier

### Priorité 4 — Améliorations futures

- 🔲 Réappliquer les instructions de session au reconnect (actuellement, si la session se coupe, les instructions reviennent au mode normal)
- 🔲 Entraîner un meilleur modèle de détection d'échiquier (actuel : générique)
- 🔲 Interface web légère pour gérer les personnes enrôlées
- 🔲 Alertes SMS/email pour les proches en cas de chute non résolue

## Notes techniques importantes

### Compatibilité

- Reachy Mini Wireless 1.5.1 : compatible, pas de breaking changes
- Python 3.12 dans `/venvs/apps_venv` (le système est Python 3.13.5 — ne pas mélanger)
- InsightFace : buffalo_s téléchargé et fonctionnel (~122 MB dans `~/.insightface/`)

### Idempotence du patch

`patch_source.py` est idempotent via le marqueur `"reachy-care-events"`.
Si le fichier est déjà patché, il affiche "Déjà patché" et n'applique rien.
Pour repatchez : `cp openai_realtime.py.bak openai_realtime.py` puis relancer le script.

### Throttle des modes

`ModeManager` impose un délai de 5 secondes entre deux changements de mode (anti-spam).

### Mémoire d'échecs

Quand MODE_ECHECS est activé, le FEN de la partie en cours est passé dans le message d'annonce. L'IA connaît donc l'état de la partie même si elle a répondu à une question entre-temps. Le tableau Python (`_chess_board`) est conservé en mémoire tout au long de la session.
