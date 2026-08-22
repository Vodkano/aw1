import { useCallback, useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { Shell, type ViewKey } from "./components/Shell";
import { ChatView } from "./views/ChatView";
import { PricesView } from "./views/PricesView";
import { MemoryView } from "./views/MemoryView";
import { SettingsView } from "./views/SettingsView";
import { AdminView } from "./views/AdminView";
import { api, ApiError, getToken, setToken } from "./lib/api";
import type { Status } from "./types";

// "admin" no esta en NAV (Shell.tsx): solo se llega escribiendo #admin.
const VALID: ViewKey[] = ["chat", "prices", "memory", "settings", "admin"];

function fromHash(): ViewKey {
  const value = window.location.hash.replace("#", "") as ViewKey;
  return VALID.includes(value) ? value : "chat";
}

/**
 * Sin esto, alguien que llega por primera vez a un servidor con
 * AW1_API_TOKEN activo ve cada mensaje del chat fallar con un 401 -sin
 * ninguna pista de que falta pegar el token en Ajustes. Se pide aqui mismo,
 * antes de dejar pasar a cualquier vista, y se valida contra un endpoint
 * real (no /api/status, que es publico y no exige token).
 */
function AuthGate({ onUnlock }: { onUnlock: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError("");
    setToken(value.trim());
    try {
      await api.conversations();
      onUnlock();
    } catch (err) {
      setToken("");
      setError(err instanceof ApiError ? err.message : "No se pudo verificar el token.");
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
        <h1 className="mt-3 text-[17px] font-semibold">AW1</h1>
        <p className="mt-1 text-[13px] muted">Este servidor exige un token de acceso.</p>
        <div className="mt-4 flex flex-col gap-2">
          <input
            type="password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && submit()}
            placeholder="Pega tu token"
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

export default function App() {
  const [view, setView] = useState<ViewKey>(fromHash);
  const [status, setStatus] = useState<Status | null>(null);
  const [priceQuery, setPriceQuery] = useState<string>();
  const [hasToken, setHasToken] = useState(() => !!getToken());

  const refresh = useCallback(() => {
    api.status().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 20_000);
    return () => window.clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    const handler = () => setView(fromHash());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);

  const go = useCallback((key: ViewKey) => {
    setView(key);
    window.location.hash = key;
  }, []);

  /** El chat puede derivar una consulta al comparador. */
  const searchPrices = useCallback(
    (query: string) => {
      setPriceQuery(query);
      go("prices");
    },
    [go],
  );

  // /#admin tiene su propia password, separada de este token -no la bloquea.
  const needsAuth = view !== "admin" && !!status?.auth_enabled && !hasToken;

  return (
    <Shell view={view} onView={go} status={status}>
      {needsAuth ? (
        <AuthGate onUnlock={() => setHasToken(true)} />
      ) : (
        <>
          {view === "chat" && <ChatView status={status} onSearchPrices={searchPrices} />}
          {view === "prices" && <PricesView initialQuery={priceQuery} />}
          {view === "memory" && <MemoryView />}
          {view === "settings" && <SettingsView status={status} onRefresh={refresh} />}
          {view === "admin" && <AdminView />}
        </>
      )}
    </Shell>
  );
}
