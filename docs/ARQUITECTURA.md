# Arquitectura de AW1 v3

Documento de decisiones: por qué el sistema está hecho así y qué se descartó.

---

## 1. El problema que define todo

La versión anterior pedía el HTML del buscador de cada tienda con `httpx` y
buscaba enlaces de producto. Contra Falabella, Ripley, Paris y Lider eso devolvía
**cero resultados, siempre y en silencio**, porque esas tiendas entregan un HTML
prácticamente vacío y pintan el catálogo con JavaScript después.

No es un detalle que se arregle con mejores selectores: no hay nada que
seleccionar. La única forma de ver lo que ve una persona es ejecutar el
JavaScript de la página. De ahí sale todo lo demás.

La prueba `test_browser.py::test_the_search_page_has_no_products_in_the_raw_html`
fija esa premisa: comprueba que el HTML crudo de la tienda simulada no contiene
ni un enlace de producto, para que nadie "optimice" el navegador quitándolo.

---

## 2. Capas

```
     api/            FastAPI. Sin lógica de negocio: valida, autentica y traduce
      │              errores de dominio a códigos HTTP.
      ▼
  chat/  pricing/    Los dos casos de uso. Orquestan; no saben de HTTP.
      │
      ├──▶ llm/      Decisiones del modelo + su verificación.
      ├──▶ browser/  Chromium y los dos extractores de página.
      ├──▶ stores/   Catálogo: cómo se busca en cada tienda.
      └──▶ db/       SQLite asíncrono.
             │
             ▼
           core/     Errores, logging, SSRF, límite de uso.
```

Las dependencias apuntan siempre hacia abajo. `pricing/` no importa nada de
`api/`, y por eso el pipeline completo se puede probar sin levantar un servidor.

---

## 3. El navegador

### Un Chromium, muchos contextos

`BrowserPool` lanza Chromium una vez en el arranque de la aplicación y reparte
contextos con un semáforo. Lanzar un navegador cuesta cerca de un segundo:
hacerlo por petición haría inviable la arquitectura.

Cada contexto es efímero y aislado. No se comparten cookies entre tiendas y se
cierra al terminar.

### Se bloquean imágenes, fuentes y vídeo

Una ficha de tienda pesa varios megabytes, y casi todo son fotos que no nos
interesan. Bloquearlas baja una carga de ~6 s a menos de 2 s. También se cortan
los rastreadores conocidos (Google Tag Manager, Hotjar, Criteo…): no aportan
texto y sí latencia.

### Esperar a que la tienda termine

`_settle` hace tres cosas en orden: espera un selector propio de la tienda,
espera `networkidle`, y añade un margen fijo. Ninguna de las dos primeras es
obligatoria; si expiran, se sigue. El objetivo es no leer un DOM a medio pintar,
no garantizar que la página esté perfecta.

### La guardia SSRF va antes de navegar

`netguard.resolves_public()` resuelve el DNS y comprueba que apunte a una IP
pública **antes** de que el navegador emita la petición. Sin eso, una redirección
de una tienda podría llevar a Chromium a la red local de quien ejecuta AW1.

---

## 4. Qué se le da al modelo y qué se le exige

### El paquete de contexto

`extract.js` corre dentro de la página y devuelve lo que un humano vería:

- título, encabezado y ruta de navegación;
- datos estructurados (JSON-LD, Open Graph, microdatos);
- disponibilidad;
- **cada importe visible**, con:
  - el texto tal cual aparece,
  - una descripción del elemento (`strong .price-internet :: Precio internet`),
  - cuánto destaca (tamaño y peso de fuente, normalizados),
  - si está tachado,
  - si su contexto habla de cuotas, descuentos o despacho.

Esas dos últimas marcas son lo que permite a un modelo de 7B distinguir el
precio de venta del precio tachado y de "12 cuotas de $45.832".

### Un detalle que costó encontrar

La etiqueta cercana de cada importe se construye mirando los hermanos y el
padre. La primera versión concatenaba el texto completo del contenedor, y eso
arrastraba los precios vecinos al contexto de **todos** los candidatos: el
modelo veía "Precio internet" en el contexto del importe de despacho. Ahora se
descarta cualquier fragmento que contenga más de un importe.

### Los cuatro jueces

| Juez | Entrada | Salida (JSON validado) |
| --- | --- | --- |
| `plan_search` | lo que escribió la persona | producto, variantes, obligatorios, prohibidos |
| `pick_products` | tarjetas del buscador, ya pre-ordenadas | ids elegidos con confianza |
| `read_page` | el paquete de contexto | `candidate_id`, `price`, `is_match`, motivo |
| `write_verdict` | ofertas finales | dos frases en español |

Todo pasa por `format: json` de Ollama y se valida contra un modelo Pydantic. Lo
que no encaja se descarta.

### Verificación: dónde se ataja la alucinación

El modelo **elige entre importes que ya existen**, nunca los escribe. Eso hace
su respuesta comprobable:

1. Si el `candidate_id` no existe, se ignora la decisión y manda la heurística.
2. Si el `price` no coincide con el valor de ese candidato, manda el candidato y
   se cuenta una corrección.
3. Si el título de la página no corresponde al producto, se descarta la oferta.
   Aquí hay un matiz: una cobertura baja de términos puede ser un título
   escueto, y una confianza alta del modelo puede sobreescribirla; que sea un
   **accesorio** o que falte un **término obligatorio** no se sobreescribe
   nunca.
4. Si el veredicto final menciona un precio que no está en la lista, se
   reescribe con la versión determinística.

