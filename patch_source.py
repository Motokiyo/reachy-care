#!/usr/bin/env python3
"""
patch_source.py — Patche le clone git de reachy_mini_conversation_app.

Cible : /home/pollen/reachy_mini_conversation_app/src/reachy_mini_conversation_app/
- openai_realtime.py : injecte _external_events, _asyncio_loop, asyncio task, méthodes bridge
- main.py            : enregistre le bridge après instanciation du handler
"""

import subprocess
import sys

CONV_APP_DIR = "/home/pollen/reachy_mini_conversation_app/src/reachy_mini_conversation_app"
REALTIME_PATH = f"{CONV_APP_DIR}/openai_realtime.py"
MAIN_PATH = f"{CONV_APP_DIR}/main.py"
MARKER_ALREADY_PATCHED = "reachy-care-events"

# ---------------------------------------------------------------------------
# Patch openai_realtime.py
# ---------------------------------------------------------------------------

REALTIME_INIT_MARKER = "        self.deps = deps"
REALTIME_INIT_INJECTION = """        self.deps = deps
        # [Reachy Care] bridge
        self._external_events: asyncio.Queue = asyncio.Queue()
        self._asyncio_loop = None"""

REALTIME_CONN_MARKER = "            self.connection = conn"
REALTIME_CONN_INJECTION = """            self.connection = conn
            # [Reachy Care] bridge — capture loop + IPC HTTP server
            self._asyncio_loop = asyncio.get_event_loop()
            asyncio.create_task(self._process_external_events(), name='reachy-care-events')
            self._start_reachy_care_server()
            # [Reachy Care] VAD — threshold élevé pour filtrer TV/conversations ambiantes
            asyncio.create_task(self.connection.session.update(session={
                "turn_detection": {
                    "type": "server_vad",
                    "silence_duration_ms": 1500,
                    "threshold": 0.7,
                    "interrupt_response": True,
                }
            }), name='reachy-care-vad')"""

REALTIME_METHODS = '''
    # ------------------------------------------------------------------
    # [Reachy Care] bridge — external event injection
    # ------------------------------------------------------------------

    async def _process_external_events(self) -> None:
        """Consomme la queue d\'événements externes et les injecte dans la session."""
        while True:
            text, instructions = await self._external_events.get()
            try:
                await self.connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    }
                )
                await self.connection.response.create(
                    response={"instructions": instructions}
                )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "[Reachy Care] Injection événement échouée : %s", exc
                )
            finally:
                self._external_events.task_done()

    async def schedule_external_event(self, text: str, response_instructions: str) -> None:
        """Planifie un événement externe depuis un thread synchrone."""
        await self._external_events.put((text, response_instructions))

    async def schedule_session_update(self, new_instructions: str) -> None:
        """Met à jour les instructions de session OpenAI Realtime en runtime."""
        import logging as _logging
        _log = _logging.getLogger(__name__)
        if not getattr(self, "connection", None):
            _log.warning("[Reachy Care] schedule_session_update: pas de connexion, ignoré.")
            return
        is_lecture = "MODE ACTIF : HISTOIRE" in new_instructions or "MODE LECTURE" in new_instructions
        max_tokens = "inf" if is_lecture else 4096
        turn_detection = {
            "type": "server_vad",
            "silence_duration_ms": 3000 if is_lecture else 1200,
            "threshold": 0.7 if is_lecture else 0.5,
            "interrupt_response": not is_lecture,
        }
        try:
            await self.connection.session.update(
                session={
                    "instructions": new_instructions,
                    "max_response_output_tokens": max_tokens,
                    "turn_detection": turn_detection,
                }
            )
            _log.info(
                "[Reachy Care] Session update : %d chars, max_tokens=%s, vad_silence=%dms.",
                len(new_instructions), max_tokens, turn_detection["silence_duration_ms"],
            )
        except Exception as exc:
            _log.error("[Reachy Care] Erreur session.update : %s", exc)

    def _start_reachy_care_server(self) -> None:
        """Démarre le serveur HTTP IPC Reachy Care sur localhost:8766."""
        import threading as _threading
        import json as _json
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import asyncio as _asyncio
        import logging as _logging
        import time as _time
        import sys as _sys
        _log = _logging.getLogger(__name__)
        _PORT = 8766
        _self = self
        _loop = self._asyncio_loop
        # Stocke le handler au niveau module pour accès direct depuis switch_mode.py
        _sys.modules[__name__]._reachy_care_handler = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self_h):
                try:
                    length = int(self_h.headers.get("Content-Length", 0))
                    body = _json.loads(self_h.rfile.read(length)) if length else {}
                    path = self_h.path

                    if path == "/event":
                        _asyncio.run_coroutine_threadsafe(
                            _self.schedule_external_event(body["text"], body["instructions"]),
                            _loop,
                        )
                    elif path == "/session_update":
                        _asyncio.run_coroutine_threadsafe(
                            _self.schedule_session_update(body["instructions"]),
                            _loop,
                        )
                    elif path == "/wake":
                        # Réinitialise l\'état idle sans injecter de message
                        if hasattr(_self, "last_activity_time"):
                            _self.last_activity_time = _time.time()
                        if hasattr(_self, "is_idle_tool_call"):
                            _self.is_idle_tool_call = False

                    self_h.send_response(200)
                except Exception as exc:
                    _log.error("[Reachy Care] IPC handler error: %s", exc)
                    self_h.send_response(500)
                finally:
                    self_h.end_headers()

            def log_message(self_h, *args):
                pass  # Silence HTTP logs

        def _serve():
            try:
                srv = HTTPServer(("127.0.0.1", _PORT), _Handler)
                _log.info("[Reachy Care] Serveur IPC HTTP démarré sur localhost:%d ✅", _PORT)
                srv.serve_forever()
            except Exception as exc:
                _log.error("[Reachy Care] Serveur IPC échec : %s", exc)

        t = _threading.Thread(target=_serve, name="reachy-care-ipc", daemon=True)
        t.start()
'''

