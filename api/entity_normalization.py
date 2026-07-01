"""KnowTwin entity normalization + type allowlist.

Config/rules module (no ML dependencies). Imported by gliner_service.py.
"""
from __future__ import annotations

import unicodedata
from typing import Literal


# 18-type allowlist: 13 offboarding domain types ∪ 6 GLiNER generic labels.
# Overlap: proyecto (in both sets).
EntityType = Literal[
    # 13 offboarding domain types (Spec §2.6)
    "persona_interna",
    "persona_externa",
    "cliente_cuenta",
    "proveedor",
    "proyecto",
    "sistema_componente",
    "tecnologia",
    "decision_tecnica",
    "riesgo",
    "deuda_tecnica",
    "acuerdo_informal",
    "procedimiento_operativo",
    "fuente_sesion",
    # 6 GLiNER generic labels (DEFAULT_LABELS minus proyecto overlap)
    "persona",
    "organizacion",
    "lugar",
    "producto",
    "agente_ia",
]

ALLOWED_ENTITY_TYPES: frozenset[str] = frozenset({
    "persona_interna",
    "persona_externa",
    "cliente_cuenta",
    "proveedor",
    "proyecto",
    "sistema_componente",
    "tecnologia",
    "decision_tecnica",
    "riesgo",
    "deuda_tecnica",
    "acuerdo_informal",
    "procedimiento_operativo",
    "fuente_sesion",
    "persona",
    "organizacion",
    "lugar",
    "producto",
    "agente_ia",
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
