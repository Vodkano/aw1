import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import {
  Search,
  Square,
  ExternalLink,
  Sparkles,
  RefreshCw,
  ChevronDown,
  TriangleAlert,
  Bookmark,
  Check,
} from "lucide-react";
import { api } from "../lib/api";
import { clp, hostname, money, plural, seconds } from "../lib/format";
import type { Comparison, Offer, SearchPlan, StoreInfo, StoreOutcome } from "../types";

type Phase = "idle" | "running" | "done" | "error";

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-accent-500",
  vacio: "bg-ink-300",
  error: "bg-red-400",
  timeout: "bg-amber-400",
  running: "bg-accent-400 animate-pulse-soft",
  pending: "bg-ink-200",
};

const STATUS_TEXT: Record<string, string> = {
  ok: "listo",
  vacio: "sin resultados",
  error: "error",
  timeout: "sin tiempo",
  running: "buscando",
  pending: "en cola",
};

export function PricesView({ initialQuery }: { initialQuery?: string }) {
  const [query, setQuery] = useState(initialQuery ?? "");
  const [phase, setPhase] = useState<Phase>("idle");
  const [plan, setPlan] = useState<SearchPlan | null>(null);
  const [stores, setStores] = useState<StoreOutcome[]>([]);
  const [live, setLive] = useState<Offer[]>([]);
  const [result, setResult] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [catalog, setCatalog] = useState<StoreInfo[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [showStores, setShowStores] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api.stores().then((payload) => setCatalog(payload.stores)).catch(() => undefined);
  }, []);

  const run = useCallback(
    async (text: string, refresh = false) => {
      const clean = text.trim();
      if (!clean) return;
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;

      setPhase("running");
      setError("");
      setPlan(null);
      setStores([]);
      setLive([]);
      setResult(null);
      setShowDetail(false);

      try {
        await api.searchPrices(
          { query: clean, stores: selected, refresh },
          {
            signal: controller.signal,
            onEvent: (type, data) => {
              switch (type) {
                case "start":
                  setStores(
                    (data.stores as string[]).map((name: string) => ({
                      slug: name,
                      name,
                      search_url: "",
                      cards_found: 0,
                      picked: 0,
                      offers: 0,
                      elapsed: 0,
                      status: "pending" as const,
                      detail: "",
                    })),
                  );
                  break;
                case "plan":
                  setPlan(data);
                  break;
                case "store_start":
                  setStores((current) =>
                    current.map((item) =>
                      item.name === data.name || item.slug === data.slug
                        ? { ...item, slug: data.slug, status: "running", search_url: data.url }
                        : item,
                    ),
                  );
                  break;
                case "store_cards":
                  setStores((current) =>
                    current.map((item) =>
                      item.slug === data.slug ? { ...item, cards_found: data.found } : item,
                    ),
                  );
                  break;
                case "store_picked":
                  setStores((current) =>
                    current.map((item) =>
                      item.slug === data.slug ? { ...item, picked: data.picked.length } : item,
                    ),
                  );
                  break;
                case "offer":
                  setLive((current) =>
                    [...current, data.offer as Offer].sort((a, b) => a.price_clp - b.price_clp),
                  );
                  break;
                case "store_done":
                  setStores((current) =>
                    current.map((item) =>
                      item.slug === data.store.slug ? (data.store as StoreOutcome) : item,
                    ),
                  );
                  break;
                case "done":
                  setResult(data.comparison as Comparison);
                  setPhase("done");
                  break;
                case "error":
                  setError(data.message);
                  setPhase("error");
                  break;
              }
            },
          },
        );
      } catch (issue) {
        if ((issue as Error).name !== "AbortError") {
          setError((issue as Error).message);
          setPhase("error");
        } else if (!result) {
          setPhase("idle");
        }
      } finally {
        abort.current = null;
      }
    },
    [selected, result],
  );

  useEffect(() => {
    if (initialQuery) {
      setQuery(initialQuery);
      void run(initialQuery);
    }
    // Solo al recibir una consulta desde el chat.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  const offers = result?.offers ?? live;
  const best = offers[0];
  const running = phase === "running";

  return (
    <div className="h-full overflow-y-auto px-5 md:px-9">
      <div className="mx-auto max-w-3xl py-6 pb-16">
        <h1 className="text-[26px] font-semibold tracking-tight md:text-[30px]">
          Comparar precios
        </h1>
        <p className="mt-1.5 max-w-xl text-[14px] muted">
          Abro cada tienda con un navegador real, leo la ficha del producto y dejo que
          el modelo decida cual es el precio de venta. Te devuelvo el enlace directo.
        </p>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void run(query);
          }}
          className="mt-6"
        >
          <div className="card flex items-center gap-2 p-2 pl-4 transition-shadow focus-within:border-accent-500">
            <Search className="size-4 shrink-0 muted" />
            <input
              value={query}
              maxLength={180}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ej: iPhone 15 128 GB"
              className="min-w-0 flex-1 bg-transparent py-1.5 outline-none placeholder:text-ink-400"
            />
            {running ? (
              <button
                type="button"
                onClick={() => abort.current?.abort()}
                className="btn btn-ghost shrink-0 px-3 py-1.5 text-[13px]"
              >
                <Square className="size-3 fill-current" />
                Detener
              </button>
            ) : (
              <button
                type="submit"
                disabled={!query.trim()}
                className="btn btn-primary shrink-0 px-4 py-1.5 text-[13px]"
              >
                Buscar
              </button>
            )}
          </div>
        </form>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setShowStores((value) => !value)}
            className="chip hover:text-[var(--text)]"
          >
            <ChevronDown className={clsx("size-3 transition-transform", showStores && "rotate-180")} />
            {selected.length ? `${selected.length} tiendas` : "Todas las tiendas"}
          </button>
          {result && (
            <>
              <span className="chip">{seconds(result.elapsed)}</span>
              {result.from_cache && <span className="chip">desde cache</span>}
              <button
                type="button"
                onClick={() => void run(query, true)}
                className="chip hover:text-[var(--text)]"
              >
                <RefreshCw className="size-3" />
                Volver a buscar
              </button>
            </>
          )}
        </div>

        {showStores && (
          <div className="card mt-3 flex flex-wrap gap-1.5 p-3">
            {catalog.map((store) => {
              const active = selected.includes(store.slug);
              return (
                <button
                  key={store.slug}
                  type="button"
                  title={store.notes}
                  onClick={() =>
                    setSelected((current) =>
                      active ? current.filter((item) => item !== store.slug) : [...current, store.slug],
                    )
                  }
                  className={clsx(
                    "chip transition-colors",
                    active && "border-accent-500 bg-accent-50 text-accent-700 dark:bg-accent-700/15 dark:text-accent-300",
                  )}
                >
                  {store.name}
                </button>
              );
            })}
            {selected.length > 0 && (
              <button type="button" onClick={() => setSelected([])} className="chip hover:text-[var(--text)]">
                Limpiar
              </button>
            )}
          </div>
        )}

        {plan && (
          <div className="mt-5 animate-in-soft text-[12.5px] muted">
            <span className="inline-flex items-center gap-1.5">
              <Sparkles className="size-3.5 text-accent-500" />
              Buscando <span className="font-medium text-[var(--text)]">{plan.product}</span>
            </span>
            {plan.required.length > 0 && <span> · debe incluir {plan.required.join(", ")}</span>}
          </div>
        )}

        {stores.length > 0 && (
          <ul className="mt-4 space-y-1">
            {stores.map((store) => (
              <li
                key={store.slug}
                className="flex items-center gap-2.5 py-1 text-[13px]"
                title={store.detail}
              >
                <span className={clsx("size-1.5 shrink-0 rounded-full", STATUS_STYLE[store.status])} />
                <span className="min-w-28 font-medium">{store.name}</span>
                <span className="muted">
                  {store.status === "running" || store.status === "pending"
                    ? STATUS_TEXT[store.status]
                    : `${plural(store.cards_found, "resultado")} · ${plural(store.offers, "precio")}`}
                </span>
                {store.elapsed > 0 && (
                  <span className="ml-auto text-[11px] tabular-nums muted">
                    {seconds(store.elapsed)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}

        {error && (
          <div className="card mt-6 flex gap-3 p-4 text-[14px]">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
            <p>{error}</p>
          </div>
        )}

        {best && (
          <section className="mt-8 animate-in-soft">
            <div className="card overflow-hidden p-5">
              <div className="text-[10.5px] uppercase tracking-[0.12em] muted">Mejor precio</div>
              <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-[34px] font-semibold tracking-tight tabular-nums">
                  {clp(best.price_clp)}
                </span>
                <span className="text-[14px] muted">en {best.store}</span>
                {best.currency !== "CLP" && (
                  <span className="chip">publicado en {money(best.price, best.currency)}</span>
                )}
              </div>
              <p className="mt-1 line-clamp-1 text-[13px] muted">{best.title}</p>
              <a
                href={best.url}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-primary mt-4 px-4 py-2 text-[13px]"
              >
                Ir a la tienda
                <ExternalLink className="size-3.5" />
              </a>
            </div>

            {result?.verdict && (
              <div className="mt-4 flex gap-2.5 rounded-[14px] surface-soft p-4 text-[14px]">
                <Sparkles className="mt-0.5 size-4 shrink-0 text-accent-500" />
                <p>{result.verdict}</p>
              </div>
            )}

            {(result?.warnings ?? []).map((warning) => (
              <div key={warning} className="mt-3 flex gap-2.5 text-[13px] text-amber-600 dark:text-amber-400">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
                <p>{warning}</p>
              </div>
            ))}

            <div className="mt-6 overflow-hidden rounded-[14px] border hairline">
              {offers.map((offer, index) => (
                <OfferRow key={offer.url} offer={offer} first={index === 0} />
              ))}
            </div>

            {result && (
              <div className="mt-4">
                <button
                  type="button"
                  onClick={() => setShowDetail((value) => !value)}
                  className="inline-flex items-center gap-1.5 text-[12.5px] muted hover:text-[var(--text)]"
                >
                  <ChevronDown className={clsx("size-3.5 transition-transform", showDetail && "rotate-180")} />
                  Como se decidio
                </button>
                {showDetail && (
                  <div className="mt-3 space-y-1.5 rounded-[12px] surface-soft p-4 text-[12.5px] muted">
                    <p>
                      {result.visited} tiendas visitadas · {result.discarded} resultados descartados ·{" "}
                      {seconds(result.elapsed)}
                    </p>
                    <p>
                      Decisiones del modelo: {result.ai.llm_used} de {result.ai.llm_calls} ·{" "}
                      {result.ai.fallbacks} resueltas sin IA · {result.ai.corrections} corregidas por
                      el verificador
                    </p>
                    {plan?.notes && <p>Plan: {plan.notes}</p>}
                    {result.ai.notes.map((note) => (
                      <p key={note}>· {note}</p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

function OfferRow({ offer, first }: { offer: Offer; first: boolean }) {
  const [saved, setSaved] = useState(false);

  return (
    <div
      className={clsx(
        "flex items-center gap-3 px-4 py-3 text-[13.5px]",
        !first && "border-t hairline",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium">{offer.store}</span>
          {offer.in_stock === false && <span className="chip text-red-500">sin stock</span>}
          {offer.decided_by === "heuristica" && <span className="chip">sin IA</span>}
        </div>
        <p className="truncate text-[12px] muted" title={offer.title}>
          {offer.title || hostname(offer.url)}
        </p>
      </div>

      <div className="shrink-0 text-right">
        <div className="font-semibold tabular-nums">{clp(offer.price_clp)}</div>
        {offer.currency !== "CLP" && (
          <div className="text-[11px] muted tabular-nums">{money(offer.price, offer.currency)}</div>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          disabled={saved}
          aria-label="Guardar oferta"
          className="btn btn-ghost size-7 p-0"
          onClick={async () => {
            await api
              .save({
                text: `${offer.title} — ${clp(offer.price_clp)} en ${offer.store}\n${offer.url}`,
                source: "local",
                kind: "offer",
                meta: { url: offer.url, price_clp: offer.price_clp, store: offer.store },
              })
              .catch(() => undefined);
            setSaved(true);
            window.dispatchEvent(new CustomEvent("aw1:memory"));
          }}
        >
          {saved ? <Check className="size-3.5" /> : <Bookmark className="size-3.5" />}
        </button>
        <a
          href={offer.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Abrir ${offer.store}`}
          className="btn btn-ghost size-7 p-0"
        >
          <ExternalLink className="size-3.5" />
        </a>
      </div>
    </div>
  );
}