Ese contador de correcciones se muestra en la interfaz, en «Cómo se decidió».

### Inyección de prompt

Una ficha de producto es texto que controla un tercero. Todo lo que viene de una
página va entre `<<<DATOS>>>` y `<<<FIN>>>`, y el prompt del sistema dice
explícitamente que ahí dentro no hay instrucciones. Además la salida es un
esquema cerrado: aunque el modelo se dejara convencer, no hay forma de que eso
se traduzca en una acción, porque lo único que puede devolver es un id y un
número que luego se verifican.

---

## 5. Degradación

Nada de esto puede ser un punto único de fallo.

| Si falla | Qué pasa |
| --- | --- |
| Ollama apagado | El comparador usa las heurísticas; las ofertas se marcan `sin IA`. El chat lo dice y explica cómo arrancarlo |
| El modelo devuelve basura | El JSON no valida, se cuenta un `fallback` y sigue la heurística |
| Chromium no instalado | La app arranca igual; el estado lo dice y el comparador falla con instrucciones |
| Una tienda cae | Las demás siguen; esa aparece con estado `error` y su motivo |
| Se acaba el tiempo | Se cancela lo pendiente y se devuelve lo que sí se obtuvo |
| Wikipedia no responde | La biografía la responde el modelo local |
| Sin clave de GPT | No se ofrece el menú de confirmación siquiera |

---

## 6. Streaming

Una búsqueda tarda entre 30 y 90 segundos. Un spinner durante ese tiempo es
inaceptable, así que el pipeline emite eventos según avanza:

```
start → plan → store_start → store_cards → store_picked
      → offer (uno por precio, según aparecen)
      → store_done → verdict_pending → done
```

Las tiendas se procesan en paralelo y sus eventos entran a una cola compartida,
de modo que el orden refleja lo que realmente va ocurriendo.

**Una nota para quien toque el cliente:** `sse-starlette` separa las líneas con
`CRLF`, que es lo que manda la especificación. Un parser que busque `\n\n` no
encuentra nunca el fin de evento y la interfaz se queda esperando para siempre,
sin ningún error visible. `lib/api.ts` normaliza a `LF` antes de partir.

---

## 7. Dinero

Comparar precios sin convertir la moneda produce resultados silenciosamente
incorrectos: 899 USD son unos 854.000 CLP y deben quedar **por delante** de una
oferta de 1.290.000 CLP.

- `money.parse` resuelve la ambigüedad entre separador de miles y decimal.
  `1.290.000` son un millón doscientos noventa mil; `1.299,50` son mil
  doscientos noventa y nueve con cincuenta.
- Todo se convierte a CLP con `AW1_FX_RATES_TO_CLP` antes de ordenar.
- Se descartan importes implausibles: el "2" de un selector de cuotas o un
  placeholder de nueve cifras.
- El formato de salida es `$1.290.000`. Nunca notación científica.
- Si la oferta más barata está muy por debajo de la mediana, se avisa: casi
  siempre significa que esa ficha era un accesorio o un repuesto.

---

## 8. Seguridad

| Riesgo | Mitigación |
| --- | --- |
| CSRF desde cualquier web abierta | `Origin` validado en toda petición con estado |
| Servicio expuesto sin auth | Token Bearer opcional, **obligatorio** en producción |
| SSRF vía URL o redirección | Guardia con resolución DNS antes de navegar |
| Abuso | Limitador por cliente con ventana deslizante |
| Secretos en los logs | Redacción por patrones en el formateador |
| Inyección desde una tienda | Delimitadores + esquema de salida cerrado |
| Fuga del razonamiento interno | Se guarda en `reasoning` y no se serializa nunca |

---

## 9. Qué se descartó y por qué

**Raspar buscadores (Bing, DuckDuckGo).** La versión anterior lo hacía. Devuelven
202 o 403 la mayor parte del tiempo, va contra sus términos de uso, y la consulta
que se les enviaba llevaba 35 exclusiones `-término` que ambos ignoran.

**Solo APIs públicas.** Rapidísimo, pero deja fuera a casi todo el comercio
chileno. Se conserva como idea: `stores/registry.py` permite declarar una tienda
con otro modo de descubrimiento sin tocar el pipeline.

**Que el modelo lea la página entera.** Se probó mentalmente y se descartó: con
`mistral` en un portátil son 10-30 s por ficha y muchas más alucinaciones de
precio. El extractor reduce una página de 300 KB a ~15 líneas, que es donde un
modelo pequeño acierta.

**Que el modelo solo redacte al final.** Rápido, pero entonces la IA no decide
nada de lo que importa, y elegir entre "precio internet" y "precio normal
tachado" es exactamente donde el criterio hace falta.

**Un ORM.** SQLite con `aiosqlite` y SQL a mano: siete tablas, consultas simples,
una dependencia menos y control total del bloqueo de escritura.

---

## 10. Límites conocidos

- **Los selectores de tienda envejecen.** `wait_selector` es una pista, no un
  requisito, así que un cambio de HTML degrada el resultado en lugar de romperlo.
  Aun así, conviene revisarlos de vez en cuando.
- **Las tasas de cambio son fijas** en configuración. Conectar una fuente real
  (Banco Central) es el siguiente paso natural.
- **Sin protección anti-bot.** Si una tienda pone un captcha, esa tienda queda
  fuera y se informa. No se intenta evadirlo.
- **Un proceso.** El limitador y el pool de navegador viven en memoria.
- **El SQLite está en texto plano.** En un servidor compartido habría que
  cifrarlo.
