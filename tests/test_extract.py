from datetime import date
from pathlib import Path

import pytest

from pellet.extract import desde_shopify_js, extraer, parse_importe
from pellet.normalize import normalizar, tipo_iva

FX = Path(__file__).parent / "fixtures"
AJ = {"iva": [{"desde": "2026-07-01", "tipo": 0.21}, {"desde": "2026-03-21", "tipo": 0.10}],
      "cordura_eur_t": {"min": 120, "max": 1500}}


@pytest.mark.parametrize("txt,esperado", [
    ("5,99 €", 5.99), ("5.99", 5.99), ("1.015,55 €", 1015.55), ("423,50", 423.5),
    ("€7,00 EUR", 7.0), ("1.155", 1155.0), (423.5, 423.5), ("sin precio", None), ("0", None),
])
def test_parse_importe(txt, esperado):
    assert parse_importe(txt) == esperado


def leer(nombre, **fuente):
    return extraer((FX / nombre).read_text("utf-8"), fuente)


def test_jsonld_simple():
    l = leer("leroy.html")
    assert (l.precio, l.disponible, l.metodo) == (5.99, True, "json-ld")


def test_jsonld_graph_sin_iva():
    l = leer("naturbero.html")
    assert l.precio == 295.0 and l.iva_incluido is False and l.disponible is True


def test_microdatos_agotado():
    l = leer("micro.html")
    assert (l.precio, l.disponible, l.metodo) == (4.99, False, "microdatos")


def test_meta():
    assert leer("meta.html").precio == 408.99


def test_texto_cerca_de_precio():
    l = leer("texto.html")
    assert l.precio == 423.5 and l.metodo == "texto"


def test_regex_configurado():
    l = leer("carbonverde.html", regex=r"Saco de pellets de 15 kg\W*:?\s*(\d+[.,]?\d*)\s*euros")
    assert l.precio == 5.0 and l.metodo == "regex"


def test_selector_css():
    l = leer("granel.html", selector=".price")
    assert l.precio == 290.0 and l.metodo == "css"


def test_shopify():
    l = desde_shopify_js((FX / "products" / "saco-15.js").read_text())
    assert l.precio == 7.0 and l.disponible is True


def test_iva_por_fechas():
    assert tipo_iva(AJ, date(2026, 5, 1)) == 0.10
    assert tipo_iva(AJ, date(2026, 11, 3)) == 0.21


def test_normalizar_saco_y_granel_sin_iva():
    n = normalizar(5.99, {"kg": 15}, None, AJ, date(2026, 11, 3))
    assert n["eur_t_con_iva"] == 399.33 and n["eur_saco15_con_iva"] == 5.99 and not n["anomalo"]
    g = normalizar(290, {"kg": 1000, "iva_incluido": False}, None, AJ, date(2026, 11, 3))
    assert g["eur_t_con_iva"] == 350.9 and g["eur_t_sin_iva"] == 290.0


def test_kg_mal_configurado_es_anomalo():
    assert normalizar(423.5, {"kg": 15}, None, AJ, date(2026, 11, 3))["anomalo"]
