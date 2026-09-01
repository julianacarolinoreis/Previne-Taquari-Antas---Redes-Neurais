import json
import os
from contextlib import asynccontextmanager
from typing import Any, Literal
from uuid import UUID

import asyncpg
from fastapi import FastAPI, Header, HTTPException, Query
from jose import JWTError, jwt
from pydantic import BaseModel, Field

DATABASE_URL = os.getenv('DATABASE_URL', '')
JWT_SECRET = os.getenv('JWT_SECRET', '')
JWT_AUDIENCE = os.getenv('JWT_AUDIENCE')
JWT_ALGORITHMS = ['HS256']
pool: asyncpg.Pool | None = None


class SyncOperation(BaseModel):
    operationId: UUID
    entity: Literal['layer', 'feature', 'photo', 'map']
    entityId: UUID
    action: Literal['upsert', 'delete']
    baseRevision: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncPush(BaseModel):
    deviceId: str = Field(min_length=1, max_length=200)
    operations: list[SyncOperation] = Field(max_length=500)


def user_id_from_header(authorization: str | None) -> UUID:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Bearer token obrigatório')
    if not JWT_SECRET:
        raise HTTPException(status_code=503, detail='JWT_SECRET não configurado')
    token = authorization.removeprefix('Bearer ').strip()
    try:
        options = {'verify_aud': JWT_AUDIENCE is not None}
        claims = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=JWT_ALGORITHMS,
            audience=JWT_AUDIENCE,
            options=options,
        )
        return UUID(str(claims['sub']))
    except (JWTError, KeyError, ValueError) as error:
        raise HTTPException(status_code=401, detail='Token inválido') from error


def require_pool() -> asyncpg.Pool:
    if pool is None:
        raise HTTPException(status_code=503, detail='Banco de dados indisponível')
    return pool


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    if DATABASE_URL:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    yield
    if pool is not None:
        await pool.close()
        pool = None


app = FastAPI(
    title='AtlasCampo API',
    version='1.0.0',
    lifespan=lifespan,
)


@app.get('/health')
async def health() -> dict[str, str | bool]:
    return {'status': 'ok', 'database': pool is not None}


@app.post('/v1/sync/push')
async def push(
    request: SyncPush,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    current_user = user_id_from_header(authorization)
    database = require_pool()
    results: list[dict[str, Any]] = []

    async with database.acquire() as connection:
        async with connection.transaction():
            for operation in request.operations:
                known = await connection.fetchrow(
                    'SELECT applied_revision FROM sync_operations WHERE operation_id = $1',
                    operation.operationId,
                )
                if known:
                    results.append({
                        'operationId': str(operation.operationId),
                        'status': 'already_applied',
                        'revision': known['applied_revision'],
                    })
                    continue

                current = await connection.fetchrow(
                    'SELECT revision FROM features WHERE id = $1 FOR UPDATE',
                    operation.entityId,
                ) if operation.entity == 'feature' else None
                current_revision = int(current['revision']) if current else 0
                if current_revision != operation.baseRevision:
                    results.append({
                        'operationId': str(operation.operationId),
                        'status': 'conflict',
                        'serverRevision': current_revision,
                    })
                    continue

                if operation.entity != 'feature':
                    results.append({
                        'operationId': str(operation.operationId),
                        'status': 'unsupported_entity',
                    })
                    continue

                if operation.action == 'delete':
                    new_revision = current_revision + 1
                    await connection.execute(
                        '''
                        UPDATE features
                        SET revision = $2, deleted_at = now(), updated_by = $3,
                            updated_at = now()
                        WHERE id = $1
                        ''',
                        operation.entityId,
                        new_revision,
                        current_user,
                    )
                    change_payload = {'deleted': True}
                else:
                    payload = operation.payload
                    try:
                        layer_id = UUID(str(payload['layerId']))
                        geometry = json.dumps(payload['geometry'])
                    except (KeyError, TypeError, ValueError) as error:
                        results.append({
                            'operationId': str(operation.operationId),
                            'status': 'invalid_payload',
                            'detail': str(error),
                        })
                        continue
                    properties = json.dumps(payload.get('properties', {}))
                    project_id = payload.get('projectId')
                    project_uuid = UUID(str(project_id)) if project_id else None
                    new_revision = current_revision + 1
                    await connection.execute(
                        '''
                        INSERT INTO features
                            (id, layer_id, project_id, geometry, properties,
                             revision, updated_by, deleted_at, updated_at)
                        VALUES
                            ($1, $2, $3,
                             ST_SetSRID(ST_GeomFromGeoJSON($4), 4326),
                             $5::jsonb, $6, $7, NULL, now())
                        ON CONFLICT (id) DO UPDATE SET
                            layer_id = EXCLUDED.layer_id,
                            project_id = EXCLUDED.project_id,
                            geometry = EXCLUDED.geometry,
                            properties = EXCLUDED.properties,
                            revision = EXCLUDED.revision,
                            updated_by = EXCLUDED.updated_by,
                            deleted_at = NULL,
                            updated_at = now()
                        ''',
                        operation.entityId,
                        layer_id,
                        project_uuid,
                        geometry,
                        properties,
                        new_revision,
                        current_user,
                    )
                    change_payload = payload

                await connection.execute(
                    '''
                    INSERT INTO sync_operations
                        (operation_id, user_id, entity, entity_id, applied_revision)
                    VALUES ($1, $2, $3, $4, $5)
                    ''',
                    operation.operationId,
                    current_user,
                    operation.entity,
                    operation.entityId,
                    new_revision,
                )
                await connection.execute(
                    '''
                    INSERT INTO sync_changes (entity, entity_id, revision, payload)
                    VALUES ($1, $2, $3, $4::jsonb)
                    ''',
                    operation.entity,
                    operation.entityId,
                    new_revision,
                    json.dumps(change_payload),
                )
                results.append({
                    'operationId': str(operation.operationId),
                    'status': 'applied',
                    'revision': new_revision,
                })
    return {'results': results}


@app.get('/v1/sync/pull')
async def pull(
    authorization: str | None = Header(default=None),
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    user_id_from_header(authorization)
    database = require_pool()
    async with database.acquire() as connection:
        rows = await connection.fetch(
            '''
            SELECT sequence, entity, entity_id, revision, payload
            FROM sync_changes
            WHERE sequence > $1
            ORDER BY sequence ASC
            LIMIT $2
            ''',
            cursor,
            limit,
        )
    changes = [
        {
            'sequence': row['sequence'],
            'entity': row['entity'],
            'entityId': str(row['entity_id']),
            'revision': row['revision'],
            'payload': row['payload'],
        }
        for row in rows
    ]
    next_cursor = changes[-1]['sequence'] if changes else cursor
    return {'cursor': next_cursor, 'changes': changes}
