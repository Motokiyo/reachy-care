# Reachy Mini — Questions & Réponses avec Cowork

> Fichier partagé entre Alexandre et l'agent Cowork.
> Alexandre écrit ses questions dans les sections `### Question`, Cowork répond dans les sections `### Réponse`.

---

## Format à utiliser

```
### Question [date]
[texte de la question]

### Réponse [date]
[réponse de Cowork]
```

---

## 🔐 Accès serveurs

### Reachy Mini
```
ssh pollen@reachy-mini.local     # ou ssh pollen@192.168.1.244
Mot de passe : root
```
- Robot : Reachy Mini Wireless (Pollen Robotics)
- OS : Linux aarch64 (Raspberry Pi 4, Debian) — kernel 6.12.47
- Diagnostic : `reachyminios_check`

### OpenClaw (serveur IA)
```
ssh root@REDACTED_IP
Gateway : http://REDACTED_IP:18789/
Auth token : REDACTED_OPENCLAW_TOKEN
```

---

## ⚡ RÉFÉRENCE SDK — TOUT CE QU'IL FAUT SAVOIR

### 1. Connexion SSH + venv OBLIGATOIRE

```bash
ssh pollen@reachy-mini.local
# mot de passe : root

# TOUJOURS activer le venv avant de lancer quoi que ce soit
source /venvs/apps_venv/bin/activate

python3 mon_script.py
```

> ⚠️ Sans le venv activé, les imports reachy_mini peuvent échouer.

### 2. Initialisation du robot

```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
import numpy as np

# Sans média (plus rapide si on ne veut que les mouvements)
with ReachyMini(media_backend="no_media") as mini:
    pass

# Avec caméra + audio (GStreamer auto en SSH local)
with ReachyMini() as mini:
    pass
```

### 3. Sortir le robot de son habitacle — position initiale

```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

with ReachyMini(media_backend="no_media") as mini:
    mini.enable_motors()   # activer les moteurs (stiff mode)

    # Position neutre : tête droite, antennes basses, corps centré
    mini.goto_target(
        head=create_head_pose(),
        antennas=[0.0, 0.0],
        body_yaw=0.0,
        duration=2.0,
        method="minjerk"
    )
```

### 4. Contrôle mouvement — goto_target (fluide, ≥ 0.5s)

```python
# Lever la tête
mini.goto_target(head=create_head_pose(z=15, mm=True), duration=1.0)

# Incliner la tête (roll=gauche/droite, pitch=bas/haut, yaw=rotation)
mini.goto_target(
    head=create_head_pose(roll=15, pitch=10, yaw=20, degrees=True),
    duration=1.5,
    method="minjerk"   # linear | minjerk | ease_in_out | cartoon
)

# Antennes [gauche, droite] en radians
mini.goto_target(antennas=[0.5, -0.5], duration=0.5)
mini.goto_target(antennas=[0.0, 0.0], duration=0.5)

# Rotation du corps
mini.goto_target(body_yaw=np.deg2rad(45), duration=1.5)

# Tout en même temps
mini.goto_target(
    head=create_head_pose(z=10, roll=15, degrees=True, mm=True),
    antennas=np.deg2rad([45, 45]),
    body_yaw=np.deg2rad(30),
    duration=2.0
)
```

### 5. Contrôle temps réel — set_target (haute fréquence ≥ 10Hz)

```python
import time

with ReachyMini(media_backend="no_media") as mini:
    mini.goto_target(create_head_pose(), antennas=[0.0, 0.0], duration=1.0)
    try:
        while True:
            t = time.time()
            pitch = np.deg2rad(10 * np.sin(2 * np.pi * 0.5 * t))
            ant   = np.deg2rad(20 * np.sin(2 * np.pi * 0.5 * t))
            mini.set_target(
                head=create_head_pose(pitch=pitch, degrees=False),
                antennas=[ant, ant]
            )
            time.sleep(0.02)  # 50 Hz
    except KeyboardInterrupt:
        pass
```

### 6. Modes moteurs

```python
mini.enable_motors()               # stiff — tient la position
mini.disable_motors()              # libre — on peut bouger à la main
mini.enable_gravity_compensation() # soft — suit la main et reste en place
```

