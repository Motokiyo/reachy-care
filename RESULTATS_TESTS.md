# Résultats des tests — Reachy Mini

---

## Test caméra SDK — 09/03/2026

- Connexion SSH : ✅ `pollen@192.168.1.244` (mdp: root)
- Démarrage backend daemon : ✅ `POST /api/daemon/start?wake_up=false`
- Frame reçue : shape=`(720, 1280, 3)` dtype=`uint8` ✅
- Image sauvegardée : ✅ `/home/pollen/test_camera.jpg`
- Observations :
  - Image noire car la tête du robot est enfoncée dans son support (caméra obstruée)
  - Le pipeline SDK fonctionne parfaitement une fois le backend démarré
  - Résolution native : **1280×720** (pas 640×480 comme estimé dans la doc)
  - Backend en mode `control_mode: disabled` au démarrage (moteurs non activés)
  - Warning audio : `No Reachy Mini Audio Source/Sink card found` (non bloquant pour la caméra)

---

## Notes importantes pour la suite

### Démarrer le backend avant d'utiliser le SDK
Le daemon tourne en `--no-autostart`. Il faut d'abord démarrer le backend via :
```bash
curl -X POST 'http://localhost:8000/api/daemon/start?wake_up=false'
```
Ou avec `wake_up=true` pour que la tête se lève automatiquement.

### Venv à utiliser
```bash
/venvs/apps_venv/bin/python  # ← celui qui a reachy_mini installé
```
(Pas `python3` système qui n'a pas le module)

### État de la tête (position de repos)
```json
{
  "pitch": 0.416,   # ≈ 24° vers le bas (tête penchée dans le support)
  "yaw": -0.371,    # ≈ -21° (légère rotation droite)
  "roll": -0.066
}
```

### Pour faire sortir la tête du support et tourner à droite
```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
import numpy as np

with ReachyMini() as mini:
    mini.wake_up()  # Sort la tête du support
    import time; time.sleep(1.5)
    head_pose = create_head_pose(yaw=np.deg2rad(-70), degrees=False)
    mini.goto_target(head=head_pose, duration=2.0)
```
⚠️ À tester une fois le robot sorti physiquement du support ou avec `wake_up=true` au démarrage.

---

---

## Séquence de démarrage complète — validée 09/03/2026

### Séquence obligatoire pour avoir la caméra ET les moteurs actifs

```bash
# 1. Configurer le path GStreamer (plugins webrtc manquants par défaut)
sudo systemctl set-environment GST_PLUGIN_PATH=/opt/gst-plugins-rs/lib/aarch64-linux-gnu/gstreamer-1.0

# 2. Restart du service systemd
sudo systemctl restart reachy-mini-daemon.service && sleep 6

# 3. Démarrer le backend avec wake_up (active moteurs + lève la tête)
curl -X POST 'http://localhost:8000/api/daemon/start?wake_up=true'
sleep 8
# → La tête se lève, son de réveil, moteurs actifs
```

### Capture photo via socket GStreamer (caméra active)

```bash
gst-launch-1.0 unixfdsrc socket-path=/tmp/reachymini_camera_socket num-buffers=1 \
  ! 'video/x-raw,format=YUY2,width=1280,height=720,framerate=30/1' \
  ! videoconvert ! jpegenc ! filesink location=/home/pollen/photo.jpg
```

### Contrôle mouvements (Python — /venvs/apps_venv/bin/python)

```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
import numpy as np, time

with ReachyMini(media_backend='no_media') as mini:
    mini.wake_up()                                              # lève la tête + son
    time.sleep(2)
    mini.goto_target(head=create_head_pose(yaw=-70, degrees=True), duration=2.0)
    time.sleep(2)
```

### Librairies installées dans /venvs/apps_venv
- opencv 4.12.0, numpy 2.2.5, onnxruntime 1.24.2 ✅
- insightface 0.7.3 ✅ (installé 09/03/2026)
- scikit-learn 1.8.0 ✅

### Ressources Pi — à surveiller
- RAM : 3.7G total, ~2.7G libre
- Disque : 14G / 84% utilisé → models ONNX nano uniquement

### Phase 1 — todo (prochaine session)
- [ ] Enrôlement visage Alexandre (10 photos → alexandre.npy via InsightFace)
- [ ] Reconnaissance temps réel (cosine similarity)
- [ ] LLM via HuggingFace apps existantes
- [ ] Stockfish ARM (armv8) + python-chess
- [ ] Agent orchestrateur Reachy Care v0.1
