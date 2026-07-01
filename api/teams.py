"""Endpoints de equipos ad-hoc -- .7.

Equipos cross-workspace: agrupan users y projects de cualquier workspace para
acceso compartido. Caso de uso: tarea transversal que agrupa personas y
recursos de departamentos distintos sin alterar la estructura organizativa.

Endpoints:
- POST   /teams                            crear team (super only).
- GET    /teams                            listar teams accesibles.
- GET    /teams/{id}                       leer team con members + resources.
- PUT    /teams/{id}                       renombrar (super only).
- DELETE /teams/{id}                       borrar team (super only). CASCADE.
- POST   /teams/{id}/members               anadir user al team (super only).
- DELETE /teams/{id}/members/{user_id}     quitar user (super only).
- POST   /teams/{id}/resources             vincular project (super only).
- DELETE /teams/{id}/resources/{pid}       desvincular (super only).

Modelo de permisos (Fase 2 single-tenant mode):
- Gestion de teams: SOLO super. Por definicion cross-workspace, el unico
  principal con visibilidad global. Lead/CEO no -- un Lead no deberia poder
  meter projects de otro workspace en un team. Multi-tenant fork futuro
  evaluara si CEO (de su org, con projects solo de su org) puede gestionar.
- Lectura de teams: super + team_members del propio team (ven name + members
  + resources de SU team).

Efecto cascada en visible_project_ids (.py):
- Si user es team_member del team T y T tiene team_resource project P,
  visible_project_ids(user) incluye P -> /search devuelve memorias de P aunque
  user NO sea project_member directo de P. Patron "acceso transversal".

Anti-IDOR: 403 unificado para "no existe" y "sin acceso" (leccion recuerdo
f7a032b4, aplicado en 2.1+2.2+2.4). Audit log atomico DELETE (leccion VS2-WS).

Schema: init.sql 211-227. teams.name UNIQUE NOT NULL global. CASCADE en
team_members y team_resources al DELETE team. CASCADE tambien al DELETE de
user (team_members) y project (team_resources) -- un team puede quedar vacio
de members o resources sin error.

Deuda registrada para fork comercial:
- Soft delete o snapshot de team al borrar (audit trail historico de quien
  estaba en que team) -- no aplicable single-tenant mode.
- Permisos team management para CEO de la org en multi-tenant fork.
"""
from __future__ import annotations

import json
from datetime import datetime

from asyncpg.exceptions import ForeignKeyViolationError, UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user, require_super
from db import get_pool
from permissions import validate_name_strip_blank


MAX_NAME_LEN = 200


router = APIRouter(prefix="/teams", tags=["teams"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return validate_name_strip_blank(v, "name")


class TeamUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str) -> str:
        return validate_name_strip_blank(v, "name")


class TeamMemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(..., gt=0)


class TeamResourceAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int = Field(..., gt=0)


class TeamMemberLink(BaseModel):
    """Respuesta de POST/DELETE /teams/{id}/members. response_model
    tipado en lugar de dict (consistencia con resto del API)."""
    team_id: int
    user_id: int


class TeamResourceLink(BaseModel):
    team_id: int
    project_id: int


class TeamResponse(BaseModel):
    id: int
    name: str
    created_at: datetime


class TeamDetailResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
    member_user_ids: list[int]
    resource_project_ids: list[int]


class TeamListResponse(BaseModel):
    items: list[TeamResponse]
    total: int


# ---------------------------------------------------------------------------
# Endpoints -- gestion de teams (super only)
# ---------------------------------------------------------------------------

@router.post("", response_model=TeamResponse, status_code=201)
async def create_team(
    body: TeamCreate,
    actor: dict = Depends(require_super),
) -> TeamResponse:
    """Crear team. Solo super (gestion cross-workspace requiere visibilidad global)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO teams (name) VALUES ($1)
                RETURNING id, name, created_at
                """,
                body.name,
            )
        except UniqueViolationError:
            raise HTTPException(409, "team with this name already exists")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'create_team', 'team', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(row["id"]),
            json.dumps({"name": body.name}),
            actor.get("organization_id"),
        )
    return TeamResponse(**dict(row))


