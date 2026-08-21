import { useState } from "react";
import clsx from "clsx";
import { api, getToken, setToken } from "../lib/api";
import type { Status } from "../types";

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b hairline py-2.5 last:border-b-0 text-[13.5px]">
      <span className="muted">{label}</span>
      <span className="flex items-center gap-2 text-right font-medium">
        {ok !== undefined && (
          <span className={clsx("size-1.5 rounded-full", ok ? "bg-accent-500" : "bg-ink-400")} />
        )}
        {value}
      </span>
    </div>
  );
}

export function SettingsView({ status, onRefresh }: { status: Status | null; onRefresh: () => void }) {
  const [token, setLocalToken] = useState(getToken());
  const [saved, setSaved] = useState(false);

  return (
    <div className="h-full overflow-y-auto px-5 md:px-9">
      <div className="mx-auto max-w-3xl py-6 pb-16">
        <h1 className="text-[26px] font-semibold tracking-tight md:text-[30px]">Ajustes</h1>
        <p className="mt-1.5 text-[14px] muted">
          Estado del sistema y control de tus datos. Todo vive en este computador.
        </p>

        <section className="card mt-7 p-5">
          <h2 className="text-[15px] font-semibold">Sistema</h2>
          <div className="mt-3">
            <Row label="Version" value={status?.version ?? "—"} />
            <Row label="Entorno" value={status?.env ?? "—"} />
            <Row
              label="Ollama"
              value={status?.ollama === "online" ? "conectado" : "no disponible"}
              ok={status?.ollama === "online"}
            />
            <Row
              label="Modelo"
              value={
                status
                  ? status.model_ready
                    ? status.model
                    : `${status.model} (no descargado)`
                  : "—"
              }
              ok={status?.model_ready}
            />
            <Row
              label="Navegador interno"
              value={status?.browser.ready ? `listo · ${status.browser.contexts} contextos` : "apagado"}
              ok={status?.browser.ready}
            />
            <Row label="Base de datos" value={status?.database ?? "—"} ok={status?.database === "online"} />
            <Row
              label="GPT"
              value={status?.gpt_configured ? "configurado, bajo permiso" : "sin configurar"}
              ok={status?.gpt_configured}
            />
          </div>

          {status && !status.model_ready && status.ollama === "online" && (
            <p className="mt-4 rounded-[10px] surface-soft p-3 text-[13px] muted">
              El modelo <code className="font-mono">{status.model}</code> no esta descargado.
              Ejecuta <code className="font-mono">ollama pull {status.model}</code>.
              {status.models.length > 0 && ` Disponibles: ${status.models.join(", ")}.`}
            </p>
          )}
          {status && !status.browser.ready && (
            <p className="mt-3 rounded-[10px] surface-soft p-3 text-[13px] muted">
              El navegador interno no arranco, asi que el comparador no puede entrar a las
              tiendas. Ejecuta <code className="font-mono">playwright install chromium</code>.
              {status.browser.error && ` Detalle: ${status.browser.error}`}
            </p>
          )}

          <button type="button" onClick={onRefresh} className="btn btn-ghost mt-4 px-3 py-1.5 text-[13px]">
            Actualizar estado
          </button>
        </section>

        {status?.auth_enabled && (
          <section className="card mt-4 p-5">
            <h2 className="text-[15px] font-semibold">Token de acceso</h2>
            <p className="mt-1 text-[13px] muted">
              Este servidor exige autenticacion. El token se guarda solo en este navegador.
            </p>
            <div className="mt-3 flex gap-2">
              <input
                type="password"
                value={token}
                onChange={(event) => setLocalToken(event.target.value)}
                placeholder="Pega tu token"
                className="input"
              />
              <button
                type="button"
                className="btn btn-primary shrink-0 px-4 py-1.5 text-[13px]"
                onClick={() => {
                  setToken(token);
                  setSaved(true);
                  onRefresh();
                  setTimeout(() => setSaved(false), 1600);
                }}
              >
                {saved ? "Guardado" : "Guardar"}
              </button>
            </div>
          </section>
        )}

        <section className="card mt-4 p-5">
          <h2 className="text-[15px] font-semibold">Privacidad</h2>
          <p className="mt-1 text-[13px] muted">
            Conversaciones, guardados, razonamiento interno del modelo y cache de precios
            estan en un archivo SQLite dentro de tu equipo. Borrarlo es definitivo.
          </p>
          <button
            type="button"
            className="btn btn-ghost mt-4 px-3 py-1.5 text-[13px] hover:border-red-400 hover:text-red-500"
            onClick={async () => {
              if (!window.confirm("Borrar TODO: chats, guardados, razonamiento y cache?")) return;
              await api.purge(true);
              window.dispatchEvent(new CustomEvent("aw1:memory"));
              window.location.reload();
            }}
          >
            Borrar todos mis datos
          </button>
        </section>

        <section className="card mt-4 p-5">
          <h2 className="text-[15px] font-semibold">Como funciona el comparador</h2>
          <ol className="mt-3 space-y-2 text-[13.5px] muted">
            <li>1. El modelo interpreta lo que pediste y decide como buscarlo.</li>
            <li>2. Un navegador real abre el buscador de cada tienda y espera a que cargue.</li>
            <li>3. El modelo elige cuales resultados son de verdad ese producto.</li>
            <li>4. Se abre cada ficha y se extraen todos sus importes con su contexto.</li>
            <li>5. El modelo decide cual es el precio de venta y por que.</li>
            <li>6. El codigo verifica que ese precio exista en la pagina antes de mostrarlo.</li>
          </ol>
        </section>
      </div>
    </div>
  );
}