# ---------------------------------------------------------------------------
# Patch moves.py — backoff sur connexion gRPC perdue (évite saturation CPU)
# ---------------------------------------------------------------------------

MOVES_PATH = f"{CONV_APP_DIR}/moves.py"
MOVES_MARKER = 'logger.error(f"Failed to set robot target: {e}"'
MOVES_INJECTION = '''import time as _time
        _now = _time.monotonic()
        if not hasattr(self, "_last_grpc_error_t") or _now - self._last_grpc_error_t > 1.0:
            logger.error(f"Failed to set robot target: {e}")
            self._last_grpc_error_t = _now'''

# ---------------------------------------------------------------------------
# Patch openai_realtime.py — idle signal adapté personnes âgées
# ---------------------------------------------------------------------------

# Idle message — remplace le message créatif par un message calme et attentif
REALTIME_IDLE_MSG_MARKER = "You've been idle for a while. Feel free to get creative - dance, show an emotion, look around, do nothing, or just be yourself!"
REALTIME_IDLE_MSG_INJECTION = "[Idle update] No activity for {idle_duration:.0f}s. Stay attentive and ready to respond."

# Idle instructions — calmes, orientées soin
REALTIME_IDLE_INSTR_MARKER = "You MUST respond with function calls only - no speech or text. Choose appropriate actions for idle behavior."
REALTIME_IDLE_INSTR_INJECTION = "You MUST respond with function calls only - no speech. Prefer do_nothing or head_tracking. Stay calm and ready."

# Idle timeout — 15 s → 60 s
REALTIME_IDLE_TIMEOUT_MARKER = "if idle_duration > 15.0"
REALTIME_IDLE_TIMEOUT_INJECTION = "if idle_duration > 60.0"

def patch_file(path: str, patches: list[tuple[str, str]], methods_append: str = "") -> None:
    with open(path, encoding="utf-8") as f:
        txt = f.read()

    if MARKER_ALREADY_PATCHED in txt:
        print(f"  Déjà patché : {path}")
        return

    # Backup
    with open(path + ".bak", "w", encoding="utf-8") as f:
        f.write(txt)

    for marker, injection in patches:
        if marker not in txt:
            print(f"  ⚠ Marqueur introuvable : {repr(marker[:60])}")
            continue
        txt = txt.replace(marker, injection, 1)
        print(f"  Patch appliqué : {repr(marker[:60])}")

    if methods_append:
        txt = txt.rstrip() + "\n" + methods_append + "\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    print(f"  Fichier mis à jour : {path}")


print("=" * 60)
print("  patch_source.py — Reachy Care bridge injection")
print("=" * 60)

print("\n[1/3] Patch openai_realtime.py …")
patch_file(
    REALTIME_PATH,
    [
        (REALTIME_INIT_MARKER, REALTIME_INIT_INJECTION),
        (REALTIME_CONN_MARKER, REALTIME_CONN_INJECTION),
        (REALTIME_IDLE_MSG_MARKER, REALTIME_IDLE_MSG_INJECTION),
        (REALTIME_IDLE_INSTR_MARKER, REALTIME_IDLE_INSTR_INJECTION),
        (REALTIME_IDLE_TIMEOUT_MARKER, REALTIME_IDLE_TIMEOUT_INJECTION),
    ],
    methods_append=REALTIME_METHODS,
)

print("\n[2/3] Patch moves.py — backoff gRPC …")
patch_file(
    MOVES_PATH,
    [(MOVES_MARKER, MOVES_INJECTION)],
)
print("  (marqueur introuvable = version moves.py différente — non bloquant)")

print("\n[3/3] Réinstallation en mode editable (pip install -e) …")
result = subprocess.run(
    [sys.executable, "-m", "pip", "install", "-e", "/home/pollen/reachy_mini_conversation_app/"],
    capture_output=True, text=True,
)
if result.returncode == 0:
    print("  ✅ Paquet réinstallé en mode editable — le patch est actif.")
else:
    print("  ⚠ Échec réinstallation editable :")
    print(result.stderr[-500:])

print("\n✅ Patch terminé.")
