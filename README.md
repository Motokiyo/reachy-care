# Reachy Care

**Reachy Mini Wireless transformé en assistant pour personnes âgées isolées.**

Projet personnel — Alexandre Mathieu Motokiyo Ferran — Mars 2026

---

## Le projet

Reachy Care transforme le robot [Reachy Mini Wireless](https://www.pollen-robotics.com/) (Pollen Robotics) en compagnon actif pour personnes âgées vivant seules. Le robot voit, reconnaît, parle, joue, lit à voix haute — et surveille discrètement.

Ce n'est pas un simple assistant vocal. C'est un robot physiquement présent, qui regarde la personne, bouge la tête, exprime des émotions avec ses antennes — et peut appeler de l'aide si elle ne répond plus.

---

## Fonctionnalités

### 👤 Reconnaissance faciale
Le robot reconnaît les membres de l'entourage (famille, aidants) et les accueille par leur prénom dès qu'ils entrent dans son champ de vision. L'enrôlement se fait à la voix : *"Reachy, mémorise cette personne, elle s'appelle Marie."*

### 🆘 Détection de chute + vérification vocale
Quand Reachy détecte une personne immobile depuis plusieurs secondes, il pose doucement la question : *"Vous êtes confortablement installé ? Tout va bien ?"*

- Réponse positive → rien, vie privée préservée
- Réponse négative ou silence → alerte Telegram + email aux proches
- La caméra ne filme pas en continu — la détection est locale et ne quitte pas le Pi

### ♟️ Partenaire d'échecs
Reachy voit l'échiquier posé devant lui, détecte les coups joués, calcule sa réponse (Stockfish), et annonce ses coups à voix haute avec des commentaires encourageants. Il adapte son niveau automatiquement.

### 📖 Lecteur à voix haute
Reachy lit des livres du domaine public (Gutenberg) à voix haute, en continu, avec une voix théâtrale et expressive. Il se souvient de sa position dans le livre d'une session à l'autre.

### 🧠 Mémoire conversationnelle
Le robot se souvient des conversations passées : habitudes, préférences, dernière visite. La conversation s'enrichit au fil du temps.

---

## Architecture technique

```
┌─────────────────────────────────────────────────┐
│              Reachy Mini (Pi 4)                 │
│                                                 │
│  ┌──────────────────┐   HTTP    ┌─────────────┐ │
│  │   Reachy Care    │ ────────► │  conv_app   │ │
│  │   (vision)       │ ◄──────── │  (GPT-4o    │ │
│  │                  │  cmd.json │   Realtime) │ │
│  │ • Face ID        │           │             │ │
│  │ • Fall detect    │           │ • Voix      │ │
│  │ • Chess YOLO     │           │ • Outils    │ │
│  │ • Memory         │           │ • Mémoire   │ │
│  └──────────────────┘           └─────────────┘ │
└─────────────────────────────────────────────────┘
```

**Stack :**
- Vision : MediaPipe Pose · InsightFace buffalo_s · YOLO ONNX (chess)
- LLM : OpenAI Realtime API (GPT-4o, VAD + ASR + TTS intégrés)
- Alertes : Telegram Bot · Email SMTP
- Moteur d'échecs : Stockfish (ARM natif)
- Tout tourne sur Pi 4 — aucun cloud pour la vision, latence < 500ms

---

## Structure du projet

```
reachy_care/
│
├── main.py                    # Orchestrateur — boucle vision + bridge
├── config.py                  # Tous les paramètres
├── conv_app_bridge.py         # Client IPC → conv_app (HTTP :8766)
├── patch_source.py            # Patch chirurgical de reachy_mini_conversation_app
│
├── modules/
│   ├── face_recognizer.py     # InsightFace buffalo_s
│   ├── fall_detector.py       # MediaPipe Pose (Algo A ratio + Algo B ghost)
│   ├── chess_detector.py      # YOLO ONNX détection pièces
│   ├── chess_engine.py        # Interface Stockfish
│   ├── memory_manager.py      # Mémoire persistante par personne
│   ├── mode_manager.py        # Gestion modes (normal/histoire/échecs/exposé)
│   └── tts.py                 # Text-to-speech local (espeak-ng)
│
├── tools_for_conv_app/        # Outils appelables par le LLM
│   ├── switch_mode.py         # Changer de mode
│   ├── gutenberg.py           # Lire un livre (avec position mémorisée)
│   ├── enroll_face.py         # Enrôler un visage
│   ├── report_wellbeing.py    # Retour check-in chute
│   └── session_memory.py      # Mémoire de session incrémentale
│
├── external_profiles/
│   └── reachy_care/
│       ├── instructions.txt           # System prompt principal
│       ├── instructions_histoire.txt  # Mode lecture
│       ├── instructions_echecs.txt    # Mode échecs
│       └── tools.txt                  # Outils actifs
│
└── cmd.sh                     # Menu déploiement (rsync + patch + lancement)
```

---

## Matériel

| Composant | Détail |
|---|---|
| Robot | Reachy Mini Wireless — Pollen Robotics |
| Caméra | Intégrée 1280×720 |
| CPU | ARM Cortex-A72 (Pi 4 class) |
| Réseau | WiFi local — aucun port ouvert |

---

## Vie privée

- La vision (détection de chute, reconnaissance faciale) est **100% locale** — aucune image ne quitte le Pi
- Seule la voix est transmise à OpenAI (API Realtime) pour la conversation
- Les données de mémoire (noms, résumés de conversation) sont stockées localement sur le Pi
- Le code source est privé

---

## Statut

🟢 **Phase 1 en cours** — Vision + LLM + outils fonctionnels, test en conditions réelles
🔶 Calibration détection de chute · Wake word custom · VAD ambiant
⬜ Phase 2 — Suivi médicaments · Mode nuit · Rapport quotidien famille

---

*Projet personnel, non affilié à Pollen Robotics ni à OpenAI.*