### 7. Caméra — ⚠️ frame déjà en BGR, pas de conversion nécessaire

```python
import cv2, time

with ReachyMini() as mini:
    frame = mini.media.get_frame()

    # Timeout si frame None au démarrage
    start = time.time()
    while frame is None:
        if time.time() - start > 20:
            break
        frame = mini.media.get_frame()
        time.sleep(1)

    if frame is not None:
        # frame = numpy (H, W, 3) uint8 — format BGR (cv2 natif)
        # NE PAS faire cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        cv2.imwrite("/home/pollen/capture.jpg", frame)
        print(f"Shape: {frame.shape}")  # ex: (480, 640, 3)
```

### 8. Audio

```python
with ReachyMini() as mini:
    mini.media.start_recording()
    mini.media.start_playing()

    samples = mini.media.get_audio_sample()  # (samples, 2) float32 16kHz
    doa, is_speech = mini.media.get_DoA()    # direction d'arrivée du son
    # doa: 0=gauche, π/2=avant/arrière, π=droite

    mini.media.push_audio_sample(samples)    # non-bloquant

    mini.media.stop_recording()
    mini.media.stop_playing()
```

### 9. Limites de sécurité (clamping automatique SDK)

| Axe | Plage |
|-----|-------|
| Head Pitch / Roll | [-40°, +40°] |
| Head Yaw | [-180°, +180°] |
| Body Yaw | [-160°, +160°] |
| Delta Yaw (tête - corps) | max 65° d'écart |

### 10. API REST (depuis n'importe où sur le réseau)

```
GET  http://reachy-mini.local:8000/api/state/full
WS   ws://reachy-mini.local:8000/api/state/ws/full
Docs http://reachy-mini.local:8000/docs   ← Swagger UI complet
```

### 11. Ressources officielles

- Doc SDK complète : https://huggingface.co/docs/reachy_mini/SDK/python-sdk
- Core concepts + limites : https://huggingface.co/docs/reachy_mini/SDK/core-concept
- Exemples officiels : https://github.com/pollen-robotics/reachy_mini/tree/main/examples
- Guide pour agents IA : https://github.com/pollen-robotics/reachy_mini/blob/develop/AGENTS.md

---

## État Reachy Mini (check du 09/03/2026)

- Services actifs : `reachy-mini-bluetooth.service`, `reachy-mini-daemon.service` ✔
- Caméra : imx708_wide ✔
- Audio : entrée + sortie ✔
- Moteurs XL330 : tous répondent ✔
- Disque : 14G total, 11G utilisé, 2.3G libre (84% — attention)
- RAM : 3.7G total, 2.7G libre
- Erreurs connues :
  - GStreamer plugins `webrtcsrc` / `webrtcsink` manquants
  - IMU non détecté (i2c bus 4, addr 0x18 et 0x69) + `i2cdetect` manquant

---

## Questions / Réponses

### Question — 09/03/2026
On vient de faire un `reachyminios_check` sur le Reachy Mini. Deux erreurs remontent :
1. Les plugins GStreamer `webrtcsrc` et `webrtcsink` sont manquants
2. L'IMU n'est pas détecté sur le bus i2c 4 (adresses 0x18 et 0x69) et `i2cdetect` n'est pas installé

Est-ce que ces erreurs sont bloquantes pour un usage basique du robot (mouvements de tête, caméra, audio) ? Est-ce qu'il faut les corriger maintenant ou peut-on avancer quand même ?

### Réponse — 09/03/2026

**Non, ces deux erreurs ne sont pas bloquantes pour avancer.**

**1. GStreamer webrtcsrc / webrtcsink manquants**
Ces plugins ne servent qu'au mode WebRTC remote (contrôle depuis un Mac/PC distant). En SSH direct sur la Pi, le backend GStreamer local fonctionne parfaitement pour `mini.media.get_frame()`. On peut totalement ignorer ces erreurs pour Phase 1 — on travaille en local.

**2. IMU non détecté**
L'IMU (accéléromètre/gyroscope) n'est pas utilisé dans Phase 1 (chess vision + face recognition). Ce n'est pas un bug critique, probablement un problème d'assemblage ou de câblage du module IMU. À investiguer plus tard si on a besoin des données de mouvement.

**Conclusion : on peut avancer sans rien corriger.**

