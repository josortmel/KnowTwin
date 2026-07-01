"""Endpoints de projects — .6.

Endpoints:
- POST   /workspaces/{ws_id}/projects   crear project en workspace.
- GET    /workspaces/{ws_id}/projects   listar projects de un workspace.
- GET    /projects/{pid}                leer project por id (cualquier workspace).
- PUT    /projects/{pid}                actualizar (solo `name`).
- DELETE /projects/{pid}                hard delete CASCADE estructural; 409 si tiene memorias/documentos.

Modelo de permisos (cascada CEO/Lead/Worker del plan v3 §4.2):
- Super: crea/lee/modifica/borra cualquiera.
- CEO: crea/lee/modifica/borra projects en workspaces de su organization.
- Lead del workspace: crea/lee/modifica/borra projects en SU workspace.
- Worker: lee projects donde es project_member O is_common=true del workspace donde
  tiene assignment en algún otro project. NO crea ni modifica ni borra.

Anti-IDOR (lección recuerdo f5960075 + 
acceso, NUNCA 404. GET /{pid} usa SQL único con cascada permisos en WHERE para
eliminar timing oracle entre "no existe" vs "existe sin acceso".

Hard delete (consenso A' 
- CASCADE estructural en schema actual: project_members, team_resources.
- FK NO ACTION en memories.project_id y documents.project_id (init.sql 304, 431)
  → Postgres rechaza el DELETE si hay data → 409 Conflict con counts.
- Audit log atómico: INSERT audit_log + DELETE projects en transacción única
  (lección VS2-WS .

`is_common` (boolean en schema, default false): proyecto común del workspace
visible para todos los workers del workspace (cualquiera que sea miembro de
algún project del ws). 
se respeta el flag en read-cascade.

Deuda registrada para Tarea 2.x (multi-tenant fork): rate limit en bulk-delete
/memories antes de exponer DELETE /projects a CEOs cliente (heredado de .
"""
from __future__ import annotations

import json
from datetime import datetime

from asyncpg.exceptions import ForeignKeyViolationError, UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user
from db import get_pool
from permissions import (
    user_can_create_project_in_ws,
    user_can_delete_project,
    user_can_manage_project_leads,
    user_can_modify_project,
    validate_name_strip_blank,
)


# Coherente con workspaces.py + DoS prevention.
MAX_NAME_LEN = 200


router = APIRouter(tags=["projects"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)
    is_common: bool = Field(
        False,
        description="Si true, proyecto común visible para todos los workers del workspace.",
    )

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return validate_name_strip_blank(v, "name")


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Solo `name` modificable. `workspace_id` no se cambia (mover project entre
    # workspaces es operación destructiva — re-cascada permisos + memorias
    # huérfanas). `is_common` tampoco — flag arquitectónico que NO cambia tras
    # creación. Si surge necesidad de re-categorizar, deuda futura.
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return validate_name_strip_blank(v, "name")


class ProjectResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    is_common: bool
    created_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int


# ---------------------------------------------------------------------------
# — project_leads 
# ---------------------------------------------------------------------------

class ProjectLeadAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(..., gt=0)


class ProjectLeadLink(BaseModel):
    project_id: int
    user_id: int


class ProjectLeadsResponse(BaseModel):
    project_id: int
    lead_user_ids: list[int]


# Helpers de permisos extraídos a permissions.py en 
#   user_can_create_project_in_ws (async — necesita SELECT del ws),
#   user_can_modify_project (sync — usa ws_organization_id del LEFT JOIN),
#   user_can_delete_project (sync — alias de modify).
# Lectura (GET /{id} y GET list) sigue haciendo filtro en SQL para evitar
# timing oracles (VS1-PROJ Loop 1).

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    workspace_id: int,
    body: ProjectCreate,
    actor: dict = Depends(get_current_user),
) -> ProjectResponse:
    """Crear project en workspace.

    Permisos: super | CEO de la org del ws | lead del ws.
    Worker → 403.

    Anti-IDOR: si workspace no existe O actor no tiene permiso → mismo 403.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await user_can_create_project_in_ws(conn, actor, workspace_id):
            # Indistinguible: ws no existe O ws existe sin permiso. Misma respuesta.
            raise HTTPException(403, "no access to this workspace")

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO projects (workspace_id, name, is_common)
                VALUES ($1, $2, $3)
                RETURNING id, workspace_id, name, is_common, created_at
                """,
                workspace_id, body.name, body.is_common,
            )
        except UniqueViolationError:
            # Schema tiene UNIQUE(workspace_id, name).
            raise HTTPException(409, "project with this name already exists in the workspace")
        except ForeignKeyViolationError:
            raise HTTPException(403, "no access to this workspace")

        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'create_project', 'project', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(row["id"]),
            json.dumps({"workspace_id": workspace_id, "name": body.name, "is_common": body.is_common}),
            actor.get("organization_id"),
        )

    return ProjectResponse(**dict(row))


