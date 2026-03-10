#!/usr/bin/env python3
"""Fix du patch conv_app — injecte le task asyncio au bon endroit."""
path = "/venvs/apps_venv/lib/python3.12/site-packages/reachy_mini_conversation_app/openai_realtime.py"
txt = open(path).read()

if "reachy-care-events" in txt:
    print("Déjà patché ✅")
    exit(0)

marker = "            self.connection = conn"
if marker not in txt:
    print(f"❌ Marqueur introuvable dans {path}")
    exit(1)

injection = (
    "            self.connection = conn\n"
    "            self._asyncio_loop = asyncio.get_event_loop()\n"
    "            asyncio.create_task(self._process_external_events(), name='reachy-care-events')\n"
)
open(path, "w").write(txt.replace(marker, injection, 1))
print("Patch OK ✅ — asyncio task injectée après self.connection = conn")