---

### Question — 09/03/2026 (suite)
Le robot reste tête molle, il ne bouge pas. Les photos sont noires car il est dans son habitacle et ne lève pas la tête. Comment forcer les moteurs à s'activer ?

### Réponse — 09/03/2026

Le problème vient probablement de l'ordre des opérations ou d'un script incomplet. Voici le script **minimal garanti** à copier-coller tel quel :

**Étape 1 — SSH + venv**
```bash
ssh pollen@reachy-mini.local
source /venvs/apps_venv/bin/activate
```

**Étape 2 — Créer ce fichier sur la Pi**
```bash
cat > /home/pollen/wake_up.py << 'SCRIPT'
import time
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

print("Connexion...")
with ReachyMini(media_backend="no_media") as mini:
    print("Connecté.")

    print("Activation des moteurs...")
    mini.enable_motors()
    time.sleep(1.0)   # laisser le temps aux moteurs de s'activer

    print("Mouvement vers position neutre...")
    mini.goto_target(
        head=create_head_pose(),
        antennas=[0.0, 0.0],
        body_yaw=0.0,
        duration=3.0,
        method="minjerk"
    )
    time.sleep(3.5)   # attendre fin du mouvement

    print("Lever la tête...")
    mini.goto_target(
        head=create_head_pose(pitch=-20, degrees=True),
        duration=2.0
    )
    time.sleep(2.5)

    print("Done — robot debout !")
    time.sleep(2.0)
SCRIPT
```

**Étape 3 — Lancer**
```bash
python3 /home/pollen/wake_up.py
```

**Si ça ne bouge toujours pas**, vérifier que le daemon tourne bien :
```bash
systemctl status reachy-mini-daemon.service
# Si arrêté :
sudo systemctl restart reachy-mini-daemon.service
# Attendre 10 secondes puis relancer le script
```

**Si erreur Python**, vérifier l'import :
```bash
python3 -c "from reachy_mini import ReachyMini; print('OK')"
```
Si `ModuleNotFoundError` → le venv n'est pas activé, refaire `source /venvs/apps_venv/bin/activate`.

---

### Réponse mise à jour — 09/03/2026 (après analyse RESULTATS_TESTS.md)

Claude Code a trouvé 3 éléments critiques absents de la doc officielle :

**1. Il faut démarrer le backend AVANT d'utiliser le SDK**
```bash
curl -X POST 'http://localhost:8000/api/daemon/start?wake_up=false'
# ou avec wake_up=true pour lever la tête automatiquement :
curl -X POST 'http://localhost:8000/api/daemon/start?wake_up=true'
```

**2. `mini.wake_up()` est la méthode pour sortir la tête du support**
```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
import time, numpy as np

with ReachyMini() as mini:
    mini.wake_up()        # ← sort la tête du support
    time.sleep(1.5)
    # Ensuite on peut bouger normalement
    mini.goto_target(
        head=create_head_pose(pitch=-20, degrees=True),
        duration=2.0
    )
    time.sleep(2.5)
```

**3. Python à utiliser : `/venvs/apps_venv/bin/python` (pas `python3`)**
```bash
/venvs/apps_venv/bin/python mon_script.py
# ou activer le venv :
source /venvs/apps_venv/bin/activate && python3 mon_script.py
```

**4. Résolution caméra réelle : 1280×720** (pas 640×480 comme estimé)

**Script complet wake_up + photo :**
```python
import time
import cv2
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

with ReachyMini() as mini:
    mini.wake_up()
    time.sleep(2.0)

    # Lever la tête pour voir devant
    mini.goto_target(head=create_head_pose(pitch=-15, degrees=True), duration=2.0)
    time.sleep(2.5)

    # Photo
    frame = mini.media.get_frame()
    start = time.time()
    while frame is None and time.time() - start < 20:
        frame = mini.media.get_frame()
        time.sleep(1)

    if frame is not None:
        cv2.imwrite("/home/pollen/photo_eveil.jpg", frame)
        print(f"Photo OK — shape={frame.shape}")
```

---

## 🚀 PHASE 1 — INSTRUCTIONS DE DÉVELOPPEMENT

