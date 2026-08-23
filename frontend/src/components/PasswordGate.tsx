import { useState } from "react";
import { Lock } from "lucide-react";
import { admin, ApiError, setAdminPassword } from "../lib/api";

/** Compartido entre las paginas privadas (Admin, Agentes): misma password
 * (X-Admin-Password), verificada contra /api/admin/config -cualquier ruta
 * bajo /api/admin/* la exige igual, asi que sirve para desbloquear cualquiera
 * de las dos. */
export function PasswordGate({
  title = "Panel privado",
  onUnlock,
}: {
  title?: string;
  onUnlock: () => void;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError("");
    setAdminPassword(value.trim());
    try {
      await admin.config();
      onUnlock();
    } catch (err) {
      setAdminPassword("");
      setError(err instanceof ApiError ? err.message : "No se pudo verificar la password.");
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
        <h1 className="mt-3 text-[17px] font-semibold">{title}</h1>
        <p className="mt-1 text-[13px] muted">Solo para ti. Pide una password aparte del token.</p>
        <div className="mt-4 flex flex-col gap-2">
          <input
            type="password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && submit()}
            placeholder="Password de administrador"
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
