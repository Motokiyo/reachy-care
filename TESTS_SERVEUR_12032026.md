# Tests à valider — Claude Serveur
## Session 12/03/2026

> Ce document est pour Claude Serveur sur le Pi.
> Valide les corrections codées cette nuit. Remonte les résultats dans un fichier `RAPPORT_SERVEUR_12032026.md`.

---

## Déploiement avant les tests

```bash
# Depuis le Mac
bash /Users/alexandre/Galaad-Motokiyo-Ferran/reachy_care/cmd.sh
# → option 2 (lancer sans repatcher — NE PAS faire option 1)
```

Vérifier que le déploiement inclut bien les fichiers modifiés :
- `main.py`
- `config.py`
- `modules/fall_detector.py`
- `modules/sound_detector.py`
- `conv_app_bridge.py`
- `tools_for_conv_app/gutenberg.py`

---

## 1. Double instance PID — Test #1

**Objectif :** Vérifier que lancer deux fois `main.py` ne crée pas de conflit moteurs.

**Procédure :**
```bash
# Terminal 1 — lancer main.py
/venvs/apps_venv/bin/python /home/pollen/reachy_care/main.py &

# Terminal 2 — relancer immédiatement
/venvs/apps_venv/bin/python /home/pollen/reachy_care/main.py
```

**Résultat attendu :**
```
ERROR: main.py déjà en cours (PID XXXXX) — arrêt immédiat pour éviter les conflits.
```
Le deuxième process doit s'arrêter instantanément (exit code 1). Pas de vibrations moteurs.

**À remonter :** log exact de la deuxième instance, exit code.

---

## 2. Telegram — Test #2

**Objectif :** Vérifier que les alertes Telegram arrivent sur le téléphone.

**Procédure :** Simuler une chute (Algo B : rester hors champ caméra > 5s après avoir été vu). Quand Reachy fait le check-in et que tu ne réponds pas pendant 45s → escalade → Telegram.

**Alternative rapide :** Dans un shell Python sur le Pi :
```bash
/venvs/apps_venv/bin/python3 -c "
import sys; sys.path.insert(0, '/home/pollen/reachy_care')
import config, requests
resp = requests.post(
    f'https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage',
    json={'chat_id': config.TELEGRAM_CHAT_ID, 'text': 'Test Telegram Reachy Care — 12/03/2026', 'parse_mode': 'Markdown'},
    timeout=10,
)
print(resp.status_code, resp.text)
"
```

**Résultat attendu :** `200` + message reçu sur le téléphone d'Alexandre.

**À remonter :** status code, texte reçu (ou erreur).

---

## 3. Algo A désactivé — Test #3

**Objectif :** Vérifier que l'Algo A ne génère plus de faux positifs.

**Procédure :** S'asseoir par terre devant Reachy (posture horizontale). Rester immobile 10 secondes. Répéter 3 fois.

**Résultat attendu :** Aucun check-in chute déclenché. Dans les logs :
```
# PAS de ligne comme :
# WARNING: Suspicion de chute — check-in LLM déclenché
```
L'Algo A est désactivé — `is_fallen()` retourne False quand le squelette est visible.

**À remonter :** Confirmer absence de faux positifs. Si check-in déclenché malgré tout → coller le log.

---

## 4. Algo B (ghost trigger) — Test #4

**Objectif :** Confirmer qu'Algo B fonctionne toujours après la refactorisation.

**Procédure :**
1. Se placer devant la caméra (Reachy doit te voir — squelette détecté)
2. Sortir brusquement du champ de vision
3. Rester hors champ 5-6 secondes

**Résultat attendu :**
```
WARNING: Suspicion de chute — check-in LLM déclenché
```
Reachy pose la question de check-in.

**Important :** Si Reachy voit le squelette puis ne le voit plus → trigger à 5.0s (pas 2.5s — augmenté pour réduire les faux positifs sur sorties de pièce normales).

**À remonter :** Délai observé entre sortie du champ et check-in, log exact.

---

## 5. Fusion audio+vidéo différée — Test #5

**Objectif :** Valider que le bug de timing est corrigé (impact son AVANT disparition squelette).

**Procédure :**
1. Se placer devant la caméra (squelette visible)
2. Faire un bruit fort et net (claquer des mains fort, frapper une table)
3. Immédiatement après (< 1s), sortir du champ de caméra et rester hors champ

**Résultat attendu dans les logs :**
```
WARNING: Impact sonore mémorisé — surveillance squelette pendant 5s (fusion différée)
WARNING: Fusion différée : squelette absent après impact sonore → check-in
```
Reachy doit déclencher le check-in même si le squelette n'était pas encore absent au moment du son.

**À remonter :** Les deux lignes de log, délai entre impact et check-in, label du son détecté (Thump/Bang/etc.).

---

## 6. Détection de cri (RMS) — Test #6

**Objectif :** Valider que "au secours" / cri fort est détecté PENDANT que Reachy parle.

**Procédure :**
1. Lancer une session conv_app (Reachy doit parler — lui poser une question longue)
2. Pendant que Reachy répond, crier fort "au secours" ou frapper dans les mains très fort
3. Observer si Reachy s'interrompt

**Résultat attendu dans les logs `reachy_care.log` :**
```
WARNING: Cri détecté (RMS) — interruption conv_app + check-in
```
Reachy doit s'interrompre et poser la question de check-in.

