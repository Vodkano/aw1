/**
 * Extractor que corre DENTRO de la pagina, en el navegador.
 *
 * Su trabajo no es decidir cual es el precio: es reunir todo lo que un humano
 * veria y entregarlo ordenado para que el modelo decida. Devuelve el titulo, los
 * datos estructurados, y cada importe visible con el contexto en el que aparece
 * y una medida de cuanto destaca en la pagina.
 *
 * Se ejecuta con page.evaluate(). No usa dependencias externas.
 */
() => {
  const MAX_CANDIDATES = 40;
  const PRICE_RE =
    /(?:\$|US\$|CLP|USD|EUR|UF)\s?\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?|\d{1,3}(?:[.]\d{3})+(?:,\d{1,2})?/;
  const NOISE_RE =
    /(cuota|cuotas|dcto|descuento|ahorra|ahorro|envio|despacho|puntos|%|hasta \d+|desde \d+ cuotas)/i;
  const STRUCK_RE = /(line-through|strike)/i;

  const text = (node) => (node ? (node.textContent || "").replace(/\s+/g, " ").trim() : "");

  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  /* Texto que pertenece al elemento y no a sus hijos: evita capturar el mismo
     precio una vez por cada contenedor que lo envuelve. */
  const ownText = (el) => {
    let out = "";
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) out += node.textContent;
    }
    return out.replace(/\s+/g, " ").trim();
  };

  const describe = (el) => {
    const bits = [el.tagName.toLowerCase()];
    if (el.id) bits.push("#" + el.id);
    const cls = typeof el.className === "string" ? el.className.trim() : "";
    if (cls) bits.push("." + cls.split(/\s+/).slice(0, 4).join("."));
    for (const attr of ["itemprop", "data-testid", "aria-label", "data-cy"]) {
      const value = el.getAttribute && el.getAttribute(attr);
      if (value) bits.push(`${attr}=${value}`);
    }
    return bits.join(" ");
  };

  /* Etiqueta cercana: lo que un humano leeria junto al numero ("Precio internet").
     Se descarta cualquier fragmento que contenga mas de un importe: si no, el
     texto del contenedor arrastra los precios vecinos al contexto de todos los
     candidatos y el modelo pierde la senal que sirve para distinguirlos. */
  const singlePriced = (value) => {
    if (!value) return false;
    const matches = value.match(new RegExp(PRICE_RE.source, "g"));
    return !matches || matches.length <= 1;
  };

  const nearbyLabel = (el) => {
    const parts = [];
    let previous = el.previousElementSibling;
    for (let i = 0; i < 2 && previous; i += 1) {
      const value = text(previous).slice(0, 80);
      if (singlePriced(value)) parts.push(value);
      previous = previous.previousElementSibling;
    }
    if (el.parentElement) {
      const label = el.parentElement.previousElementSibling;
      if (label) {
        const value = text(label).slice(0, 80);
        if (singlePriced(value)) parts.push(value);
      }
      const parent = text(el.parentElement).slice(0, 90);
      if (singlePriced(parent)) parts.push(parent);
      const aria = el.parentElement.getAttribute("aria-label");
      if (aria) parts.push(aria.slice(0, 60));
    }
    return parts.filter(Boolean).join(" | ").slice(0, 140);
  };

  const struck = (el) => {
    let node = el;
    for (let i = 0; i < 3 && node; i += 1) {
      const style = window.getComputedStyle(node);
      if (STRUCK_RE.test(style.textDecorationLine || style.textDecoration || "")) return true;
      if (node.tagName === "S" || node.tagName === "DEL" || node.tagName === "STRIKE") return true;
      node = node.parentElement;
    }
    return false;
  };

  // ---- datos estructurados -------------------------------------------------
  const structured = {};
  const structuredPrices = [];

  const walk = (node, visit) => {
    if (Array.isArray(node)) {
      node.forEach((item) => walk(item, visit));
    } else if (node && typeof node === "object") {
      visit(node);
      Object.values(node).forEach((value) => walk(value, visit));
    }
  };

  document.querySelectorAll('script[type="application/ld+json"]').forEach((script) => {
    let data;
    try {
      data = JSON.parse(script.textContent || "");
    } catch (_) {
      try {
        data = JSON.parse("[" + (script.textContent || "").trim().replace(/,$/, "") + "]");
      } catch (_e) {
        return;
      }
    }
    walk(data, (node) => {
      const type = String(node["@type"] || "");
      if (/product/i.test(type) && node.name && !structured.name) {
        structured.name = String(node.name).slice(0, 200);
        if (node.sku) structured.sku = String(node.sku).slice(0, 60);
        if (node.brand) {
          structured.brand = String(
            typeof node.brand === "object" ? node.brand.name || "" : node.brand
          ).slice(0, 60);
        }
      }
      ["price", "lowPrice", "highPrice"].forEach((key) => {
        if (node[key] !== undefined && node[key] !== null && node[key] !== "") {
          structuredPrices.push({
            raw: String(node[key]),
            currency: String(node.priceCurrency || "").toUpperCase(),
            key,
          });
        }
      });
      if (node.availability) {
        structured.availability = String(node.availability).slice(0, 80);
      }
    });
  });

  const metaPairs = [
    ["product:price:amount", "product:price:currency"],
    ["og:price:amount", "og:price:currency"],
  ];
  metaPairs.forEach(([amountKey, currencyKey]) => {
    const amount = document.querySelector(`meta[property="${amountKey}"]`);
    if (!amount || !amount.content) return;
    const currency = document.querySelector(`meta[property="${currencyKey}"]`);
    structuredPrices.push({
      raw: amount.content,
      currency: currency && currency.content ? currency.content.toUpperCase() : "",
      key: amountKey,
    });
  });
  const itempropPrice = document.querySelector('[itemprop="price"]');
  if (itempropPrice) {
    const raw = itempropPrice.getAttribute("content") || text(itempropPrice);
    if (raw) {
      const currency = document.querySelector('[itemprop="priceCurrency"]');
      structuredPrices.push({
        raw,
        currency: currency
          ? (currency.getAttribute("content") || text(currency)).toUpperCase()
          : "",
        key: "itemprop",
      });
    }
  }

  // ---- importes visibles ---------------------------------------------------
  const seen = new Set();
  const visual = [];
  let maxFont = 0;

  document.querySelectorAll("body *").forEach((el) => {
    if (visual.length >= MAX_CANDIDATES * 3) return;
    const tag = el.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT" || tag === "SVG") return;
    const own = ownText(el);
    if (!own || own.length > 60) return;
    if (!PRICE_RE.test(own)) return;
    if (!visible(el)) return;

    const style = window.getComputedStyle(el);
    const font = parseFloat(style.fontSize) || 12;
    maxFont = Math.max(maxFont, font);
    const rect = el.getBoundingClientRect();
    const label = nearbyLabel(el);

    visual.push({
      text: own.slice(0, 60),
      context: `${describe(el)} :: ${label}`.slice(0, 220),
      font,
      weight: parseInt(style.fontWeight, 10) || 400,
      top: rect.top + window.scrollY,
      struck: struck(el),
      noisy: NOISE_RE.test(own) || NOISE_RE.test(label),
    });
  });

  const candidates = [];
  let id = 0;

  structuredPrices.slice(0, 6).forEach((item) => {
    const key = `s:${item.raw}:${item.currency}`;
    if (seen.has(key)) return;
    seen.add(key);
    id += 1;
    candidates.push({
      id,
      text: item.currency ? `${item.raw} ${item.currency}` : String(item.raw),
      raw: String(item.raw),
      currency: item.currency,
      kind: "structured",
      context: `json-ld/meta (${item.key})`,
      prominence: 1,
      struck: false,
      noisy: false,
    });
  });

  visual
    .sort((a, b) => b.font * b.weight - a.font * a.weight)
    .forEach((item) => {
      if (candidates.length >= MAX_CANDIDATES) return;
      const key = `v:${item.text}`;
      if (seen.has(key)) return;
      seen.add(key);
      id += 1;
      const fontScore = maxFont ? item.font / maxFont : 0.5;
      const weightScore = Math.min(item.weight, 800) / 800;
      candidates.push({
        id,
        text: item.text,
        raw: item.text,
        currency: "",
        kind: "visual",
        context: item.context,
        prominence: Math.round((fontScore * 0.7 + weightScore * 0.3) * 100) / 100,
        struck: item.struck,
        noisy: item.noisy,
      });
    });

  // ---- disponibilidad y especificaciones -----------------------------------
  const bodyText = (document.body ? document.body.innerText || "" : "").slice(0, 20000);
  let availability = "";
  const outMatch = bodyText.match(
    /(sin stock|agotado|no disponible|producto no disponible|out of stock|sold out)/i
  );
  const inMatch = bodyText.match(/(en stock|disponible|agregar al carro|añadir al carro|comprar ahora)/i);
  if (outMatch) availability = outMatch[0];
  else if (inMatch) availability = inMatch[0];
  if (structured.availability) availability = structured.availability;

  const specs = [];
  document.querySelectorAll("table tr, dl > div, li").forEach((row) => {
    if (specs.length >= 12) return;
    const value = text(row);
    if (value.length > 8 && value.length < 90 && /[:|]|\d/.test(value)) specs.push(value);
  });

  const crumbs = [];
  document
    .querySelectorAll('nav[aria-label*="read" i] a, .breadcrumb a, [class*="breadcrumb"] a')
    .forEach((link) => {
      const value = text(link);
      if (value && crumbs.length < 6) crumbs.push(value);
    });

  const heading = document.querySelector("h1");
  const ogTitle = document.querySelector('meta[property="og:title"]');

  return {
    url: location.href,
    title: (ogTitle && ogTitle.content) || structured.name || document.title || "",
    heading: text(heading),
    breadcrumb: crumbs.join(" > "),
    structured,
    price_candidates: candidates,
    availability_text: availability,
    specs,
  };
};
