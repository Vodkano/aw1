import { useCallback, useEffect, useState } from "react";
import { Shell, type ViewKey } from "./components/Shell";
import { ChatView } from "./views/ChatView";
import { PricesView } from "./views/PricesView";
import { MemoryView } from "./views/MemoryView";
import { SettingsView } from "./views/SettingsView";
import { api } from "./lib/api";
import type { Status } from "./types";

const VALID: ViewKey[] = ["chat", "prices", "memory", "settings"];

function fromHash(): ViewKey {
  const value = window.location.hash.replace("#", "") as ViewKey;
  return VALID.includes(value) ? value : "chat";
}

export default function App() {
  const [view, setView] = useState<ViewKey>(fromHash);
  const [status, setStatus] = useState<Status | null>(null);
  const [priceQuery, setPriceQuery] = useState<string>();

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

  return (
    <Shell view={view} onView={go} status={status}>
      {view === "chat" && <ChatView status={status} onSearchPrices={searchPrices} />}
      {view === "prices" && <PricesView initialQuery={priceQuery} />}
      {view === "memory" && <MemoryView />}
      {view === "settings" && <SettingsView status={status} onRefresh={refresh} />}
    </Shell>
  );
}
