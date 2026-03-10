"""
gutenberg.py — Outil de récupération de textes Project Gutenberg.

Utilise l'API Gutendex (gutendex.com) — libre, sans clé API.
Retourne un extrait de texte brut pour le mode lecture.
"""

import asyncio
import logging
from typing import Any

import requests

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

_GUTENDEX_URL = "https://gutendex.com/books/"
_GUTENBERG_TEXT_URL = "https://www.gutenberg.org/files/{id}/{id}-0.txt"
_DEFAULT_MAX_CHARS = 1500
# Skip l'en-tête boilerplate Gutenberg (environ 500 chars)
_HEADER_SKIP = 500


class GutenbergFetch(Tool):
    """Récupère un extrait d'un livre du domaine public depuis Project Gutenberg."""

    name = "gutenberg"
    description = (
        "Récupère un extrait d'un livre du domaine public depuis Project Gutenberg. "
        "Utilise pour le mode lecture. Cherche par auteur ou titre en français."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Auteur ou titre à chercher. Exemple : 'La Fontaine fables', 'Perrault contes'.",
            },
            "book_id": {
                "type": "integer",
                "description": "ID Gutenberg si déjà connu (évite la recherche).",
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Position de départ dans le texte (en caractères). "
                    "Passe la valeur 'next_offset' renvoyée par l'appel précédent pour continuer la lecture."
                ),
            },
            "max_chars": {
                "type": "integer",
                "description": f"Longueur max de l'extrait (défaut : {_DEFAULT_MAX_CHARS}).",
            },
        },
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        book_id: int | None = kwargs.get("book_id")
        offset: int = int(kwargs.get("offset") or _HEADER_SKIP)
        max_chars: int = int(kwargs.get("max_chars") or _DEFAULT_MAX_CHARS)

        def _fetch() -> dict[str, Any]:
            nonlocal book_id

            if not book_id:
                if not query:
                    return {"error": "Précise un auteur ou un titre à chercher."}
                resp = requests.get(
                    _GUTENDEX_URL,
                    params={"search": query, "languages": "fr"},
                    timeout=10,
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                if not results:
                    return {"error": f"Aucun livre trouvé pour : {query}"}
                book = results[0]
                book_id = book["id"]
                title = book.get("title", "")
                authors = ", ".join(a.get("name", "") for a in book.get("authors", []))
            else:
                title = ""
                authors = ""

            text_url = _GUTENBERG_TEXT_URL.format(id=book_id)
            try:
                text_resp = requests.get(text_url, timeout=15)
                text_resp.raise_for_status()
                raw = text_resp.text
            except Exception:
                # Fallback: essayer l'URL sans le suffixe -0
                text_url_alt = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
                text_resp = requests.get(text_url_alt, timeout=15)
                text_resp.raise_for_status()
                raw = text_resp.text

            start = max(offset, _HEADER_SKIP)
            excerpt = raw[start : start + max_chars]
            return {
                "book_id": book_id,
                "title": title,
                "authors": authors,
                "excerpt": excerpt,
                "offset_used": start,
                "next_offset": start + len(excerpt),
                "end_of_book": (start + max_chars) >= len(raw),
            }

        try:
            result = await asyncio.get_running_loop().run_in_executor(None, _fetch)
            if "error" not in result:
                logger.info(
                    "gutenberg: livre %d récupéré (%d chars).",
                    result["book_id"],
                    len(result.get("excerpt", "")),
                )
            return result
        except requests.Timeout:
            return {"error": "La récupération du livre a pris trop de temps."}
        except requests.HTTPError as exc:
            return {"error": f"Erreur HTTP {exc.response.status_code} pour le livre."}
        except Exception as exc:
            logger.error("gutenberg: erreur : %s", exc)
            return {"error": "Impossible de récupérer le livre."}
