"""Helpers de permisos compartidos — .

Consolida helpers de cascada CEO/Lead/Worker que vivían dispersos en
memories.py, workspaces.py y projects.py (deuda IC1 acumulada en .2).
Coherencia + única implementación + tests unitarios independientes.

Nuevo en 2.3 además de la consolidación: `visible_project_ids(actor)` que
.

Modelo de roles (desde sesión 2026-05-07 cierre 
- Super (is_super=true): sees and modifies everything.
- CEO (dueño empresa cliente): users.is_ceo=true + organizations.ceo_user_id.
- Admin/Lead (jefe departamento): workspace_leads.user_id.
- Usuario/Worker (empleado): project_members.user_id.

Convención: todos los helpers reciben `actor: dict` con shape de JWT/build_jwt_payload
(`is_super`, `is_ceo`, `organization_id`, `lead_workspaces`, `sub`).

Helpers SÍNCRONOS: deciden con info que ya está en memoria (actor + row leída
previamente). Sin DB round-trip — evitan timing oracles (lección VS1-WS + VS1-PROJ .

Helpers ASÍNCRONOS: hacen DB queries. Reciben `conn` asyncpg como primer parámetro.
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _ws_org_id(conn, ws_id: int) -> Optional[int]:
    """Return organization_id for a workspace, or None if not found."""
    return await conn.fetchval(
        "SELECT organization_id FROM workspaces WHERE id = $1", ws_id
    )


# ---------------------------------------------------------------------------
# Validación común — null bytes
# ---------------------------------------------------------------------------

def no_null_bytes(value: str, field_name: str) -> str:
    """Rechazar null bytes (\\x00) en TEXT input — rompen JSONB del soft-delete
    (memorias indestructibles) y pueden engañar parsers downstream. Aplicable
    a cualquier campo TEXT que entre por el API."""
    if "\x00" in value:
        raise ValueError(f"{field_name} cannot contain null bytes")
    return value


def validate_name_strip_blank(value: str, field_name: str = "name") -> str:
    """Validador común para campos `name` (workspaces, projects):
    1. Strip de espacios al inicio/final.
    2. Rechazar si queda blank o solo whitespace.
    3. Rechazar null bytes.

    Razones (OBS-WS1 
    - `name=" "` (un solo espacio) pasa min_length=1 de Pydantic — sin strip,
      crea workspace/project con nombre invisible.
    - `name="  foo  "` se guardaría con espacios y UNIQUE constraint lo trataría
      distinto de "foo" — queries LIKE no matchearían los nombres con espacios
      iniciales (cleanup pytest demostró el side-effect).
    """
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} cannot be blank or whitespace-only")
    return no_null_bytes(value, field_name)


# ---------------------------------------------------------------------------
# Workspace permissions
# ---------------------------------------------------------------------------

def user_can_create_workspace(actor: dict, organization_id: Optional[int]) -> bool:
    """Cascada de creación de workspace:
    - Super: cualquier organization_id, incluido NULL (workspaces del sistema).
    - CEO: solo SU organization_id. NO puede crear workspaces sistema (org=NULL).
    - Lead/Worker: NO pueden crear workspaces.
    """
    is_super = bool(actor.get("is_super"))
    is_ceo = bool(actor.get("is_ceo"))

    if is_super:
        return True
    if organization_id is None:
        # Solo super crea sistema.
        return False
    if not is_ceo:
        return False
    actor_org = actor.get("organization_id")
    return actor_org is not None and actor_org == organization_id


def user_can_modify_workspace(actor: dict, ws_row) -> bool:
    """Cascada de modificación (PUT name): super | CEO de la org | lead del ws.
    Worker NO modifica."""
    if actor.get("is_super"):
        return True
    if actor.get("is_ceo"):
        org_id = actor.get("organization_id")
        if org_id is not None and ws_row["organization_id"] == org_id:
            return True
    if ws_row["id"] in (actor.get("lead_workspaces") or []):
        return True
    return False


def user_can_delete_workspace(actor: dict, ws_row) -> bool:
    """Cascada de borrado: super | CEO de la org. NI lead NI worker pueden borrar.
    Razonamiento: DELETE workspace borra estructura organizacional, decisión que
    queda al dueño de la organization, no al jefe de departamento."""
    if actor.get("is_super"):
        return True
    if actor.get("is_ceo"):
        org_id = actor.get("organization_id")
        if org_id is not None and ws_row["organization_id"] == org_id:
            return True
    return False


# ---------------------------------------------------------------------------
# Project permissions (síncronos — usan project_row con ws_organization_id
# del LEFT JOIN, patrón VS1-PROJ 
# ---------------------------------------------------------------------------

def user_can_modify_project(actor: dict, project_row) -> bool:
    """Cascada de modificación: super | CEO de la org del ws | lead del ws.
    Worker NO modifica.

    `project_row` debe incluir `ws_organization_id` (vía LEFT JOIN workspaces
    en el SELECT inicial) para que el check de CEO sea síncrono — sin DB query
    extra que produciría timing oracle (VS1-PROJ Loop 1)."""
    if actor.get("is_super"):
        return True
    if project_row["workspace_id"] in (actor.get("lead_workspaces") or []):
        return True
    if actor.get("is_ceo"):
        org_id = actor.get("organization_id")
        if org_id is None:
            return False
        return project_row["ws_organization_id"] == org_id
    return False


def user_can_delete_project(actor: dict, project_row) -> bool:
    """Misma autorización que modificación — el lead del workspace puede borrar
    sus propios projects (a diferencia de DELETE workspace que solo super/CEO).
    Razonamiento: project es nivel de departamento interno; workspace es
    departamento entero (decisión más arriba)."""
    return user_can_modify_project(actor, project_row)


def user_can_manage_project_leads(actor: dict, project_row) -> bool:
    """Cascada para asignar/revocar project_leads: super | CEO de la org del ws |
    Lead del ws. — consenso 5/5 sala ecodb-consejo.

    NO project_lead se auto-asigna ni asigna otros project_leads (anti-horizontal-
    escalation, observación adv-seg). El check es idéntico a user_can_modify_project
    porque ambos requieren el mismo nivel de autoridad sobre el project, pero se
    expone función separada por claridad de intención y para futuros refactors
    (ej. si en multi-tenant fork se separa la autoridad de gestión de leads vs
    modificación del project)."""
    return user_can_modify_project(actor, project_row)


# ---------------------------------------------------------------------------
# Project create — async (necesita validar existencia + org del workspace)
# ---------------------------------------------------------------------------

async def user_can_create_project_in_ws(conn, actor: dict, workspace_id: int) -> bool:
    """Cascada de creación de project: super | CEO de la org del ws | lead del ws.

    Async porque necesita resolver `organization_id` del workspace para el check
    de CEO. NO introduce timing oracle — el endpoint POST devuelve 403 para
    "ws no existe" y "ws existe sin permiso" indistinguiblemente (1 query).
    """
    if actor.get("is_super"):
        return True
    ws_row = await conn.fetchrow(
        "SELECT id, organization_id FROM workspaces WHERE id = $1", workspace_id
    )
    if ws_row is None:
        return False
    ws_org = ws_row["organization_id"]
    if workspace_id in (actor.get("lead_workspaces") or []):
        return True
    if actor.get("is_ceo") and ws_org is not None:
        org_id = actor.get("organization_id")
        if org_id is not None and ws_org == org_id:
            return True
    return False


# ---------------------------------------------------------------------------
# Memory permissions (mantienen el shape async actual de memories.py)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Admin operation permissions (multi-tenant v0.9)
# ---------------------------------------------------------------------------

_CEO_ALLOWED_ADMIN_OPS = frozenset({
    "alias_candidates",
    "merge_entities",
    "undo_merge",
    "trust_tier",
    "confirm_related_docs",
    "graph_vocabulary",
})


async def resolve_entity_org_ids(conn, entity_name: str) -> set[int]:
    """Resolve which organizations an entity belongs to via its memory links."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT w.organization_id
        FROM entity_links el
        JOIN memories m ON m.id = el.memory_id
        JOIN projects p ON p.id = m.project_id
        JOIN workspaces w ON w.id = p.workspace_id
        WHERE el.entity = $1 AND w.organization_id IS NOT NULL
        """,
        entity_name,
    )
    return {r["organization_id"] for r in rows}


async def user_can_admin_operation(
    conn, actor: dict, operation: str, target_org_id: Optional[int] = None
) -> bool:
    """Check if actor can perform an admin operation.

    - super: any operation, any org.
    - CEO: only operations in _CEO_ALLOWED_ADMIN_OPS, only own org.
    - others: denied.
    """
    if actor.get("is_super"):
        return True
    if not actor.get("is_ceo"):
        return False
    if operation not in _CEO_ALLOWED_ADMIN_OPS:
        return False
    actor_org = actor.get("organization_id")
    if actor_org is None:
        return False
    if target_org_id is None:
        return False
    return actor_org == target_org_id


async def visible_workspace_ids(conn, actor: dict) -> set[int]:
    """Conjunto de workspace_ids que el actor puede leer.
    super → todos. CEO → todos los de su org. Lead → solo los suyos.
    Worker → workspaces de los projects donde es member."""
    if actor.get("is_super"):
        rows = await conn.fetch("SELECT id FROM workspaces")
        return {r["id"] for r in rows}
    org_id = actor.get("organization_id")
    if actor.get("is_ceo") and org_id is not None:
        rows = await conn.fetch(
            "SELECT id FROM workspaces WHERE organization_id = $1", org_id
        )
        return {r["id"] for r in rows}
    leads = set(actor.get("lead_workspaces") or [])
    rows = await conn.fetch(
        """
        SELECT DISTINCT p.workspace_id
        FROM project_members pm
        JOIN projects p ON p.id = pm.project_id
        WHERE pm.user_id = $1
        """,
        int(actor["sub"]),
    )
    return leads | {r["workspace_id"] for r in rows}


async def visible_project_ids(conn, actor: dict) -> set[int]:
    """Conjunto de project_ids que el actor puede leer.

    Cascada (NUEVO en .5 con team_resources):
    - Super: todos los projects.
    - CEO: projects de workspaces de su organization.
    - Lead: projects de SUS workspaces.
    - Worker: projects donde es project_member, MÁS projects is_common del
      workspace donde tiene algún assignment, MÁS projects vinculados a teams
      ad-hoc donde es team_member (.
    """
    if actor.get("is_super"):
        rows = await conn.fetch("SELECT id FROM projects")
        return {r["id"] for r in rows}
    org_id = actor.get("organization_id")
    if actor.get("is_ceo") and org_id is not None:
        rows = await conn.fetch(
            """
            SELECT p.id FROM projects p
            JOIN workspaces w ON w.id = p.workspace_id
            WHERE w.organization_id = $1
            """,
            org_id,
        )
        return {r["id"] for r in rows}
    user_id = int(actor["sub"])
    lead_ws = list(actor.get("lead_workspaces") or [])
    rows = await conn.fetch(
        """
        SELECT DISTINCT p.id
        FROM projects p
        WHERE p.workspace_id = ANY($1::int[])
           OR p.id IN (SELECT project_id FROM project_members WHERE user_id = $2)
           OR (p.is_common = true AND p.workspace_id IN (
                 SELECT DISTINCT pp.workspace_id
                 FROM project_members pm
                 JOIN projects pp ON pp.id = pm.project_id
                 WHERE pm.user_id = $2
              ))
           OR p.id IN (
                SELECT tr.project_id
                FROM team_resources tr
                JOIN team_members tm ON tm.team_id = tr.team_id
                WHERE tm.user_id = $2
              )
           OR p.id IN (
                SELECT project_id FROM project_leads WHERE user_id = $2
              )
        """,
        lead_ws, user_id,
    )
    return {r["id"] for r in rows}


async def precompute_read_visibility(conn, actor: dict) -> dict:
    """Pre-fetch all visibility data for batch filtering. Eliminates N+1 queries."""
    if actor.get("is_super"):
        return {"is_super": True}
    user_id = int(actor["sub"])
    vis_ws = await visible_workspace_ids(conn, actor)
    is_ceo = bool(actor.get("is_ceo"))
    org_id = actor.get("organization_id") if is_ceo else None
    ws_org_map = {}
    if is_ceo and org_id and vis_ws:
        rows = await conn.fetch(
            "SELECT id, organization_id FROM workspaces WHERE id = ANY($1::int[])",
            list(vis_ws))
        ws_org_map = {r["id"]: r["organization_id"] for r in rows}
    return {
        "is_super": False, "user_id": user_id,
        "is_ceo": is_ceo, "org_id": org_id,
        "visible_ws": vis_ws, "ws_org_map": ws_org_map,
    }


def check_read_memory(vis: dict, memory) -> bool:
    """Check visibility without DB queries. Requires precomputed context."""
    if vis.get("is_super"):
        return True
    if memory["visibility"] == "private":
        if memory["user_id"] == vis["user_id"]:
            return True
        if vis["is_ceo"] and vis["org_id"]:
            ws_org = vis["ws_org_map"].get(memory["workspace_id"])
            return ws_org == vis["org_id"]
        return False
    return memory["workspace_id"] in vis["visible_ws"]


async def can_read_memory(conn, actor: dict, memory) -> bool:
    """Permiso de lectura de una memoria concreta.
    - super: siempre.
    - private: solo creador o CEO de la org del workspace.
    - public: cascada por workspace (lead/CEO/worker member ve)."""
    if actor.get("is_super"):
        return True
    user_id = int(actor["sub"])
    if memory["visibility"] == "private":
        if memory["user_id"] == user_id:
            return True
        if actor.get("is_ceo"):
            org_id = actor.get("organization_id")
            if org_id is None:
                return False
            return await _ws_org_id(conn, memory["workspace_id"]) == org_id
        return False
    visible_ws = await visible_workspace_ids(conn, actor)
    return memory["workspace_id"] in visible_ws


async def can_write_memory(conn, actor: dict, memory) -> bool:
    """Permiso de escritura/borrado de una memoria concreta.
    - super: siempre.
    - private: solo el creador (no Lead/CEO — invariante VS5 adv-seg L1).
    - public: CEO de la org, Lead del ws, o el creador.
    """
    if actor.get("is_super"):
        return True
    user_id = int(actor["sub"])
    if memory["visibility"] == "private" and memory["user_id"] != user_id:
        return False
    if actor.get("is_ceo"):
        org_id = actor.get("organization_id")
        if org_id is None:
            return False
        return await _ws_org_id(conn, memory["workspace_id"]) == org_id
    if memory["workspace_id"] in (actor.get("lead_workspaces") or []):
        return True
    return memory["user_id"] == user_id


async def resolve_agent_for_actor(conn, actor: dict, agent_identifier: str) -> dict:
    """Resolve agent + verify ownership. 404 anti-discovery.
    Shared by all metacognition endpoints."""
    from fastapi import HTTPException
    row = await conn.fetchrow(
        "SELECT id, identifier, user_id FROM agents "
        "WHERE identifier = $1 AND active = true",
        agent_identifier)
    if row is None:
        raise HTTPException(404, f"agent {agent_identifier!r} not found")
    if actor.get("is_super"):
        return dict(row)
    if row["user_id"] is not None and int(row["user_id"]) == int(actor["sub"]):
        return dict(row)
    raise HTTPException(404, f"agent {agent_identifier!r} not found")


# resolve_cluster_for_actor REMOVED — the clusters table is dropped in KnowTwin
# (metacognition stripped; only caller was the stripped clusters.py router).
