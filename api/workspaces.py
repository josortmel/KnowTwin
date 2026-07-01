"""Endpoints de workspaces — .6.

Endpoints:
- POST   /workspaces        crear workspace.
- GET    /workspaces        listar accesibles.
- GET    /workspaces/{id}   leer uno.
- PUT    /workspaces/{id}   actualizar (solo `name`).
- DELETE /workspaces/{id}   borrar (hard delete CASCADE estructural; 409 si tiene data).

Modelo de permisos (cascada CEO/Lead/Worker del plan v3 §4.2):
- Super: crea/lee/modifica/borra cualquiera, incluido `organization_id=NULL` (sistema).
- CEO: crea/lee/modifica/borra solo workspaces de su organization. NO puede crear
  workspaces del sistema (`organization_id=NULL`).
- Lead: lee/modifica los workspaces donde es lead. NO crea ni borra.
- Worker: lee los workspaces que contienen projects donde es member. NO modifica.

Anti-IDOR (lección recuerdo f5960075): siempre 403 cuando sin acceso, NUNCA 404.
Distinguir 404 vs 403 permite enumerar IDs ajenos. Coherente con search.py 1.11.

Hard delete :
- CASCADE estructural en schema actual: workspace_leads, projects → project_members,
  team_resources.
- FK NO ACTION en memories.workspace_id y documents.workspace_id (init.sql 303-304,
  430-431) → Postgres rechaza el DELETE si hay data → 409 Conflict con counts.
- Sin papelera nueva (memories ya tienen memories_trash + endpoint /admin/trash en
  plan v3 §2.7). Schema NO se toca.

Deuda registrada para fork comercial multi-tenant (no bloquea single-tenant mode):
- Rate limit en bulk-delete /memories antes de exponer DELETE /workspaces a CEOs
  cliente (adv-seg). Sin esto, atacante con CEO comprometido vacía workspace
  silenciosamente con N DELETEs antes del DELETE final.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from asyncpg.exceptions import ForeignKeyViolationError, UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user
from db import get_pool
from permissions import (
    user_can_create_workspace,
    user_can_delete_workspace,
    user_can_modify_workspace,
    validate_name_strip_blank,
)


# Limite de tamaño coherente con resto de la API + DoS prevention.
MAX_NAME_LEN = 200


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

# Validador de name extraído a permissions.validate_name_strip_blank en .


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)
    organization_id: Optional[int] = Field(
        None,
        description="ID de la organization. NULL = workspace del sistema (solo super).",
    )

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return validate_name_strip_blank(v, "name")


class WorkspaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Solo `name` es modificable. `organization_id` no se cambia (mover workspace
    # entre orgs es operación destructiva — re-cascada permisos + dataset enorme.
    # Si surge necesidad real, deuda futura).
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return validate_name_strip_blank(v, "name")


class WorkspaceResponse(BaseModel):
    id: int
    organization_id: Optional[int]
    name: str
    created_at: datetime


class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceResponse]
    total: int


# Helpers de permisos extraídos a permissions.py en 
#   user_can_create_workspace, user_can_modify_workspace, user_can_delete_workspace.
# Lectura (GET) sigue haciendo filtro en SQL para evitar timing oracles.

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    actor: dict = Depends(get_current_user),
) -> WorkspaceResponse:
    """Crear workspace.

    Permisos:
    - super: cualquier `organization_id`, incluido NULL (workspace del sistema).
    - CEO: solo su `organization_id`. NO puede crear sistema (NULL).
    - lead/worker: 403.
    """
    # Mensaje granular para superusuario en futuro debug — lo construimos antes
    # del check porque user_can_create_workspace abstrae las 3 razones (no super,
    # CEO sin org, CEO con org distinta) en un único bool. Para Fase 2 single-tenant
    # un mensaje genérico basta; si llega multi-tenant fork con UX rich, separar.
    if not user_can_create_workspace(actor, body.organization_id):
        if body.organization_id is None:
            raise HTTPException(403, "only super can create system workspaces (organization_id=NULL)")
        if not actor.get("is_ceo"):
            raise HTTPException(403, "only super or ceo can create workspaces")
        raise HTTPException(403, "ceo can only create workspaces in their own organization")

    # 
    # transacción atómica. Razón: sin un project común, el workspace nuevo no
    # es usable hasta que alguien cree manualmente un project — los workers
    # añadidos al workspace no tienen sitio donde escribir memorias. La
    # invariante "todo workspace nace con un common" elimina ese gap UX.
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO workspaces (organization_id, name)
                    VALUES ($1, $2)
                    RETURNING id, organization_id, name, created_at
                    """,
                    body.organization_id, body.name,
                )
                # Project común 'general' asociado al workspace recién creado.
                # is_common=true → visible para todos los workers que tengan
                # cualquier project_member en el workspace (cascada definida
                # en visible_project_ids de .
                await conn.execute(
                    """
                    INSERT INTO projects (workspace_id, name, is_common)
                    VALUES ($1, 'general', true)
                    """,
                    row["id"],
                )
                await conn.execute(
                    """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'create_workspace', 'workspace', $2, $3::jsonb, $4)""",
                    int(actor["sub"]), str(row["id"]),
                    json.dumps({"name": body.name, "organization_id": body.organization_id}),
                    actor.get("organization_id"),
                )
        except UniqueViolationError:
            # Schema tiene UNIQUE(org_id, name) + partial unique idx para org_id IS NULL.
            # Si la collision es del workspace name, mensaje específico.
            raise HTTPException(409, "workspace with this name already exists in the organization")
        except ForeignKeyViolationError:
            # organization_id no existe.
            raise HTTPException(422, "organization_id does not exist")

    return WorkspaceResponse(**dict(row))


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    actor: dict = Depends(get_current_user),
) -> WorkspaceListResponse:
    """Listar workspaces accesibles para el actor.

    Filtro cascada:
    - super: todos.
    - CEO: los de su organization.
    - lead + worker: union de (lead_workspaces) ∪ (workspaces con project donde es member).
    """
    is_super = bool(actor.get("is_super"))
    is_ceo = bool(actor.get("is_ceo"))
    user_id = int(actor["sub"])
    org_id = actor.get("organization_id")
    lead_ws = list(actor.get("lead_workspaces") or [])

    pool = await get_pool()
    async with pool.acquire() as conn:
        if is_super:
            rows = await conn.fetch(
                "SELECT id, organization_id, name, created_at FROM workspaces ORDER BY id"
            )
        elif is_ceo and org_id is not None:
            rows = await conn.fetch(
                """
                SELECT id, organization_id, name, created_at
                FROM workspaces
                WHERE organization_id = $1
                ORDER BY id
                """,
                org_id,
            )
        else:
            # Lead + worker: union por id.
            rows = await conn.fetch(
                """
                SELECT DISTINCT w.id, w.organization_id, w.name, w.created_at
                FROM workspaces w
                WHERE w.id = ANY($1::int[])
                   OR w.id IN (
                        SELECT DISTINCT p.workspace_id
                        FROM project_members pm
                        JOIN projects p ON p.id = pm.project_id
                        WHERE pm.user_id = $2
                   )
                ORDER BY id
                """,
                lead_ws, user_id,
            )

    items = [WorkspaceResponse(**dict(r)) for r in rows]
    return WorkspaceListResponse(items=items, total=len(items))


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: int,
    actor: dict = Depends(get_current_user),
) -> WorkspaceResponse:
    """Leer workspace por id. 403 si no tiene acceso O no existe (anti-IDOR).

    VS1-WS fix (adv-seg Loop 1): el SELECT + filtro de permisos viaja en UNA
    sola query con cascada en el WHERE. Sin esto, la rama "workspace existe
    pero sin acceso" hacía 2 queries (SELECT + project_members JOIN) y la rama
    "workspace no existe" 1 query — la latencia diferenciaba ambos casos
    permitiendo enumerar IDs ajenos vía timing oracle. Ahora ambas ramas tienen
    el mismo coste — fila o None tras la misma query.
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
            SELECT w.id, w.organization_id, w.name, w.created_at
            FROM workspaces w
            WHERE w.id = $1
              AND (
                   $2::bool
                OR ($3::bool AND w.organization_id = $4)
                OR w.id = ANY($5::int[])
                OR w.id IN (
                     SELECT DISTINCT p.workspace_id
                     FROM project_members pm
                     JOIN projects p ON p.id = pm.project_id
                     WHERE pm.user_id = $6
                   )
              )
            """,
            workspace_id, is_super, is_ceo, org_id, lead_ws, user_id,
        )
    if row is None:
        # Indistinguible: workspace no existe O existe sin acceso. Misma query,
        # misma latencia. Anti-IDOR garantizado a nivel SQL.
        raise HTTPException(403, "no access to this workspace")
    return WorkspaceResponse(**dict(row))


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: int,
    body: WorkspaceUpdate,
    actor: dict = Depends(get_current_user),
) -> WorkspaceResponse:
    """Actualizar `name` del workspace. 403 si no tiene permiso O no existe."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, organization_id, name, created_at FROM workspaces WHERE id = $1",
            workspace_id,
        )
        if row is None:
            raise HTTPException(403, "no access to this workspace")
        if not user_can_modify_workspace(actor, row):
            raise HTTPException(403, "no access to this workspace")

        try:
            new_row = await conn.fetchrow(
                """
                UPDATE workspaces SET name = $2
                WHERE id = $1
                RETURNING id, organization_id, name, created_at
                """,
                workspace_id, body.name,
            )
        except UniqueViolationError:
            raise HTTPException(409, "workspace with this name already exists in the organization")

        # BC2 pattern (memories.py): si DELETE concurrente entre SELECT y UPDATE,
        # RETURNING devuelve None. Sin guard, _row_to_response crashea 500.
        if new_row is None:
            raise HTTPException(403, "no access to this workspace")

        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'update_workspace', 'workspace', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(workspace_id),
            json.dumps({"name": body.name}),
            actor.get("organization_id"),
        )

    return WorkspaceResponse(**dict(new_row))


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: int,
    actor: dict = Depends(get_current_user),
) -> None:
    """Hard delete con CASCADE estructural.

    Comportamiento del schema (init.sql 172-227, 303-304, 430-431):
    - CASCADE en `workspace_leads`, `projects`, `project_members`, `team_resources`.
    - FK NO ACTION en `memories.workspace_id` y `documents.workspace_id`.
    - Si workspace contiene memorias o documentos → Postgres rechaza con FK
      violation → endpoint devuelve 409 Conflict con count + mensaje "vacía
      primero" .

    Permisos: super | CEO de la org. Lead y worker → 403.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, organization_id, name, created_at FROM workspaces WHERE id = $1",
            workspace_id,
        )
        if row is None:
            raise HTTPException(403, "no access to this workspace")
        if not user_can_delete_workspace(actor, row):
            raise HTTPException(403, "no access to this workspace")

        # audit log en transacción atómica
        # con el DELETE. Sin esto, hard delete con cascade leaves zero forensic
        # trail. Tabla audit_log existe en schema desde Fase 1 (init.sql:532-546).
        # ip_address omitido por ahora — añadir Request dependency es deuda
        # transversal a todos los endpoints, no solo workspaces (registrado en
        # backlog para Tarea 2.x junto con scoping CEO).
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'delete', 'workspace', $2, $3::jsonb, $4)
                    """,
                    int(actor["sub"]), str(workspace_id),
                    json.dumps({
                        "name": row["name"],
                        "organization_id": row["organization_id"],
                    }),
                    actor.get("organization_id"),
                )
                await conn.execute("DELETE FROM workspaces WHERE id = $1", workspace_id)
        except ForeignKeyViolationError:
            # Workspace tiene memorias o documentos → bloqueo del schema. Contar
            # para que el cliente sepa qué vaciar. OBS-WS2 fix (verificador Loop 1):
            # omitir el componente con count=0 para no confundir ("vacía 0 documentos").
            n_memories = await conn.fetchval(
                "SELECT count(*) FROM memories WHERE workspace_id = $1", workspace_id
            )
            n_documents = await conn.fetchval(
                "SELECT count(*) FROM documents WHERE workspace_id = $1", workspace_id
            )
            parts = []
            if n_memories:
                parts.append(f"{n_memories} memories")
            if n_documents:
                parts.append(f"{n_documents} documents")
            blockers = " and ".join(parts) if parts else "data"
            raise HTTPException(
                409,
                f"workspace contains {blockers} — empty before deleting the workspace",
            )
