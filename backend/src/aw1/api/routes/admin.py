"""Panel admin privado: claves de proveedores y claves de API propias.

Nada de esto pasa por AW1_API_TOKEN: cada ruta exige ademas
``X-Admin-Password`` (``AW1_ADMIN_PASSWORD``), separado del token general de
la app a proposito. Sin esa variable definida, el panel entero responde 401.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...core.errors import NotFoundError, ValidationError
from ..deps import Container, container
from ..schemas import (
    AdminConfig,
    AdminStatus,
    ApiKeyCreated,
    ApiKeySummary,
    CreateApiKeyRequest,
    SetSecretRequest,
)
from ..security import check_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Las unicas claves que el panel puede leer/escribir: nunca un nombre libre,
# para no convertir esto en un almacen generico de lo que sea.
ALLOWED_SECRETS = frozenset(
    {"openai_api_key", "groq_api_key", "ollama_host", "llm_provider"}
)


@router.get("/status", response_model=AdminStatus)
async def get_status(request: Request, box: Container = Depends(container)) -> AdminStatus:
    check_admin(request, box.settings)
    provider = box.secrets.get("llm_provider") or box.settings.llm_provider
    model = box.settings.groq_model if provider == "groq" else box.settings.ollama_model
    conversations = await box.repo.conversations(limit=10_000)
    api_keys = await box.api_keys.list()
    return AdminStatus(
        llm_provider=provider,
        llm_model=model,
        database="online" if await box.repo.healthy() else "offline",
        api_token_configured=box.settings.auth_enabled,
        api_keys_issued=len(api_keys),
        conversations=len(conversations),
        messages=sum(row["messages"] for row in conversations),
        saved_items=await box.repo.count_items(),
    )


@router.get("/config", response_model=AdminConfig)
async def get_config(request: Request, box: Container = Depends(container)) -> AdminConfig:
    check_admin(request, box.settings)
    provider = box.secrets.get("llm_provider") or box.settings.llm_provider
    groq_key = box.secrets.get("groq_api_key") or (
        box.settings.groq_api_key.get_secret_value() if box.settings.groq_api_key else ""
    )
    return AdminConfig(
        llm_provider=provider,
        ollama_host=box.secrets.get("ollama_host") or box.settings.ollama_host,
        groq_configured=bool(groq_key.strip()),
        openai_configured=box.chat.gpt_configured(),
    )


@router.put("/config/{name}", response_model=AdminConfig)
async def set_config(
    name: str, payload: SetSecretRequest, request: Request, box: Container = Depends(container)
) -> AdminConfig:
    check_admin(request, box.settings)
    if name not in ALLOWED_SECRETS:
        raise ValidationError(f"Clave no reconocida: {name}")
    if name == "llm_provider" and payload.value not in ("ollama", "groq"):
        raise ValidationError("llm_provider debe ser 'ollama' o 'groq'.")
    await box.secrets.set(name, payload.value)
    if name in ("llm_provider", "groq_api_key", "ollama_host"):
        await box.reload_llm()
    return await get_config(request, box)


@router.delete("/config/{name}", response_model=AdminConfig)
async def delete_config(
    name: str, request: Request, box: Container = Depends(container)
) -> AdminConfig:
    check_admin(request, box.settings)
    if name not in ALLOWED_SECRETS:
        raise ValidationError(f"Clave no reconocida: {name}")
    await box.secrets.delete(name)
    if name in ("llm_provider", "groq_api_key", "ollama_host"):
        await box.reload_llm()
    return await get_config(request, box)


@router.get("/api-keys", response_model=list[ApiKeySummary])
async def list_api_keys(
    request: Request, box: Container = Depends(container)
) -> list[ApiKeySummary]:
    check_admin(request, box.settings)
    rows = await box.api_keys.list()
    return [ApiKeySummary(**row) for row in rows]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    payload: CreateApiKeyRequest, request: Request, box: Container = Depends(container)
) -> ApiKeyCreated:
    check_admin(request, box.settings)
    row = await box.api_keys.create(payload.label)
    return ApiKeyCreated(**row)


@router.delete("/api-keys/{key_id}", status_code=204)
async def delete_api_key(
    key_id: int, request: Request, box: Container = Depends(container)
) -> None:
    check_admin(request, box.settings)
    ok = await box.api_keys.delete(key_id)
    if not ok:
        raise NotFoundError("Esa clave no existe.")
