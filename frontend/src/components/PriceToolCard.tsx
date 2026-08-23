import clsx from "clsx";
import { ExternalLink, Sparkles } from "lucide-react";
import { STATUS_STYLE, STATUS_TEXT } from "../lib/priceSearch";
import { clp } from "../lib/format";
import type { PriceToolState } from "../types";

/** Tarjeta compacta de la herramienta de precios, dentro de una burbuja del chat. */
export function PriceToolCard({
  state,
  onOpenFull,
}: {
  state: PriceToolState;
  onOpenFull: (query: string) => void;
}) {
  const offers = state.comparison?.offers ?? state.offers;
  const best = offers[0];
  const running = state.phase !== "done" && state.phase !== "error";

  return (
    <div className="card mt-2 max-w-md overflow-hidden p-3.5">
      {state.plan && (
        <div className="mb-2 text-[12px] muted">
          Buscando <span className="font-medium text-[var(--text)]">{state.plan.product}</span>
        </div>
      )}

      {state.stores.length > 0 && running && (
        <ul className="mb-2 space-y-1">
          {state.stores.map((store) => (
            <li key={store.slug} className="flex items-center gap-2 text-[12px]">
              <span className={clsx("size-1.5 shrink-0 rounded-full", STATUS_STYLE[store.status])} />
              <span className="min-w-20 font-medium">{store.name}</span>
              <span className="muted">
                {store.status === "running" || store.status === "pending"
                  ? STATUS_TEXT[store.status]
                  : `${store.offers} precio${store.offers === 1 ? "" : "s"}`}
              </span>
            </li>
          ))}
        </ul>
      )}

      {state.phase === "error" && <p className="text-[13px] text-red-500">{state.error}</p>}

      {best && (
        <div className="rounded-[10px] surface-soft p-3">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-[19px] font-semibold tabular-nums">{clp(best.price_clp)}</span>
            <span className="text-[12.5px] muted">en {best.store}</span>
          </div>
          <p className="mt-0.5 line-clamp-1 text-[12px] muted">{best.title}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <a
              href={best.url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary px-3 py-1 text-[12.5px]"
            >
              Ir a la tienda
              <ExternalLink className="size-3" />
            </a>
            {offers.length > 1 && (
              <button
                type="button"
                onClick={() => onOpenFull(state.query)}
                className="chip hover:text-[var(--text)]"
              >
                Ver {offers.length} ofertas
              </button>
            )}
          </div>
        </div>
      )}

      {state.comparison?.verdict && (
        <div className="mt-2.5 flex gap-2 text-[12.5px]">
          <Sparkles className="mt-0.5 size-3.5 shrink-0 text-accent-500" />
          <p>{state.comparison.verdict}</p>
        </div>
      )}

      {running && !best && (
        <p className="text-[12.5px] muted">Recorriendo tiendas…</p>
      )}
    </div>
  );
}
