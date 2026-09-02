# AW1S — Documentacion de arquitectura

Version: 0.1.0.1-SK (primer documento fuente procesado). Estado: diseno,
sin implementar. Fuente: spec entregada por el usuario, ver
`docs/aw1s/planos/0.1.0.1-SK.md` para el analisis linea a linea y los
puntos que la spec deja abiertos.

## 1. Definicion

AW1S es una entidad computacional inteligente: una unidad autonoma con
identidad, estado, memoria, capacidades y mecanismos de interaccion con su
entorno, implementada como la coordinacion de componentes especializados
(no un unico modelo).

## 2. Componentes

La entidad tiene seis componentes. Uno es un cortocircuito que corre antes
que todo lo demas; tres son capas de pre/post-procesamiento alrededor de un
componente central; uno es persistencia transversal a todos.

### 2.0 Atajo semantico (fast path)

**Fuente**: no forma parte de la spec 0.1.0.1-SK original — se agrego en
conversacion, ver `docs/aw1s/planos/0.1.0.2-atajo-semantico.md`.

**Responsabilidad**: interceptar el mensaje antes de que llegue a
Inteligencia y resolverlo sin invocar ningun modelo cuando ya es un caso
conocido (saludos, despedidas, agradecimientos, y otras frases que el
sistema tiene memorizadas con una respuesta fija).

**Mecanismo**: comparacion por similitud contra un vectorDB chico y
curado — distinto del pgvector de Memoria (seccion 2.5): este indice no
es el historial dinamico de conversaciones, es una lista acotada y
mantenida a mano de pares frase→respuesta.

**Salida**: si hay match por encima del umbral definido, la respuesta
prearmada, sin pasar por Inteligencia, Procesamiento principal ni
Humanizacion. Si no hay match, el mensaje sigue el flujo normal completo
(seccion 4).

**Por que existe**: mitigar el costo operativo descrito en la seccion 7 —
la mayoria del trafico conversacional real es trivial y no necesita
clasificacion ni resolucion.

**Riesgo a controlar**: un umbral mal calibrado puede hacer que un mensaje
real matchee por una frase parecida (ej. "hola, tengo un problema urgente"
contestado como si fuera solo "hola"). Ver puntos abiertos en el plano de
origen.

### 2.1 Inteligencia

**Responsabilidad**: analizar la entrada antes de que llegue al
procesamiento principal. Clasifica el problema y determina que informacion
hace falta para resolverlo. Ademas, recopila y persiste los datos del
usuario/interaccion en la base de datos — ver "Persistencia" mas abajo.

**Entrada**:
- Mensaje/input del usuario
- Contexto disponible en el momento
- Historial relevante
- Metadata de la interaccion: hora, fecha, IP (si corresponde y es
  legitimo obtenerla), ID de usuario (si existe), ID de sesion, otros datos
  tecnicos del input
- En iteraciones posteriores a la primera: el resultado de la recuperacion
  anterior hecha por Contexto, para evaluar si alcanza

**Salida**: una decision estructurada que especifica que informacion se
necesita, donde buscarla (Postgres, pgvector, o ambos), que tan relevante
es, cuanta recuperar, y si la interaccion actual amerita usar memoria de
sesion, memoria semantica, o combinar fuentes.

**Persistencia** (fuente: `planos/0.1.0.3-inteligencia-recoleccion-datos.md`,
aporte en conversacion, no parte de la spec 0.1.0.1-SK original):
Inteligencia no es un componente de solo lectura — ademas de clasificar,
escribe en Postgres las entidades estructuradas de la interaccion (Usuario,
Sesion, Interaccion, Evento) apenas las recibe, temprano en el ciclo. Esto
es distinto de lo que hace Memoria (seccion 2.5), que decide al **cierre**
del ciclo que se eleva a Memoria semantica y se vectoriza. Alcance de "todos
los datos del usuario" y su politica de retencion: sin definir todavia, ver
puntos abiertos en el plano de origen — es una decision de producto/
privacidad, no solo de arquitectura.

**Regla de control**: puede iterar. Si evalua que la informacion
recuperada por Contexto no alcanza, vuelve a emitir una necesidad de
informacion en vez de dejar pasar el problema con datos insuficientes.

### 2.2 Contexto

**Responsabilidad**: ejecutar lo que Inteligencia determino que hace falta.
Recupera, filtra y organiza informacion desde Memoria. No decide que se
necesita — esa decision es exclusiva de Inteligencia.

**Entrada**: la necesidad de informacion estructurada emitida por
Inteligencia.

**Salida**: el contexto ya armado y organizado, listo para entregar al
procesamiento principal.

**Mecanismo de recuperacion**: PostgreSQL para informacion estructurada,
pgvector para informacion recuperable por significado, o ambos combinados
segun lo que haya pedido Inteligencia.

### 2.3 Procesamiento principal

**Responsabilidad**: resolver el problema identificado.

**Entrada**: consulta del usuario + instrucciones + el contexto ya armado
por la capa de Contexto. **Nunca** recibe la memoria completa ni toda la
informacion disponible — solo lo que las capas anteriores seleccionaron.

**Salida**: un resultado interno (la resolucion del problema, antes de
adaptarse a una respuesta conversacional).

### 2.4 Humanizacion

**Responsabilidad**: convertir el resultado interno en una respuesta
coherente con el contexto de la interaccion.

**Entrada**: el resultado interno del procesamiento principal.

**Salida**: la respuesta final, tal como la recibe el usuario.

**Restriccion**: no modifica la decision ni el razonamiento producido por
el procesamiento principal — solo su forma de presentacion.

### 2.5 Memoria

