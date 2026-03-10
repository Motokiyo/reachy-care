"""
gutenberg.py — Récupération de textes du domaine public pour le mode lecture.

Chaîne de sources (par ordre de qualité) :
  1. Wikisource FR   — textes relus, fiables, pour les titres connus
  2. Gallica BnF     — OCR numérisé, catalogue immense (littérature FR 17e-20e)
  3. Project Gutenberg — pour les textes non couverts par les deux sources FR

Aucune clé API requise.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies

logger = logging.getLogger(__name__)

_GUTENDEX_URL        = "https://gutendex.com/books/"
_GUTENBERG_TEXT_URL  = "https://www.gutenberg.org/files/{id}/{id}-0.txt"
_GALLICA_SRU_URL     = "https://gallica.bnf.fr/SRU"
_DEFAULT_MAX_CHARS   = 1500
_HEADER_SKIP         = 500   # skip boilerplate Gutenberg (~500 chars)

# Wikisource FR — titres hardcodés pour les pièces classiques (qualité maximale)
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
    "les misérables":           "Les_Mis%C3%A9rables",
    "notre-dame de paris":      "Notre-Dame_de_Paris",
    "cyrano de bergerac":       "Cyrano_de_Bergerac_(Rostand)",
}

# Gallica — auteurs français classiques (couverture exceptionnelle BnF)
_GALLICA_FR_AUTHORS = {
    "molière", "moliere", "racine", "corneille", "hugo", "zola", "flaubert",
    "baudelaire", "maupassant", "balzac", "stendhal", "dumas", "musset",
    "rostand", "la fontaine", "perrault", "voltaire", "rousseau", "sand",
    "verne", "verlaine", "rimbaud", "daudet", "mérimée", "nerval",
}


class GutenbergFetch(Tool):
    """Récupère un extrait d'un livre du domaine public (Wikisource FR / Gallica / Gutenberg)."""

    name = "gutenberg"
    description = (
        "Récupère un extrait d'un livre du domaine public pour le mode lecture. "
        "Cherche d'abord sur Wikisource FR et Gallica (BnF) pour les auteurs français, "
        "puis sur Project Gutenberg pour les autres. Cherche par auteur ou titre."
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
        # Source 1 — Wikisource FR
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
                start = max(offset, 0)
                excerpt = text[start: start + max_chars]
                return {
                    "title": page.get("title", ""),
                    "authors": "",
                    "excerpt": excerpt,
                    "offset_used": start,
                    "next_offset": start + len(excerpt),
                    "end_of_book": (start + max_chars) >= len(text),
                    "source": "wikisource_fr",
                }
            except Exception as exc:
                logger.debug("wikisource: échec pour '%s' : %s", page_title, exc)
                return None

        # ------------------------------------------------------------------
        # Source 2 — Gallica BnF (SRU + /texteBrut)
        # ------------------------------------------------------------------

        def _fetch_gallica(search_query: str) -> dict[str, Any] | None:
            try:
                # Recherche SRU — auteur + monographie + accès libre
                sru_query = (
                    f'(gallica all "{search_query}") '
                    f'and (dc.type all "monographie") '
                    f'and (access all "fayes")'
                )
                resp = requests.get(
                    _GALLICA_SRU_URL,
                    params={
                        "version": "1.2",
                        "operation": "searchRetrieve",
                        "query": sru_query,
                        "maximumRecords": 5,
                        "startRecord": 1,
                    },
                    timeout=12,
                )
                resp.raise_for_status()

                # Parse XML Dublin Core
                root = ET.fromstring(resp.content)
                ns = {
                    "srw": "http://www.loc.gov/zing/srw/",
                    "dc":  "http://purl.org/dc/elements/1.1/",
                }

                ark_url = None
                doc_title = ""
                doc_authors = ""
                for record in root.findall(".//srw:record", ns):
                    data = record.find(".//srw:recordData", ns)
                    if data is None:
                        continue
                    identifier = data.find(".//dc:identifier", ns)
                    if identifier is None or not identifier.text:
                        continue
                    # Garder uniquement les URLs ARK Gallica
                    if "gallica.bnf.fr/ark:" in identifier.text:
                        ark_url = identifier.text.strip()
                        title_el = data.find(".//dc:title", ns)
                        creator_el = data.find(".//dc:creator", ns)
                        if title_el is not None:
                            doc_title = title_el.text or ""
                        if creator_el is not None:
                            doc_authors = creator_el.text or ""
                        break

                if not ark_url:
                    logger.debug("gallica: aucun résultat pour '%s'", search_query)
                    return None

                # Récupérer le texte brut OCR
                text_resp = requests.get(f"{ark_url}/texteBrut", timeout=20)
                text_resp.raise_for_status()
                text_resp.encoding = "utf-8"

                # Nettoyer le HTML léger retourné par Gallica
                raw = text_resp.text
                text = re.sub(r"<[^>]+>", " ", raw)        # balises HTML
                text = re.sub(r"&[a-z]+;", " ", text)       # entités HTML
                text = re.sub(r"\s{2,}", " ", text)
                text = re.sub(r"\n{3,}", "\n\n", text).strip()

                if len(text) < 200:
                    logger.debug("gallica: texte trop court pour '%s'", search_query)
                    return None

                start = max(offset, 0)
                excerpt = text[start: start + max_chars]
                logger.info("gallica: '%s' récupéré depuis %s", search_query, ark_url)
                return {
                    "title": doc_title,
                    "authors": doc_authors,
                    "excerpt": excerpt,
                    "offset_used": start,
                    "next_offset": start + len(excerpt),
                    "end_of_book": (start + max_chars) >= len(text),
                    "source": "gallica_bnf",
                    "ark_url": ark_url,
                }
            except Exception as exc:
                logger.debug("gallica: échec pour '%s' : %s", search_query, exc)
                return None

        # ------------------------------------------------------------------
        # Source 3 — Gutenberg (Gutendex + texte brut)
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
            return {
                "book_id": book_id,
                "title": title,
                "authors": authors,
                "excerpt": excerpt,
                "offset_used": start,
                "next_offset": start + len(excerpt),
                "end_of_book": (start + max_chars) >= len(raw),
                "source": "gutenberg",
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

            # 1. Wikisource FR — titre exact ou partiel dans le dictionnaire
            for key, page_title in _WIKISOURCE_FR.items():
                if key in query_lower:
                    result = _fetch_wikisource(page_title)
                    if result:
                        return result
                    break  # Si Wikisource échoue, continuer vers Gallica

            # 2. Gallica BnF — auteur français classique ou requête quelconque FR
            is_fr_author = any(a in query_lower for a in _GALLICA_FR_AUTHORS)
            if is_fr_author:
                result = _fetch_gallica(query)
                if result:
                    return result

            # 3. Gutenberg — filtre langue FR si auteur classique connu
            result = _fetch_gutenberg(query, lang_filter="fr" if is_fr_author else None)
            if result:
                return result

            # 4. Gutenberg sans filtre langue (dernier recours)
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
