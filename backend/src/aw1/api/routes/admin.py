"""Panel admin privado: claves de proveedores y claves de API propias.

Nada de esto pasa por AW1_API_TOKEN: cada ruta exige ademas
``X-Admin-Password`` (``AW1_ADMIN_PASSWORD``), separado del token general de
la app a proposito. Sin esa variable definida, el panel entero responde 401.
La verificacion vive en ``dependencies=[Depends(require_admin)]`` a nivel de
router -no en cada handler- para que una ruta nueva no pueda quedar
desprotegida por un descuido al copiar/pegar.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request

from ...core import llm_provider
from ...core.errors import NotFoundError, ProviderError, ValidationError
from ..deps import Container, container
from ..schemas import (
    AdminConfig,
    AdminStatus,
    ApiKeyCreated,
    ApiKeySummary,
    CreateApiKeyRequest,
    CreateTelegramProfileRequest,
    GeneratedPromptResult,
    GeneratePromptRequest,
    SetSecretRequest,
    TelegramProfileDetail,
    TelegramProfileSummary,
    TestSecretResult,
    UpdateTelegramProfileRequest,
)
from ..security import check_admin


def require_admin(request: Request, box: Container = Depends(container)) -> None:
    check_admin(request, box.settings)


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

# Las unicas claves que el panel puede leer/escribir: nunca un nombre libre,
# para no convertir esto en un almacen generico de lo que sea.
ALLOWED_SECRETS = frozenset(
    {"openai_api_key", "groq_api_key", "ollama_host", "ollama_tunnel_key", "llm_provider"}
)


@router.get("/status", response_model=AdminStatus)
async def get_status(box: Container = Depends(container)) -> AdminStatus:
    provider = llm_provider.effective_provider(box.settings, box.secrets)
    model = llm_provider.chat_model(box.settings, box.secrets)
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


def _config_snapshot(box: Container) -> AdminConfig:
    provider = llm_provider.effective_provider(box.settings, box.secrets)
    groq_key = box.secrets.get("groq_api_key") or (
        box.settings.groq_api_key.get_secret_value() if box.settings.groq_api_key else ""
    )
    return AdminConfig(
        llm_provider=provider,
        ollama_host=box.secrets.get("ollama_host") or box.settings.ollama_host,
        groq_configured=bool(groq_key.strip()),
        openai_configured=box.chat.gpt_configured(),
    )


@router.get("/config", response_model=AdminConfig)
async def get_config(box: Container = Depends(container)) -> AdminConfig:
    return _config_snapshot(box)


async def _test_provider_key(value: str, base_url: str) -> TestSecretResult:
    """Groq y OpenAI comparten protocolo (GET /models con Bearer): alcanza
    una funcion para las dos. No gasta tokens, solo confirma que la clave
    es valida -pensado para no repetir el error de guardar por error un
    valor que no es la clave (paso una password de otro campo, por ejemplo)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {value}"},
            )
    except httpx.HTTPError:
        return TestSecretResult(ok=False, detail="No se pudo contactar al proveedor.")
    if response.status_code == 200:
        return TestSecretResult(ok=True, detail="Clave valida.")
    if response.status_code in (401, 403):
        return TestSecretResult(ok=False, detail="El proveedor rechazo la clave.")
    return TestSecretResult(ok=False, detail=f"El proveedor respondio {response.status_code}.")


@router.post("/config/{name}/test", response_model=TestSecretResult)
async def test_config(
    name: str, payload: SetSecretRequest, box: Container = Depends(container)
) -> TestSecretResult:
    if name == "openai_api_key":
        return await _test_provider_key(payload.value, box.settings.openai_base_url)
    if name == "groq_api_key":
        return await _test_provider_key(payload.value, box.settings.groq_base_url)
    raise ValidationError(f"Esta clave no se puede probar: {name}")


@router.put("/config/{name}", response_model=AdminConfig)
async def set_config(
    name: str, payload: SetSecretRequest, box: Container = Depends(container)
) -> AdminConfig:
    if name not in ALLOWED_SECRETS:
        raise ValidationError(f"Clave no reconocida: {name}")
    if name == "llm_provider" and payload.value not in ("ollama", "groq"):
        raise ValidationError("llm_provider debe ser 'ollama' o 'groq'.")
    await box.secrets.set(name, payload.value)
    if name in ("llm_provider", "groq_api_key", "ollama_host", "ollama_tunnel_key"):
        await box.reload_llm()
    return _config_snapshot(box)


@router.delete("/config/{name}", response_model=AdminConfig)
async def delete_config(name: str, box: Container = Depends(container)) -> AdminConfig:
    if name not in ALLOWED_SECRETS:
        raise ValidationError(f"Clave no reconocida: {name}")
    await box.secrets.delete(name)
    if name in ("llm_provider", "groq_api_key", "ollama_host", "ollama_tunnel_key"):
        await box.reload_llm()
    return _config_snapshot(box)


