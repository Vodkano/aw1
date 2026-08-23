import { useEffect, useState } from "react";
import clsx from "clsx";
import { ChevronDown, Sparkles, Trash2 } from "lucide-react";
import { admin, ApiError, getAdminPassword, setAdminPassword } from "../lib/api";
import { PasswordGate } from "../components/PasswordGate";
import type { TelegramProfileDetail, TelegramProfileSummary } from "../types";

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
    <section className="card mt-7 p-5">
      <h2 className="text-[15px] font-semibold">Nuevo agente</h2>
      <p className="mt-1 text-[13px] muted">
        Cada agente es un bot de Telegram independiente (su propio token de @BotFather), con su
        propia personalidad. Necesita <code className="font-mono">AW1_PUBLIC_BASE_URL</code>{" "}
        configurado para registrar el webhook.
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
        {profiles?.length === 0 && <p className="text-[13px] muted">Ningun agente creado todavia.</p>}
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

export function AgentsView() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (!getAdminPassword()) {
      setChecking(false);
      return;
    }
    admin
      .config()
      .then(() => setUnlocked(true))
      .catch(() => setAdminPassword(""))
      .finally(() => setChecking(false));
  }, []);

  if (checking) return null;
  if (!unlocked) {
    return <PasswordGate title="Agentes" onUnlock={() => setUnlocked(true)} />;
  }

  return (
    <div className="h-full overflow-y-auto px-5 md:px-9">
      <div className="mx-auto max-w-3xl py-6 pb-16">
        <h1 className="text-[26px] font-semibold tracking-tight md:text-[30px]">Agentes</h1>
        <p className="mt-1.5 text-[14px] muted">
          Bots de Telegram, cada uno con su propio token y personalidad. Corren todos al mismo
          tiempo, sin limite -sumar uno es solo crear el perfil.
        </p>

        <TelegramProfilesCard />
      </div>
    </div>
  );
}
