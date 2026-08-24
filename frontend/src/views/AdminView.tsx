import { useEffect, useState } from "react";
import clsx from "clsx";
import { Copy, KeyRound, Trash2 } from "lucide-react";
import { admin, ApiError, getAdminPassword, setAdminPassword } from "../lib/api";
import { PasswordGate } from "../components/PasswordGate";
import type { AdminConfig, AdminStatus, ApiKeyCreated, ApiKeySummary } from "../types";

function StatusRow({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b hairline py-2 last:border-b-0 text-[13px]">
      <span className="muted">{label}</span>
      <span className="flex items-center gap-2 font-medium">
        {ok !== undefined && (
          <span className={clsx("size-1.5 rounded-full", ok ? "bg-accent-500" : "bg-ink-400")} />
        )}
        {value}
      </span>
    </div>
  );
}

function StatusCard() {
  const [status, setStatus] = useState<AdminStatus | null>(null);

  useEffect(() => {
    admin.status().then(setStatus).catch(() => setStatus(null));
  }, []);

  return (
    <section className="card mt-7 p-5">
      <h2 className="text-[15px] font-semibold">Estado</h2>
      <p className="mt-1 text-[13px] muted">IA, memoria y accesos, todo junto.</p>
      <div className="mt-3">
        <StatusRow
          label="Proveedor / modelo"
          value={status ? `${status.llm_provider} · ${status.llm_model}` : "—"}
        />
        <StatusRow
          label="Base de datos"
          value={status?.database ?? "—"}
          ok={status?.database === "online"}
        />
        <StatusRow
          label="Token general (AW1_API_TOKEN)"
          value={status?.api_token_configured ? "configurado" : "sin configurar"}
          ok={status?.api_token_configured}
        />
        <StatusRow
          label="Claves de API emitidas"
          value={status ? String(status.api_keys_issued) : "—"}
        />
        <StatusRow
          label="Memoria"
          value={
            status
              ? `${status.conversations} conversaciones · ${status.messages} mensajes · ${status.saved_items} guardados`
              : "—"
          }
        />
      </div>
    </section>
  );
}