@router.get("/workspaces/{workspace_id}/projects", response_model=ProjectListResponse)
async def list_projects_in_workspace(
    workspace_id: int,
    actor: dict = Depends(get_current_user),
) -> ProjectListResponse:
    """Listar projects de un workspace específico.

    Cascada lectura:
    - super: todos los projects del ws.
    - CEO: si org del ws es su org → todos los projects.
    - lead del ws: todos los projects del ws.
    - worker: solo los projects donde es project_member, MÁS los is_common del
      workspace (si el worker tiene algún project_member en este ws).

    Si el actor no tiene NINGÚN acceso al workspace → 403 (anti-IDOR vs
    "workspace existe pero sin permiso").
    """
    is_super = bool(actor.get("is_super"))
    is_ceo = bool(actor.get("is_ceo"))
    user_id = int(actor["sub"])
    org_id = actor.get("organization_id")
    lead_ws = list(actor.get("lead_workspaces") or [])

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Determinar nivel de acceso al workspace en una sola query.
        access_row = await conn.fetchrow(
            """
            SELECT
                w.organization_id,
                ($1::bool
                  OR ($2::bool AND w.organization_id = $3)
                  OR w.id = ANY($4::int[])) AS has_full_access,
                EXISTS (
                    SELECT 1 FROM project_members pm
                    JOIN projects p ON p.id = pm.project_id
                    WHERE pm.user_id = $5 AND p.workspace_id = w.id
                ) AS has_worker_access
            FROM workspaces w
            WHERE w.id = $6
            """,
            is_super, is_ceo, org_id, lead_ws, user_id, workspace_id,
        )
        if access_row is None:
            raise HTTPException(403, "no access to this workspace")

        if access_row["has_full_access"]:
            rows = await conn.fetch(
                """
                SELECT id, workspace_id, name, is_common, created_at
                FROM projects WHERE workspace_id = $1 ORDER BY id
                """,
                workspace_id,
            )
        elif access_row["has_worker_access"]:
            # Worker: project_members del worker en este ws + is_common del ws.
            rows = await conn.fetch(
                """
                SELECT DISTINCT p.id, p.workspace_id, p.name, p.is_common, p.created_at
                FROM projects p
                WHERE p.workspace_id = $1
                  AND (
                       p.is_common = true
                    OR p.id IN (
                         SELECT project_id FROM project_members WHERE user_id = $2
                       )
                  )
                ORDER BY id
                """,
                workspace_id, user_id,
            )
        else:
            raise HTTPException(403, "no access to this workspace")

    items = [ProjectResponse(**dict(r)) for r in rows]
    return ProjectListResponse(items=items, total=len(items))


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    actor: dict = Depends(get_current_user),
) -> ProjectResponse:
    """Leer project por id. 403 si no tiene acceso O no existe (anti-IDOR).

    VS1-WS pattern ( — ambas
    ramas (no existe / existe sin acceso) tienen mismo coste, sin timing oracle.
    """
    is_super = bool(actor.get("is_super"))
    is_ceo = bool(actor.get("is_ceo"))
    user_id = int(actor["sub"])
    org_id = actor.get("organization_id")
    lead_ws = list(actor.get("lead_workspaces") or [])

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.id, p.workspace_id, p.name, p.is_common, p.created_at
            FROM projects p
            JOIN workspaces w ON w.id = p.workspace_id
            WHERE p.id = $1
              AND (
                   $2::bool
                OR ($3::bool AND w.organization_id = $4)
                OR p.workspace_id = ANY($5::int[])
                OR p.id IN (
                     SELECT project_id FROM project_members WHERE user_id = $6
                   )
                OR (p.is_common = true AND p.workspace_id IN (
                     SELECT DISTINCT pp.workspace_id
                     FROM project_members pm
                     JOIN projects pp ON pp.id = pm.project_id
                     WHERE pm.user_id = $6
                   ))
              )
            """,
            project_id, is_super, is_ceo, org_id, lead_ws, user_id,
        )
    if row is None:
        raise HTTPException(403, "no access to this project")
    return ProjectResponse(**dict(row))


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    actor: dict = Depends(get_current_user),
) -> ProjectResponse:
    """Actualizar `name` del project. Worker NO puede (mismo patrón que workspaces)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # VS1-PROJ fix (adv-seg Loop 1): SELECT inicial con LEFT JOIN para traer
        # `ws_organization_id` en la misma query — el helper de permisos queda
        # síncrono, ambas ramas (CEO de org distinta vs project no existe)
        # cuestan el mismo round-trip → sin timing oracle.
        row = await conn.fetchrow(
            """
            SELECT p.id, p.workspace_id, p.name, p.is_common, p.created_at,
                   w.organization_id AS ws_organization_id
            FROM projects p
            LEFT JOIN workspaces w ON w.id = p.workspace_id
            WHERE p.id = $1
            """,
            project_id,
        )
        if row is None or not user_can_modify_project(actor, row):
            raise HTTPException(403, "no access to this project")

        try:
            new_row = await conn.fetchrow(
                """
                UPDATE projects SET name = $2
                WHERE id = $1
                RETURNING id, workspace_id, name, is_common, created_at
                """,
                project_id, body.name,
            )
        except UniqueViolationError:
            raise HTTPException(409, "project with this name already exists in the workspace")

        # BC2 pattern (
        # RETURNING devuelve None.
        if new_row is None:
            raise HTTPException(403, "no access to this project")

        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'update_project', 'project', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(project_id),
            json.dumps({"name": body.name}),
            actor.get("organization_id"),
        )

    return ProjectResponse(**dict(new_row))


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    actor: dict = Depends(get_current_user),
) -> None:
    """Hard delete con CASCADE estructural.

    Cascade del schema (init.sql 196-209):
    - CASCADE en `project_members`, `team_resources`.
    - FK NO ACTION en `memories.project_id` (línea 304) y `documents.project_id`
      (línea 431) → Postgres rechaza si hay data → 409 Conflict con counts
      condicionales (OBS-WS2 .

    Audit log atómico VS2-WS pattern (.

    Permisos: super | CEO de la org del ws | lead del ws. Worker → 403.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # VS1-PROJ fix (adv-seg Loop 1): mismo patrón que update_project.
        row = await conn.fetchrow(
            """
            SELECT p.id, p.workspace_id, p.name, p.is_common, p.created_at,
                   w.organization_id AS ws_organization_id
            FROM projects p
            LEFT JOIN workspaces w ON w.id = p.workspace_id
            WHERE p.id = $1
            """,
            project_id,
        )
        if row is None or not user_can_delete_project(actor, row):
            raise HTTPException(403, "no access to this project")

        # VS1 fix 
        # project_common del workspace. La 
        # "todo workspace nace con un project_common" para que workers añadidos
        # tengan sitio de escritura desde día 0. Un Lead borrando el common
        # rompe esa utilidad sin fricción (DoS funcional). Si the platform owner quiere
        # rotar el common (raro, no escalado para single-tenant), tendría que
        # crear otro is_common primero y luego borrar este — fuera de scope
        # de Fase 2, deuda futura para multi-tenant si surge caso.
        if row["is_common"]:
            raise HTTPException(
                409,
                "cannot delete the common project of a workspace — every workspace must keep one is_common project",
            )

        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'delete', 'project', $2, $3::jsonb, $4)
                    """,
                    int(actor["sub"]), str(project_id),
                    json.dumps({
                        "name": row["name"],
                        "workspace_id": row["workspace_id"],
                        "is_common": row["is_common"],
                    }), actor.get("organization_id"),
                )
                # Cleanup explícito project_leads (no hay CASCADE en projects→
                # project_leads en orden — sí lo hay vía FK pero el DELETE de
                # projects ya lo cubre por CASCADE definido en la FK).
                await conn.execute("DELETE FROM projects WHERE id = $1", project_id)
        except ForeignKeyViolationError:
            # Project tiene memorias o documentos → bloqueo del schema.
            n_memories = await conn.fetchval(
                "SELECT count(*) FROM memories WHERE project_id = $1", project_id
            )
            n_documents = await conn.fetchval(
                "SELECT count(*) FROM documents WHERE project_id = $1", project_id
            )
            parts = []
            if n_memories:
                parts.append(f"{n_memories} memories")
            if n_documents:
                parts.append(f"{n_documents} documents")
            blockers = " and ".join(parts) if parts else "data"
            raise HTTPException(
                409,
                f"project contains {blockers} — empty before deleting the project",
            )


