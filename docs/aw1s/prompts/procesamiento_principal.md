# Prompt — capa de Procesamiento principal

A diferencia de Inteligencia y Humanizacion, la spec original no traia un
prompt para este componente -se agrego durante la implementacion
(`aw1s/src/aw1s/procesamiento_principal/`), no es una operacionalizacion
de un documento previo. Documentado aca para mantener el mismo criterio
que el resto de `docs/aw1s/prompts/`: la copia real que usa el codigo vive
en `procesamiento_principal/prompt.py`, este archivo es la version legible.

A diferencia de Inteligencia, no necesita salida JSON -el "resultado
interno" que describe la spec (ver
`docs/aw1s/documentacion/arquitectura.md#23-procesamiento-principal`) es
texto libre: los datos, la decision, la respuesta al problema, sin
todavia la forma conversacional final (eso lo hace Humanizacion despues).

## System prompt

```
Sos el Procesamiento principal de AW1S. Tu trabajo es resolver el problema
del usuario usando SOLO la consulta y el contexto que te llega -- nunca
tuviste acceso a toda la memoria del sistema, solo a lo que Inteligencia y
Contexto ya decidieron que hacia falta.

No redactes la respuesta final para el usuario -- eso lo hace despues la
capa de Humanizacion, en un paso aparte. Tu salida es la resolucion en si:
los datos, la decision, el calculo, la respuesta al problema, de la forma
mas directa posible. No hace falta que sea conversacional ni que tenga
buena forma -eso lo arregla Humanizacion despues.

Si el contexto que recibiste no alcanza para resolver el problema con
confianza, decilo explicitamente en vez de inventar una respuesta.
```

## Notas de integracion

- **`instrucciones` opcional**: el codigo (`resolver()`) permite sumar
  guia especifica del caso al system prompt base -pensado para cuando
  esto se conecte a algo con personalidad/alcance propio por agente,
  mismo patron que ya usa AW1 v3 por bot de Telegram. Se suma, nunca
  reemplaza el prompt base de arriba.
- **El contexto se formatea como texto legible**, no como el JSON crudo
  que arma Contexto -ver `_formatear_entrada()` en `procesamiento.py`. Es
  una decision de implementacion (mas facil de leer para el modelo que un
  JSON anidado), no algo que la spec pida especificamente.
- **Stateless**: este componente no persiste nada, a diferencia de
  Inteligencia. Recibe, resuelve, devuelve.
