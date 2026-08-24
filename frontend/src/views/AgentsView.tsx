import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import clsx from "clsx";
import { ChevronDown, Sparkles, Trash2, Plus, X, Upload, Globe, Wand2 } from "lucide-react";
import { admin, ApiError, getAdminPassword, setAdminPassword } from "../lib/api";
import { PasswordGate } from "../components/PasswordGate";
import type {
  TelegramAgentApiSummary,
  TelegramAgentFileSummary,
  TelegramAgentSummary,
  TelegramTokenSummary,
} from "../types";

const PERSONALITY_NAMES: Record<string, string> = {
  calida: "Camila",
  directa: "Javiera",
  entusiasta: "Antonia",
};

function TokenRow({
  agentId,
  token,
  onChanged,
}: {
  agentId: string;
  token: TelegramTokenSummary;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const toggle = async () => {
    setBusy(true);
    try {
      await admin.setTelegramTokenEnabled(agentId, token.id, !token.enabled);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Quitar el bot @${token.bot_username || token.token_preview}? Tambien se quita su webhook de Telegram.`)) return;
    setBusy(true);
    try {
      await admin.deleteTelegramToken(agentId, token.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2 py-1 text-[12.5px]">
      <span className={clsx("size-1.5 shrink-0 rounded-full", token.enabled ? "bg-accent-500" : "bg-ink-400")} />
      <span className="font-mono">
        {token.bot_username ? `@${token.bot_username}` : `···${token.token_preview}`}
      </span>
      <button
        type="button"
        disabled={busy}
        onClick={toggle}
        className="chip ml-auto hover:text-[var(--text)]"
      >
        {token.enabled ? "Desactivar" : "Activar"}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={remove}
        aria-label="Quitar bot"
        className="btn btn-ghost size-6 p-0 hover:border-red-400 hover:text-red-500"
      >
        <Trash2 className="size-3" />
      </button>
    </div>
  );
}

function AddTokenForm({ agentId, onAdded }: { agentId: string; onAdded: () => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const add = async () => {
    const token = value.trim();
    if (!token) return;
    setBusy(true);
    setError("");
    try {
      const result = await admin.testTelegramToken(token);
      if (!result.ok) {
        setError(result.detail);
        return;
      }
      await admin.createTelegramToken(agentId, token);
      setValue("");
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo agregar el bot.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-1.5">
      <div className="flex gap-2">
        <input
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Token de otro bot de @BotFather..."
          className="input"
        />
        <button
          type="button"
          disabled={busy || !value.trim()}
          onClick={add}
          className="btn btn-ghost shrink-0 px-3 py-1.5 text-[13px]"
        >
          <Plus className="size-3.5" />
          Agregar bot
        </button>
      </div>
      {error && <p className="mt-1 text-[12px] text-red-500">{error}</p>}
    </div>
  );
}

function FilesSection({
  agentId,
  files,
  onChanged,
}: {
  agentId: string;
  files: TelegramAgentFileSummary[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const onFileSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await admin.uploadTelegramAgentFile(agentId, file);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo subir el archivo.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (fileId: string, filename: string) => {
    if (!window.confirm(`Quitar el archivo "${filename}"?`)) return;
    setBusy(true);
    try {
      await admin.deleteTelegramAgentFile(agentId, fileId);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="surface-soft rounded-[var(--radius-md)] p-3">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wide muted">Archivos</p>
        <label className={clsx("chip cursor-pointer hover:text-[var(--text)]", busy && "pointer-events-none opacity-50")}>
          <Upload className="size-3" />
          {busy ? "Subiendo..." : "Subir archivo"}
          <input
            type="file"
            accept=".pdf,.xlsx,.xlsm,.csv,.txt"
            className="hidden"
            disabled={busy}
            onChange={onFileSelected}
          />
        </label>
      </div>
      {files.length === 0 && (
        <p className="mt-1 text-[12.5px] muted">Sin archivos (menu, catalogo, precios...).</p>
      )}
      {files.map((file) => (
        <div key={file.id} className="flex items-center gap-2 py-1 text-[12.5px]">
          <span className="truncate font-mono">{file.filename}</span>
          <span className="muted shrink-0 text-[11px] tabular-nums">
            {file.char_count.toLocaleString("es-CL")} caracteres
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => remove(file.id, file.filename)}
            aria-label="Quitar archivo"
            className="btn btn-ghost ml-auto size-6 shrink-0 p-0 hover:border-red-400 hover:text-red-500"
          >
            <Trash2 className="size-3" />
          </button>
        </div>
      ))}
      {error && <p className="mt-1 text-[12px] text-red-500">{error}</p>}
    </div>
  );
}

function ApiRow({
  agentId,
  api,
  onChanged,
}: {
  agentId: string;
  api: TelegramAgentApiSummary;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const toggle = async () => {
    setBusy(true);
    try {
      await admin.setTelegramAgentApiEnabled(agentId, api.id, !api.enabled);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Quitar la API "${api.name}"?`)) return;
    setBusy(true);
    try {
      await admin.deleteTelegramAgentApi(agentId, api.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="py-1.5 text-[12.5px]">
      <div className="flex items-center gap-2">
        <span className={clsx("size-1.5 shrink-0 rounded-full", api.enabled ? "bg-accent-500" : "bg-ink-400")} />
        <span className="font-mono">{api.name}</span>
        <span className="chip shrink-0">{api.method}</span>
        <button
          type="button"
          disabled={busy}
          onClick={toggle}
          className="chip ml-auto hover:text-[var(--text)]"
        >
          {api.enabled ? "Desactivar" : "Activar"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={remove}
          aria-label="Quitar API"
          className="btn btn-ghost size-6 p-0 hover:border-red-400 hover:text-red-500"
        >
          <Trash2 className="size-3" />
        </button>
      </div>
      <p className="mt-0.5 truncate pl-3.5 text-[11.5px] muted" title={api.url}>
        {api.description}
      </p>
    </div>
  );
}

function AddApiForm({ agentId, onAdded }: { agentId: string; onAdded: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [url, setUrl] = useState("");
  const [method, setMethod] = useState("GET");
  const [headersText, setHeadersText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const add = async () => {
    if (!name.trim() || !description.trim() || !url.trim()) return;
    let headers: Record<string, string> = {};
    if (headersText.trim()) {
      try {
        headers = JSON.parse(headersText);
      } catch {
        setError('Los headers deben ser JSON valido, ej: {"Authorization": "Bearer ..."}');
        return;
      }
    }
    setBusy(true);
    setError("");
    try {
      await admin.createTelegramAgentApi(agentId, {
        name: name.trim(), description: description.trim(), url: url.trim(), method, headers,
      });
      setName("");
      setDescription("");
      setUrl("");
      setHeadersText("");
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo agregar la API.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex gap-2">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Nombre (ej: consultar_stock)"
          className="input"
        />
        <select
          value={method}
          onChange={(event) => setMethod(event.target.value)}
          className="input w-24 shrink-0"
        >
          <option value="GET">GET</option>
          <option value="POST">POST</option>
        </select>
      </div>
      <input
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        placeholder="Que hace y cuando usarla (esto lo lee el modelo para decidir)"
        className="input w-full"
      />
      <input
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder="https://tu-api.cl/stock?sku={query}"
        className="input w-full font-mono"
      />
      <input
        value={headersText}
        onChange={(event) => setHeadersText(event.target.value)}
        placeholder='Headers opcionales, JSON: {"Authorization": "Bearer ..."}'
        className="input w-full font-mono"
      />
      <button
        type="button"
        disabled={busy || !name.trim() || !description.trim() || !url.trim()}
        onClick={add}
        className="btn btn-ghost px-3 py-1.5 text-[13px]"
      >
        <Plus className="size-3.5" />
        Agregar API
      </button>
      {error && <p className="text-[12px] text-red-500">{error}</p>}
    </div>
  );
}

function ApisSection({
  agentId,
  apis,
  onChanged,
}: {
  agentId: string;
  apis: TelegramAgentApiSummary[];
  onChanged: () => void;
}) {
  return (
    <div className="surface-soft rounded-[var(--radius-md)] p-3">
      <div className="flex items-center gap-1.5">
        <Globe className="size-3 muted" />
        <p className="text-[11px] font-medium uppercase tracking-wide muted">
          APIs (el agente decide cuando llamarlas)
        </p>
      </div>
      {apis.length === 0 && <p className="mt-1 text-[12.5px] muted">Ninguna API conectada.</p>}
      {apis.map((api) => (
        <ApiRow key={api.id} agentId={agentId} api={api} onChanged={onChanged} />
      ))}
      <AddApiForm agentId={agentId} onAdded={onChanged} />
    </div>
  );
}

function AgentRow({
  agent,
  expanded,
  onToggle,
  onChanged,
}: {
  agent: TelegramAgentSummary;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const [label, setLabel] = useState(agent.label);
  const [prompt, setPrompt] = useState(agent.system_prompt);
  const [showGenerate, setShowGenerate] = useState(false);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLabel(agent.label);
    setPrompt(agent.system_prompt);
  }, [agent.label, agent.system_prompt]);

  const dirty = label.trim() !== agent.label || prompt !== agent.system_prompt;

  const save = async (changes: Partial<{ label: string; system_prompt: string; enabled: boolean }>) => {
    setBusy(true);
    setError("");
    try {
      await admin.updateTelegramAgent(agent.id, {
        label: changes.label ?? label.trim() ?? agent.label,
        system_prompt: changes.system_prompt ?? prompt,
        enabled: changes.enabled ?? agent.enabled,
      });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo guardar.");
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

  const humanize = async () => {
    const value = prompt.trim();
    if (!value) return;
    setBusy(true);
    setError("");
    try {
      const result = await admin.humanizePrompt(value);
      setPrompt(result.system_prompt);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo humanizar el prompt.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Borrar el agente "${agent.label}" y todos sus bots? Tambien se quitan sus webhooks de Telegram.`)) return;
    await admin.deleteTelegramAgent(agent.id);
    onChanged();
  };

  return (
    <div className="border-b hairline py-2.5 last:border-b-0">
      <div className="flex items-center gap-2.5">
        <button
          type="button"
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-2.5 text-left text-[13px]"
        >
          <ChevronDown className={clsx("size-3.5 shrink-0 transition-transform", expanded && "rotate-180")} />
          <span className={clsx("size-1.5 shrink-0 rounded-full", agent.enabled ? "bg-accent-500" : "bg-ink-400")} />
          <span className="truncate font-medium">{agent.label}</span>
          <span className="chip shrink-0 font-mono">
            {PERSONALITY_NAMES[agent.personality] ?? agent.personality}
          </span>
          <span className="muted hidden shrink-0 text-[12px] sm:inline">
            {agent.tokens.length} bot{agent.tokens.length === 1 ? "" : "s"}
          </span>
        </button>
        <button
          type="button"
          onClick={remove}
          aria-label="Borrar agente"
          className="btn btn-ghost size-7 shrink-0 p-0 hover:border-red-400 hover:text-red-500"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>

      {expanded && (
        <div className="mt-3 space-y-4 pl-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Nombre"
              className="input sm:max-w-56"
            />
            <div className="flex-1">
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={4}
                placeholder="Instrucciones propias del agente (system prompt)..."
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
                  disabled={busy || !prompt.trim()}
                  onClick={humanize}
                  className="chip hover:text-[var(--text)]"
                  title="Reescribe el texto actual para que suene mas natural, sin cambiar lo que dice"
                >
                  <Wand2 className="size-3" />
                  Humanizar
                </button>
                <button
                  type="button"
                  disabled={busy || !dirty}
                  onClick={() => save({})}
                  className="btn btn-primary ml-auto px-3 py-1 text-[12.5px]"
                >
                  Guardar cambios
                </button>
              </div>
              {showGenerate && (
                <div className="mt-2 flex gap-2">
                  <input
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Describe el agente en una frase..."
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
          </div>

          <div className="surface-soft rounded-[var(--radius-md)] p-3">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-medium uppercase tracking-wide muted">
                Bots de Telegram
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => save({ enabled: !agent.enabled })}
                className="chip hover:text-[var(--text)]"
              >
                {agent.enabled ? "Agente activo" : "Agente inactivo"}
              </button>
            </div>
            {agent.tokens.length === 0 && (
              <p className="mt-1 text-[12.5px] muted">Este agente todavia no tiene ningun bot.</p>
            )}
            {agent.tokens.map((token) => (
              <TokenRow key={token.id} agentId={agent.id} token={token} onChanged={onChanged} />
            ))}
            <AddTokenForm agentId={agent.id} onAdded={onChanged} />
          </div>

          <FilesSection agentId={agent.id} files={agent.files} onChanged={onChanged} />
          <ApisSection agentId={agent.id} apis={agent.apis} onChanged={onChanged} />

          {error && <p className="text-[12px] text-red-500">{error}</p>}
        </div>
      )}
    </div>
  );
}

function NewAgentForm({ onCreated, onCancel }: { onCreated: (id: string) => void; onCancel?: () => void }) {
  const [newLabel, setNewLabel] = useState("");
  const [newToken, setNewToken] = useState("");
  const [newPrompt, setNewPrompt] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [generateBusy, setGenerateBusy] = useState(false);
  const [generateError, setGenerateError] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");

  const generateNewPrompt = async () => {
    const value = newDescription.trim();
    if (!value) return;
    setGenerateBusy(true);
    setGenerateError("");
    try {
      const result = await admin.generatePrompt(value);
      setNewPrompt(result.system_prompt);
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.message : "No se pudo generar el prompt.");
    } finally {
      setGenerateBusy(false);
    }
  };

  const humanizeNewPrompt = async () => {
    const value = newPrompt.trim();
    if (!value) return;
    setGenerateBusy(true);
    setGenerateError("");
    try {
      const result = await admin.humanizePrompt(value);
      setNewPrompt(result.system_prompt);
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.message : "No se pudo humanizar el prompt.");
    } finally {
      setGenerateBusy(false);
    }
  };

  const create = async () => {
    if (!newLabel.trim()) return;
    setCreateBusy(true);
    setCreateError("");
    try {
      const row = await admin.createTelegramAgent({
        label: newLabel.trim(), system_prompt: newPrompt.trim(), bot_token: newToken.trim(),
      });
      onCreated(row.id);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "No se pudo crear el agente.");
    } finally {
      setCreateBusy(false);
    }
  };

  return (
    <div className="mt-4 border-t hairline pt-4">
      <p className="text-[13px] muted">
        Un agente es su prompt y personalidad (elegida al azar entre 3 al crearlo). Puede atender
        uno o varios bots de Telegram a la vez -pegale un primer token aca, o agregaselo despues.
        Necesita <code className="font-mono">AW1_PUBLIC_BASE_URL</code> configurado para
        registrar el webhook de cada bot.
      </p>

      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          value={newLabel}
          onChange={(event) => setNewLabel(event.target.value)}
          placeholder="Nombre (ej: Atencion al cliente)"
          className="input"
        />
        <input
          type="password"
          value={newToken}
          onChange={(event) => setNewToken(event.target.value)}
          placeholder="Token de @BotFather (opcional)"
          className="input"
        />
      </div>

      <div className="mt-2">
        <textarea
          value={newPrompt}
          onChange={(event) => setNewPrompt(event.target.value)}
          rows={4}
          placeholder="Instrucciones propias del agente. Puedes dejarlo vacio y usar el estilo por defecto."
          className="input w-full resize-y"
        />
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <input
            value={newDescription}
            onChange={(event) => setNewDescription(event.target.value)}
            placeholder="Describe el agente en una frase..."
            className="input max-w-xs"
          />
          <button
            type="button"
            disabled={generateBusy || !newDescription.trim()}
            onClick={generateNewPrompt}
            className="chip hover:text-[var(--text)]"
          >
            <Sparkles className="size-3" />
            {generateBusy ? "Generando..." : "Generar con IA"}
          </button>
          <button
            type="button"
            disabled={generateBusy || !newPrompt.trim()}
            onClick={humanizeNewPrompt}
            className="chip hover:text-[var(--text)]"
            title="Reescribe el texto actual para que suene mas natural, sin cambiar lo que dice"
          >
            <Wand2 className="size-3" />
            Humanizar
          </button>
        </div>
        {generateError && <p className="mt-1.5 text-[12px] text-red-500">{generateError}</p>}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          disabled={createBusy || !newLabel.trim()}
          onClick={create}
          className="btn btn-primary px-4 py-1.5 text-[13px]"
        >
          {createBusy ? "Creando..." : "Crear agente"}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className="btn btn-ghost px-3 py-1.5 text-[13px]">
            Cancelar
          </button>
        )}
      </div>
      {createError && <p className="mt-2 text-[12.5px] text-red-500">{createError}</p>}
    </div>
  );
}

function TelegramAgentsCard() {
  const [agents, setAgents] = useState<TelegramAgentSummary[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);

  const load = () => admin.telegramAgents().then(setAgents).catch(() => setAgents([]));
  useEffect(() => {
    load();
  }, []);

  const onCreated = (id: string) => {
    setShowNewForm(false);
    setExpandedId(id);
    load();
  };

  const noAgentsYet = agents?.length === 0;

  return (
    <section className="card mt-7 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-[15px] font-semibold">Agentes</h2>
        {!showNewForm && (
          <button
            type="button"
            onClick={() => setShowNewForm(true)}
            className="btn btn-primary px-3 py-1.5 text-[13px]"
          >
            <Plus className="size-3.5" />
            Nuevo agente
          </button>
        )}
      </div>

      <div className="mt-1">
        {agents === null && <p className="text-[13px] muted">Cargando...</p>}
        {noAgentsYet && !showNewForm && (
          <p className="mt-2 text-[13px] muted">Ningun agente creado todavia.</p>
        )}
        {agents?.map((agent) => (
          <AgentRow
            key={agent.id}
            agent={agent}
            expanded={expandedId === agent.id}
            onToggle={() => setExpandedId(expandedId === agent.id ? null : agent.id)}
            onChanged={load}
          />
        ))}
      </div>

      {showNewForm && (
        <div className="relative">
          {!noAgentsYet && (
            <button
              type="button"
              onClick={() => setShowNewForm(false)}
              aria-label="Cerrar"
              className="btn btn-ghost absolute right-0 top-3 size-6 p-0"
            >
              <X className="size-3.5" />
            </button>
          )}
          <NewAgentForm onCreated={onCreated} onCancel={!noAgentsYet ? () => setShowNewForm(false) : undefined} />
        </div>
      )}
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
          Agentes de Telegram: cada uno tiene su prompt y personalidad, y puede atender uno o
          varios bots a la vez. Corren todos al mismo tiempo, sin limite.
        </p>

        <TelegramAgentsCard />
      </div>
    </div>
  );
}
