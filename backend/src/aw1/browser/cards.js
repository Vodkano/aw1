/**
 * Extractor de tarjetas de resultado, para paginas de busqueda de tiendas.
 *
 * Recibe la lista de patrones de URL que identifican una ficha de producto en
 * esa tienda y devuelve, por cada enlace que encaje, el titulo y el precio que
 * se ve en la tarjeta. Ese resumen es lo que despues juzga el modelo.
 *
 * Se ejecuta con page.evaluate(patterns).
 */
(patterns) => {
  const MAX_CARDS = 60;
  const PRICE_RE =
    /(?:\$|US\$|CLP|USD)\s?\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?|\d{1,3}(?:[.]\d{3})+/;

  const text = (node) => (node ? (node.textContent || "").replace(/\s+/g, " ").trim() : "");

  const looksLikeProduct = (href) => {
    if (!href) return false;
    const lowered = href.toLowerCase();
    if (/#|javascript:|mailto:|tel:/.test(lowered)) return false;
    if (
      /\/(login|signin|registro|register|cuenta|account|carro|cart|checkout|ayuda|help|terminos|privacidad|contacto|blog)\b/.test(
        lowered
      )
    ) {
      return false;
    }
    if (!patterns || patterns.length === 0) return true;
    return patterns.some((pattern) => lowered.includes(pattern.toLowerCase()));
  };

  /* Contenedores candidatos: los ancestros del enlace, del mas cercano al mas
     lejano. Se empieza por el padre y no por el propio <a>, porque el enlace
     suele llamarse "product-link" y coincidiria con el selector sin contener
     nunca el precio, que vive en la tarjeta que lo envuelve. */
  const containersOf = (anchor) => {
    const selectors =
      "li, article, [class*='product'], [class*='Product'], [class*='item'], [class*='Item'], [class*='card'], [class*='Card'], [data-testid], [data-pod], [itemtype]";
    const chain = [];
    let node = anchor.parentElement;
    for (let depth = 0; depth < 6 && node && node.tagName !== "BODY"; depth += 1) {
      if (!node.matches || node.matches(selectors)) chain.push(node);
      node = node.parentElement;
    }
    if (chain.length === 0 && anchor.parentElement) chain.push(anchor.parentElement);
    return chain;
  };

  const cardOf = (anchor) => containersOf(anchor)[0] || anchor.parentElement || anchor;

  const titleOf = (anchor, card) => {
    const direct = text(anchor);
    if (direct.length > 8) return direct;
    const label = anchor.getAttribute("aria-label") || anchor.getAttribute("title");
    if (label && label.length > 8) return label.replace(/\s+/g, " ").trim();
    const heading = card.querySelector("h1, h2, h3, h4, [class*='name'], [class*='title']");
    const headingText = text(heading);
    if (headingText.length > 4) return headingText;
    const image = card.querySelector("img[alt]");
    if (image && image.alt && image.alt.length > 4) return image.alt.replace(/\s+/g, " ").trim();
    return direct;
  };

  const priceOf = (card) => {
    const nodes = card.querySelectorAll(
      "[class*='price'], [class*='Price'], [data-testid*='price'], [itemprop='price'], span, div, p"
    );
    for (const node of nodes) {
      const value = text(node);
      if (!value || value.length > 40) continue;
      if (/cuota|dcto|descuento|ahorra|envio|despacho|%/i.test(value)) continue;
      const match = value.match(PRICE_RE);
      if (match) return match[0];
    }
    const whole = text(card);
    const match = whole.match(PRICE_RE);
    return match ? match[0] : "";
  };

  const seen = new Set();
  const cards = [];

  document.querySelectorAll("a[href]").forEach((anchor) => {
    if (cards.length >= MAX_CARDS) return;
    let href;
    try {
      href = new URL(anchor.getAttribute("href"), location.href).href;
    } catch (_) {
      return;
    }
    if (!looksLikeProduct(href)) return;
    const clean = href.split("#")[0];
    if (seen.has(clean)) return;

    const containers = containersOf(anchor);
    const card = containers[0] || anchor;
    const title = titleOf(anchor, card);
    if (!title || title.length < 5) return;

    /* El precio se busca subiendo hasta encontrar uno: en algunas tiendas vive
       en el mismo div del titulo y en otras dos niveles mas arriba. Se para en
       el primero que aparece para no robarle el precio a la tarjeta vecina. */
    let priceText = "";
    for (const container of containers.slice(0, 3)) {
      priceText = priceOf(container);
      if (priceText) break;
    }

    seen.add(clean);
    cards.push({
      url: clean,
      title: title.slice(0, 200),
      price_text: priceText.slice(0, 40),
      position: cards.length + 1,
    });
  });

  return cards;
};
