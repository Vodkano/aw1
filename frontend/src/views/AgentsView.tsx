import { useEffect, useState } from "react";
import clsx from "clsx";
import { ChevronDown, Sparkles, Trash2, Plus } from "lucide-react";
import { admin, ApiError, getAdminPassword, setAdminPassword } from "../lib/api";
import { PasswordGate } from "../components/PasswordGate";
import type { TelegramAgentSummary, TelegramTokenSummary } from "../types";

const PERSONALITY_LABELS: Record<string, string> = {
  calida: "Camila · cercana y calida",
  directa: "Javiera · directa y eficiente",
  entusiasta: "Antonia · entusiasta y positiva",
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

  const save = async (changes: Partial<{ label: string; system_prompt: string; enabled: boolean }>) => {
    setBusy(true);
    setError("");
    try {
      await admin.updateTelegramAgent(agent.id, {
        label: changes.label ?? label,
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

  const remove = async () => {
    if (!window.confirm(`Borrar el agente "${agent.label}" y todos sus bots? Tambien se quitan sus webhooks de Telegram.`)) return;
    await admin.deleteTelegramAgent(agent.id);
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
        <span className={clsx("size-1.5 shrink-0 rounded-full", agent.enabled ? "bg-accent-500" : "bg-ink-400")} />
        <span className="font-medium">{agent.label}</span>
        <span className="muted text-[12px]">
          {agent.tokens.length} bot{agent.tokens.length === 1 ? "" : "s"} ·{" "}
          {PERSONALITY_LABELS[agent.personality] ?? agent.personality}
        </span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3 pl-6">
          <div className="flex gap-2">
            <input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Nombre"
              className="input"
            />
            <button
              type="button"
              disabled={busy || !label.trim() || label === agent.label}
              onClick={() => save({ label: label.trim() })}
              className="btn btn-ghost shrink-0 px-3 py-1.5 text-[13px]"
            >
              Guardar
            </button>
          </div>

          <div>
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={4}
              placeholder="Personalidad del agente (system prompt)..."
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
                disabled={busy || prompt === agent.system_prompt}
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

          <div>
            <p className="text-[12px] font-medium uppercase tracking-wide muted">Bots de Telegram</p>
            {agent.tokens.length === 0 && (
              <p className="mt-1 text-[12.5px] muted">Este agente todavia no tiene ningun bot.</p>
            )}
            {agent.tokens.map((token) => (
              <TokenRow key={token.id} agentId={agent.id} token={token} onChanged={onChanged} />
            ))}
            <AddTokenForm agentId={agent.id} onAdded={onChanged} />
          </div>

          <div className="flex items-center justify-between">
            <button
              type="button"
              disabled={busy}
              onClick={() => save({ enabled: !agent.enabled })}
              className="chip hover:text-[var(--text)]"
            >
              {agent.enabled ? "Activo · click para desactivar" : "Inactivo · click para activar"}
            </button>
            <button
              type="button"
              onClick={remove}
              aria-label="Borrar agente"
              className="btn btn-ghost size-7 p-0 hover:border-red-400 hover:text-red-500"
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
          {error && <p className="text-[12px] text-red-500">{error}</p>}
        </div>
      )}
    </div>
  );
}

function TelegramAgentsCard() {
  const [agents, setAgents] = useState<TelegramAgentSummary[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("");
  const [newToken, setNewToken] = useState("");
  const [newPrompt, setNewPrompt] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [generateBusy, setGenerateBusy] = useState(false);
  const [generateError, setGenerateError] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");

  const load = () => admin.telegramAgents().then(setAgents).catch(() => setAgents([]));
  useEffect(() => {
    load();
  }, []);

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

  const create = async () => {
    if (!newLabel.trim()) return;
    setCreateBusy(true);
    setCreateError("");
    try {
      const row = await admin.createTelegramAgent({
        label: newLabel.trim(), system_prompt: newPrompt.trim(), bot_token: newToken.trim(),
      });
      setNewLabel("");
      setNewToken("");
      setNewPrompt("");
      setNewDescription("");
      setExpandedId(row.id);
      load();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "No se pudo crear el agente.");
    } finally {
      setCreateBusy(false);
    }
  };

  return (
    <section className="card mt-7 p-5">
      <h2 className="text-[15px] font-semibold">Nuevo agente</h2>
      <p className="mt-1 text-[13px] muted">
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
        </div>
        {generateError && <p className="mt-1.5 text-[12px] text-red-500">{generateError}</p>}
      </div>

      <button
        type="button"
        disabled={createBusy || !newLabel.trim()}
        onClick={create}
        className="btn btn-primary mt-3 px-4 py-1.5 text-[13px]"
      >
        {createBusy ? "Creando..." : "Crear agente"}
      </button>
      {createError && <p className="mt-2 text-[12.5px] text-red-500">{createError}</p>}

      <div className="mt-4">
        {agents === null && <p className="text-[13px] muted">Cargando...</p>}
        {agents?.length === 0 && <p className="text-[13px] muted">Ningun agente creado todavia.</p>}
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
