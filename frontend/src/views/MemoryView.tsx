import { useCallback, useEffect, useState } from "react";
import { Trash2, ExternalLink, Bookmark } from "lucide-react";
import { api } from "../lib/api";
import { plural, when } from "../lib/format";
import type { SavedItem } from "../types";

export function MemoryView() {
  const [items, setItems] = useState<SavedItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const payload = await api.memory();
      setItems(payload.items);
      setTotal(payload.total);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const handler = () => void load();
    window.addEventListener("aw1:memory", handler);
    return () => window.removeEventListener("aw1:memory", handler);
  }, [load]);

  return (
    <div className="h-full overflow-y-auto px-5 md:px-9">
      <div className="mx-auto max-w-3xl py-6 pb-16">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-[26px] font-semibold tracking-tight md:text-[30px]">Guardado</h1>
            <p className="mt-1.5 text-[14px] muted">
              {plural(total, "elemento")} en la base de datos local.
            </p>
          </div>
          {items.length > 0 && (
            <button
              type="button"
              className="btn btn-ghost px-3 py-1.5 text-[13px]"
              onClick={async () => {
                if (!window.confirm("Borrar todo lo guardado?")) return;
                await api.purge(false);
                void load();
              }}
            >
              Vaciar
            </button>
          )}
        </div>

        {loading ? null : items.length === 0 ? (
          <div className="mt-10 flex flex-col items-center gap-3 rounded-[14px] border border-dashed hairline py-14 text-center">
            <Bookmark className="size-5 muted" />
            <p className="text-[14px] muted">
              Aun no guardas nada. Usa el boton Guardar en una respuesta o en una oferta.
            </p>
          </div>
        ) : (
          <ul className="mt-7 space-y-2.5">
            {items.map((item) => {
              const url = typeof item.meta.url === "string" ? item.meta.url : "";
              return (
                <li key={item.id} className="card group p-4">
                  <p className="whitespace-pre-wrap break-words text-[14px]">{item.text}</p>
                  <div className="mt-3 flex items-center gap-2 text-[11px] muted">
                    <span className="chip">{item.kind === "offer" ? "oferta" : item.source}</span>
                    <time dateTime={item.created_at}>{when(item.created_at)}</time>
                    <div className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      {url && (
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-ghost size-7 p-0"
                          aria-label="Abrir enlace"
                        >
                          <ExternalLink className="size-3.5" />
                        </a>
                      )}
                      <button
                        type="button"
                        aria-label="Eliminar"
                        className="btn btn-ghost size-7 p-0 hover:text-red-500"
                        onClick={async () => {
                          await api.deleteItem(item.id);
                          void load();
                        }}
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