> **Statut caméra (09/03/2026) :** ✅ Opérationnelle — 1280×720, image claire
> **Librairies déjà installées :** opencv, numpy, onnxruntime, insightface 0.7.3, scikit-learn
> **Structure cible :** `/home/pollen/reachy_care/` sur la Pi

---

### MODULE 1A — Reconnaissance Faciale (InsightFace)

**Objectif :** Le robot identifie Alexandre dès qu'il le voit et adapte son comportement.

#### Étape 1 — Créer la structure projet sur la Pi

```bash
ssh pollen@reachy-mini.local
source /venvs/apps_venv/bin/activate
mkdir -p /home/pollen/reachy_care/{models,known_faces,modules,logs}
```

#### Étape 2 — Script d'enrôlement (register_face.py)

Créer `/home/pollen/reachy_care/modules/register_face.py` :

```python
"""
Enregistrement d'un visage connu via la caméra Reachy.
Usage : python3 register_face.py --name alexandre --photos 20
"""
import argparse
import time
import cv2
import numpy as np
from pathlib import Path
from reachy_mini import ReachyMini
import insightface
from insightface.app import FaceAnalysis

def register_face(name: str, num_photos: int = 20):
    save_dir = Path("/home/pollen/reachy_care/known_faces")
    save_dir.mkdir(exist_ok=True)

    # Initialiser InsightFace
    print("Chargement InsightFace buffalo_s...")
    app = FaceAnalysis(
        name="buffalo_s",  # nano model, plus léger que buffalo_l pour la Pi
        root="/home/pollen/reachy_care/models",
        providers=["CPUExecutionProvider"]
    )
    app.prepare(ctx_id=0, det_size=(320, 320))

    embeddings = []
    print(f"Enrôlement de '{name}' — {num_photos} photos...")
    print("Placez-vous face à la caméra. Capture dans 3 secondes...")
    time.sleep(3)

    with ReachyMini() as mini:
        mini.wake_up()
        time.sleep(1.5)
        # Tête légèrement levée pour viser le visage
        from reachy_mini.utils import create_head_pose
        mini.goto_target(head=create_head_pose(pitch=-10, degrees=True), duration=1.5)
        time.sleep(2.0)

        for i in range(num_photos):
            frame = mini.media.get_frame()
            start = time.time()
            while frame is None and time.time() - start < 5:
                frame = mini.media.get_frame()
                time.sleep(0.2)

            if frame is None:
                print(f"  Photo {i+1}/{num_photos} — frame None, skip")
                continue

            faces = app.get(frame)
            if not faces:
                print(f"  Photo {i+1}/{num_photos} — aucun visage détecté, repositionnez-vous")
                time.sleep(0.5)
                continue

            # Prendre le visage le plus grand (le plus proche)
            face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
            embeddings.append(face.embedding)
            print(f"  Photo {i+1}/{num_photos} — visage capturé ✅ (det_score={face.det_score:.2f})")
            time.sleep(0.3)

    if not embeddings:
        print("❌ Aucun embedding collecté. Réessayez avec un meilleur éclairage.")
        return

    # Calcul de l'embedding moyen et sauvegarde
    mean_embedding = np.mean(embeddings, axis=0)
    mean_embedding /= np.linalg.norm(mean_embedding)  # normalisation L2
    save_path = save_dir / f"{name}.npy"
    np.save(save_path, mean_embedding)
    print(f"✅ Embedding sauvegardé : {save_path} ({len(embeddings)} photos valides)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="alexandre")
    parser.add_argument("--photos", type=int, default=20)
    args = parser.parse_args()
    register_face(args.name, args.photos)
```

**Lancer l'enrôlement :**
```bash
cd /home/pollen/reachy_care
/venvs/apps_venv/bin/python modules/register_face.py --name alexandre --photos 20
```

#### Étape 3 — Script de reconnaissance temps réel (face_recognizer.py)

Créer `/home/pollen/reachy_care/modules/face_recognizer.py` :

