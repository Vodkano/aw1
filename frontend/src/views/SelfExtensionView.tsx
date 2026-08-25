import { useEffect, useState } from "react";
import clsx from "clsx";
import {
  ChevronDown,
  Trash2,
  Wand2,
  FlaskConical,
  Check,
  X,
  Plus,
} from "lucide-react";
import { admin, ApiError, getAdminPassword, setAdminPassword } from "../lib/api";
import { PasswordGate } from "../components/PasswordGate";
import type {
  CapabilityGapSummary,
  GeneratedToolDetail,
  GeneratedToolSummary,
  TelegramAgentSummary,
} from "../types";

const STATUS_LABEL: Record<string, string> = {
  PROPOSED: "Propuesta",
  GENERATING: "Con codigo, sin probar",
  PENDING_APPROVAL: "Lista para revisar",
  ACTIVE: "Activa",
  REJECTED: "Rechazada",
};

const STATUS_COLOR: Record<string, string> = {
  PROPOSED: "bg-ink-400",
  GENERATING: "bg-amber-500",
  PENDING_APPROVAL: "bg-amber-500",
  ACTIVE: "bg-accent-500",
  REJECTED: "bg-red-400",
};

function StatusPill({ status }: { status: string }) {
  return (
    <span className="chip shrink-0">
      <span className={clsx("size-1.5 rounded-full", STATUS_COLOR[status] ?? "bg-ink-400")} />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function GapRow({
  gap,
  agentLabel,
  onCreated,
}: {
  gap: CapabilityGapSummary;
  agentLabel: string;
  onCreated: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const createTool = async () => {
    if (!gap.agent_id) return;
    setBusy(true);
    setError("");
    try {
      await admin.createGeneratedTool({
        agent_id: gap.agent_id, name: gap.name || "herramienta",
        description: gap.description || gap.why, source_gap_reasoning_id: gap.id,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo crear la herramienta.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-b hairline py-2.5 last:border-b-0">
      <div className="flex items-start gap-2.5 text-[13px]">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{gap.name || "(sin nombre)"}</span>
            <span className="chip shrink-0 font-mono">{agentLabel}</span>
          </div>
          <p className="mt-1 text-[12.5px] muted">{gap.description}</p>
          {gap.why && <p className="mt-0.5 text-[12px] muted">Motivo: {gap.why}</p>}
        </div>
        {gap.tool_id ? (
          <StatusPill status={gap.tool_status ?? "PROPOSED"} />
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={createTool}
            className="chip shrink-0 hover:text-[var(--text)]"
          >
            <Plus className="size-3" />
            Crear herramienta
          </button>
        )}
      </div>
      {error && <p className="mt-1 text-[12px] text-red-500">{error}</p>}
    </div>
  );
}

function CapabilityGapsSection({
  gaps,
  agentLabels,
  onChanged,
}: {
  gaps: CapabilityGapSummary[];
  agentLabels: Record<string, string>;
  onChanged: () => void;
}) {
  return (
    <section className="card mt-7 p-5">
      <h2 className="text-[15px] font-semibold">Capacidades pedidas</h2>
      <p className="mt-1 text-[13px] muted">
        Cuando un agente de Telegram se topa con algo que no puede resolver, lo anota aca en vez
        de inventar que puede -vos decidis si vale la pena convertirlo en una herramienta.
      </p>
      <div className="mt-2">
        {gaps.length === 0 && (
          <p className="text-[13px] muted">Ningun pedido registrado todavia.</p>
        )}
        {gaps.map((gap) => (
          <GapRow
            key={gap.id}
            gap={gap}
            agentLabel={agentLabels[gap.agent_id ?? ""] ?? "(agente desconocido)"}
            onCreated={onChanged}
          />
        ))}
      </div>
    </section>
  );
}

function ToolCard({
  tool,
  agentLabel,
  expanded,
  onToggle,
  onChanged,
}: {
  tool: GeneratedToolSummary;
  agentLabel: string;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<GeneratedToolDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!expanded) return;
    admin.generatedTool(tool.id).then(setDetail).catch(() => setDetail(null));
  }, [expanded, tool.id, tool.status]);

  const run = async (action: () => Promise<GeneratedToolDetail>) => {
    setBusy(true);
    setError("");
    try {
      const updated = await action();
      setDetail(updated);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo completar la accion.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Borrar la herramienta "${tool.name}"?`)) return;
    setBusy(true);
    try {
      await admin.deleteGeneratedTool(tool.id);
      onChanged();
    } finally {
      setBusy(false);
    }
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
          <span className="truncate font-medium">{tool.name}</span>
          <span className="chip shrink-0 font-mono">{agentLabel}</span>
          <StatusPill status={tool.status} />
          {tool.call_count > 0 && (
            <span className="muted hidden shrink-0 text-[12px] sm:inline">
              {tool.call_count} uso{tool.call_count === 1 ? "" : "s"}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={remove}
          aria-label="Borrar herramienta"
          className="btn btn-ghost size-7 shrink-0 p-0 hover:border-red-400 hover:text-red-500"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>

      {expanded && (
        <div className="mt-3 space-y-3 pl-6">
          <p className="text-[12.5px] muted">{tool.description}</p>

          {detail?.code && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide muted">Codigo generado</p>
              <pre className="surface-soft mt-1 max-h-64 overflow-auto rounded-[var(--radius-md)] p-2.5 text-[12px] leading-relaxed">
                <code>{detail.code}</code>
              </pre>
            </div>
          )}

          {detail?.sandbox_result && Object.keys(detail.sandbox_result).length > 0 && (
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide muted">
                Resultado de la prueba en sandbox
              </p>
              <pre className="surface-soft mt-1 max-h-40 overflow-auto rounded-[var(--radius-md)] p-2.5 text-[12px] leading-relaxed">
                <code>{JSON.stringify(detail.sandbox_result, null, 2)}</code>
              </pre>
            </div>
          )}

          {tool.status === "REJECTED" && detail?.reject_reason && (
            <p className="text-[12.5px] text-red-500">Motivo del rechazo: {detail.reject_reason}</p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {tool.status === "PROPOSED" && (
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => admin.generateGeneratedToolCode(tool.id))}
                className="btn btn-primary px-3 py-1.5 text-[13px]"
              >
                <Wand2 className="size-3.5" />
                Generar codigo
              </button>
            )}
            {tool.status === "GENERATING" && (
              <button
                type="button"
                disabled={busy}
                onClick={() => run(() => admin.testGeneratedTool(tool.id))}
                className="btn btn-primary px-3 py-1.5 text-[13px]"
              >
                <FlaskConical className="size-3.5" />
                Probar en sandbox
              </button>
            )}
            {tool.status === "PENDING_APPROVAL" && (
              <>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => run(() => admin.approveGeneratedTool(tool.id))}
                  className="btn btn-primary px-3 py-1.5 text-[13px]"
                >
                  <Check className="size-3.5" />
                  Aprobar
                </button>
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Motivo del rechazo (opcional)"
                  className="input max-w-xs text-[12.5px]"
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => run(() => admin.rejectGeneratedTool(tool.id, reason))}
                  className="btn btn-ghost px-3 py-1.5 text-[13px] hover:border-red-400 hover:text-red-500"
                >
                  <X className="size-3.5" />
                  Rechazar
                </button>
              </>
            )}
          </div>
          {error && <p className="text-[12px] text-red-500">{error}</p>}
        </div>
      )}
    </div>
  );
}

function GeneratedToolsSection({
  tools,
  agentLabels,
  onChanged,
}: {
  tools: GeneratedToolSummary[];
  agentLabels: Record<string, string>;
  onChanged: () => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <section className="card mt-7 p-5">
      <h2 className="text-[15px] font-semibold">Herramientas generadas</h2>
      <p className="mt-1 text-[13px] muted">
        Cada una pasa por generar codigo, probarlo aislado, y que la apruebes a mano -recien ahi
        queda disponible en conversaciones reales. Nunca se activa sola.
      </p>
      <div className="mt-2">
        {tools.length === 0 && (
          <p className="text-[13px] muted">
            Ninguna herramienta generada todavia -se crean desde un pedido de arriba.
          </p>
        )}
        {tools.map((tool) => (
          <ToolCard
            key={tool.id}
            tool={tool}
            agentLabel={agentLabels[tool.agent_id] ?? "(agente desconocido)"}
            expanded={expandedId === tool.id}
            onToggle={() => setExpandedId(expandedId === tool.id ? null : tool.id)}
            onChanged={onChanged}
          />
        ))}
      </div>
    </section>
  );
}

function SelfExtensionContent() {
  const [gaps, setGaps] = useState<CapabilityGapSummary[] | null>(null);
  const [tools, setTools] = useState<GeneratedToolSummary[] | null>(null);
  const [agents, setAgents] = useState<TelegramAgentSummary[]>([]);

  const load = () => {
    admin.capabilityGaps().then(setGaps).catch(() => setGaps([]));
    admin.generatedTools().then(setTools).catch(() => setTools([]));
    admin.telegramAgents().then(setAgents).catch(() => setAgents([]));
  };

  useEffect(() => {
    load();
  }, []);

  const agentLabels = Object.fromEntries(agents.map((agent) => [agent.id, agent.label]));

  return (
    <div className="h-full overflow-y-auto px-5 md:px-9">
      <div className="mx-auto max-w-3xl py-6 pb-16">
        <h1 className="text-[26px] font-semibold tracking-tight md:text-[30px]">Auto-extension</h1>
        <p className="mt-1.5 text-[14px] muted">
          Cuando a un agente le falta una capacidad, queda anotado aca -nunca se genera ni activa
          codigo solo, cada paso lo arrancas vos.
        </p>

        {gaps === null || tools === null ? (
          <p className="mt-6 text-[13px] muted">Cargando...</p>
        ) : (
          <>
            <CapabilityGapsSection gaps={gaps} agentLabels={agentLabels} onChanged={load} />
            <GeneratedToolsSection tools={tools} agentLabels={agentLabels} onChanged={load} />
          </>
        )}
      </div>
    </div>
  );
}

export function SelfExtensionView() {
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
    return <PasswordGate title="Auto-extension" onUnlock={() => setUnlocked(true)} />;
  }

  return <SelfExtensionContent />;
}
