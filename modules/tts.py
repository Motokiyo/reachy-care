"""
tts.py — Wrapper TTS léger pour espeak-ng avec fallback pyttsx3.

Priorité des backends :
  1. espeak-ng  (subprocess, non-bloquant par défaut)
  2. pyttsx3    (si espeak-ng absent)
  3. print()    (mode dégradé silencieux, aucune exception levée)

Usage :
    tts = TTSEngine(voice="fr", speed=140)
    tts.say("Bonjour !")
    tts.say("Attention !", blocking=True)
    tts.stop()
"""

import subprocess
import shutil


class TTSEngine:
    """Moteur TTS abstrait avec trois niveaux de dégradation."""

    MAX_TEXT_LENGTH = 200

    def __init__(self, voice: str = "fr", speed: int = 140, amplitude: int = 200, backend: str = "espeak"):
        """
        Paramètres
        ----------
        voice   : code langue/voix espeak-ng (ex. "fr", "en", "fr+f3")
        speed   : vitesse en mots/min (espeak-ng -s)
        backend : ignoré — le backend est résolu automatiquement selon disponibilité
        """
        self.voice = voice
        self.speed = speed
        self.amplitude = amplitude
        self._process: subprocess.Popen | None = None
        self._backend = self._resolve_backend()

    def _resolve_backend(self) -> str:
        if shutil.which("espeak-ng"):
            return "espeak"
        try:
            import pyttsx3  # noqa: F401
            return "pyttsx3"
        except ImportError:
            pass
        return "print"

    def say(self, text: str, blocking: bool = False) -> None:
        """
        Synthétise `text` (tronqué à MAX_TEXT_LENGTH caractères).

        Paramètres
        ----------
        text     : texte à prononcer
        blocking : si True, attend la fin de la synthèse avant de rendre la main
        """
        if not text:
            return

        text = text[:self.MAX_TEXT_LENGTH]

        if self._backend == "espeak":
            self._say_espeak(text, blocking)
        elif self._backend == "pyttsx3":
            self._say_pyttsx3(text)
        else:
            print(f"[TTS] {text}")

    def stop(self) -> None:
        """Interrompt la synthèse espeak-ng en cours (sans effet si bloquant)."""
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def is_speaking(self) -> bool:
        """Retourne True si une synthèse non-bloquante est en cours."""
        return self._process is not None and self._process.poll() is None

    def _say_espeak(self, text: str, blocking: bool) -> None:
        self.stop()
        cmd = ["espeak-ng", "-v", self.voice, "-s", str(self.speed), "-a", str(self.amplitude), text]
        if blocking:
            subprocess.run(cmd, check=False)
        else:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _say_pyttsx3(self, text: str) -> None:
        """pyttsx3 est toujours bloquant dans ce wrapper."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", self.speed)
            for voice in engine.getProperty("voices"):
                voice_id = (voice.id or "").lower()
                voice_name = (voice.name or "").lower()
                if self.voice in voice_id or self.voice in voice_name:
                    engine.setProperty("voice", voice.id)
                    break
            engine.say(text)
            engine.runAndWait()
        except Exception:
            print(f"[TTS] {text}")
