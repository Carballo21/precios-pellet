"""Prueba completa: servidor web local con páginas de prueba, dos rondas, alarmas y panel."""
import functools
import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest
import yaml

from pellet import main as app

RAIZ = Path(__file__).resolve().parent.parent
FX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def entorno(tmp_path):
    web = tmp_path / "web"
    shutil.copytree(FX, web)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(web))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    cfg = tmp_path / "config"
    shutil.copytree(RAIZ / "config", cfg)
    aj = yaml.safe_load((cfg / "ajustes.yaml").read_text())
    aj["descarga"].update(pausa_min=0, pausa_max=0, reintentos=0, timeout=10, playwright_si_falla=False)
    (cfg / "ajustes.yaml").write_text(yaml.safe_dump(aj, allow_unicode=True))

    fuentes = [
        dict(id="lm", nombre="Saco Iberpellet", tienda="Leroy Merlin", url=f"{base}/leroy.html",
             tipo="destino", formato="saco", kg=15, region="Nacional"),
        dict(id="bauhaus", nombre="Ecoloma", tienda="Bauhaus", url=f"{base}/micro.html",
             tipo="destino", formato="saco", kg=15, region="Nacional"),
        dict(id="caexven", nombre="Saco", tienda="Caexven", url=f"{base}/products/saco-15",
             tipo="destino", formato="saco", kg=15, region="Región de Murcia"),
        dict(id="cverde", nombre="Saco", tienda="Carbón Verde", url=f"{base}/carbonverde.html",
             tipo="destino", formato="saco", kg=15, region="Castilla y León",
             regex=r"Saco de pellets de 15 kg\W*:?\s*(\d+[.,]?\d*)\s*euros"),
        dict(id="mansele", nombre="Palet 77", tienda="Mansele", url=f"{base}/texto.html",
             tipo="destino", formato="palet", kg=1155, region="Extremadura"),
        dict(id="agro", nombre="Palet 72", tienda="Agrotiendas", url=f"{base}/meta.html",
             tipo="destino", formato="palet", kg=1080, region="Nacional"),
        dict(id="carrefour", nombre="Palet 77 (JS)", tienda="Carrefour", url=f"{base}/js.html",
             tipo="destino", formato="palet", kg=1155, region="Nacional", playwright=True, selector=".precio"),
        dict(id="sbi", nombre="Granel", tienda="SBI", url=f"{base}/granel.html", tipo="destino",
             formato="granel", kg=1000, iva_incluido=False, region="Cataluña", selector=".price"),
        dict(id="falsa", nombre="Asturias 77 sacos", tienda="Web dudosa", url=f"{base}/fraude.html",
             tipo="destino", formato="palet", kg=1155, region="Nacional"),
        dict(id="naturbero", nombre="Big bag", tienda="Naturbero", url=f"{base}/naturbero.html",
             tipo="origen", formato="bigbag", kg=1000, region="País Vasco"),
        dict(id="rota", nombre="Página rota", tienda="Rota", url=f"{base}/no-existe.html",
             tipo="destino", formato="saco", kg=15, region="Nacional"),
    ]
    (cfg / "fuentes.yaml").write_text(yaml.safe_dump({"fuentes": fuentes}, allow_unicode=True))

    datos = tmp_path / "data"
    datos.mkdir()
    for f in ("avebiom_ipb.csv", "avebiom_exw.csv", "presupuestos_origen.csv"):
        shutil.copy(RAIZ / "data" / f, datos / f)
    yield dict(web=web, cfg=cfg, datos=datos, salida=tmp_path / "docs")
    srv.shutdown()


def ronda(e):
    return app.main(["--config", str(e["cfg"]), "--fuentes", str(e["cfg"] / "fuentes.yaml"),
                     "--datos", str(e["datos"]), "--salida", str(e["salida"]),
                     "--sin-avisos", "--sin-red-avebiom"])


def test_dos_rondas(entorno, capsys):
    assert ronda(entorno) == 0
    filas = app.leer_csv(entorno["datos"] / "precios.csv")
    por_id = {f["fuente_id"]: f for f in filas}
    assert len(filas) == 11
    assert por_id["lm"]["eur_t_con_iva"] == "399.33"
    assert por_id["caexven"]["metodo"] == "shopify" and por_id["caexven"]["precio"] == "7.0"
    assert por_id["carrefour"]["precio"] == "445.0"          # leído con navegador real
    assert por_id["sbi"]["eur_t_con_iva"] == "350.9"         # 290 + 21 % IVA
    assert por_id["naturbero"]["iva_incluido"] == "no"       # declarado por la web
    assert por_id["falsa"]["sospechoso"] == "si"
    assert por_id["rota"]["estado"] == "error"
    assert por_id["bauhaus"]["disponible"] == "no"
    salida1 = capsys.readouterr().out
    assert "sospechosamente bajo" in salida1

    # Segunda ronda: Leroy sube un 10 %, la página rota sigue rota
    p = entorno["web"] / "leroy.html"
    p.write_text(p.read_text().replace('"5.99"', '"6.59"'))
    assert ronda(entorno) == 0
    salida2 = capsys.readouterr().out
    assert "Leroy Merlin · Saco Iberpellet: sube 10.0 %" in salida2
    assert "falla 2 veces seguidas" in salida2
    assert "sospechosamente bajo" not in salida2             # enfriamiento: no se repite

    datos = json.loads((entorno["salida"] / "datos.json").read_text())
    assert datos["num_rondas"] == 2 and len(datos["tabla"]) == 11
    assert datos["kpis"]["exw"]["mes"] == "2026-09"
    lm = next(f for f in datos["tabla"] if f["fuente_id"] == "lm")
    assert lm["var_pct"] == 10.0
    html = (entorno["salida"] / "index.html").read_text()
    assert "/*__DATOS__*/null" not in html