```python
"""
Module de reconnaissance faciale temps réel.
Retourne le nom de la personne identifiée ou None.
"""
import numpy as np
from pathlib import Path
import insightface
from insightface.app import FaceAnalysis

class FaceRecognizer:
    def __init__(self, known_faces_dir="/home/pollen/reachy_care/known_faces",
                 threshold=0.4):
        self.threshold = threshold
        self.known = {}

        # Charger InsightFace
        self.app = FaceAnalysis(
            name="buffalo_s",
            root="/home/pollen/reachy_care/models",
            providers=["CPUExecutionProvider"]
        )
        self.app.prepare(ctx_id=0, det_size=(320, 320))

        # Charger les visages connus
        for f in Path(known_faces_dir).glob("*.npy"):
            self.known[f.stem] = np.load(f)
        print(f"FaceRecognizer: {len(self.known)} personne(s) connue(s) — {list(self.known.keys())}")

    def identify(self, frame):
        """
        Retourne (nom, score) du visage le plus probable, ou (None, 0) si inconnu.
        """
        faces = self.app.get(frame)
        if not faces:
            return None, 0.0

        face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        emb = face.embedding / np.linalg.norm(face.embedding)

        best_name, best_score = None, 0.0
        for name, known_emb in self.known.items():
            score = float(np.dot(emb, known_emb))
            if score > best_score:
                best_score = score
                best_name = name

        if best_score >= self.threshold:
            return best_name, best_score
        return None, best_score

    def is_known(self, frame):
        name, score = self.identify(frame)
        return name is not None
```

#### Étape 4 — Test rapide reconnaissance

```bash
# Test en une ligne depuis SSH
/venvs/apps_venv/bin/python - << 'EOF'
import cv2, time
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
import sys
sys.path.insert(0, '/home/pollen/reachy_care')
from modules.face_recognizer import FaceRecognizer

rec = FaceRecognizer()
with ReachyMini() as mini:
    mini.wake_up(); time.sleep(1.5)
    mini.goto_target(head=create_head_pose(pitch=-10, degrees=True), duration=1.5)
    time.sleep(2.0)
    frame = mini.media.get_frame()
    name, score = rec.identify(frame)
    print(f"Résultat : {name or 'inconnu'} (score={score:.3f})")
EOF
```

---

### MODULE 1B — Chess Vision + Stockfish

**Objectif :** Reachy lit la position sur l'échiquier, calcule et annonce le meilleur coup.

#### Étape 1 — Installer les dépendances

```bash
source /venvs/apps_venv/bin/activate
pip install ultralytics python-chess stockfish --quiet
```

#### Étape 2 — Installer Stockfish ARM

```bash
# Option A : depuis apt (plus simple)
sudo apt-get install -y stockfish
which stockfish  # → /usr/games/stockfish

# Option B : si apt non disponible, compiler (plus long)
cd /tmp
git clone --depth 1 https://github.com/official-stockfish/Stockfish
cd Stockfish/src
make build ARCH=armv8
sudo mv stockfish /usr/local/bin/
```

#### Étape 3 — Télécharger le modèle YOLO chess

```python
# Créer /home/pollen/reachy_care/modules/download_models.py
from ultralytics import YOLO
import shutil, os

# Télécharger yamero999/chess-piece-detection-yolo11n depuis HuggingFace
# (ou acapitani/chesspiece-detection-yolo comme alternative)
model = YOLO("yamero999/chess-piece-detection-yolo11n")
# Le modèle est mis en cache automatiquement par ultralytics
print(f"Modèle chess YOLO : {model.model}")
```

#### Étape 4 — chess_detector.py

Créer `/home/pollen/reachy_care/modules/chess_detector.py` :