@router.get("/api-keys", response_model=list[ApiKeySummary])
async def list_api_keys(box: Container = Depends(container)) -> list[ApiKeySummary]:
    rows = await box.api_keys.list()
    return [ApiKeySummary(**row) for row in rows]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    payload: CreateApiKeyRequest, box: Container = Depends(container)
) -> ApiKeyCreated:
    row = await box.api_keys.create(payload.label)
    return ApiKeyCreated(**row)


@router.delete("/api-keys/{key_id}", status_code=204)
async def delete_api_key(key_id: int, box: Container = Depends(container)) -> None:
    ok = await box.api_keys.delete(key_id)
    if not ok:
        raise NotFoundError("Esa clave no existe.")


# -- perfiles de Telegram: cada uno ES un bot independiente -----------------
@router.get("/telegram-profiles", response_model=list[TelegramProfileSummary])
async def list_telegram_profiles(
    box: Container = Depends(container),
) -> list[TelegramProfileSummary]:
    return [TelegramProfileSummary(**row) for row in box.telegram_profiles.list()]


@router.post("/telegram-profiles", response_model=TelegramProfileDetail, status_code=201)
async def create_telegram_profile(
    payload: CreateTelegramProfileRequest, box: Container = Depends(container)
) -> TelegramProfileDetail:
    row = await box.telegram_profiles.create(
        label=payload.label, bot_token=payload.bot_token, system_prompt=payload.system_prompt,
    )
    return TelegramProfileDetail(**row)


@router.get("/telegram-profiles/{profile_id}", response_model=TelegramProfileDetail)
async def get_telegram_profile(
    profile_id: str, box: Container = Depends(container)
) -> TelegramProfileDetail:
    row = await box.telegram_profiles.get(profile_id)
    if row is None:
        raise NotFoundError("Ese perfil no existe.")
    return TelegramProfileDetail(**row)


@router.put("/telegram-profiles/{profile_id}", response_model=TelegramProfileDetail)
async def update_telegram_profile(
    profile_id: str, payload: UpdateTelegramProfileRequest, box: Container = Depends(container)
) -> TelegramProfileDetail:
    row = await box.telegram_profiles.update(
        profile_id, label=payload.label, bot_token=payload.bot_token,
        system_prompt=payload.system_prompt, enabled=payload.enabled,
    )
    if row is None:
        raise NotFoundError("Ese perfil no existe.")
    return TelegramProfileDetail(**row)


@router.delete("/telegram-profiles/{profile_id}", status_code=204)
async def delete_telegram_profile(profile_id: str, box: Container = Depends(container)) -> None:
    if not await box.telegram_profiles.delete(profile_id):
        raise NotFoundError("Ese perfil no existe.")


@router.post("/telegram-profiles/test-token", response_model=TestSecretResult)
async def test_telegram_token(
    payload: SetSecretRequest, box: Container = Depends(container)
) -> TestSecretResult:
    return TestSecretResult(**await box.telegram_profiles.test_token(payload.value))


async def _draft_system_prompt(description: str, box: Container) -> str:
    """Un prompt de sistema listo para un bot de Telegram, a partir de una
    descripcion corta. No es un turno de ChatService.stream() -eso traeria
    ruteo/memoria/menciones, de mas para esto- sino una llamada directa y
    simple a OpenAI, mismo patron crudo que _test_provider_key."""
    key = llm_provider.openai_key(box.settings, box.secrets)
    if not key.strip():
        raise ValidationError("GPT no esta configurado; agrega una clave de OpenAI primero.")
    payload = {
        "model": box.settings.openai_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Escribes prompts de sistema para bots de Telegram en espanol, "
                    "breves, claros y accionables. A partir de una descripcion corta "
                    "del proposito del bot, redacta un system prompt completo y listo "
                    "para usar -tono, limites, que hacer y que no hacer. Responde SOLO "
                    "con el texto del prompt, sin explicaciones ni comillas."
                ),
            },
            {"role": "user", "content": description[:500]},
        ],
        "temperature": 0.6,
        "max_tokens": 400,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.post(
                f"{box.settings.openai_base_url.rstrip('/')}/chat/completions",
                json=payload, headers={"Authorization": f"Bearer {key}"},
            )
        except httpx.HTTPError as error:
            raise ProviderError("No se pudo contactar a GPT.") from error
    if response.status_code != 200:
        raise ProviderError("GPT no pudo generar el prompt.")
    return str(response.json()["choices"][0]["message"]["content"]).strip()


@router.post("/telegram-profiles/generate-prompt", response_model=GeneratedPromptResult)
async def generate_prompt(
    payload: GeneratePromptRequest, box: Container = Depends(container)
) -> GeneratedPromptResult:
    text = await _draft_system_prompt(payload.description, box)
    return GeneratedPromptResult(system_prompt=text)
