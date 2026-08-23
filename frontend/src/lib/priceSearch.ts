/**
 * Reduce los eventos "tool_event" (tool: "prices") que emite el chat cuando
 * invoca la herramienta de precios inline, en un solo estado que pinta
 * PriceToolCard. Espejo, en miniatura, del switch que ya vive en
 * PricesView.tsx para el mismo vocabulario de eventos del pipeline.
 */
import type { Comparison, Offer, PriceToolState, SearchPlan, StoreOutcome } from "../types";

export const STATUS_STYLE: Record<string, string> = {
  ok: "bg-accent-500",
  vacio: "bg-ink-300",
  error: "bg-red-400",
  timeout: "bg-amber-400",
  running: "bg-accent-400 animate-pulse-soft",
  pending: "bg-ink-200",
};

export const STATUS_TEXT: Record<string, string> = {
  ok: "listo",
  vacio: "sin resultados",
  error: "error",
  timeout: "sin tiempo",
  running: "buscando",
  pending: "en cola",
};

export function initialPriceToolState(query: string): PriceToolState {
  return { phase: "start", query, plan: null, stores: [], offers: [], comparison: null, error: "" };
}

export function reducePriceEvent(
  state: PriceToolState,
  type: string,
  data: any,
): PriceToolState {
  switch (type) {
    // Solo lo manda la herramienta de precios del chat (ver chat/tools/prices.py),
    // antes que nada mas: en un resultado desde cache el pipeline nunca emite
    // "start" (que es de donde normalmente sale la query), asi que sin este
    // caso la tarjeta se queda sin saber que se busco.
    case "query":
      return { ...state, query: data.query as string };
    case "start":
      return {
        ...state,
        phase: "start",
        stores: (data.stores as string[]).map((name) => ({
          slug: name, name, search_url: "", cards_found: 0, picked: 0,
          offers: 0, elapsed: 0, status: "pending", detail: "",
        })),
      };
    case "plan":
      return { ...state, phase: "plan", plan: data as SearchPlan };
    case "store_start":
      return {
        ...state,
        phase: "store_start",
        stores: state.stores.map((item) =>
          item.name === data.name || item.slug === data.slug
            ? { ...item, slug: data.slug, status: "running", search_url: data.url }
            : item,
        ),
      };
    case "store_cards":
      return {
        ...state,
        phase: "store_cards",
        stores: state.stores.map((item) =>
          item.slug === data.slug ? { ...item, cards_found: data.found } : item,
        ),
      };
    case "store_picked":
      return {
        ...state,
        phase: "store_picked",
        stores: state.stores.map((item) =>
          item.slug === data.slug ? { ...item, picked: data.picked.length } : item,
        ),
      };
    case "offer":
      return {
        ...state,
        phase: "offer",
        offers: [...state.offers, data.offer as Offer].sort((a, b) => a.price_clp - b.price_clp),
      };
    case "store_done":
      return {
        ...state,
        phase: "store_done",
        stores: state.stores.map((item) =>
          item.slug === data.store.slug ? (data.store as StoreOutcome) : item,
        ),
      };
    case "verdict_pending":
      return { ...state, phase: "verdict_pending" };
    case "done":
      return { ...state, phase: "done", comparison: data.comparison as Comparison };
    case "error":
      return { ...state, phase: "error", error: data.message as string };
    default:
      return state;
  }
}
