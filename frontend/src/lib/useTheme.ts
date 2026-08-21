import { useCallback, useEffect, useState } from "react";

/** Tema claro/oscuro, recordado en el navegador y aplicado antes del primer pintado. */
export function useTheme() {
  const [dark, setDark] = useState<boolean>(() =>
    typeof document === "undefined" ? false : document.documentElement.classList.contains("dark"),
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("aw1-theme", dark ? "dark" : "light");
    } catch {
      /* sin almacenamiento: el tema dura lo que la pestana */
    }
  }, [dark]);

  return { dark, toggle: useCallback(() => setDark((value) => !value), []) };
}
