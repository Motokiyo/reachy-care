# 🤖 REACHY CARE — Analyse Globale & Plan d'Action Phase 1
**Projet :** Reachy Care
**Auteur :** Alexandre Mathieu Motokiyo Ferran
**Date :** Mars 2026
**Modèle :** Reachy Mini Wireless (Pollen Robotics × Hugging Face)

---

## 1. COMPRÉHENSION DU MATÉRIEL

### 1.1 Hardware — Reachy Mini Wireless

| Composant | Spec |
|---|---|
| Ordinateur embarqué | **Raspberry Pi 4** (4 Go RAM) |
| Connectivité | WiFi + Batterie intégrée (wireless charging) |
| Caméra | Grand angle (wide-angle), accès frame numpy `(H, W, 3)` uint8 |
| Audio IN | **4 microphones omnidirectionnels** |
| Audio OUT | Haut-parleur **5W** |
| Capteurs | **IMU** (accéléromètre + gyroscope + quaternions) |
| Degrés de liberté | 6 DoF tête + rotation corps + antennes |
| OS | Linux (Raspberry Pi OS) |
| Poids | ~1,5 kg |

### 1.2 Architecture Software

```
┌─────────────────────────────────────────────────────┐
│            REACHY MINI WIRELESS                     │
│                                                     │
│  Raspberry Pi 4                                     │
│  ┌────────────────────────────────────────────┐     │
│  │  reachy_mini SDK (Python)                  │     │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  │     │
│  │  │  Media  │  │ Movement │  │ Sensors  │  │     │
│  │  │ (cam+   │  │ (goto_   │  │  (IMU,   │  │     │
│  │  │  audio) │  │  target) │  │  DoA)    │  │     │
│  │  └─────────┘  └──────────┘  └──────────┘  │     │
│  │                                            │     │
│  │  Daemon HTTP/WS (port 8000)                │     │
│  │  → REST: GET /api/state/full               │     │
│  │  → WebSocket: /api/state/ws/full           │     │
│  └────────────────────────────────────────────┘     │
│                                                     │
│  GStreamer (video/audio pipeline local)             │
└─────────────────────────────────────────────────────┘
         │                         │
    WiFi/SSH                   WebRTC
    (local)                  (remote)
         │                         │
  ┌─────────────┐       ┌──────────────────┐
  │ Programme   │       │ App HF Space     │
  │ Python SSH  │       │ (Gradio/FastAPI) │
  └─────────────┘       └──────────────────┘
```

---

## 2. L'API SDK — CE QU'ON PEUT FAIRE EN CODE

### 2.1 Initialisation

```python
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
import numpy as np

# Auto-détection USB/WiFi
with ReachyMini() as mini:
    pass  # tout le code va ici

# Forcer un mode si besoin
with ReachyMini(connection_mode="network") as mini:
    pass
```

### 2.2 Caméra — Point critique pour notre projet

```python
with ReachyMini() as mini:
    # Récupérer une frame
    frame = mini.media.get_frame()
    # → numpy array shape (H, W, 3), dtype uint8, format RGB

    # Sur wireless local (SSH) : backend GStreamer automatique
    # Sur wireless remote : backend WebRTC automatique
    # Sur Lite : OpenCV ou GStreamer
```

**⚠️ Point d'attention Phase 1 :** Le backend WebRTC est actuellement **Linux only** pour le client remote. Sur la Pi elle-même (SSH), GStreamer fonctionne directement.

### 2.3 Contrôle du mouvement

```python
with ReachyMini() as mini:
    # Mouvement fluide (interpolation minjerk par défaut)
    mini.goto_target(
        head=create_head_pose(z=10, roll=15, degrees=True, mm=True),
        antennas=np.deg2rad([45, -45]),
        body_yaw=np.deg2rad(30),
        duration=2.0,
        method="minjerk"  # linear | minjerk | ease_in_out | cartoon
    )

    # Mouvement instantané (haute fréquence, tracking)
    mini.set_target(...)

    # Enregistrement de mouvements
    mini.start_recording()
    recorded = mini.stop_recording()
```