**Responsabilidad**: decidir que se conserva mas alla de la interaccion
puntual y persistirlo como Memoria semantica. Los datos crudos de la
interaccion (Usuario, Sesion, Interaccion, Evento) ya quedaron escritos por
Inteligencia al principio del ciclo (seccion 2.1) — Memoria trabaja sobre
lo que ya existe, no repite esa escritura.

**Arquitectura**: hibrida, sobre una unica infraestructura.
- **PostgreSQL**: fuente de verdad. Todo dato persistente (usuarios,
  sesiones, interacciones, mensajes, contexto, metadata, eventos, estados,
  relaciones, memorias) existe originalmente ahi.
- **pgvector**: extension de PostgreSQL, no una base separada. Almacena
  embeddings para recuperacion por similitud semantica.

**Regla de prioridad**: el dato original en PostgreSQL siempre tiene
prioridad sobre su embedding. El embedding es un mecanismo de recuperacion,
nunca reemplaza al contenido original.

**Regla de cobertura**: no toda la informacion se vectoriza. Los
identificadores, timestamps, estados, relaciones, metadata y
clasificaciones quedan solo en PostgreSQL. Solo se generan embeddings para
contenido cuyo significado puede ser relevante para busquedas semanticas
futuras (memorias, contexto, historial relevante).

## 3. Modelo de datos

Siete entidades, relacionadas por identificadores:

| Entidad | Relacion | Notas |
|---|---|---|
| Usuario | 1—N Sesion | Identificacion opcional: no toda interaccion tiene usuario identificable. |
| Sesion | 1—N Interaccion | Agrupa interacciones de una misma sesion. |
| Interaccion | 1—1 Contexto, 1—N Memoria | Una entrada + su procesamiento. |
| Contexto | N—1 Interaccion | Informacion contextual de esa interaccion puntual. |
| Memoria | N—1 Interaccion, 1—0/1 Embedding | Lo que AW1S decide conservar mas alla de la interaccion. |
| Embedding | 1—1 Memoria (u otro registro) | Representacion vectorial; referencia siempre al original por ID. |
| Evento | N—1 Interaccion (opcional) | Acciones/acontecimientos del sistema, no de la conversacion. |

Este modelo es conceptual — no hay todavia tipos de columna, indices ni
constraints. No debe confundirse ni fusionarse con el schema real de AW1 v3
(`backend/src/aw1/db/schema.sql` / `schema_postgres.sql`), que es un
sistema en produccion con su propio ciclo de cambios.

## 4. Flujo de una interaccion

```
Entrada
  → Atajo semantico: compara contra el indice de frases conocidas
        → match fuerte: responde directo con lo prearmado. FIN, sin LLM.
        → sin match: continua
  → Inteligencia: analiza y clasifica
  → Inteligencia: persiste Usuario / Sesion / Interaccion / Evento en Postgres
  → Inteligencia: determina necesidad de informacion
  → Contexto: recupera (Postgres / pgvector / ambos)
  → Inteligencia: evalua si alcanza
        → si no alcanza: vuelve a "determina necesidad de informacion"
        → si alcanza: continua
  → Contexto: construye el contexto final
  → Procesamiento principal: resuelve
  → Humanizacion: redacta la respuesta
  → Memoria: almacena resultado; genera embeddings donde corresponda
```

## 5. Principio de diseno

> "El modelo recibe lo que necesita, no todo lo que existe."

Este es el criterio que distingue a AW1S de un sistema que envia todo el
historial/memoria disponible a un LLM y confia en que el modelo filtre. En
AW1S el filtrado es un paso previo y explicito, responsabilidad de
Inteligencia + Contexto — el procesamiento principal nunca ve la memoria
cruda.

## 6. Limites de responsabilidad (no relajar sin redefinir la spec)

- Inteligencia decide **que** informacion hace falta. Contexto no toma esa
  decision, solo la ejecuta.
- Procesamiento principal no elige que informacion usar — la recibe ya
  filtrada.
- Humanizacion no altera el razonamiento ni la decision — solo la forma.
- Memoria participa activamente al cierre de cada ciclo (que guardar, que
  vectorizar) — no es un cache pasivo.

## 7. Costo operativo (implicancia practica, no parte de la spec original)

Un ciclo completo implica como minimo dos llamadas a un modelo de lenguaje
por turno de conversacion (Inteligencia clasificando + Procesamiento
principal resolviendo), tres si Humanizacion tambien es un paso generativo
separado — contra una unica llamada en la arquitectura actual de AW1
(`backend/src/aw1/chat/service.py`). Cualquier decision de que proveedor/
modelo corre cada capa debe tomarse con ese costo adicional explicito.

**Mitigacion definida**: el Atajo semantico (seccion 2.0) evita ese costo
por completo para el subconjunto de mensajes que ya son casos conocidos —
el costo de 2-3 llamadas por turno aplica solo a lo que el atajo no
resuelve.

## 8. Pendiente de la spec (no resuelto por este documento)

1. Metodo de entrenamiento/construccion del componente de Inteligencia.
2. Regla o heuristica para decidir que interaccion se convierte en Memoria.
3. Enumeracion completa de "otros datos tecnicos del input" que Inteligencia
   puede recibir.
4. Relacion entre AW1S y el AW1 actual: sistema nuevo, reemplazo de
   `chat/service.py`, o ejecucion en paralelo.
5. Umbral de similitud y curaduria del indice del Atajo semantico
   (seccion 2.0), y como evitar falsos positivos con mensajes reales.
6. Alcance exacto de "todos los datos del usuario" que Inteligencia
   persiste, y su politica de retencion — decision de producto/privacidad,
   no solo tecnica (seccion 2.1).

Se actualiza este documento a medida que lleguen mas fuentes.
