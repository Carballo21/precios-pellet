"""Extracción del precio de una página de producto.

Orden de intentos (método "auto"):
  1. Datos estructurados JSON-LD (schema.org Product / Offer)
  2. Microdatos  itemprop="price"
  3. Metaetiquetas  product:price:amount / og:price:amount
  4. Selector CSS o expresión regular configurados en la fuente
  5. Texto visible: primer importe en euros cerca de la palabra "precio"
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup


@dataclass
class Lectura:
    precio: float | None = None
    disponible: bool | None = None
    iva_incluido: bool | None = None   # solo si la web lo declara
    metodo: str = ""
    nota: str = ""
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------- números
_NUM = re.compile(r"\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?(?!\d)|\d+(?:[.,]\d{1,2})?")


def parse_importe(texto) -> float | None:
    """Convierte '1.015,55 €', '5,99', '5.99', 423.5 ... en float."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto) if texto > 0 else None
    s = str(texto).replace("\xa0", " ").strip()
    m = _NUM.search(s)
    if not m:
        return None
    n = m.group(0).replace(" ", "")
    if "," in n and "." in n:          # 1.015,55
        n = n.replace(".", "").replace(",", ".")
    elif "," in n:                     # 5,99
        n = n.replace(",", ".")
    elif n.count(".") >= 1 and all(len(x) == 3 for x in n.split(".")[1:]):  # 1.155 (miles)
        n = n.replace(".", "")
    try:
        v = float(n)
    except ValueError:
        return None
    return v if v > 0 else None


def _disponibilidad(valor) -> bool | None:
    if not valor:
        return None
    v = str(valor).lower()
    if any(k in v for k in ("outofstock", "soldout", "discontinued", "agotado")):
        return False
    if any(k in v for k in ("instock", "instoreonly", "limitedavailability",
                            "onlineonly", "preorder", "backorder")):
        return True
    return None


# ----------------------------------------------------------------- JSON-LD
def _recorrer(nodo):
    """Itera todos los diccionarios anidados (incluye @graph y listas)."""
    if isinstance(nodo, dict):
        yield nodo
        for v in nodo.values():
            yield from _recorrer(v)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from _recorrer(v)


def _es_tipo(d: dict, *tipos) -> bool:
    t = d.get("@type")
    if isinstance(t, list):
        return any(x in tipos for x in t)
    return t in tipos


def _precio_oferta(oferta: dict):
    """Devuelve (precio, iva_incluido) de un Offer/AggregateOffer."""
    iva = None
    precio = None
    spec = oferta.get("priceSpecification")
    specs = spec if isinstance(spec, list) else [spec] if spec else []
    for s in specs:
        if isinstance(s, dict) and s.get("price") is not None:
            precio = parse_importe(s.get("price"))
            if "valueAddedTaxIncluded" in s:
                iva = str(s["valueAddedTaxIncluded"]).lower() in ("true", "1")
            if precio:
                break
    if precio is None:
        precio = parse_importe(oferta.get("price"))
    if precio is None:
        precio = parse_importe(oferta.get("lowPrice"))
    if iva is None and "valueAddedTaxIncluded" in oferta:
        iva = str(oferta["valueAddedTaxIncluded"]).lower() in ("true", "1")
    return precio, iva


def desde_jsonld(soup: BeautifulSoup) -> Lectura | None:
    candidatas = []
    for tag in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:  # algunas webs dejan comas colgando
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except json.JSONDecodeError:
                continue
        for d in _recorrer(data):
            if _es_tipo(d, "Product", "ProductGroup", "IndividualProduct"):
                ofertas = d.get("offers")
                lista = ofertas if isinstance(ofertas, list) else [ofertas] if ofertas else []
                for o in lista:
                    if isinstance(o, dict):
                        p, iva = _precio_oferta(o)
                        if p:
                            candidatas.append(Lectura(p, _disponibilidad(o.get("availability")),
                                                      iva, "json-ld"))
            elif _es_tipo(d, "Offer", "AggregateOffer") and not candidatas:
                p, iva = _precio_oferta(d)
                if p:
                    candidatas.append(Lectura(p, _disponibilidad(d.get("availability")),
                                              iva, "json-ld"))
    if not candidatas:
        return None
    # Si hay varias ofertas (p.ej. con y sin IVA), la primera es la principal
    return candidatas[0]


# ----------------------------------------------------------------- microdatos / meta
def desde_microdatos(soup: BeautifulSoup) -> Lectura | None:
    el = soup.find(attrs={"itemprop": "price"})
    if el is None:
        return None
    p = parse_importe(el.get("content") or el.get_text(" "))
    if not p:
        return None
    disp = soup.find(attrs={"itemprop": "availability"})
    d = _disponibilidad(disp.get("href") or disp.get("content")) if disp else None
    return Lectura(p, d, None, "microdatos")


def desde_meta(soup: BeautifulSoup) -> Lectura | None:
    for prop in ("product:price:amount", "og:price:amount", "product:sale_price:amount"):
        el = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if el and parse_importe(el.get("content")):
            disp = soup.find("meta", attrs={"property": "product:availability"})
            d = _disponibilidad(disp.get("content")) if disp else None
            return Lectura(parse_importe(el.get("content")), d, None, "meta")
    return None


# ----------------------------------------------------------------- Shopify
def desde_shopify_js(texto_json: str) -> Lectura | None:
    """Respuesta de /products/<handle>.js (precio en céntimos)."""
    try:
        data = json.loads(texto_json)
    except (json.JSONDecodeError, TypeError):
        return None
    precio = data.get("price")
    if precio is None and data.get("variants"):
        precio = data["variants"][0].get("price")
    if precio is None:
        return None
    return Lectura(float(precio) / 100.0, data.get("available"), None, "shopify")


# ----------------------------------------------------------------- texto
_EURO = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*,\d{2}|\d+[.,]\d{2}|\d+)\s*(?:€|eur\b|euros)", re.I)


def desde_texto(soup: BeautifulSoup) -> Lectura | None:
    texto = soup.get_text(" ", strip=True)
    # Preferimos importes cerca de "precio"
    zona = re.search(r"precio.{0,120}", texto, re.I)
    for fragmento in ([zona.group(0)] if zona else []) + [texto]:
        m = _EURO.search(fragmento)
        if m:
            p = parse_importe(m.group(1))
            if p:
                return Lectura(p, None, None, "texto", "leído del texto visible; conviene configurar selector")
    return None


# ----------------------------------------------------------------- principal
def extraer(html: str, fuente: dict) -> Lectura:
    soup = BeautifulSoup(html, "lxml")
    metodo = fuente.get("metodo", "auto")

    # Selector o regex explícitos tienen prioridad si están configurados
    if fuente.get("selector"):
        el = soup.select_one(fuente["selector"])
        if el is not None:
            p = parse_importe(el.get("content") or el.get_text(" "))
            if p:
                return Lectura(p, None, None, "css")
    if fuente.get("regex"):
        texto = soup.get_text(" ", strip=True)
        m = re.search(fuente["regex"], texto, re.I | re.S)
        if m:
            p = parse_importe(m.group(1))
            if p:
                return Lectura(p, None, None, "regex")

    if metodo in ("css", "regex"):
        return Lectura(nota=f"el {metodo} configurado no encontró el precio")

    for funcion in (desde_jsonld, desde_microdatos, desde_meta):
        lec = funcion(soup)
        if lec and lec.precio:
            return lec

    lec = desde_texto(soup)
    if lec:
        return lec
    return Lectura(nota="no se encontró ningún precio en la página")
