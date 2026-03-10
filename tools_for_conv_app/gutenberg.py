"""
gutenberg.py — Récupération de textes du domaine public pour le mode lecture.

Chaîne de sources (par ordre de qualité) :
  1. Wikisource FR   — textes relus, fiables, pour les pièces de théâtre (pages uniques)
  2. Project Gutenberg — catalogue immense, filtre langue FR pour les auteurs français

Note : Gallica BnF est inaccessible sans navigateur réel (Altcha anti-bot, 403 ou
captcha HTML). Gutenberg couvre très bien la littérature française du domaine public.

Aucune clé API requise.
"""

import asyncio
import logging
import re
from typing import Any

import requests

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

_GUTENDEX_URL       = "https://gutendex.com/books/"
_GUTENBERG_TEXT_URL = "https://www.gutenberg.org/files/{id}/{id}-0.txt"
_DEFAULT_MAX_CHARS  = 4000  # 4000 chars ≈ 3-4min de lecture orale fluide
_HEADER_SKIP        = 500   # skip boilerplate Gutenberg (~500 chars)

# Wikisource FR — pièces de théâtre et textes courts sur une seule page
# (les romans sont sur des sous-pages Wikisource → utiliser Gutenberg à la place)
_WIKISOURCE_FR = {
    "le cid":                   "Le_Cid_(Corneille)",
    "phèdre":                   "Ph%C3%A8dre_(Racine)",
    "tartuffe":                 "Le_Tartuffe",
    "andromaque":               "Andromaque",
    "britannicus":              "Britannicus",
    "horace":                   "Horace_(Corneille)",
    "l'avare":                  "L%27Avare",
    "le bourgeois gentilhomme": "Le_Bourgeois_gentilhomme",
    "les femmes savantes":      "Les_Femmes_savantes",
    "cyrano de bergerac":       "Cyrano_de_Bergerac_(Rostand)",
}

# Auteurs français classiques → recherche Gutenberg avec filtre langue FR
_GUTENBERG_FR_AUTHORS = {
    "molière", "moliere", "racine", "corneille", "hugo", "zola", "flaubert",
    "baudelaire", "maupassant", "balzac", "stendhal", "dumas", "musset",
    "rostand", "la fontaine", "perrault", "voltaire", "rousseau", "sand",
    "verne", "verlaine", "rimbaud", "daudet", "mérimée", "nerval",
}

_WIKISOURCE_HEADERS = {"User-Agent": "ReachyCareReader/1.0 (robot bienveillant)"}