# ---------------------------------------------------------------------------
# — endpoints project_leads
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/leads", response_model=ProjectLeadLink, status_code=201)
async def add_project_lead(
    project_id: int,
    body: ProjectLeadAdd,
    actor: dict = Depends(get_current_user),
) -> ProjectLeadLink:
    """Asignar user como project_lead. Permisos: super | CEO de la org del ws |
    Lead del ws. NO project_lead self-assign (anti-horizontal-escalation,
    observación adv-seg consenso 5/5).

    Idempotente (ON CONFLICT DO NOTHING + 201). 422 si user_id no existe.
    Audit log atómico (VS1 pattern ."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.id, p.workspace_id, p.name, p.is_common, p.created_at,
                   w.organization_id AS ws_organization_id
            FROM projects p
            LEFT JOIN workspaces w ON w.id = p.workspace_id
            WHERE p.id = $1
            """,
            project_id,
        )
        if row is None or not user_can_manage_project_leads(actor, row):
            raise HTTPException(403, "no access to manage project leads")

        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'add_lead', 'project', $2, $3::jsonb, $4)
                    """,
                    int(actor["sub"]), str(project_id),
                    json.dumps({"user_id": body.user_id}), actor.get("organization_id"),
                )
                await conn.execute(
                    """
                    INSERT INTO project_leads (project_id, user_id) VALUES ($1, $2)
                    ON CONFLICT (project_id, user_id) DO NOTHING
                    """,
                    project_id, body.user_id,
                )
        except ForeignKeyViolationError:
            raise HTTPException(422, "user does not exist")
    return ProjectLeadLink(project_id=project_id, user_id=body.user_id)


@router.delete("/projects/{project_id}/leads/{user_id}", status_code=204)
async def remove_project_lead(
    project_id: int,
    user_id: int,
    actor: dict = Depends(get_current_user),
) -> None:
    """Quitar project_lead. Mismos permisos que add. Idempotente (204 incluso
    si no era lead). Audit log atómico."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.id, p.workspace_id, p.name, p.is_common, p.created_at,
                   w.organization_id AS ws_organization_id
            FROM projects p
            LEFT JOIN workspaces w ON w.id = p.workspace_id
            WHERE p.id = $1
            """,
            project_id,
        )
        if row is None or not user_can_manage_project_leads(actor, row):
            raise HTTPException(403, "no access to manage project leads")

        # BC1 fix 
        # a rowcount>0. Antes el endpoint era idempotente 204 incluso si el
        # user nunca fue project_lead, y el audit log se ensuciaba con
        # 'remove_lead' para asignaciones inexistentes. Ahora: solo audit
        # cuando efectivamente hubo borrado. Sigue idempotente (204 siempre).
        async with conn.transaction():
            deleted = await conn.fetchval(
                """
                DELETE FROM project_leads
                WHERE project_id = $1 AND user_id = $2
                RETURNING user_id
                """,
                project_id, user_id,
            )
            if deleted is not None:
                await conn.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'remove_lead', 'project', $2, $3::jsonb, $4)
                    """,
                    int(actor["sub"]), str(project_id),
                    json.dumps({"user_id": user_id}), actor.get("organization_id"),
                )


