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

# Fallback Wikisource FR pour les classiques absents de Gutenberg en français
# Corneille, Racine, Molière, Hugo, etc. : Gutenberg n'a que les traductions anglaises
_WIKISOURCE_FR_FALLBACK = {
    "le cid": "https://fr.wikisource.org/w/api.php?action=query&titles=Le_Cid_(Corneille)&prop=revisions&rvprop=content&rvslots=main&format=json",
    "phèdre": "https://fr.wikisource.org/w/api.php?action=query&titles=Ph%C3%A8dre_(Racine)&prop=revisions&rvprop=content&rvslots=main&format=json",
    "tartuffe": "https://fr.wikisource.org/w/api.php?action=query&titles=Le_Tartuffe&prop=revisions&rvprop=content&rvslots=main&format=json",
    "les misérables": "https://fr.wikisource.org/w/api.php?action=query&titles=Les_Mis%C3%A9rables&prop=revisions&rvprop=content&rvslots=main&format=json",
    "andromaque": "https://fr.wikisource.org/w/api.php?action=query&titles=Andromaque&prop=revisions&rvprop=content&rvslots=main&format=json",
    "britannicus": "https://fr.wikisource.org/w/api.php?action=query&titles=Britannicus&prop=revisions&rvprop=content&rvslots=main&format=json",
    "horace": "https://fr.wikisource.org/w/api.php?action=query&titles=Horace_(Corneille)&prop=revisions&rvprop=content&rvslots=main&format=json",
    "l'avare": "https://fr.wikisource.org/w/api.php?action=query&titles=L%27Avare&prop=revisions&rvprop=content&rvslots=main&format=json",
    "le bourgeois gentilhomme": "https://fr.wikisource.org/w/api.php?action=query&titles=Le_Bourgeois_gentilhomme&prop=revisions&rvprop=content&rvslots=main&format=json",
    "les femmes savantes": "https://fr.wikisource.org/w/api.php?action=query&titles=Les_Femmes_savantes&prop=revisions&rvprop=content&rvslots=main&format=json",
    "notre-dame de paris": "https://fr.wikisource.org/w/api.php?action=query&titles=Notre-Dame_de_Paris&prop=revisions&rvprop=content&rvslots=main&format=json",
    "cyrano de bergerac": "https://fr.wikisource.org/w/api.php?action=query&titles=Cyrano_de_Bergerac_(Rostand)&prop=revisions&rvprop=content&rvslots=main&format=json",
}

# Auteurs classiques français dont les œuvres sont mieux sur Wikisource
_FR_CLASSIC_AUTHORS = {
    "corneille", "racine", "molière", "moliere", "rostand", "musset",
}


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

        def _fetch_wikisource(api_url: str, max_chars: int, offset: int) -> dict[str, Any] | None:
            """Récupère un extrait depuis l'API Wikisource FR. Retourne None si échec."""
            try:
                resp = requests.get(api_url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                pages = data.get("query", {}).get("pages", {})
                page = next(iter(pages.values()))
                if "missing" in page:
                    return None
                wikitext = page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
                if not wikitext:
                    return None
                # Nettoyer le wikitext basiquement (supprimer les balises wiki)
                import re
                text = re.sub(r"\{\{[^}]*\}\}", "", wikitext)   # templates
                text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)  # liens wiki
                text = re.sub(r"<[^>]+>", "", text)             # balises HTML
                text = re.sub(r"={2,}[^=]+=*", "", text)        # titres de section
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
                start = max(offset, 0)
                excerpt = text[start : start + max_chars]
                return {
                    "book_id": None,
                    "title": page.get("title", ""),
                    "authors": "",
                    "excerpt": excerpt,
                    "offset_used": start,
                    "next_offset": start + len(excerpt),
                    "end_of_book": (start + max_chars) >= len(text),
                    "source": "wikisource_fr",
                }
            except Exception as exc:
                logger.debug("gutenberg: wikisource fallback échoué : %s", exc)
                return None

        def _fetch() -> dict[str, Any]:
            nonlocal book_id

            title = ""
            authors = ""

            if not book_id:
                if not query:
                    return {"error": "Précise un auteur ou un titre à chercher."}

                query_lower = query.lower()

                # 1. Titre exact dans le fallback Wikisource FR ?
                wikisource_url = _WIKISOURCE_FR_FALLBACK.get(query_lower)
                if wikisource_url is None:
                    for title_key, url in _WIKISOURCE_FR_FALLBACK.items():
                        if title_key in query_lower:
                            wikisource_url = url
                            break

                if wikisource_url:
                    result = _fetch_wikisource(wikisource_url, max_chars, offset)
                    if result:
                        logger.info("gutenberg: wikisource FR utilisé pour '%s'.", query)
                        return result
                    # Wikisource a échoué → continuer vers Gutenberg

                # 2. Auteur classique FR → forcer filtre langue=fr sur Gutendex
                is_classic_fr = any(a in query_lower for a in _FR_CLASSIC_AUTHORS)
                if is_classic_fr and not book_id:
                    resp = requests.get(
                        _GUTENDEX_URL,
                        params={"search": query, "languages": "fr"},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    results = resp.json().get("results", [])
                    if results:
                        book = results[0]
                        book_id = book["id"]
                        title = book.get("title", "")
                        authors = ", ".join(a.get("name", "") for a in book.get("authors", []))
                    else:
                        return {"error": f"Aucun livre trouvé en français pour : {query}. Essayez un titre exact (ex: 'Le Cid', 'Tartuffe')."}

                # 3. Recherche Gutendex normale
                if not book_id:
                    resp = requests.get(
                        _GUTENDEX_URL,
                        params={"search": query},
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
