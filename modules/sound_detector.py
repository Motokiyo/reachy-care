"""
sound_detector.py — Détection audio d'impact (chute) via YAMNet TFLite.

Tourne dans un thread daemon séparé. Appelle `on_impact(label, score)` quand un son
suspect est détecté (Thump/thud, Bang, Crash, Slam).

Dépendances :
    pip install tflite-runtime  # ou tensorflow-lite sur Pi
    pip install pyaudio         # déjà installé via openwakeword
"""

import contextlib
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Labels YAMNet qui indiquent une possible chute
_IMPACT_LABELS = {"Thump, thud", "Bang", "Crash", "Slam", "Knock"}

# Paramètres audio
_SAMPLE_RATE = 16000
_WINDOW_SAMPLES = 15600   # 975ms — taille fenêtre YAMNet (15600 échantillons @ 16kHz)
_HOP_SAMPLES = 8000       # 500ms entre fenêtres

# Détection de cri par RMS (indépendant de YAMNet — fonctionne pendant lecture Reachy)
_CRY_RMS_THRESHOLD = 0.15  # RMS > 0.15 sur 500ms = son fort (cri, appel à l'aide)


class SoundDetector:
    """Détecteur audio d'impact via YAMNet TFLite.

    Usage :
        det = SoundDetector(
            model_path="/home/pollen/reachy_care/models/yamnet.tflite",
            on_impact=lambda label, score: print(f"Impact : {label} ({score:.2f})"),
            threshold=0.30,
        )
        det.start()
        # ... boucle principale ...
        det.stop()
    """

    def __init__(
        self,
        model_path: str,
        on_impact: Callable[[str, float], None],
        threshold: float = 0.30,
        device_index: Optional[int] = None,
        on_cry: Optional[Callable[[], None]] = None,
    ) -> None:
        self._model_path = Path(model_path)
        self._on_impact = on_impact
        self._threshold = threshold
        self._device_index = device_index
        self._on_cry = on_cry
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._interpreter = None
        self._class_names: list[str] = []
        self._available = False

        self._load_model()

    def _load_model(self) -> None:
        """Charge le modèle YAMNet TFLite et la liste des classes."""
        if not self._model_path.exists():
            logger.warning(
                "SoundDetector: modèle introuvable : %s — détection audio désactivée.",
                self._model_path,
            )
            return
        try:
            import tflite_runtime.interpreter as tflite
        except ImportError:
            try:
                import ai_edge_litert.interpreter as tflite
            except ImportError:
                try:
                    from tensorflow.lite.python import interpreter as tflite
                except ImportError:
                    logger.warning(
                        "SoundDetector: tflite_runtime non disponible — détection audio désactivée."
                    )
                    return
        try:
            self._interpreter = tflite.Interpreter(model_path=str(self._model_path))
            self._interpreter.allocate_tensors()
            # Charger la liste des classes YAMNet (521 classes)
            self._class_names = self._load_class_names()
            self._available = True
            logger.info(
                "SoundDetector: modèle YAMNet chargé (%s), %d classes.",
                self._model_path.name,
                len(self._class_names),
            )
        except Exception as exc:
            logger.warning("SoundDetector: chargement modèle échoué : %s", exc)

    def _load_class_names(self) -> list[str]:
        """Retourne les noms de classes YAMNet (ordre fixe, 521 classes)."""
        # Classes YAMNet pertinentes pour la détection de chute
        # Liste complète disponible dans yamnet_class_map.csv (AudioSet)
        # On retourne une liste partielle — l'indice correspond au score YAMNet
        # Pour simplifier, on utilise une liste de 521 éléments vides
        # sauf pour les indices connus des classes d'impact.
        # Source : https://github.com/tensorflow/models/blob/master/research/audioset/yamnet/yamnet_class_map.csv
        names = [""] * 521
        # Indices YAMNet des sons d'impact (AudioSet ontology)
        names[461] = "Thump, thud"
        names[462] = "Thump, thud"   # alias
        names[463] = "Bang"
        names[464] = "Crash"
        names[460] = "Slam"
        names[465] = "Knock"
        names[466] = "Tap"
        names[399] = "Crash"
        names[398] = "Bang"
        return names

    def _run(self) -> None:
        """Thread principal : capture audio et détecte les impacts."""
        try:
            import pyaudio
            import numpy as np
        except ImportError as e:
            logger.warning("SoundDetector: dépendance manquante : %s", e)
            return

        pa = pyaudio.PyAudio()
        stream = None
        buffer = np.zeros(_WINDOW_SAMPLES, dtype=np.float32)

        try:
            stream = pa.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=_SAMPLE_RATE,
                input=True,
                input_device_index=self._device_index,
                frames_per_buffer=_HOP_SAMPLES,
            )
            logger.info("SoundDetector: flux audio ouvert @ %d Hz", _SAMPLE_RATE)

            while not self._stop_event.is_set():
                try:
                    raw = stream.read(_HOP_SAMPLES, exception_on_overflow=False)
                    chunk = np.frombuffer(raw, dtype=np.float32)

                    # Détection de cri par RMS — indépendant de YAMNet
                    # Fonctionne même quand Reachy parle (conv_app VAD aveugle pendant lecture)
                    if self._on_cry is not None:
                        rms = float(np.sqrt(np.mean(chunk ** 2)))
                        if rms >= _CRY_RMS_THRESHOLD:
                            try:
                                self._on_cry()
                            except Exception as cb_exc:
                                logger.debug("SoundDetector: on_cry erreur : %s", cb_exc)

                    # Fenêtre glissante pour YAMNet
                    buffer = np.roll(buffer, -len(chunk))
                    buffer[-len(chunk):] = chunk
                    self._infer(buffer)
                except Exception as exc:
                    logger.debug("SoundDetector: erreur lecture audio : %s", exc)
                    time.sleep(0.05)

        except Exception as exc:
            logger.warning("SoundDetector: erreur ouverture flux audio : %s", exc)
        finally:
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.stop_stream()
                    stream.close()
            pa.terminate()
            logger.info("SoundDetector: flux audio fermé.")

    def _infer(self, waveform) -> None:
        """Lance une inférence YAMNet sur la fenêtre audio."""
        if self._interpreter is None:
            return
        try:
            import numpy as np
            inp = self._interpreter.get_input_details()
            out = self._interpreter.get_output_details()
            self._interpreter.set_tensor(inp[0]["index"], waveform)
            self._interpreter.invoke()
            scores = self._interpreter.get_tensor(out[0]["index"])   # shape (N, 521)
            mean_scores = scores.mean(axis=0)
            for idx, score in enumerate(mean_scores):
                if score >= self._threshold and idx < len(self._class_names):
                    label = self._class_names[idx]
                    if label in _IMPACT_LABELS:
                        logger.warning(
                            "SoundDetector: impact détecté — %s (score=%.2f)", label, score
                        )
                        try:
                            self._on_impact(label, float(score))
                        except Exception as cb_exc:
                            logger.debug("SoundDetector: callback erreur : %s", cb_exc)
                        break   # un seul callback par fenêtre
        except Exception as exc:
            logger.debug("SoundDetector: erreur inférence : %s", exc)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Démarre le thread de détection audio."""
        if not self._available:
            logger.info("SoundDetector: non disponible — thread non démarré.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="sound-detector",
            daemon=True,
        )
        self._thread.start()
        logger.info("SoundDetector: thread démarré.")

    def stop(self) -> None:
        """Arrête le thread de détection audio."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        logger.info("SoundDetector: arrêté.")

    @property
    def available(self) -> bool:
        """True si le modèle a été chargé avec succès."""
        return self._available