function Field({
  label,
  hint,
  configured,
  onSave,
  onClear,
  onTest,
}: {
  label: string;
  hint: string;
  configured: boolean;
  onSave: (value: string) => Promise<void>;
  onClear: () => Promise<void>;
  /** Si viene, se prueba la clave contra el proveedor antes de guardarla -asi
   * un valor pegado por error (ej. otra password) no queda guardado en
   * silencio hasta que falla horas despues, a mitad de un chat. */
  onTest?: (value: string) => Promise<{ ok: boolean; detail: string }>;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testError, setTestError] = useState("");

  return (
    <div className="border-b hairline py-3.5 last:border-b-0">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[13.5px] font-medium">
            {label}
            <span
              className={clsx(
                "chip !py-0 !px-1.5 text-[10px]",
                configured ? "border-accent-500/40 text-accent-600 dark:text-accent-300" : "muted",
              )}
            >
              {configured ? "configurado" : "sin configurar"}
            </span>
          </div>
          <p className="mt-0.5 text-[12px] muted">{hint}</p>
        </div>
        {configured && (
          <button
            type="button"
            className="btn btn-ghost shrink-0 px-2.5 py-1 text-[12px] hover:border-red-400 hover:text-red-500"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onClear();
                setValue("");
              } finally {
                setBusy(false);
              }
            }}
          >
            Quitar
          </button>
        )}
      </div>
      <div className="mt-2 flex gap-2">
        <input
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={configured ? "Reemplazar valor..." : "Pega el valor aqui..."}
          className="input"
        />
        <button
          type="button"
          className="btn btn-primary shrink-0 px-4 py-1.5 text-[13px]"
          disabled={busy || !value.trim()}
          onClick={async () => {
            setBusy(true);
            setTestError("");
            const clean = value.trim();
            try {
              if (onTest) {
                const result = await onTest(clean);
                if (!result.ok) {
                  setTestError(result.detail);
                  return;
                }
              }
              await onSave(clean);
              setValue("");
              setSaved(true);
              setTimeout(() => setSaved(false), 1600);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Probando..." : saved ? "Guardado" : onTest ? "Probar y guardar" : "Guardar"}
        </button>
      </div>
      {testError && <p className="mt-1.5 text-[12px] text-red-500">{testError}</p>}
    </div>
  );
}

function HostField({
  value: currentValue,
  onSave,
}: {
  value: string;
  onSave: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState(currentValue);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => setValue(currentValue), [currentValue]);

  return (
    <div className="border-b hairline py-3.5 last:border-b-0">
      <div className="text-[13.5px] font-medium">Host de Ollama</div>
      <p className="mt-0.5 text-[12px] muted">
        Por ejemplo, la URL de un tunel hacia el Ollama de tu Mac.
      </p>
      <div className="mt-2 flex gap-2">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="http://127.0.0.1:11434"
          className="input"
        />
        <button
          type="button"
          className="btn btn-primary shrink-0 px-4 py-1.5 text-[13px]"
          disabled={busy || !value.trim() || value.trim() === currentValue}
          onClick={async () => {
            setBusy(true);
            try {
              await onSave(value.trim());
              setSaved(true);
              setTimeout(() => setSaved(false), 1600);
            } finally {
              setBusy(false);
            }
          }}
        >
          {saved ? "Guardado" : "Guardar"}
        </button>
      </div>
    </div>
  );
}

function ApiKeysCard() {
  const [keys, setKeys] = useState<ApiKeySummary[] | null>(null);
  const [label, setLabel] = useState("");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [error, setError] = useState("");

  const load = () => admin.apiKeys().then(setKeys).catch(() => setKeys([]));
  useEffect(() => {
    load();
  }, []);

  return (
    <section className="card mt-4 p-5">
      <h2 className="text-[15px] font-semibold">Claves de API</h2>
      <p className="mt-1 text-[13px] muted">
        Ademas del token general, puedes emitir claves para llamar esta API desde afuera
        (scripts, otras apps) — sirven para <code className="font-mono">/api/prices</code> y
        el resto de la API igual que el token.
      </p>

      {created && (
        <div className="mt-3 rounded-[10px] border border-accent-500/40 bg-accent-500/5 p-3">
          <p className="text-[12.5px] font-medium text-accent-700 dark:text-accent-300">
            Copia esta clave ahora — no se vuelve a mostrar.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 truncate rounded-[8px] surface-soft px-2.5 py-1.5 text-[12.5px]">
              {created.value}
            </code>
            <button
              type="button"
              className="btn btn-ghost shrink-0 size-8 p-0"
              aria-label="Copiar"
              onClick={() => navigator.clipboard?.writeText(created.value)}
            >
              <Copy className="size-4" />
            </button>
          </div>
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <input
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="Nombre (ej: mi script de precios)"
          className="input"
        />
        <button
          type="button"
          className="btn btn-primary shrink-0 px-4 py-1.5 text-[13px]"
          disabled={!label.trim()}
          onClick={async () => {
            setError("");
            try {
              const row = await admin.createApiKey(label.trim());
              setCreated(row);
              setLabel("");
              load();
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "No se pudo crear la clave.");
            }
          }}
        >
          Crear
        </button>
      </div>
      {error && <p className="mt-2 text-[12.5px] text-red-500">{error}</p>}

      <div className="mt-4">
        {keys === null && <p className="text-[13px] muted">Cargando...</p>}
        {keys?.length === 0 && <p className="text-[13px] muted">Ninguna clave emitida todavia.</p>}
        {keys?.map((key) => (
          <div
            key={key.id}
            className="flex items-center justify-between gap-3 border-b hairline py-2.5 last:border-b-0"
          >
            <div className="flex items-center gap-2.5 text-[13px]">
              <KeyRound className="size-3.5 shrink-0 muted" />
              <span className="font-medium">{key.label}</span>
              <span className="muted font-mono text-[12px]">···{key.key_preview}</span>
            </div>
            <button
              type="button"
              className="btn btn-ghost shrink-0 size-7 p-0 hover:border-red-400 hover:text-red-500"
              aria-label="Revocar"
              onClick={async () => {
                if (!window.confirm(`Revocar la clave "${key.label}"?`)) return;
                await admin.deleteApiKey(key.id);
                if (created?.id === key.id) setCreated(null);
                load();
              }}
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

export function AdminView() {
  const [unlocked, setUnlocked] = useState(false);
  const [config, setConfig] = useState<AdminConfig | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (!getAdminPassword()) {
      setChecking(false);
      return;
    }
    admin
      .config()
      .then((cfg) => {
        setConfig(cfg);
        setUnlocked(true);
      })
      .catch(() => setAdminPassword(""))
      .finally(() => setChecking(false));
  }, []);

  const refresh = () => admin.config().then(setConfig);

  if (checking) return null;
  if (!unlocked) {
    return (
      <PasswordGate
        title="Panel admin"
        onUnlock={() => {
          setUnlocked(true);
          refresh();
        }}
      />
    );
  }

  return (
    <div className="h-full overflow-y-auto px-5 md:px-9">
      <div className="mx-auto max-w-3xl py-6 pb-16">
        <h1 className="text-[26px] font-semibold tracking-tight md:text-[30px]">Panel admin</h1>
        <p className="mt-1.5 text-[14px] muted">
          Claves de proveedores y accesos. Los cambios aplican al instante, sin reiniciar.
        </p>

        <StatusCard />

        <section className="card mt-4 p-5">
          <h2 className="text-[15px] font-semibold">Proveedor del LLM</h2>
          <p className="mt-1 text-[13px] muted">
            Cual usa el chat y el comparador de precios ahora mismo.
          </p>
          <div className="mt-3 flex gap-2">
            {(["ollama", "groq"] as const).map((provider) => (
              <button
                key={provider}
                type="button"
                className={clsx(
                  "btn flex-1 py-1.5 text-[13px] capitalize",
                  config?.llm_provider === provider ? "btn-primary" : "btn-ghost",
                )}
                onClick={async () => {
                  const updated = await admin.setSecret("llm_provider", provider);
                  setConfig(updated);
                }}
              >
                {provider}
              </button>
            ))}
          </div>

          {config?.llm_provider === "ollama" && (
            <HostField
              value={config?.ollama_host ?? ""}
              onSave={async (value) => setConfig(await admin.setSecret("ollama_host", value))}
            />
          )}
          {config?.llm_provider === "groq" && (
            <Field
              label="Clave de Groq"
              hint="console.groq.com/keys"
              configured={!!config?.groq_configured}
              onSave={async (value) => setConfig(await admin.setSecret("groq_api_key", value))}
              onClear={async () => setConfig(await admin.deleteSecret("groq_api_key"))}
              onTest={(value) => admin.testSecret("groq_api_key", value)}
            />
          )}
        </section>

        <section className="card mt-4 p-5">
          <h2 className="text-[15px] font-semibold">GPT (OpenAI)</h2>
          <p className="mt-1 text-[13px] muted">
            Se usa automaticamente para codigo, analisis largo o actualidad -sin pedir
            permiso cada vez. La etiqueta bajo cada respuesta del chat avisa cuando vino
            de aqui. Con esta clave configurada, los bots de Telegram tambien pueden
            generar y mandar imagenes (DALL-E) cuando alguien se lo pide.
          </p>
          <Field
            label="Clave de OpenAI"
            hint="platform.openai.com/api-keys"
            configured={!!config?.openai_configured}
            onSave={async (value) => setConfig(await admin.setSecret("openai_api_key", value))}
            onClear={async () => setConfig(await admin.deleteSecret("openai_api_key"))}
            onTest={(value) => admin.testSecret("openai_api_key", value)}
          />
        </section>

        <section className="card mt-4 p-5">
          <h2 className="text-[15px] font-semibold">Busqueda web (@buscar)</h2>
          <p className="mt-1 text-[13px] muted">
            Herramienta del chat para buscar en cualquier sitio -descripciones de producto,
            comparativas, noticias- ademas de la comparacion de precios en tiendas chilenas.
            Se invoca escribiendo <code className="font-mono">@buscar</code> en el chat.
          </p>
          <Field
            label="Clave de Brave Search"
            hint="brave.com/search/api"
            configured={!!config?.brave_configured}
            onSave={async (value) => setConfig(await admin.setSecret("brave_search_api_key", value))}
            onClear={async () => setConfig(await admin.deleteSecret("brave_search_api_key"))}
            onTest={(value) => admin.testSecret("brave_search_api_key", value)}
          />
        </section>

        <ApiKeysCard />
      </div>
    </div>
  );
}
