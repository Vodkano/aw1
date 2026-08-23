import { useEffect, useState } from "react";
import clsx from "clsx";
import { ChevronDown, Copy, KeyRound, Lock, Sparkles, Trash2 } from "lucide-react";
import { admin, ApiError, getAdminPassword, setAdminPassword } from "../lib/api";
import type {
  AdminConfig,
  AdminStatus,
  ApiKeyCreated,
  ApiKeySummary,
  TelegramProfileDetail,
  TelegramProfileSummary,
} from "../types";

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

function TelegramProfileRow({
  profile,
  expanded,
  onToggle,
  onChanged,
}: {
  profile: TelegramProfileSummary;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<TelegramProfileDetail | null>(null);
  const [label, setLabel] = useState(profile.label);
  const [token, setToken] = useState("");
  const [prompt, setPrompt] = useState(profile.system_prompt);
  const [showGenerate, setShowGenerate] = useState(false);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tokenError, setTokenError] = useState("");

  useEffect(() => {
    if (expanded && !detail) {
      admin
        .telegramProfile(profile.id)
        .then((row) => {
          setDetail(row);
          setLabel(row.label);
          setPrompt(row.system_prompt);
        })
        .catch(() => undefined);
    }
  }, [expanded, detail, profile.id]);

  const save = async (changes: Partial<{ label: string; bot_token: string; system_prompt: string; enabled: boolean }>) => {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      const updated = await admin.updateTelegramProfile(profile.id, {
        label: changes.label ?? label,
        bot_token: changes.bot_token ?? detail.bot_token,
        system_prompt: changes.system_prompt ?? prompt,
        enabled: changes.enabled ?? detail.enabled,
      });
      setDetail(updated);
      setLabel(updated.label);
      setPrompt(updated.system_prompt);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };

  const testAndSaveToken = async () => {
    const value = token.trim();
    if (!value) return;
    setBusy(true);
    setTokenError("");
    try {
      const result = await admin.testTelegramToken(value);
      if (!result.ok) {
        setTokenError(result.detail);
        return;
      }
      await save({ bot_token: value });
      setToken("");
    } finally {
      setBusy(false);
    }
  };

  const generate = async () => {
    const value = description.trim();
    if (!value) return;
    setBusy(true);
    setError("");
    try {
      const result = await admin.generatePrompt(value);
      setPrompt(result.system_prompt);
      setShowGenerate(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo generar el prompt.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Borrar el bot "${profile.label}"? Tambien se quita su webhook de Telegram.`)) return;
    await admin.deleteTelegramProfile(profile.id);
    onChanged();
  };

  return (
    <div className="border-b hairline py-2.5 last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2.5 text-left text-[13px]"
      >
        <ChevronDown className={clsx("size-3.5 shrink-0 transition-transform", expanded && "rotate-180")} />
        <span className={clsx("size-1.5 shrink-0 rounded-full", profile.enabled ? "bg-accent-500" : "bg-ink-400")} />
        <span className="font-medium">{profile.label}</span>
        <span className="muted font-mono text-[12px]">
          {profile.bot_username ? `@${profile.bot_username}` : `···${profile.token_preview}`}
        </span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3 pl-6">
          {!detail ? (
            <p className="text-[13px] muted">Cargando...</p>
          ) : (
            <>
              <div className="flex gap-2">
                <input
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="Nombre"
                  className="input"
                />
                <button
                  type="button"
                  disabled={busy || !label.trim() || label === detail.label}
                  onClick={() => save({ label: label.trim() })}
                  className="btn btn-ghost shrink-0 px-3 py-1.5 text-[13px]"
                >
                  Guardar
                </button>
              </div>

              <div className="flex gap-2">
                <input
                  type="password"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  placeholder="Reemplazar token de @BotFather..."
                  className="input"
                />
                <button
                  type="button"
                  disabled={busy || !token.trim()}
                  onClick={testAndSaveToken}
                  className="btn btn-primary shrink-0 px-3 py-1.5 text-[13px]"
                >
                  Probar y guardar
                </button>
              </div>
              {tokenError && <p className="text-[12px] text-red-500">{tokenError}</p>}

              <div>
                <textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  rows={4}
                  placeholder="Personalidad del bot (system prompt)..."
                  className="input w-full resize-y"
                />
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowGenerate((value) => !value)}
                    className="chip hover:text-[var(--text)]"
                  >
                    <Sparkles className="size-3" />
                    Generar con IA
                  </button>
                  <button
                    type="button"
                    disabled={busy || prompt === detail.system_prompt}
                    onClick={() => save({ system_prompt: prompt })}
                    className="btn btn-primary px-3 py-1 text-[12.5px]"
                  >
                    Guardar prompt
                  </button>
                </div>
                {showGenerate && (
                  <div className="mt-2 flex gap-2">
                    <input
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      placeholder="Describe el bot en una frase..."
                      className="input"
                    />
                    <button
                      type="button"
                      disabled={busy || !description.trim()}
                      onClick={generate}
                      className="btn btn-ghost shrink-0 px-3 py-1.5 text-[13px]"
                    >
                      Generar
                    </button>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => save({ enabled: !detail.enabled })}
                  className="chip hover:text-[var(--text)]"
                >
                  {detail.enabled ? "Activo · click para desactivar" : "Inactivo · click para activar"}
                </button>
                <button
                  type="button"
                  onClick={remove}
                  aria-label="Borrar"
                  className="btn btn-ghost size-7 p-0 hover:border-red-400 hover:text-red-500"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
              {!detail.webhook_registered && (
                <p className="text-[12px] text-amber-600 dark:text-amber-400">
                  El webhook no quedo registrado en Telegram -reemplaza el token para reintentar.
                </p>
              )}
              {error && <p className="text-[12px] text-red-500">{error}</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function TelegramProfilesCard() {
  const [profiles, setProfiles] = useState<TelegramProfileSummary[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("");
  const [newToken, setNewToken] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = () => admin.telegramProfiles().then(setProfiles).catch(() => setProfiles([]));
  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    if (!newLabel.trim() || !newToken.trim()) return;
    setCreateBusy(true);
    setCreateError("");
    try {
      const row = await admin.createTelegramProfile({
        label: newLabel.trim(), bot_token: newToken.trim(), system_prompt: "",
      });
      setNewLabel("");
      setNewToken("");
      setExpandedId(row.id);
      load();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "No se pudo crear el bot.");
    } finally {
      setCreateBusy(false);
    }
  };

  return (
    <section className="card mt-4 p-5">
      <h2 className="text-[15px] font-semibold">Bots de Telegram</h2>
      <p className="mt-1 text-[13px] muted">
        Cada perfil es un bot independiente (su propio token de @BotFather), con su propia
        personalidad. Necesita <code className="font-mono">AW1_PUBLIC_BASE_URL</code> configurado
        para registrar el webhook.
      </p>

      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          value={newLabel}
          onChange={(event) => setNewLabel(event.target.value)}
          placeholder="Nombre (ej: Bot personal)"
          className="input"
        />
        <input
          type="password"
          value={newToken}
          onChange={(event) => setNewToken(event.target.value)}
          placeholder="Token de @BotFather"
          className="input"
        />
        <button
          type="button"
          disabled={createBusy || !newLabel.trim() || !newToken.trim()}
          onClick={create}
          className="btn btn-primary shrink-0 px-4 py-1.5 text-[13px]"
        >
          {createBusy ? "Creando..." : "Crear"}
        </button>
      </div>
      {createError && <p className="mt-2 text-[12.5px] text-red-500">{createError}</p>}

      <div className="mt-4">
        {profiles === null && <p className="text-[13px] muted">Cargando...</p>}
        {profiles?.length === 0 && <p className="text-[13px] muted">Ningun bot creado todavia.</p>}
        {profiles?.map((profile) => (
          <TelegramProfileRow
            key={profile.id}
            profile={profile}
            expanded={expandedId === profile.id}
            onToggle={() => setExpandedId(expandedId === profile.id ? null : profile.id)}
            onChanged={load}
          />
        ))}
      </div>
    </section>
  );
}

function PasswordGate({ onUnlock }: { onUnlock: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError("");
    setAdminPassword(value.trim());
    try {
      await admin.config();
      onUnlock();
    } catch (err) {
      setAdminPassword("");
      setError(err instanceof ApiError ? err.message : "No se pudo verificar la password.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center px-5">
      <div className="card w-full max-w-sm p-6 text-center">
        <div className="mx-auto grid size-10 place-items-center rounded-[10px] bg-accent-600">
          <Lock className="size-5 text-white" />
        </div>
        <h1 className="mt-3 text-[17px] font-semibold">Panel admin</h1>
        <p className="mt-1 text-[13px] muted">Solo para ti. Pide una password aparte del token.</p>
        <div className="mt-4 flex flex-col gap-2">
          <input
            type="password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && submit()}
            placeholder="Password de administrador"
            className="input text-center"
            autoFocus
          />
          <button
            type="button"
            className="btn btn-primary py-1.5 text-[13px]"
            disabled={busy || !value.trim()}
            onClick={submit}
          >
            Entrar
          </button>
        </div>
        {error && <p className="mt-2 text-[12.5px] text-red-500">{error}</p>}
      </div>
    </div>
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
            de aqui.
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

        <ApiKeysCard />
        <TelegramProfilesCard />
      </div>
    </div>
  );
}
