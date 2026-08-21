import { useEffect, useState } from "react";
import clsx from "clsx";
import {
  MessageSquare,
  Tags,
  Bookmark,
  SlidersHorizontal,
  Moon,
  Sun,
  Circle,
} from "lucide-react";
import type { Status } from "../types";
import { useTheme } from "../lib/useTheme";

export type ViewKey = "chat" | "prices" | "memory" | "settings";

const NAV: { key: ViewKey; label: string; icon: typeof MessageSquare }[] = [
  { key: "chat", label: "Chat", icon: MessageSquare },
  { key: "prices", label: "Precios", icon: Tags },
  { key: "memory", label: "Guardado", icon: Bookmark },
  { key: "settings", label: "Ajustes", icon: SlidersHorizontal },
];

function StatusDot({ status }: { status: Status | null }) {
  const online = status?.ollama === "online" && status?.model_ready;
  const partial = status?.ollama === "online" && !status?.model_ready;
  return (
    <span
      className={clsx(
        "size-1.5 rounded-full",
        online ? "bg-accent-500" : partial ? "bg-amber-500" : "bg-ink-400",
      )}
      aria-hidden
    />
  );
}

export function Shell({
  view,
  onView,
  status,
  children,
}: {
  view: ViewKey;
  onView: (key: ViewKey) => void;
  status: Status | null;
  children: React.ReactNode;
}) {
  const { dark, toggle } = useTheme();
  const [clock, setClock] = useState("");

  useEffect(() => {
    const tick = () => {
      setClock(new Date().toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" }));
      // Alineado al minuto siguiente: un reloj hh:mm no necesita 60 renders por minuto.
      return window.setTimeout(tick, 60_000 - (Date.now() % 60_000) + 50);
    };
    const id = tick();
    return () => window.clearTimeout(id);
  }, []);

  const label = status
    ? status.ollama === "online"
      ? status.model_ready
        ? status.model
        : `${status.model} no descargado`
      : "Ollama apagado"
    : "conectando";

  return (
    <div className="flex h-full flex-col md:flex-row">
      {/* Barra lateral en escritorio, barra inferior en movil */}
      <aside
        className={clsx(
          "z-20 shrink-0 border-hairline",
          "md:flex md:w-60 md:flex-col md:border-r md:px-3 md:py-5",
          "fixed inset-x-0 bottom-0 border-t md:static md:border-t-0",
          "surface md:surface-soft",
        )}
      >
        <div className="hidden items-center gap-2.5 px-3 pb-7 md:flex">
          <div className="grid size-8 place-items-center rounded-[10px] bg-accent-600">
            <svg viewBox="0 0 32 32" className="size-5" aria-hidden>
              <path d="M9 22 16 10l7 12" stroke="white" strokeWidth="2.6" fill="none" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight">AW1</div>
            <div className="text-[10px] uppercase tracking-[0.14em] muted">Asistente local</div>
          </div>
        </div>

        <nav className="flex md:flex-col md:gap-0.5" aria-label="Secciones">
          {NAV.map(({ key, label: text, icon: Icon }) => {
            const active = view === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => onView(key)}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "flex flex-1 flex-col items-center gap-1 px-3 py-2.5 text-[11px] font-medium transition-colors",
                  "md:flex-row md:gap-3 md:rounded-[10px] md:py-2 md:text-[13.5px]",
                  active
                    ? "text-accent-600 md:bg-white md:shadow-[0_1px_2px_rgba(0,0,0,0.05)] dark:text-accent-300 dark:md:bg-ink-900"
                    : "muted hover:text-[var(--text)]",
                )}
              >
                <Icon className="size-[18px]" strokeWidth={active ? 2.2 : 1.8} />
                {text}
              </button>
            );
          })}
        </nav>

        <div className="mt-auto hidden px-3 pt-5 md:block">
          <div className="flex items-center gap-2 border-t hairline pt-4 text-[11px] muted">
            <StatusDot status={status} />
            <span className="truncate" title={label}>
              {label}
            </span>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col pb-16 md:pb-0">
        <header className="flex items-center justify-between gap-4 px-5 pt-5 md:px-9 md:pt-7">
          <div className="flex items-center gap-2 md:hidden">
            <StatusDot status={status} />
            <span className="text-[11px] muted">{label}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {status?.browser && (
              <span className="chip hidden sm:inline-flex" title={status.browser.error || undefined}>
                <Circle
                  className={clsx(
                    "size-2 fill-current",
                    status.browser.ready ? "text-accent-500" : "text-ink-400",
                  )}
                />
                Navegador {status.browser.ready ? "listo" : "apagado"}
              </span>
            )}
            <span className="chip hidden sm:inline-flex tabular-nums">{clock}</span>
            <button
              type="button"
              onClick={toggle}
              className="btn btn-ghost size-8 p-0"
              aria-label={dark ? "Cambiar a tema claro" : "Cambiar a tema oscuro"}
            >
              {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
      </div>
    </div>
  );
}
