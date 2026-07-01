"""Normalizacion de entidades + allowlist tipos — .

Modulo de CONFIG/REGLAS puro (separacion adv-code 2026-05-09):
- gliner_service.py = ejecucion del pipeline ML.
- entity_normalization.py = config/reglas (este modulo).

Funciones puras, unit-testeables sin dependencias ML.
"""
from __future__ import annotations

import unicodedata
from typing import Literal


# Allowlist de entity_type permitidos en el sistema EcoDB.
# Entity type allowlist (6 categories):
# - 6 categorias que GLiNER puede clasificar decentemente Y aportan valor unico
#   al grafo. Graph includes: person, organization, location, technology, product, project.
# - producto = software/herramientas de terceros (FastAPI, GLiNER, Jina v4).
# - proyecto = projects and platforms (e.g. EcoDB).
# - organizacion = companies and organizations (e.g. Anthropic) — even if they
#   construimos por dentro, son entidades empresariales con NIF.
EntityType = Literal[
    "persona",
    "agente_ia",
    "organizacion",
    "lugar",
    "producto",
    "proyecto",
    "tecnologia",
    "concepto",
    "evento",
    "artefacto",
    "modelo_ia",
    "metodologia",
]

ALLOWED_ENTITY_TYPES: frozenset[str] = frozenset({
    "persona",
    "agente_ia",
    "organizacion",
    "lugar",
    "producto",
    "proyecto",
    "tecnologia",
    "concepto",
    "evento",
    "artefacto",
    "modelo_ia",
    "metodologia",
})


def normalize_name(name: str) -> str:
    """Normaliza un nombre para lookup: lower + NFKD strip + .strip().

    Reglas :
    - lower() for case-insensitive lookup.
    - NFKD decomposes accents ("Café" → "Cafe").
    - Mn (Mark, Nonspacing) se elimina para que "Año" → "ano", "España" → "Espana".
    - .strip() final por seguridad.

    Esta funcion la llaman dos consumidores:
    1. La columna `entity_dictionary.name_normalized` se precomputa con esto al
       INSERT/PUT (matiz coord: PUT recompute si cambia name).
    2. El texto del usuario se normaliza igual antes del lookup (matching
       case-insensitive + accent-insensitive).

    NO normaliza homoglyphs cross-script (Cirilico "Р" vs Latin "P") — adv-seg
    deuda multi-tenant registrada.
    """
    if not name:
        return ""
    # NFKD descompone los caracteres con tilde en (caracter base + diacritico).
    decomposed = unicodedata.normalize("NFKD", name)
    # Eliminamos los diacriticos (categoria 'Mn' = Mark, Nonspacing).
    no_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return no_accents.lower().strip()


def is_valid_entity_type(entity_type: str) -> bool:
    """True si el tipo esta en la allowlist EntityType.

    Usado por endpoints REST /admin/entity-dictionary para rechazar typos
    como "persoana" con 422 (matiz adv-code 2026-05-09).
    """
    return entity_type in ALLOWED_ENTITY_TYPES
