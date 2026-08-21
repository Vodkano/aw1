"""Los jueces: donde la IA toma las decisiones del comparador.

Hay cuatro momentos en los que interviene Ollama, y en los cuatro el codigo hace
lo mismo: prepara un contexto acotado, pide un JSON cerrado, valida la respuesta
y **verifica** lo que el modelo afirmo contra los datos reales de la pagina.

    plan_search   ->  que buscar, con que variantes y que descartar
    pick_products ->  cuales de los resultados del buscador son el producto
    read_page     ->  cual de los importes de la ficha es el precio de venta
    write_verdict ->  como resumirle la comparacion a la persona

Si Ollama no esta disponible o devuelve algo que no encaja, cada juez tiene una
alternativa deterministica y el comparador sigue funcionando. La IA mejora el
resultado; no es un punto unico de fallo.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..pricing import matching, money
from . import prompts
from .client import OllamaClient
from .groq_client import GroqClient
from .schemas import CandidateSelection, ChatRoute, PriceVerdict, SearchPlan

logger = logging.getLogger(__name__)

MAX_CARDS_IN_PROMPT = 14
MAX_PRICE_CANDIDATES = 16
PRICE_TOLERANCE = 0.02  # 2 % de margen al comparar lo que dijo el modelo


@dataclass(slots=True)
class JudgeStats:
    """Cuantas decisiones tomo la IA y cuantas hubo que corregir."""

    llm_calls: int = 0
    llm_used: int = 0
    fallbacks: int = 0
    corrections: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "llm_used": self.llm_used,
            "fallbacks": self.fallbacks,
            "corrections": self.corrections,
            "notes": self.notes[-8:],
        }


class Judges:
    def __init__(
        self, client: OllamaClient | GroqClient, *, model: str, timeout: float = 45.0
    ) -> None:
        self._llm = client
        self._model = model
        self._timeout = timeout
        self.stats = JudgeStats()

    # ------------------------------------------------------------------
    # 1. Plan de busqueda
    # ------------------------------------------------------------------
    async def plan_search(self, query: str) -> SearchPlan:
        fallback = self._fallback_plan(query)
        self.stats.llm_calls += 1
        payload = await self._llm.json_call(
            [
                {"role": "system", "content": prompts.SEARCH_PLAN_SYSTEM},
                {"role": "user", "content": prompts.SEARCH_PLAN_USER.format(query=query[:400])},
            ],
            model=self._model,
            timeout=self._timeout,
        )
        if payload is None:
            self.stats.fallbacks += 1
            self.stats.notes.append("Plan de busqueda sin IA: Ollama no respondio.")
            return fallback
        try:
            plan = SearchPlan.model_validate(payload)
        except Exception:  # noqa: BLE001 - una salida rara no puede tumbar la busqueda
            self.stats.fallbacks += 1
            self.stats.notes.append("Plan de busqueda sin IA: el JSON no encajo en el esquema.")
            return fallback

        # El modelo puede vaciar campos clave; se rellenan con la heuristica.
        if not plan.product.strip():
            plan.product = fallback.product
        if not plan.queries:
            plan.queries = fallback.queries
        plan.forbidden = self._clean_terms(plan.forbidden, plan.product)
        plan.required = self._clean_terms(plan.required, "", keep_from_product=plan.product)
        self.stats.llm_used += 1
        return plan

    @staticmethod
    def _fallback_plan(query: str) -> SearchPlan:
        clean = " ".join(str(query).split())
        return SearchPlan(
            product=clean,
            queries=matching.fallback_queries(clean),
            required=[],
            forbidden=sorted(matching.ACCESSORY_WORDS - set(matching.tokenize(clean)))[:12],
            notes="Plan generado sin IA.",
        )

    @staticmethod
    def _clean_terms(
        terms: list[str], product: str, *, keep_from_product: str = ""
    ) -> list[str]:
        """Quita terminos vacios, larguisimos o que contradigan lo que se pidio."""
        product_tokens = set(matching.tokenize(product or keep_from_product))
        cleaned: list[str] = []
        for term in terms:
            text = " ".join(str(term).split())[:40]
            if not text or len(text) < 2:
                continue
            if product and set(matching.tokenize(text)) & product_tokens:
                continue  # nunca prohibir algo que la persona pidio
            if text.lower() not in {item.lower() for item in cleaned}:
                cleaned.append(text)
        return cleaned[:14]

    # ------------------------------------------------------------------
    # 2. Seleccion de candidatos del buscador
    # ------------------------------------------------------------------
    async def pick_products(
        self, plan: SearchPlan, store: str, cards: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        """Devuelve las tarjetas elegidas, en orden de preferencia."""
        if not cards:
            return []

        ranked = self._prerank(plan, cards)
        shortlist = ranked[:MAX_CARDS_IN_PROMPT]
        by_id = {card["id"]: card for card in shortlist}

        self.stats.llm_calls += 1
        payload = await self._llm.json_call(
            [
                {"role": "system", "content": prompts.CANDIDATES_SYSTEM},
                {
                    "role": "user",
                    "content": prompts.CANDIDATES_USER.format(
                        product=plan.product,
                        max_picks=limit,
                        required=", ".join(plan.required) or "(nada en particular)",
                        forbidden=", ".join(plan.forbidden) or "(nada en particular)",
                        store=store,
                        cards=self._render_cards(shortlist),
                    ),
                },
            ],
            model=self._model,
            timeout=self._timeout,
        )

        if payload is None:
            self.stats.fallbacks += 1
            return self._fallback_picks(plan, ranked, limit)
        try:
            selection = CandidateSelection.model_validate(payload)
        except Exception:  # noqa: BLE001
            self.stats.fallbacks += 1
            return self._fallback_picks(plan, ranked, limit)

        chosen: list[dict[str, Any]] = []
        for pick in selection.picks:
            card = by_id.get(pick.id)
            if card is None:
                self.stats.corrections += 1
                continue  # el modelo invento un id: se ignora
            chosen.append({**card, "confidence": pick.confidence, "why": pick.reason})
            if len(chosen) >= limit:
                break

        if not chosen:
            # La IA descarto todo. Se respeta salvo que la heuristica este muy
            # segura, porque un falso negativo deja la tienda sin resultados.
            strong = [card for card in ranked if card["_score"] >= 0.85]
            if strong:
                self.stats.corrections += 1
                self.stats.notes.append(
                    f"{store}: la IA descarto todo pero habia coincidencias claras."
                )
                return strong[:limit]
            return []

        self.stats.llm_used += 1
        return chosen

    @staticmethod
    def _prerank(plan: SearchPlan, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ordena por coincidencia antes de gastar contexto del modelo."""
        scored: list[dict[str, Any]] = []
        for index, card in enumerate(cards, start=1):
            text = f"{card.get('title', '')} {card.get('url', '')}"
            result = matching.score(
                text, plan.product, required=plan.required, forbidden=plan.forbidden
            )
            scored.append({**card, "id": index, "_score": result.score, "_ok": result.ok})
        scored.sort(key=lambda card: (card["_ok"], card["_score"]), reverse=True)
        return scored

    @staticmethod
    def _fallback_picks(
        plan: SearchPlan, ranked: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        good = [card for card in ranked if card["_ok"]]
        return [
            {**card, "confidence": round(card["_score"], 2), "why": "Seleccion sin IA."}
            for card in good[:limit]
        ]

    @staticmethod
    def _render_cards(cards: list[dict[str, Any]]) -> str:
        lines = []
        for card in cards:
            price = card.get("price_text") or "sin precio visible"
            title = str(card.get("title", ""))[:150]
            lines.append(f"[{card['id']}] {title} | precio mostrado: {price}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 3. Lectura de la ficha  (la decision principal)
    # ------------------------------------------------------------------
    async def read_page(self, plan: SearchPlan, page: dict[str, Any]) -> PriceVerdict:
        """Le entrega a Ollama el contexto de la ficha y valida lo que decida."""
        candidates: list[dict[str, Any]] = page.get("price_candidates", [])[:MAX_PRICE_CANDIDATES]
        if not candidates:
            return PriceVerdict(
                is_match=False, reason="La pagina no expone ningun importe legible."
            )

        by_id = {int(item["id"]): item for item in candidates}

        self.stats.llm_calls += 1
        payload = await self._llm.json_call(
            [
                {"role": "system", "content": prompts.PAGE_VERDICT_SYSTEM},
                {
                    "role": "user",
                    "content": prompts.PAGE_VERDICT_USER.format(
                        product=plan.product,
                        required=", ".join(plan.required) or "(nada en particular)",
                        forbidden=", ".join(plan.forbidden) or "(nada en particular)",
                        page=self._render_page(page, candidates),
                    ),
                },
            ],
            model=self._model,
            timeout=self._timeout,
        )

        if payload is None:
            self.stats.fallbacks += 1
            return self._fallback_verdict(plan, page, candidates, "Decision sin IA.")
        try:
            verdict = PriceVerdict.model_validate(payload)
        except Exception:  # noqa: BLE001
            self.stats.fallbacks += 1
            return self._fallback_verdict(
                plan, page, candidates, "Decision sin IA: el JSON no encajo."
            )

        verdict = self._verify(verdict, by_id, plan, page)
        if verdict.is_match:
            self.stats.llm_used += 1
        return verdict

    def _verify(
        self,
        verdict: PriceVerdict,
        by_id: dict[int, dict[str, Any]],
        plan: SearchPlan,
        page: dict[str, Any],
    ) -> PriceVerdict:
        """Contrasta el veredicto con los datos reales. Aqui se ataja la alucinacion.

        El modelo elige entre importes que ya existen en la pagina, asi que su
        respuesta se puede comprobar: si el numero que escribio no corresponde al
        candidato que dijo elegir, manda el candidato.
        """
        if not verdict.is_match:
            return verdict

        candidate = by_id.get(verdict.candidate_id) if verdict.candidate_id is not None else None
        if candidate is None:
            self.stats.corrections += 1
            self.stats.notes.append("El modelo eligio un importe que no estaba en la pagina.")
            return self._fallback_verdict(
                plan, page, list(by_id.values()), "El id elegido no existia; se uso la heuristica."
            )

        real_value = float(candidate["value"])
        claimed = verdict.price
        if claimed is None or abs(claimed - real_value) > max(real_value * PRICE_TOLERANCE, 1.0):
            self.stats.corrections += 1
            self.stats.notes.append(
                f"Precio corregido: el modelo dijo {claimed} y la pagina dice {real_value}."
            )
        verdict.price = real_value
        verdict.currency = str(candidate.get("currency") or verdict.currency).upper()

        # Segunda comprobacion: que el titulo real de la pagina sea el producto.
        title = page.get("title") or verdict.product_title
        check = matching.score(
            f"{title} {page.get('url', '')}",
            plan.product,
            required=plan.required,
            forbidden=plan.forbidden,
        )
        # Un fallo de cobertura puede ser un titulo escueto, y ahi la confianza
        # alta del modelo manda. Un accesorio o un requisito ausente, no: eso es
        # otro producto y ninguna confianza lo convierte en el correcto.
        hard_no = check.kind in {"accessory", "required"}
        if not check.ok and (hard_no or verdict.confidence < 0.85):
            self.stats.corrections += 1
            self.stats.notes.append(f"Descartado por titulo: {check.reason}")
            return PriceVerdict(is_match=False, reason=check.reason, confidence=check.score)

        if not verdict.product_title:
            verdict.product_title = str(title or "")
        return verdict

    def _fallback_verdict(
        self,
        plan: SearchPlan,
        page: dict[str, Any],
        candidates: list[dict[str, Any]],
        note: str,
    ) -> PriceVerdict:
        """Elige el importe mas fiable sin IA: estructurado > destacado > barato."""
        title = str(page.get("title") or "")
        check = matching.score(
            f"{title} {page.get('url', '')}",
            plan.product,
            required=plan.required,
            forbidden=plan.forbidden,
        )
        if not check.ok:
            return PriceVerdict(is_match=False, reason=check.reason, confidence=check.score)

        usable = [item for item in candidates if money.plausible(float(item.get("value_clp") or 0))]
        if not usable:
            usable = candidates
        if not usable:
            return PriceVerdict(is_match=False, reason="Sin importes utilizables.")

        best = min(
            usable,
            key=lambda item: (
                0 if item.get("kind") == "structured" else 1,
                -float(item.get("prominence") or 0),
                float(item.get("value_clp") or item.get("value") or 0),
            ),
        )
        return PriceVerdict(
            is_match=True,
            candidate_id=int(best["id"]),
            price=float(best["value"]),
            currency=str(best.get("currency") or "CLP"),
            product_title=title,
            in_stock=page.get("in_stock"),
            confidence=round(min(check.score, 0.75), 2),
            reason=note,
        )

    @staticmethod
    def _render_page(page: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
        """Serializa la pagina para el modelo: compacto, ordenado y sin HTML."""
        lines: list[str] = [
            f"URL: {page.get('url', '')}",
            f"Titulo: {page.get('title', '')}",
        ]
        if page.get("heading"):
            lines.append(f"Encabezado: {page['heading']}")
        if page.get("breadcrumb"):
            lines.append(f"Ruta: {page['breadcrumb']}")
        if page.get("availability_text"):
            lines.append(f"Disponibilidad: {page['availability_text']}")
        if page.get("structured"):
            lines.append(
                "Datos estructurados: "
                + json.dumps(page["structured"], ensure_ascii=False)[:600]
            )
        specs = page.get("specs") or []
        if specs:
            lines.append("Especificaciones: " + " | ".join(str(item)[:80] for item in specs[:8]))

        lines.append("")
        lines.append("Importes encontrados en la pagina:")
        for item in candidates:
            origin = "datos estructurados" if item.get("kind") == "structured" else "texto"
            context = str(item.get("context", ""))[:110]
            lines.append(
                f"[{item['id']}] {item.get('text', '')} "
                f"(valor {item.get('value')} {item.get('currency', 'CLP')}, "
                f"origen {origin}, contexto: {context})"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 4. Veredicto final
    # ------------------------------------------------------------------
    async def write_verdict(
        self, product: str, offers: list[dict[str, Any]], visited: int, discarded: int
    ) -> str:
        if not offers:
            return "No se encontraron precios utiles para este producto."

        deterministic = self._fallback_verdict_text(product, offers, visited, discarded)
        rendered = "\n".join(
            f"- {offer['store']}: {money.format_clp(offer['price_clp'])}"
            + (f" (publicado en {offer['currency']})" if offer["currency"] != "CLP" else "")
            + (" [sin stock]" if offer.get("in_stock") is False else "")
            for offer in offers[:10]
        )

        self.stats.llm_calls += 1
        try:
            text = await self._llm.chat(
                [
                    {"role": "system", "content": prompts.COMPARISON_SYSTEM},
                    {
                        "role": "user",
                        "content": prompts.COMPARISON_USER.format(
                            product=product,
                            offers=rendered,
                            visited=visited,
                            discarded=discarded,
                        ),
                    },
                ],
                model=self._model,
                temperature=0.3,
                timeout=self._timeout,
                max_tokens=220,
            )
        except Exception:  # noqa: BLE001
            self.stats.fallbacks += 1
            return deterministic

        clean = " ".join(text.split())
        if not clean:
            self.stats.fallbacks += 1
            return deterministic
        # Si el modelo se inventa un precio que no esta en la lista, no se usa.
        if not self._prices_are_real(clean, offers):
            self.stats.corrections += 1
            self.stats.notes.append("El veredicto mencionaba un precio inexistente; se reescribio.")
            return deterministic
        self.stats.llm_used += 1
        return clean[:600]

    #: Solo se auditan importes: un numero suelto como el "256" de "256GB" no es
    #: un precio y no debe invalidar el veredicto.
    _MONEY_IN_TEXT = re.compile(
        r"(?:\$|US\$|CLP\s?)\s?\d[\d.,]*|\b\d{1,3}(?:\.\d{3})+\b"
    )

    @classmethod
    def _prices_are_real(cls, text: str, offers: list[dict[str, Any]]) -> bool:
        """Comprueba que todo importe citado en el veredicto exista de verdad."""
        real: set[str] = set()
        for offer in offers:
            for value in (offer.get("price_clp"), offer.get("price")):
                if value is None:
                    continue
                real.add(str(int(round(float(value)))))
        for token in cls._MONEY_IN_TEXT.findall(text):
            digits = re.sub(r"\D", "", token)
            if not digits:
                continue
            if digits not in real:
                return False
        return True

    @staticmethod
    def _fallback_verdict_text(
        product: str, offers: list[dict[str, Any]], visited: int, discarded: int
    ) -> str:
        best = offers[0]
        parts = [
            f"Se revisaron {visited} tiendas y {product} aparece mas barato en "
            f"{best['store']}, a {money.format_clp(best['price_clp'])}."
        ]
        if len(offers) > 1:
            worst = offers[-1]
            gap = worst["price_clp"] - best["price_clp"]
            if gap > 0:
                percent = gap / worst["price_clp"] * 100
                parts.append(
                    f"Entre la oferta mas barata y la mas cara hay "
                    f"{money.format_clp(gap)} de diferencia ({percent:.0f}%)."
                )
        if discarded:
            parts.append(f"Se descartaron {discarded} resultados que no eran el producto.")
        return " ".join(parts)

    # ------------------------------------------------------------------
    # 5. Enrutado del chat
    # ------------------------------------------------------------------
    async def route_chat(self, message: str) -> ChatRoute | None:
        self.stats.llm_calls += 1
        payload = await self._llm.json_call(
            [
                {"role": "system", "content": prompts.ROUTE_SYSTEM},
                {"role": "user", "content": prompts.ROUTE_USER.format(message=message[:1500])},
            ],
            model=self._model,
            timeout=min(self._timeout, 25.0),
        )
        if payload is None:
            self.stats.fallbacks += 1
            return None
        try:
            route = ChatRoute.model_validate(payload)
        except Exception:  # noqa: BLE001
            self.stats.fallbacks += 1
            return None
        self.stats.llm_used += 1
        return route