@router.get("", response_model=TeamListResponse)
async def list_teams(actor: dict = Depends(get_current_user)) -> TeamListResponse:
    """Listar teams accesibles para el actor.

    - Super: todos los teams.
    - No-super: solo los teams donde es team_member.
    """
    pool = await get_pool()
    user_id = int(actor["sub"])

    async with pool.acquire() as conn:
        if actor.get("is_super"):
            rows = await conn.fetch(
                "SELECT id, name, created_at FROM teams ORDER BY id"
            )
        else:
            rows = await conn.fetch(
                """
                SELECT t.id, t.name, t.created_at FROM teams t
                JOIN team_members tm ON tm.team_id = t.id
                WHERE tm.user_id = $1 ORDER BY t.id
                """,
                user_id,
            )
    items = [TeamResponse(**dict(r)) for r in rows]
    return TeamListResponse(items=items, total=len(items))


@router.get("/{team_id}", response_model=TeamDetailResponse)
async def get_team(
    team_id: int,
    actor: dict = Depends(get_current_user),
) -> TeamDetailResponse:
    """Leer team por id con members y resources. 403 si no es super ni member.

    Anti-IDOR: 403 unificado para "no existe" y "no es member" via SQL unico
    con cascada permisos en WHERE (patron VS1-WS ."""
    is_super = bool(actor.get("is_super"))
    user_id = int(actor["sub"])

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT t.id, t.name, t.created_at
            FROM teams t
            WHERE t.id = $1
              AND (
                   $2::bool
                OR EXISTS (
                     SELECT 1 FROM team_members tm
                     WHERE tm.team_id = t.id AND tm.user_id = $3
                   )
              )
            """,
            team_id, is_super, user_id,
        )
        if row is None:
            raise HTTPException(403, "no access to this team")

        members = await conn.fetch(
            "SELECT user_id FROM team_members WHERE team_id = $1 ORDER BY user_id",
            team_id,
        )
        resources = await conn.fetch(
            "SELECT project_id FROM team_resources WHERE team_id = $1 ORDER BY project_id",
            team_id,
        )

    return TeamDetailResponse(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
        member_user_ids=[m["user_id"] for m in members],
        resource_project_ids=[r["project_id"] for r in resources],
    )


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: int,
    body: TeamUpdate,
    actor: dict = Depends(require_super),
) -> TeamResponse:
    """Renombrar team. Solo super."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                UPDATE teams SET name = $2
                WHERE id = $1
                RETURNING id, name, created_at
                """,
                team_id, body.name,
            )
        except UniqueViolationError:
            raise HTTPException(409, "team with this name already exists")
        if row is None:
            raise HTTPException(403, "no access to this team")
        await conn.execute(
            """INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
            VALUES ($1, 'update_team', 'team', $2, $3::jsonb, $4)""",
            int(actor["sub"]), str(team_id),
            json.dumps({"name": body.name}),
            actor.get("organization_id"),
        )
    return TeamResponse(**dict(row))


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: int,
    actor: dict = Depends(require_super),
) -> None:
    """Delete team with CASCADE on team_members + team_resources.

    Audit log is atomic. No 409 conflict -- team_members and
    team_resources are CASCADE, no NO ACTION FK that blocks the delete.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, created_at FROM teams WHERE id = $1", team_id
        )
        if row is None:
            raise HTTPException(403, "no access to this team")

        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'delete', 'team', $2, $3::jsonb, $4)
                """,
                int(actor["sub"]), str(team_id),
                json.dumps({"name": row["name"]}), actor.get("organization_id"),
            )
            await conn.execute("DELETE FROM teams WHERE id = $1", team_id)


# ---------------------------------------------------------------------------
# Endpoints -- gestion de team_members (super only)
# ---------------------------------------------------------------------------

@router.post("/{team_id}/members", response_model=TeamMemberLink, status_code=201)
async def add_team_member(
    team_id: int,
    body: TeamMemberAdd,
    actor: dict = Depends(require_super),
) -> TeamMemberLink:
    """Add user to team. Idempotent: if already a member, returns 201 anyway
    (no error). Intentional: callers adding members do not need to distinguish
    already-existed vs created -- what matters is the user is now inside.
    422 if user_id does not exist (FK violation).

    Audit log is atomic -- the ADD grants cross-workspace access to all
    projects in the team via visible_project_ids; without audit, who granted
    access to whom is lost.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Verificar team existe (para 403 anti-IDOR vs FK generico).
        team = await conn.fetchval("SELECT 1 FROM teams WHERE id = $1", team_id)
        if team is None:
            raise HTTPException(403, "no access to this team")
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'add_member', 'team', $2, $3::jsonb, $4)
                    """,
                    int(actor["sub"]), str(team_id),
                    json.dumps({"user_id": body.user_id}), actor.get("organization_id"),
                )
                await conn.execute(
                    """
                    INSERT INTO team_members (team_id, user_id) VALUES ($1, $2)
                    ON CONFLICT (team_id, user_id) DO NOTHING
                    """,
                    team_id, body.user_id,
                )
        except ForeignKeyViolationError:
            raise HTTPException(422, "user does not exist")
    return TeamMemberLink(team_id=team_id, user_id=body.user_id)


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(
    team_id: int,
    user_id: int,
    actor: dict = Depends(require_super),
) -> None:
    """Quitar user del team. 403 si team no existe (anti-IDOR). 204 incluso si
    el user no era member (idempotente).

    audit_log atomico -- la revocacion de acceso cross-workspace
    debe quedar registrada para forensics (heredado de VS2-WS)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        team = await conn.fetchval("SELECT 1 FROM teams WHERE id = $1", team_id)
        if team is None:
            raise HTTPException(403, "no access to this team")
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'remove_member', 'team', $2, $3::jsonb, $4)
                """,
                int(actor["sub"]), str(team_id),
                json.dumps({"user_id": user_id}), actor.get("organization_id"),
            )
            await conn.execute(
                "DELETE FROM team_members WHERE team_id = $1 AND user_id = $2",
                team_id, user_id,
            )


# ---------------------------------------------------------------------------
# Endpoints -- gestion de team_resources (super only)
# ---------------------------------------------------------------------------

@router.post("/{team_id}/resources", response_model=TeamResourceLink, status_code=201)
async def add_team_resource(
    team_id: int,
    body: TeamResourceAdd,
    actor: dict = Depends(require_super),
) -> TeamResourceLink:
    """Vincular project al team. Idempotente: si ya esta vinculado, devuelve
    201 igual (decision consciente, ver add_team_member docstring).
    422 si project_id no existe.

    audit_log atomico -- vincular un project a un team activa
    la cascada visible_project_ids para todos los team_members. Es la
    operacion mas sensible del sistema (acceso cross-workspace), debe
    quedar registrada para forensics."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        team = await conn.fetchval("SELECT 1 FROM teams WHERE id = $1", team_id)
        if team is None:
            raise HTTPException(403, "no access to this team")
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                    VALUES ($1, 'add_resource', 'team', $2, $3::jsonb, $4)
                    """,
                    int(actor["sub"]), str(team_id),
                    json.dumps({"project_id": body.project_id}), actor.get("organization_id"),
                )
                await conn.execute(
                    """
                    INSERT INTO team_resources (team_id, project_id) VALUES ($1, $2)
                    ON CONFLICT (team_id, project_id) DO NOTHING
                    """,
                    team_id, body.project_id,
                )
        except ForeignKeyViolationError:
            raise HTTPException(422, "project does not exist")
    return TeamResourceLink(team_id=team_id, project_id=body.project_id)


@router.delete("/{team_id}/resources/{project_id}", status_code=204)
async def remove_team_resource(
    team_id: int,
    project_id: int,
    actor: dict = Depends(require_super),
) -> None:
    """Desvincular project del team. 403 si team no existe. 204 idempotente.

    audit_log atomico -- la revocacion del recurso del team
    revoca acceso cross-workspace a todos los team_members. Forensics."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        team = await conn.fetchval("SELECT 1 FROM teams WHERE id = $1", team_id)
        if team is None:
            raise HTTPException(403, "no access to this team")
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO audit_log (user_id, action, resource, resource_id, details, organization_id)
                VALUES ($1, 'remove_resource', 'team', $2, $3::jsonb, $4)
                """,
                int(actor["sub"]), str(team_id),
                json.dumps({"project_id": project_id}), actor.get("organization_id"),
            )
            await conn.execute(
                "DELETE FROM team_resources WHERE team_id = $1 AND project_id = $2",
                team_id, project_id,
            )
