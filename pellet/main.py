"""Ronda completa: leer precios -> guardar -> comparar con AVEBIOM -> alarmas -> panel.

Uso:
    python -m pellet.main                 # ronda normal
    python -m pellet.main --sin-avisos    # no envía avisos (solo los muestra)
    python -m pellet.main --solo-panel    # regenera el panel con los datos guardados
    python -m pellet.main --solo ID1,ID2  # prueba solo algunas fuentes
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import alerts, avebiom as av, dashboard, notify
from .extract import desde_shopify_js, extraer
from .fetch import Descargador
from .normalize import normalizar

RAIZ = Path(__file__).resolve().parent.parent
COLUMNAS = ["ronda", "fecha", "fuente_id", "tienda", "nombre", "tipo", "formato", "region",
            "canal", "certificacion", "transporte", "kg", "precio", "iva_incluido",
            "eur_t_con_iva", "eur_t_sin_iva", "eur_saco15_con_iva", "disponible",
            "metodo", "estado", "sospechoso", "error", "url"]

log = logging.getLogger("pellet")


def ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cargar_yaml(ruta: Path) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def leer_csv(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def anexar_csv(ruta: Path, filas: list[dict]):
    nuevo = not ruta.exists()
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
        if nuevo:
            w.writeheader()
        w.writerows(filas)


# ------------------------------------------------------------------ lectura de una fuente
def leer_fuente(d: Descargador, fuente: dict, ajustes: dict, ronda: str, hoy) -> dict:
    fila = {k: fuente.get(k, "") for k in ("tienda", "nombre", "tipo", "formato", "region",
                                           "canal", "certificacion", "transporte", "kg", "url")}
    fila.update({"ronda": ronda, "fecha": hoy.isoformat(), "fuente_id": fuente["id"],
                 "estado": "error", "sospechoso": "no"})
    url = fuente["url"]
    try:
        if not d.permitido(url):
            fila["error"] = "robots.txt no permite leer esta página"
            return fila

        lectura, error = None, ""
        shop = d.get_shopify(url)
        if shop:
            lectura = desde_shopify_js(shop)

        if not (lectura and lectura.precio) and not fuente.get("playwright"):
            try:
                lectura = extraer(d.get(url), fuente)
            except RuntimeError as e:
                error = str(e)

        if not (lectura and lectura.precio) and (fuente.get("playwright") or d.usar_playwright):
            try:
                lectura = extraer(d.get_navegador(url, forzar=bool(fuente.get("playwright"))), fuente)
                if lectura.precio:
                    lectura.metodo += "+navegador"
            except Exception as e:      # noqa: BLE001 - cualquier fallo del navegador
                error = error or f"navegador: {type(e).__name__}"

        if not (lectura and lectura.precio):
            fila["error"] = error or (lectura.nota if lectura else "sin precio")
            return fila

        n = normalizar(lectura.precio, fuente, lectura.iva_incluido, ajustes, hoy)
        fila.update({
            "precio": round(lectura.precio, 2),
            "iva_incluido": "si" if n["iva_incluido"] else "no",
            "eur_t_con_iva": n["eur_t_con_iva"],
            "eur_t_sin_iva": n["eur_t_sin_iva"],
            "eur_saco15_con_iva": n["eur_saco15_con_iva"],
            "disponible": {True: "si", False: "no"}.get(lectura.disponible, ""),
            "metodo": lectura.metodo,
            "estado": "anomalo" if n["anomalo"] else "ok",
            "error": "precio fuera de rango: revisa kg o selector" if n["anomalo"] else "",
        })
    except Exception as e:              # noqa: BLE001 - que una web rota no pare la ronda
        fila["error"] = f"{type(e).__name__}: {e}"[:200]
    return fila


# ------------------------------------------------------------------ ronda
def ejecutar(args) -> int:
    cfg_dir = Path(args.config)
    datos = Path(args.datos)
    ajustes = cargar_yaml(cfg_dir / "ajustes.yaml")
    conf_al = cargar_yaml(cfg_dir / "alertas.yaml")
    fuentes = [f for f in cargar_yaml(Path(args.fuentes))["fuentes"] if f.get("activo", True)]
    if args.solo:
        ids = set(args.solo.split(","))
        fuentes = [f for f in fuentes if f["id"] in ids]

    ipb = av.cargar_ipb(datos / "avebiom_ipb.csv")
    exw = av.cargar_exw(datos / "avebiom_exw.csv", ajustes["avebiom"]["exw_base_eur_t"])
    ruta_precios = datos / "precios.csv"
    ruta_estado = datos / "estado.json"
    estado = json.loads(ruta_estado.read_text("utf-8")) if ruta_estado.exists() else {}

    momento = ahora()
    hoy = momento.date()
    ipb_fila, exw_fila = av.ipb_vigente(ipb, hoy), av.exw_vigente(exw, hoy)
    historico = leer_csv(ruta_precios)

    if not args.solo_panel:
        ronda = momento.strftime("%Y-%m-%dT%H:%M:%S")
        d = Descargador(ajustes)
        actual = []
        try:
            for i, f in enumerate(fuentes, 1):
                fila = leer_fuente(d, f, ajustes, ronda, hoy)
                estado_txt = f"{fila.get('precio')} € → {fila.get('eur_t_con_iva')} €/t" \
                    if fila["estado"] != "error" else f"ERROR {fila['error']}"
                log.info("[%2d/%d] %-28s %s", i, len(fuentes), f["id"], estado_txt)
                actual.append(fila)
        finally:
            d.cerrar()

        alerts.marcar_sospechosos(actual, ipb_fila, ajustes, conf_al.get("reglas", []))

        # contador de fallos consecutivos
        fallos = estado.setdefault("fallos", {})
        for f in actual:
            fallos[f["fuente_id"]] = fallos.get(f["fuente_id"], 0) + 1 if f["estado"] == "error" else 0

        rondas = sorted({h["ronda"] for h in historico})
        anterior = [h for h in historico if rondas and h["ronda"] == rondas[-1]]

        lista = alerts.evaluar(actual, anterior, ipb_fila, exw_fila, ajustes, conf_al, estado)

        # ¿AVEBIOM ha publicado un índice nuevo?
        regla_av = next((r for r in conf_al.get("reglas", []) if r["tipo"] == "nuevo_indice_avebiom"
                         and r.get("activa", True)), None)
        if regla_av and not args.sin_red_avebiom:
            try:
                pdfs = av.enlaces_pdf(d.get(ajustes["avebiom"]["pagina_indices"]))
                conocidos = set(estado.get("avebiom_pdfs", []))
                nuevos = [u for u in pdfs if u not in conocidos]
                if conocidos and nuevos:
                    lista.append(alerts.Alerta(f"av:{nuevos[0]}", "nuevo_indice_avebiom", "importante",
                                               "AVEBIOM ha publicado un índice nuevo",
                                               "\n   ".join(nuevos) +
                                               "\n   Añade sus valores a data/avebiom_ipb.csv o avebiom_exw.csv"))
                if pdfs:
                    estado["avebiom_pdfs"] = sorted(conocidos | set(pdfs))
            except Exception as e:      # noqa: BLE001
                log.info("No se pudo revisar la página de AVEBIOM: %s", e)

        lista = alerts.filtrar_enfriamiento(lista, estado, conf_al.get("enfriamiento_dias", 4), momento)
        url_panel = os.getenv("PANEL_URL")
        if lista and not args.sin_avisos:
            res = notify.enviar(lista, conf_al.get("canales", {}), url_panel, hoy.isoformat())
            log.info("Avisos enviados: %s", res or "ninguno")
        elif lista:
            print("\n".join(a.texto() for a in lista))

        anexar_csv(ruta_precios, actual)
        hist_al = estado.setdefault("historial_alertas", [])
        hist_al.extend({"fecha": ronda, "nivel": a.nivel, "regla": a.regla,
                        "titulo": a.titulo, "detalle": a.detalle} for a in lista)
        estado["historial_alertas"] = hist_al[-200:]
        estado["ultima_ronda"] = ronda
        ruta_estado.write_text(json.dumps(estado, ensure_ascii=False, indent=1), "utf-8")
        historico = leer_csv(ruta_precios)

        ok = sum(1 for f in actual if f["estado"] == "ok")
        log.info("Ronda %s: %d/%d puntos leídos, %d alertas nuevas", ronda, ok, len(actual), len(lista))

    dashboard.generar(Path(args.salida), historico, ipb, exw, ajustes, conf_al, estado,
                      presupuestos=leer_csv(datos / "presupuestos_origen.csv"))
    log.info("Panel generado en %s", args.salida)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Monitor de precios del pellet")
    p.add_argument("--config", default=str(RAIZ / "config"))
    p.add_argument("--fuentes", default=str(RAIZ / "config" / "fuentes.yaml"))
    p.add_argument("--datos", default=str(RAIZ / "data"))
    p.add_argument("--salida", default=str(RAIZ / "docs"))
    p.add_argument("--solo", help="IDs de fuentes separados por comas")
    p.add_argument("--solo-panel", action="store_true")
    p.add_argument("--sin-avisos", action="store_true")
    p.add_argument("--sin-red-avebiom", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return ejecutar(args)


if __name__ == "__main__":
    sys.exit(main())