class GutenbergFetch(Tool):
    """Récupère un extrait d'un livre du domaine public (Wikisource FR / Project Gutenberg)."""

    name = "gutenberg"
    description = (
        "Récupère un extrait d'un livre du domaine public pour le mode lecture. "
        "Cherche sur Wikisource FR pour les pièces de théâtre classiques, "
        "puis sur Project Gutenberg (filtre français pour les auteurs FR). "
        "Cherche par auteur ou titre. "
        "Exemples : 'Molière Tartuffe', 'Dumas Les Trois Mousquetaires', 'Verne 20000 lieues'."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Auteur ou titre à chercher. Exemple : 'Molière Tartuffe', 'Hugo Les Misérables', 'La Fontaine fables'.",
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
        query     = (kwargs.get("query") or "").strip()
        book_id: int | None = kwargs.get("book_id")
        offset    = int(kwargs.get("offset") or _HEADER_SKIP)
        max_chars = int(kwargs.get("max_chars") or _DEFAULT_MAX_CHARS)

        # ------------------------------------------------------------------
        # Source 1 — Wikisource FR (pièces de théâtre, textes courts)
        # ------------------------------------------------------------------

        def _fetch_wikisource(page_title: str) -> dict[str, Any] | None:
            try:
                resp = requests.get(
                    "https://fr.wikisource.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": page_title,
                        "prop": "revisions",
                        "rvprop": "content",
                        "rvslots": "main",
                        "format": "json",
                    },
                    headers=_WIKISOURCE_HEADERS,
                    timeout=10,
                )
                resp.raise_for_status()
                pages = resp.json().get("query", {}).get("pages", {})
                page = next(iter(pages.values()))
                if "missing" in page:
                    return None
                wikitext = page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
                if not wikitext:
                    return None
                text = re.sub(r"\{\{[^}]*\}\}", "", wikitext)
                text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
                text = re.sub(r"<[^>]+>", "", text)
                text = re.sub(r"={2,}[^=]+=*", "", text)
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
                # Rejeter les pages TOC (moins de 500 chars = juste une table des matières)
                if len(text) < 500:
                    logger.debug("wikisource: page '%s' trop courte (%d chars) — probablement une TOC", page_title, len(text))
                    return None
                start = max(offset, 0)
                excerpt = text[start: start + max_chars]
                end = (start + max_chars) >= len(text)
                next_off = start + len(excerpt)
                return {
                    "title": page.get("title", ""),
                    "authors": "",
                    "excerpt": excerpt,
                    "offset_used": start,
                    "next_offset": next_off,
                    "end_of_book": end,
                    "source": "wikisource_fr",
                    "continuation_hint": (
                        "FIN DU LIVRE — annonce la fin chaleureusement." if end else
                        f"IMPORTANT : lis ce texte à voix haute IMMÉDIATEMENT, "
                        f"puis appelle gutenberg(offset={next_off}) pour la suite. "
                        f"NE T'ARRÊTE PAS — c'est une boucle de lecture continue."
                    ),
                }
            except Exception as exc:
                logger.debug("wikisource: échec pour '%s' : %s", page_title, exc)
                return None

        # ------------------------------------------------------------------
        # Source 2 — Project Gutenberg (Gutendex + texte brut)
        # ------------------------------------------------------------------

        def _fetch_gutenberg(search_query: str, lang_filter: str | None = None) -> dict[str, Any] | None:
            nonlocal book_id
            try:
                params: dict = {"search": search_query}
                if lang_filter:
                    params["languages"] = lang_filter
                resp = requests.get(_GUTENDEX_URL, params=params, timeout=10)
                resp.raise_for_status()
                results = resp.json().get("results", [])
                if not results:
                    return None
                book = results[0]
                book_id = book["id"]
                title   = book.get("title", "")
                authors = ", ".join(a.get("name", "") for a in book.get("authors", []))
            except Exception as exc:
                logger.debug("gutendex: recherche échouée : %s", exc)
                return None

            try:
                text_resp = requests.get(_GUTENBERG_TEXT_URL.format(id=book_id), timeout=15)
                text_resp.raise_for_status()
                raw = text_resp.text
            except Exception:
                try:
                    alt_url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
                    text_resp = requests.get(alt_url, timeout=15)
                    text_resp.raise_for_status()
                    raw = text_resp.text
                except Exception as exc:
                    logger.debug("gutenberg: texte introuvable pour id=%s : %s", book_id, exc)
                    return None

            start = max(offset, _HEADER_SKIP)
            excerpt = raw[start: start + max_chars]
            end = (start + max_chars) >= len(raw)
            next_off = start + len(excerpt)
            return {
                "book_id": book_id,
                "title": title,
                "authors": authors,
                "excerpt": excerpt,
                "offset_used": start,
                "next_offset": next_off,
                "end_of_book": end,
                "source": "gutenberg",
                "continuation_hint": (
                    "FIN DU LIVRE — annonce la fin chaleureusement." if end else
                    f"IMPORTANT : lis ce texte à voix haute IMMÉDIATEMENT, "
                    f"puis appelle gutenberg(book_id={book_id}, offset={next_off}) pour la suite. "
                    f"NE T'ARRÊTE PAS — c'est une boucle de lecture continue."
                ),
            }

        # ------------------------------------------------------------------
        # Orchestration
        # ------------------------------------------------------------------

        def _fetch() -> dict[str, Any]:
            # Cas direct : book_id fourni → Gutenberg direct
            if book_id:
                result = _fetch_gutenberg(query or "")
                return result or {"error": f"Livre Gutenberg id={book_id} introuvable."}

            if not query:
                return {"error": "Précise un auteur ou un titre à chercher."}

            query_lower = query.lower()

            # 1. Wikisource FR — pièces de théâtre hardcodées (qualité maximale)
            for key, page_title in _WIKISOURCE_FR.items():
                if key in query_lower:
                    result = _fetch_wikisource(page_title)
                    if result:
                        return result
                    break  # Si Wikisource échoue, continuer vers Gutenberg

            # 2. Gutenberg avec filtre langue FR pour les auteurs français classiques
            is_fr_author = any(a in query_lower for a in _GUTENBERG_FR_AUTHORS)
            result = _fetch_gutenberg(query, lang_filter="fr" if is_fr_author else None)
            if result:
                return result

            # 3. Gutenberg sans filtre langue (dernier recours — si auteur FR pas trouvé en FR)
            if is_fr_author:
                result = _fetch_gutenberg(query)
                if result:
                    return result

            return {"error": f"Aucun texte trouvé pour : {query}"}

        try:
            result = await asyncio.get_running_loop().run_in_executor(None, _fetch)
            if "error" not in result:
                logger.info(
                    "gutenberg tool: '%s' récupéré via %s (%d chars).",
                    query,
                    result.get("source", "?"),
                    len(result.get("excerpt", "")),
                )
            return result
        except requests.Timeout:
            return {"error": "La récupération du livre a pris trop de temps."}
        except requests.HTTPError as exc:
            return {"error": f"Erreur HTTP {exc.response.status_code} pour le livre."}
        except Exception as exc:
            logger.error("gutenberg tool: erreur : %s", exc)
            return {"error": "Impossible de récupérer le livre."}