**Points de vigilance :**
- Si trop de faux positifs (voix normale déclenche le RMS) → noter le niveau RMS moyen d'une conversation normale. Le seuil actuel est 0.15.
- Si le micro SoundDetector est en conflit avec WakeWord/conv_app → noter l'erreur exacte.
- Cooldown 5s anti-spam : attendre 5s entre deux cris pour tester plusieurs fois.

**À remonter :**
- Cri détecté ou non
- Faux positifs (voix normale détectée comme cri ?)
- Conflit micro PyAudio (error log) ?
- Suggestion de seuil RMS si nécessaire

---

## 7. Check-in perceptible MODE_HISTOIRE — Test #7

**Objectif :** Vérifier que le check-in interrompt bien la lecture en mode histoire.

**Procédure :**
1. Demander à Reachy de lire quelque chose (La Fontaine, etc.)
2. Pendant la lecture, sortir du champ caméra > 5s → trigger Algo B

**Résultat attendu :**
Reachy interrompt la lecture et dit quelque chose du genre "Je m'arrête un instant — tout va bien ?"
(Pas une question anodine qui se fond dans le récit)

**À remonter :** Transcription exacte de ce que Reachy a dit pour le check-in.

---

## 8. Gutenberg / Wikisource — Test #8

**Objectif :** Vérifier que Corneille/Racine/Molière fonctionnent en français.

**Procédure :** Demander à Reachy de lire :
- "Lis-moi Le Cid de Corneille"
- "Lis-moi Tartuffe de Molière"
- "Lis-moi Phèdre de Racine"

**Résultat attendu dans les logs :**
```
INFO: gutenberg: wikisource FR utilisé pour 'le cid'
```
La lecture doit être en français.

**À remonter :** Source utilisée (wikisource ou gutenberg), langue du texte récupéré, erreur le cas échéant.

---

## 9. Reconnexion proactive 55min — Test #9

**Objectif :** Vérifier que le timer de reconnexion est initialisé (test manuel du timer).

**Procédure :** Dans les logs après 55min de session, chercher :
```bash
grep "Session OpenAI Realtime proche" /home/pollen/reachy_care/logs/reachy_care.log
```

**Note :** Ce test ne peut pas être fait en temps réel (55min d'attente). Laisser tourner une session longue et vérifier les logs après.

**À remonter :** Présence ou absence du log de reconnexion proactive après 55min.

---

## 10. YAMNet indices — Vérification #10

**Objectif :** Confirmer que les indices de classes dans `sound_detector.py` sont corrects.

**Procédure :**
```bash
/venvs/apps_venv/bin/python3 -c "
import tflite_runtime.interpreter as tflite
import numpy as np
m = tflite.Interpreter('/home/pollen/reachy_care/models/yamnet.tflite')
m.allocate_tensors()
inp = m.get_input_details()
out = m.get_output_details()
print('Input shape:', inp[0]['shape'])
print('Nb sorties:', len(out))
# Inférence sur silence
audio = np.zeros(15600, dtype=np.float32)
m.set_tensor(inp[0]['index'], audio)
m.invoke()
scores = m.get_tensor(out[0]['index'])
print('Output 0 shape:', scores.shape)
print('Top-5 indices sur silence:', np.argsort(scores[0])[-5:][::-1])
"
```

**À remonter :** `Input shape`, `Output 0 shape`, top-5 indices. Cela permettra de valider ou corriger les indices hardcodés dans `_load_class_names()`.

---

## 11. Wake word — Diagnostic #11

**Objectif :** Identifier les modèles disponibles sur le Pi.

**Procédure :**
```bash
/venvs/apps_venv/bin/python3 -c "
import openwakeword, os
path = openwakeword.MODELS_PATH
print('Chemin modèles:', path)
if os.path.exists(path):
    files = os.listdir(path)
    print('Fichiers:', files)
else:
    print('Dossier introuvable')
"
```

Également :
```bash
ls /home/pollen/reachy_care/models/*.onnx 2>/dev/null || echo "Aucun .onnx dans models/"
ls /home/pollen/reachy_care/models/*.tflite 2>/dev/null || echo "Aucun .tflite dans models/"
```

**À remonter :** Liste complète des fichiers `.onnx` et `.tflite` disponibles (chemin openwakeword + models/). Cela permettra de configurer le bon fallback.

---

## Format du rapport

Créer `/home/pollen/reachy_care/RAPPORT_SERVEUR_12032026.md` avec :

```markdown
# Rapport tests — 12/03/2026

## Test #1 — Double instance PID
**Statut :** ✅ / ❌ / 🔶
**Observation :** ...
**Log :** ...

## Test #2 — Telegram
...
```

Un bloc par test. Pour chaque test :
- **Statut** : ✅ OK / ❌ Échec / 🔶 Partiel / ❓ Non testé
- **Observation** : ce qui s'est passé
- **Log** : copie des lignes de log pertinentes (2-5 lignes max)
- **Suggestion** si quelque chose cloche

---

## Priorité des tests

| Priorité | Tests |
|---|---|
| Faire en premier | #2 (Telegram), #3 (Algo A), #4 (Algo B), #1 (PID) |
| Faire ensuite | #5 (fusion différée), #6 (cri RMS), #7 (check-in histoire) |
| Si le temps le permet | #8 (Gutenberg), #10 (YAMNet indices), #11 (wake word) |
| Long terme | #9 (reconnexion 55min — session longue) |