```python
"""
Détection des pièces sur un échiquier via YOLO.
Retourne un dict {case: piece} et une string FEN partielle.
"""
import cv2
import numpy as np
from ultralytics import YOLO

# Classes YOLO → notation FEN
YOLO_TO_FEN = {
    "white-king": "K", "white-queen": "Q", "white-rook": "R",
    "white-bishop": "B", "white-knight": "N", "white-pawn": "P",
    "black-king": "k", "black-queen": "q", "black-rook": "r",
    "black-bishop": "b", "black-knight": "n", "black-pawn": "p",
}

class ChessDetector:
    def __init__(self, model_path="yamero999/chess-piece-detection-yolo11n"):
        self.model = YOLO(model_path)
        print(f"ChessDetector: modèle chargé")

    def detect(self, frame, conf=0.4):
        """Retourne liste de détections [{class, bbox, conf}]"""
        results = self.model(frame, imgsz=640, conf=conf, verbose=False)
        detections = []
        for r in results:
            for box in r.boxes:
                cls_name = r.names[int(box.cls)]
                detections.append({
                    "class": cls_name,
                    "fen_char": YOLO_TO_FEN.get(cls_name, "?"),
                    "bbox": box.xyxy[0].tolist(),
                    "conf": float(box.conf)
                })
        return detections

    def frame_to_board(self, frame):
        """
        Tente de mapper les détections sur une grille 8×8.
        Retourne dict {(col, row): fen_char} avec col,row en 0-7.
        NOTE: nécessite que l'échiquier soit bien cadré dans le frame.
        """
        detections = self.detect(frame)
        if not detections:
            return {}

        # Trouver les limites de l'échiquier à partir des détections
        all_x = [d["bbox"][0] for d in detections] + [d["bbox"][2] for d in detections]
        all_y = [d["bbox"][1] for d in detections] + [d["bbox"][3] for d in detections]
        x_min, x_max = min(all_x), max(all_x)
        y_min, y_max = min(all_y), max(all_y)
        board_w = x_max - x_min
        board_h = y_max - y_min

        board = {}
        for d in detections:
            cx = (d["bbox"][0] + d["bbox"][2]) / 2
            cy = (d["bbox"][1] + d["bbox"][3]) / 2
            col = int((cx - x_min) / board_w * 8)
            row = int((cy - y_min) / board_h * 8)
            col = max(0, min(7, col))
            row = max(0, min(7, row))
            board[(col, row)] = d["fen_char"]

        return board
```

#### Étape 5 — chess_engine.py (Stockfish wrapper)

Créer `/home/pollen/reachy_care/modules/chess_engine.py` :

```python
"""
Interface avec Stockfish pour obtenir le meilleur coup depuis un état de jeu.
"""
import chess
import chess.engine
from pathlib import Path

# Chemins possibles pour stockfish selon installation
STOCKFISH_PATHS = ["/usr/games/stockfish", "/usr/local/bin/stockfish", "/usr/bin/stockfish"]

class ChessEngine:
    def __init__(self, think_time=2.0):
        self.think_time = think_time
        self.engine = None
        sf_path = next((p for p in STOCKFISH_PATHS if Path(p).exists()), None)
        if not sf_path:
            raise FileNotFoundError("Stockfish introuvable. Installer avec: sudo apt install stockfish")
        self.engine = chess.engine.SimpleEngine.popen_uci(sf_path)
        print(f"ChessEngine: Stockfish chargé depuis {sf_path}")

    def best_move(self, board: chess.Board) -> str:
        """Retourne le meilleur coup en notation UCI (ex: 'e2e4')"""
        result = self.engine.play(board, chess.engine.Limit(time=self.think_time))
        return result.move.uci() if result.move else None

    def best_move_san(self, board: chess.Board) -> str:
        """Retourne le meilleur coup en notation algébrique (ex: 'Nf3')"""
        result = self.engine.play(board, chess.engine.Limit(time=self.think_time))
        if result.move:
            return board.san(result.move)
        return None

    def close(self):
        if self.engine:
            self.engine.quit()

    def __del__(self):
        self.close()
```

---

### MODULE 1C — App principale (main.py)

Créer `/home/pollen/reachy_care/main.py` — orchestre tout :