### 2.4 Audio

```python
with ReachyMini() as mini:
    mini.media.start_recording()
    mini.media.start_playing()

    # Lire audio (numpy array shape (samples, 2), float32, 16kHz)
    samples = mini.media.get_audio_sample()

    # Direction d'arrivée du son (DoA)
    # 0 rad = gauche, π/2 rad = avant/arrière, π rad = droite
    doa, is_speech = mini.media.get_DoA()

    # Jouer de l'audio
    mini.media.push_audio_sample(samples)  # non-bloquant !

    mini.media.stop_recording()
    mini.media.stop_playing()
```

### 2.5 IMU (wireless uniquement)

```python
with ReachyMini() as mini:
    imu = mini.imu
    ax, ay, az = imu["accelerometer"]  # m/s²
    gx, gy, gz = imu["gyroscope"]      # rad/s
    qw, qx, qy, qz = imu["quaternion"]
    temp = imu["temperature"]          # °C
```

---

## 3. ARCHITECTURE DES APPS

### 3.1 Structure d'une App Reachy Mini

Le SDK propose un système d'apps compatible **Hugging Face Spaces**. Une app standard ressemble à :

```
mon_app/
├── app.py           # Point d'entrée principal (Gradio ou FastAPI)
├── requirements.txt
├── README.md        # Métadonnées HF Space
└── modules/
    ├── vision.py    # Traitement caméra
    ├── chess.py     # Logique échecs
    └── face_id.py   # Reconnaissance personne
```

### 3.2 App existante : Conversation (référence LLM)

L'app officielle `reachy_mini_conversation_app` utilise :
- **OpenAI Realtime API** (STT + LLM + TTS en streaming)
- **fastrtc** pour le streaming bas-latence
- **SmolVLM2** (optionnel, `--local-vision`) pour la vision locale sur Pi
- **Gradio** comme interface web
- **fastrtc** pour le son temps réel

**Ce qu'elle fait :** VAD → ASR → LLM → TTS → mouvement du robot

---

## 4. CONTRAINTES RASPBERRY PI 4

Ce point est **crucial** pour choisir nos modèles IA :

| Ressource | Valeur | Impact |
|---|---|---|
| CPU | ARM Cortex-A72, 4 cores, 1.8 GHz | Inference lente sans quantization |
| RAM | 4 Go (partagée OS + modèles + cam) | Modèles ≤ 500 MB recommandés |
| GPU | VideoCore VI (pas de CUDA) | Pas d'accélération PyTorch GPU |
| Stockage | MicroSD (I/O limitées) | Éviter lectures/écritures répétées |
| Réseau | WiFi 802.11ac | OK pour API distantes |

**Stratégies d'optimisation :**
- Préférer les modèles **nano/tiny** (YOLO11n, MobileNet)
- Utiliser **ONNX Runtime** ou **TFLite** plutôt que PyTorch brut
- Quantization INT8 quand disponible
- Ou déléguer l'inference à un serveur externe (ton Mac/PC)

---

## 5. PHASE 1 — MODULE ÉCHECS (Chess Vision)

### 5.1 Objectif

