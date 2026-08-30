# Estado del proyecto -- 2026-08-28

## Donde quedamos

Lo ultimo que se hizo fue el **sistema de agentes auto-extensibles**
(commit `7552b5d`): un bot de Telegram puede notar que le falta una
capacidad y anotarlo, y desde el panel "Auto-extension" un humano puede
convertir ese pedido en una herramienta generada por IA, probarla en un
sandbox aislado y aprobarla para uso real. Tambien se agrego `CLAUDE.md`
como guia de referencia para quien retome el repo despues.

Verificado ahora mismo:
- Working tree limpio, sin cambios pendientes, `main` al dia con `origin/main`.
- Tests del backend: **todos pasan** (234 tests, `pytest -k "not browser and not pipeline"`).
- Frontend: `tsc --noEmit` sin errores.
- Servidor de produccion (EC2 `i-084f5d23ba86d844f`): ya tiene desplegado
  este mismo commit (`7552b5d`) y responde OK en `/api/status`
  (`database: online`, `browser.ready: true`, `gpt_configured: true`).

**No hay nada a medio terminar ni deploy pendiente.** El repo esta en un
punto estable y coincide con lo que corre en produccion.

## Que hay construido (resumen del mapa completo)

- **Chat personal**: Ollama local + GPT opcional segun la tarea, con
  tool-calling (precios, busqueda web) y streaming.
- **Comparador de precios**: navega tiendas chilenas reales con Chromium
  (Playwright), corre en el mismo contenedor.
- **Plataforma de bots de Telegram** (`telegram/orchestrator.py` +
  `core/telegram_store.py`): multi-bot, cada uno con su agente (prompt +
  personalidad), memoria de corto plazo (48h), moderacion antes de GPT,
  manejo de errores unificado, archivos/APIs por agente como contexto o
  tool-call en vivo, creador de prompts con few-shot y boton de
  "humanizar", y `@buscar` para busqueda web general.
- **Sistema de memoria**: un enrutador decide si conviene revisar notas
  guardadas antes de responder o ir directo a la salida.
- **Agentes auto-extensibles** (lo mas nuevo, ver arriba): deteccion de
  huecos -> generacion de herramienta en sandbox -> aprobacion humana
  obligatoria en cada paso. Invariantes de seguridad documentadas en
  `CLAUDE.md` (sandbox sin credenciales, sin imports peligrosos, anti-SSRF
  via `netguard`, nunca se activa nada sin click humano).
- **Frontend**: React + TS + Vite + Tailwind v4, vistas privadas
  (`agents`, `admin`, `autoextension`) protegidas con password aparte.

## Lo que se decidio explicitamente NO construir todavia

Documentado en `CLAUDE.md`, no es un olvido: memoria episodica/procedural
con scoring, dataset de entrenamiento por refuerzo, un "Evolver" que
proponga mejoras del sistema solo. Los datos crudos que harian falta
(pedidos de capacidad, uso de herramientas) ya se estan guardando, asi
que no se pierde nada si mas adelante se decide construir esto.

## Proximos pasos posibles (sin decidir nada, para conversarlo)

No hay un TODO pendiente explicito en el codigo. Si el usuario quiere
seguir, las lineas naturales segun lo ya construido serian:
1. Usar el panel de Auto-extension en un caso real (un bot pide una
   capacidad concreta) para validar el flujo de punta a punta en
   produccion, no solo en tests.
2. Si aparecen varios pedidos de capacidad repetidos, evaluar si conviene
   automatizar mas el paso de "generar" (siempre manteniendo la
   aprobacion humana como limite, segun la invariante ya fijada).
3. Nada de esto esta decidido -depende de que necesite el usuario.