```python
"""
Reachy Care v0.1 — Phase 1
Lance : /venvs/apps_venv/bin/python /home/pollen/reachy_care/main.py
"""
import time
import sys
sys.path.insert(0, '/home/pollen/reachy_care')

from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
from modules.face_recognizer import FaceRecognizer
from modules.chess_detector import ChessDetector
from modules.chess_engine import ChessEngine
import chess

def say(mini, text):
    """TTS simple via espeak (installé sur Pi)"""
    import subprocess
    print(f"[Reachy] {text}")
    subprocess.Popen(["espeak-ng", "-v", "fr", "-s", "140", text])

def run():
    print("=== Reachy Care v0.1 — Phase 1 ===")

    face_rec = FaceRecognizer()
    chess_det = ChessDetector()
    chess_eng = ChessEngine(think_time=2.0)
    board = chess.Board()

    with ReachyMini() as mini:
        mini.wake_up()
        time.sleep(2.0)
        mini.goto_target(head=create_head_pose(pitch=-10, degrees=True), duration=2.0)
        time.sleep(2.0)

        say(mini, "Bonjour, je suis Reachy. Je vous observe.")

        # Boucle principale
        while True:
            frame = mini.media.get_frame()
            if frame is None:
                time.sleep(0.5)
                continue

            # 1. Reconnaissance personne
            name, score = face_rec.identify(frame)
            if name:
                print(f"✅ Personne reconnue : {name} (score={score:.2f})")
            else:
                print(f"👤 Personne inconnue (score={score:.2f})")

            # 2. Détection échiquier (si activé)
            pieces = chess_det.detect(frame)
            if pieces:
                print(f"♟ {len(pieces)} pièces détectées")
                move = chess_eng.best_move(board)
                if move:
                    board.push_uci(move)
                    say(mini, f"Je joue {move}")

            time.sleep(1.0)

if __name__ == "__main__":
    run()
```

---

### MODULE 1D — Détection de chute (fall_detector.py)

**Note :** À ajouter après validation des modules 1A et 1B.

```bash
# Installer mediapipe (léger, tourne sur Pi)
pip install mediapipe --quiet
```

```python
# /home/pollen/reachy_care/modules/fall_detector.py
import mediapipe as mp
import numpy as np

class FallDetector:
    def __init__(self, fall_threshold_sec=5):
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            model_complexity=0,   # 0=lite, 1=full, 2=heavy → 0 pour la Pi
            min_detection_confidence=0.5
        )
        self.fall_threshold = fall_threshold_sec
        self._last_upright_time = None

    def is_fallen(self, frame):
        """
        Retourne True si la personne semble être allongée au sol.
        Critère : épaules et hanches toutes à hauteur similaire (corps horizontal).
        """
        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.pose.process(rgb)
        if not results.pose_landmarks:
            return False

        lm = results.pose_landmarks.landmark
        # Points clés : épaule gauche(11), épaule droite(12), hanche gauche(23), hanche droite(24)
        shoulders_y = [lm[11].y, lm[12].y]
        hips_y = [lm[23].y, lm[24].y]

        shoulder_mean = np.mean(shoulders_y)
        hip_mean = np.mean(hips_y)

        # Si épaules et hanches à moins de 15% de hauteur d'écart → corps horizontal
        vertical_ratio = abs(shoulder_mean - hip_mean)
        return vertical_ratio < 0.15
```

---

### INSTALLATION COMPLÈTE — commandes à lancer sur la Pi

```bash
ssh pollen@reachy-mini.local
source /venvs/apps_venv/bin/activate

# 1. Dépendances
pip install ultralytics python-chess stockfish mediapipe --quiet

# 2. Stockfish
sudo apt-get install -y stockfish espeak-ng

# 3. Structure projet
mkdir -p /home/pollen/reachy_care/{models,known_faces,modules,logs}

# 4. Copier tous les modules (les créer selon les scripts ci-dessus)

# 5. Enrôlement Alexandre
/venvs/apps_venv/bin/python /home/pollen/reachy_care/modules/register_face.py --name alexandre --photos 20

# 6. Test reconnaissance
/venvs/apps_venv/bin/python /home/pollen/reachy_care/modules/face_recognizer.py

# 7. Lancer l'app principale
/venvs/apps_venv/bin/python /home/pollen/reachy_care/main.py
```

### RÉSULTATS À ÉCRIRE dans RESULTATS_TESTS.md

Après chaque module, ajouter une section :

```
## Module 1A — Reco faciale — [date]
- Enrôlement : ✅/❌ (N photos valides sur 20)
- Reconnaissance Alexandre : ✅/❌ (score=X.XX)
- Faux positifs testés : ✅/❌
- Temps inference : Xms

## Module 1B — Chess Vision — [date]
- YOLO chess : ✅/❌ (N pièces détectées sur image test)
- Stockfish : ✅/❌ (coup calculé en Xs)
- FEN correcte : ✅/❌

## Module 1D — Détection chute — [date]
- MediaPipe Pose : ✅/❌
- Détection position debout : ✅/❌
- Détection position allongée (test) : ✅/❌
```

---