Créer un module autonome permettant à Reachy Mini de :
1. **Voir** l'échiquier via sa caméra
2. **Identifier** toutes les pièces et leur position (notation FEN)
3. **Calculer** le meilleur coup via Stockfish
4. **Annoncer** le coup (TTS ou affichage)
5. (Bonus) **Réagir** visuellement (tête qui suit l'échiquier)

### 5.2 Stack technique recommandé

```
PIPELINE COMPLET :
Camera frame (Reachy SDK)
    ↓
Détection échiquier + pièces (YOLO)
    ↓
Reconstruction position FEN (python-chess)
    ↓
Analyse Stockfish (stockfish Python)
    ↓
Meilleur coup → TTS / affichage
    ↓
Mouvement tête Reachy (goto_target)
```

### 5.3 Modèles HuggingFace — Chess Vision

#### Option A (Recommandée) : `yamero999/chess-piece-detection-yolo11n`
- **Architecture :** YOLO11n (nano)
- **Format :** ONNX + PyTorch
- **Input :** 416×416 px
- **Classes :** 12 (6 blancs + 6 noirs : Pawn, Knight, Bishop, Rook, Queen, King)
- **Licence :** Apache 2.0 ✅
- **Avantages :** ONNX = rapide sur Pi, nano = léger
- **Usage :**
```python
from ultralytics import YOLO
model = YOLO("yamero999/chess-piece-detection-yolo11n")
results = model(frame, imgsz=416, conf=0.5)
```

#### Option B : `acapitani/chesspiece-detection-yolo`
- **Architecture :** YOLOv10n (nano)
- **Dataset :** 4 420 images
- **Classes :** 12
- **Licence :** MIT (attention : dépendance GPL-3.0 via Ultralytics)
- **Entraînement :** 100 epochs

#### Option C : `schumannc/detect-chess-pieces`
- Alternative légère, à évaluer selon perf sur Pi

#### Dataset de référence : `jalFaizy/detect_chess_pieces`
- Pour fine-tuning si les modèles prêts ne sont pas assez précis

### 5.4 Stockfish sur Raspberry Pi

```bash
# Installation sur la Pi (ARM)
git clone https://github.com/official-stockfish/Stockfish
cd Stockfish/src
make net
make build ARCH=armv8   # Pour RPi 4 (64-bit OS)
# ou ARCH=armv7 pour OS 32-bit

# Python wrapper
pip install stockfish python-chess
```

```python
import chess
import chess.engine

# Charger le moteur
engine = chess.engine.SimpleEngine.popen_uci("/usr/local/bin/stockfish")

# Analyser une position
board = chess.Board(fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
result = engine.play(board, chess.engine.Limit(time=2.0))
print(result.move)  # ex: e7e5

engine.quit()
```

### 5.5 Conversion Frame → FEN (algorithme)

```python
# Pseudo-code du pipeline de détection
def frame_to_fen(frame):
    # 1. Détecter l'échiquier (homographie)
    corners = detect_board_corners(frame)
    board_img = warp_perspective(frame, corners)  # → 512x512

    # 2. Détecter les pièces
    results = yolo_model(board_img)

    # 3. Mapper positions pixels → cases (a1-h8)
    pieces_on_board = {}
    for detection in results:
        square = pixel_to_square(detection.bbox, board_img.shape)
        piece = detection.class_name  # ex: "White_Queen"
        pieces_on_board[square] = piece

    # 4. Construire le FEN
    fen = build_fen_from_pieces(pieces_on_board)
    return fen
```

---

## 6. PHASE 1 — RECONNAISSANCE DE PERSONNES

### 6.1 Objectif

Permettre à Reachy Mini d'identifier une personne spécifique (toi, Alexandre) dans son champ de vision, en utilisant uniquement la Pi et sa caméra.

### 6.2 Modèles & Librairies recommandés

#### Option A (Recommandée) : **DeepFace + InsightFace**
- **DeepFace** : wrapper Python léger qui supporte VGG-Face, ArcFace, MobileNet
- **InsightFace / Buffalo_L** : [`deepghs/insightface`](https://huggingface.co/deepghs/insightface)
- Avantage : pipeline complet détection + embedding + reconnaissance en quelques lignes
- **Modèle Buffalo_L** disponible sur HuggingFace : [`immich-app/buffalo_l`](https://huggingface.co/immich-app/buffalo_l)

```python
from deepface import DeepFace

# Vérifier si une personne est connue
result = DeepFace.verify(
    img1_path=frame,  # numpy array depuis Reachy
    img2_path="known_person.jpg",
    model_name="ArcFace",  # ou "MobileNet"
    detector_backend="opencv"
)
print(result["verified"])  # True/False
```

#### Option B (Très légère) : **OpenCV + LBPH**
- Local Binary Patterns Histograms
- Classique, rapide sur Pi, pas de GPU
- Entrainement sur quelques photos (10-20 suffisent)
- Idéal pour reconnaître une personne spécifique

```python
import cv2

# Entraînement
recognizer = cv2.face.LBPHFaceRecognizer_create()
recognizer.train(faces_array, labels_array)

# Prédiction
label, confidence = recognizer.predict(face_roi)
```

#### Option C : **InsightFace Python + ONNX**
- [`public-data/insightface`](https://huggingface.co/public-data/insightface)
- Modèle buffalo_l : très précis, tourne en ONNX Runtime (rapide sur Pi)
- < 2ms d'inference sur edge

```python
import insightface
from insightface.app import FaceAnalysis

app = FaceAnalysis(providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

# Analyser une frame
faces = app.get(frame)  # retourne embeddings + bbox + attributs
```

### 6.3 Stratégie d'enregistrement d'une personne

```python
# Workflow : Créer une "base" de connaissances

def register_person(name, num_photos=20):
    """Enregistrer une nouvelle personne"""
    embeddings = []
    with ReachyMini() as mini:
        for i in range(num_photos):
            frame = mini.media.get_frame()
            faces = face_analyzer.get(frame)
            if faces:
                embeddings.append(faces[0].embedding)

    # Sauvegarder l'embedding moyen
    mean_embedding = np.mean(embeddings, axis=0)
    np.save(f"known_faces/{name}.npy", mean_embedding)

def identify_person(frame):
    """Identifier qui est devant le robot"""
    faces = face_analyzer.get(frame)
    if not faces:
        return None

    embedding = faces[0].embedding

    # Comparer avec tous les visages connus
    best_match = None
    best_score = 0
    for known_file in Path("known_faces").glob("*.npy"):
        known_emb = np.load(known_file)
        score = cosine_similarity(embedding, known_emb)
        if score > 0.4 and score > best_score:  # seuil ajustable
            best_score = score
            best_match = known_file.stem

    return best_match
```

---

## 7. PLAN D'ACTION — PHASE 1 COMPLÈTE

### Étape 0 : Setup environnement (Jour 1)

```bash
# Sur la Pi (SSH dans la Reachy)
pip install ultralytics python-chess stockfish
pip install deepface insightface onnxruntime
pip install opencv-python-headless scipy

# Compiler Stockfish ARM
git clone https://github.com/official-stockfish/Stockfish
cd Stockfish/src && make build ARCH=armv8
```

**Tester la caméra :**
```python
from reachy_mini import ReachyMini
with ReachyMini() as mini:
    frame = mini.media.get_frame()
    print(f"Camera OK: shape={frame.shape}")  # (480, 640, 3) typiquement
```

### Étape 1 : Module détection d'échiquier (Semaine 1)

1. Télécharger `yamero999/chess-piece-detection-yolo11n`
2. Tester sur images statiques d'échiquier
3. Développer `detect_board_corners()` (Harris corners ou YOLO board)
4. Développer `pixel_to_square()` (grille 8x8)
5. Valider la reconstruction FEN

**Fichier :** `phase1_chess_vision/chess_detector.py`

### Étape 2 : Intégration Stockfish (Semaine 1-2)

1. Intégrer le moteur Stockfish compilé
2. Créer `chess_engine.py` avec gestion des tours
3. Tester pipeline complet : frame → FEN → meilleur coup
4. Ajouter TTS (pyttsx3 ou API) pour annoncer le coup

**Fichier :** `phase1_chess_vision/chess_engine.py`

### Étape 3 : Module reconnaissance personnes (Semaine 2)

1. Installer InsightFace + ONNX Runtime sur Pi
2. Créer script `register_person.py` (enregistrement via caméra)
3. Enregistrer Alexandre (20+ photos)
4. Créer `face_recognizer.py` (identification temps réel)
5. Intégrer : si personne connue détectée → comportement personnalisé

**Fichier :** `phase1_chess_vision/face_recognizer.py`

### Étape 4 : App Reachy Care v0.1 (Semaine 3)

1. Créer `app.py` unifiant chess + face recognition
2. Ajouter comportement robot (tête vers échiquier, expressions antennes)
3. Tester end-to-end
4. Publier en HF Space optionnel

**Structure finale :**
```
reachy_care/
├── app.py                          # Entry point
├── requirements.txt
├── phase1_chess_vision/
│   ├── chess_detector.py           # YOLO → FEN
│   ├── chess_engine.py             # Stockfish integration
│   └── face_recognizer.py          # InsightFace recognition
├── known_faces/                    # Embeddings visages enregistrés
│   └── alexandre.npy
└── docs/
    └── ANALYSE_GLOBALE_REACHY_CARE.md  # Ce document
```

---

## 8. RESSOURCES CLÉS

### SDK & Documentation
- [Reachy Mini SDK docs](https://huggingface.co/docs/reachy_mini/index)
- [Python SDK Reference](https://huggingface.co/docs/reachy_mini/SDK/python-sdk)
- [Quickstart Guide](https://huggingface.co/docs/reachy_mini/SDK/quickstart)
- [GitHub pollen-robotics/reachy_mini](https://github.com/pollen-robotics/reachy_mini)
- [Conversation App (référence LLM)](https://github.com/pollen-robotics/reachy_mini_conversation_app)

### Modèles HuggingFace — Chess Vision
- [yamero999/chess-piece-detection-yolo11n](https://huggingface.co/yamero999/chess-piece-detection-yolo11n) ← **RECOMMANDÉ**
- [acapitani/chesspiece-detection-yolo](https://huggingface.co/acapitani/chesspiece-detection-yolo)
- [schumannc/detect-chess-pieces](https://huggingface.co/schumannc/detect-chess-pieces)
- [dopaul/chess-piece-detector-merged-v2](https://huggingface.co/dopaul/chess-piece-detector-merged-v2)
- [Dataset: jalFaizy/detect_chess_pieces](https://huggingface.co/datasets/jalFaizy/detect_chess_pieces)

### Modèles HuggingFace — Face Recognition
- [deepghs/insightface](https://huggingface.co/deepghs/insightface) ← **RECOMMANDÉ**
- [immich-app/buffalo_l](https://huggingface.co/immich-app/buffalo_l)
- [public-data/insightface](https://huggingface.co/public-data/insightface)
- [qualcomm/Lightweight-Face-Detection](https://huggingface.co/qualcomm/Lightweight-Face-Detection)

### Chess Engine
- [Stockfish Python wrapper](https://pypi.org/project/stockfish/)
- [python-chess library](https://python-chess.readthedocs.io/)
- [Compilation Stockfish ARM/RPi](https://www.qunsul.com/posts/compiling-stockfish-on-raspberry-pi.html)

---

## 9. POINTS D'ATTENTION & RISQUES

| Risque | Probabilité | Mitigation |
|---|---|---|
| WebRTC remote non dispo sur Mac/Windows | Haute ⚠️ | Travailler en SSH direct sur la Pi |
| YOLO trop lent sur Pi (inference > 2s) | Moyenne | ONNX Runtime + quantization INT8 |
| Détection échiquier difficile (lumière) | Moyenne | Calibration + preprocessing (CLAHE) |
| Manque de RAM (modèles + OS) | Faible | Swapfile + modèles nano |
| Stockfish compilation ARM | Faible | Package apt disponible en backup |

---

## 10. PROCHAINE SESSION

**Objectif :** Ouvrir Claude Code sur la Reachy (SSH) et commencer à coder `chess_detector.py`

**Checklist avant de coder :**
- [ ] Tester SSH sur la Reachy Mini
- [ ] Vérifier `python3 -c "from reachy_mini import ReachyMini; print('OK')"`
- [ ] Tester `frame = mini.media.get_frame()` et sauvegarder une image
- [ ] Installer `ultralytics` : `pip install ultralytics`
- [ ] Télécharger le modèle YOLO chess
- [ ] Prendre une photo de l'échiquier pour les premiers tests

---

*Document généré le 9 mars 2026 — Reachy Care v0.1 Planning*