@router.get("/projects/{project_id}/leads", response_model=ProjectLeadsResponse)
async def list_project_leads(
    project_id: int,
    actor: dict = Depends(get_current_user),
) -> ProjectLeadsResponse:
    """Listar project_leads del project. Permisos lectura: super | CEO de la
    org del ws | Lead del ws | el propio project_lead listado.

    Anti-IDOR: 403 unificado para "no existe" y "sin acceso"."""
    pool = await get_pool()
    user_id = int(actor["sub"])
    is_super = bool(actor.get("is_super"))
    is_ceo = bool(actor.get("is_ceo"))
    org_id = actor.get("organization_id")
    lead_ws = list(actor.get("lead_workspaces") or [])

    async with pool.acquire() as conn:
        # Acceso vía SQL único (anti-IDOR + anti-timing). Pasa si: super | CEO
        # de la org del ws | Lead del ws | self (project_lead listándose a sí mismo).
        row = await conn.fetchrow(
            """
            SELECT p.id, p.workspace_id
            FROM projects p
            LEFT JOIN workspaces w ON w.id = p.workspace_id
            WHERE p.id = $1
              AND (
                   $2::bool
                OR ($3::bool AND w.organization_id = $4)
                OR p.workspace_id = ANY($5::int[])
                OR EXISTS(SELECT 1 FROM project_leads
                          WHERE project_id = p.id AND user_id = $6)
              )
            """,
            project_id, is_super, is_ceo, org_id, lead_ws, user_id,
        )
        if row is None:
            raise HTTPException(403, "no access to this project")

        leads = await conn.fetch(
            "SELECT user_id FROM project_leads WHERE project_id = $1 ORDER BY user_id",
            project_id,
        )

    return ProjectLeadsResponse(
        project_id=project_id,
        lead_user_ids=[r["user_id"] for r in leads],
    )
