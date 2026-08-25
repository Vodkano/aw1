"""Configuracion del sistema.

Todo se lee del entorno con prefijo ``AW1_`` y se valida en el arranque. La idea
es que un despliegue mal configurado falle de inmediato con un mensaje util, no
a mitad de una busqueda.
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AW1_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # -- entorno ------------------------------------------------------------
    env: Environment = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    log_json: bool = False
    data_dir: Path = Path("data")
    # Ruta del frontend compilado. Vacio: se infiere subiendo desde este
    # archivo hasta la raiz del repo -sirve para una instalacion editable
    # (`pip install -e`, como en desarrollo local), pero no para una
    # instalacion real (wheel, como en Docker), que no conserva esa
    # estructura de carpetas. Ahi hace falta fijarla explicitamente.
    web_dist: str = ""
    # Vacio: SQLite en data_dir/aw1.sqlite3 (por defecto, ideal para local).
    # postgres://... o postgresql://...: usa Postgres (recomendado en la nube).
    database_url: str = ""

    # -- Ollama -------------------------------------------------------------
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "mistral"
    # Modelo pequeno y rapido para las decisiones estructuradas del comparador.
    # Si no esta descargado se usa `ollama_model`.
    ollama_fast_model: str = ""
    ollama_chat_timeout: float = Field(default=120.0, gt=0)
    ollama_judge_timeout: float = Field(default=45.0, gt=0)
    ollama_num_ctx: int = Field(default=8192, ge=2048, le=131072)
    # Si Ollama se expone por un tunel publico (ej. Cloudflare Tunnel hacia
    # una Mac), esta clave viaja en cada peticion como header
    # "X-Aw1-Tunnel-Key" y un WAF la exige del otro lado -Ollama no tiene
    # autenticacion propia, asi que sin esto cualquiera que adivine la URL
    # del tunel podria usarlo.
    ollama_tunnel_key: SecretStr | None = None

    # -- Groq (proveedor alternativo, recomendado en la nube) ---------------
    # Ollama corriendo local es gratis pero necesita CPU/RAM dedicada 24/7.
    # Groq es una API de pago barata y muy rapida (LPUs): con AW1_GROQ_API_KEY
    # definido y AW1_LLM_PROVIDER=groq, reemplaza a Ollama para chat y jueces.
    llm_provider: Literal["ollama", "groq"] = "ollama"
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fast_model: str = "llama-3.1-8b-instant"

    # -- GPT opcional (solo con confirmacion explicita) ---------------------
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    # Modelo de imagenes que los agentes de Telegram pueden invocar como
    # herramienta (ver chat/tools -> _answer_with_gpt_tools). dall-e-3 es el
    # mas barato de los que devuelven buena calidad razonable por defecto.
    openai_image_model: str = "dall-e-3"

    # -- busqueda web opcional (herramienta @buscar) -------------------------
    # Brave Search API: clave simple (un solo header), tiene capa gratuita, y
    # no depende de un motor de busqueda "custom" aparte como Google CSE. Sin
    # esto configurado la herramienta @buscar avisa que falta la clave, igual
    # que GPT sin AW1_OPENAI_API_KEY.
    brave_search_api_key: SecretStr | None = None
    brave_search_base_url: str = "https://api.search.brave.com/res/v1/web/search"

    # -- navegador ----------------------------------------------------------
    browser_headless: bool = True
    browser_max_contexts: int = Field(default=3, ge=1, le=12)
    browser_nav_timeout: float = Field(default=20.0, gt=1, le=120)
    browser_locale: str = "es-CL"
    browser_timezone: str = "America/Santiago"
    browser_block_media: bool = True
    browser_executable_path: str = ""
    # URL de un proxy rotativo (ej. http://usuario:clave@host:puerto), para
    # cuando el navegador corre desde una IP de datacenter (AWS, etc.) y una
    # tienda la bloquea directo -pasa igual con cualquier proveedor que
    # entregue una URL de proxy estandar, no hay codigo especifico de nadie.
    # Debe ser residencial/ISP: un proxy de datacenter no resuelve el bloqueo,
    # sigue viendose como datacenter. Vacio: sin proxy (uso local normal).
    browser_proxy_url: SecretStr | None = None

    # -- comparador ---------------------------------------------------------
    search_budget_seconds: float = Field(default=90.0, gt=5, le=600)
    stores_per_search: int = Field(default=5, ge=1, le=12)
    candidates_per_store: int = Field(default=12, ge=1, le=40)
    products_per_store: int = Field(default=2, ge=1, le=6)
    max_offers: int = Field(default=12, ge=1, le=50)
    cache_ttl_seconds: int = Field(default=1800, ge=0)
    fx_rates_to_clp: dict[str, float] = Field(
        default_factory=lambda: {"CLP": 1.0, "USD": 950.0, "EUR": 1030.0, "UF": 39000.0}
    )

    # -- seguridad ----------------------------------------------------------
    api_token: SecretStr | None = None
    # Panel privado para guardar claves de proveedores (OpenAI, Groq, etc.) y
    # generar claves de API adicionales, sin reiniciar el proceso. Sin esto
    # definido, el panel /api/admin/* rechaza todo.
    admin_password: SecretStr | None = None
    # NoDecode: sin esto, pydantic-settings intenta parsear el valor del
    # entorno como JSON antes de que el validador de abajo vea la lista
    # separada por comas documentada en .env.example, y siempre falla.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    rate_limit_per_minute: int = Field(default=90, ge=0)
    max_request_bytes: int = Field(default=128_000, ge=1_000)
    # Solo para pruebas: permite navegar a 127.0.0.1 (tiendas simuladas).
    allow_private_hosts: bool = False
    # Tienda de demostracion. Si se define, se anade al catalogo y permite
    # comprobar el comparador completo sin depender de tiendas reales.
    # Ejemplo: AW1_DEMO_STORE_URL=http://127.0.0.1:9100
    demo_store_url: str = ""

    # -- memoria ------------------------------------------------------------
    max_history_turns: int = Field(default=10, ge=0, le=50)
    max_saved_items: int = Field(default=500, ge=1)
    # Memoria de corto plazo de los bots de Telegram: cuantas horas hacia
    # atras se manda como contexto, con un tope duro de mensajes ademas del
    # tiempo (una charla muy activa no debe mandarle al modelo un historial
    # gigante). El chat web usa max_history_turns en su lugar -distinto por
    # diseno, Telegram es una charla que sigue horas o dias, el chat web
    # suele ser una sesion mas acotada.
    telegram_history_hours: float = Field(default=72.0, ge=1.0, le=720.0)
    telegram_history_max_messages: int = Field(default=120, ge=1, le=500)

    # -- Telegram -------------------------------------------------------------
    # URL publica y estable de esta instancia (ej. https://app.aw1s.online),
    # para construir la webhook URL de cada perfil al llamar Telegram
    # setWebhook. Sin esto no se puede crear un perfil de Telegram -falla
    # explicito al crear, no en silencio (ver core/telegram_store.py).
    public_base_url: str = ""
    # Cada cuanto se revisan TODOS los seguimientos de precio activos (todos
    # los perfiles). Default 6h: mas seguido aumenta el riesgo de que una
    # tienda bloquee la IP de la VPS (ya paso con Falabella/Ripley).
    price_watch_interval_seconds: float = Field(default=21600.0, gt=60)

    # -- sandbox de herramientas generadas ---------------------------------
    # Limites del subproceso donde corre codigo generado por IA (ver
    # core/sandbox.py) -tanto al probarlo como despues, ya aprobado, en
    # conversaciones reales. Conservadores a proposito: son herramientas
    # chicas (una llamada HTTP y algo de procesamiento), no scripts largos.
    sandbox_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    sandbox_cpu_seconds: int = Field(default=5, ge=1, le=30)
    sandbox_memory_mb: int = Field(default=256, ge=64, le=1024)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("fx_rates_to_clp", mode="before")
    @classmethod
    def _parse_rates(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return json.loads(value)
        return value

    @field_validator("fx_rates_to_clp")
    @classmethod
    def _check_rates(cls, value: dict[str, float]) -> dict[str, float]:
        rates = {str(key).upper(): float(rate) for key, rate in value.items()}
        rates["CLP"] = 1.0
        if any(rate <= 0 for rate in rates.values()):
            raise ValueError("Las tasas de cambio deben ser positivas.")
        return rates

    @model_validator(mode="after")
    def _port_fallback(self) -> Settings:
        # Railway/Render/Heroku asignan el puerto por la variable `PORT` (sin
        # prefijo) en vez de AW1_PORT.
        if "AW1_PORT" not in os.environ and "PORT" in os.environ:
            with suppress(ValueError):
                self.port = int(os.environ["PORT"])
        return self

    @model_validator(mode="after")
    def _database_url_fallback(self) -> Settings:
        # Railway/Render/Heroku inyectan `DATABASE_URL` (sin prefijo) al agregar
        # un addon de Postgres; se acepta como alternativa a AW1_DATABASE_URL.
        if not self.database_url:
            fallback = os.environ.get("DATABASE_URL", "")
            if fallback:
                self.database_url = fallback
        return self

    @model_validator(mode="after")
    def _production_rules(self) -> Settings:
        if self.env == "production":
            # AW1_API_TOKEN es opcional: el chat y el comparador de precios son
            # de uso libre por diseno (no dependen de una clave). Si se define
            # igual se exige un largo minimo, para que no quede una clave debil
            # protegiendo /api/admin/api-keys u otro uso futuro.
            token = self.api_token.get_secret_value().strip() if self.api_token else ""
            if token and len(token) < 24:
                raise ValueError("AW1_API_TOKEN debe tener al menos 24 caracteres si se define.")
            if self.allow_private_hosts:
                raise ValueError("AW1_ALLOW_PRIVATE_HOSTS no puede activarse en produccion.")
        if self.llm_provider == "groq":
            key = self.groq_api_key.get_secret_value() if self.groq_api_key else ""
            if not key.strip():
                raise ValueError(
                    "AW1_LLM_PROVIDER=groq necesita AW1_GROQ_API_KEY. "
                    "Consiguela gratis en https://console.groq.com/keys"
                )
        return self

    # -- derivados ----------------------------------------------------------
    @property
    def database_path(self) -> Path:
        return self.data_dir / "aw1.sqlite3"

    # uses_groq/judge_model solo miran el entorno (AW1_LLM_PROVIDER y afines):
    # sirven para probar Settings de forma aislada. La app en si nunca los usa
    # directo -pasa por core.llm_provider, que ademas respeta el override del
    # panel admin guardado en la base de datos.
    @property
    def uses_groq(self) -> bool:
        return self.llm_provider == "groq"

    @property
    def judge_model(self) -> str:
        if self.uses_groq:
            return self.groq_fast_model or self.groq_model
        return self.ollama_fast_model or self.ollama_model

    @property
    def gpt_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.get_secret_value().strip())

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_token and self.api_token.get_secret_value().strip())

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
