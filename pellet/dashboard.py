"""Genera el panel web estático (docs/index.html + docs/datos.json) para GitHub Pages."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from statistics import mean

from . import avebiom as av
from .alerts import medias_por_formato, media_destino_sin_iva

PLANTILLA = Path(__file__).with_name("plantilla_panel.html")
GRUPOS = {"saco": "saco", "palet": "palet", "granel": "granel", "bigbag": "granel"}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def construir_datos(historico, ipb, exw, ajustes, conf_al, estado, presupuestos=None):
    rondas = sorted({h["ronda"] for h in historico})
    ultima = rondas[-1] if rondas else None
    penultima = rondas[-2] if len(rondas) > 1 else None
    por_ronda = {r: [h for h in historico if h["ronda"] == r] for r in rondas}
    hoy = date.fromisoformat(por_ronda[ultima][0]["fecha"]) if ultima else date.today()
    ipb_v = av.ipb_vigente(ipb, hoy)
    exw_v = av.exw_vigente(exw, hoy)

    # --- series del mercado por ronda (destino por grupo de formato; origen aparte)
    mercado = {"saco": [], "palet": [], "granel": [], "origen": []}
    for r in rondas:
        filas = [f for f in por_ronda[r] if f["estado"] == "ok" and f.get("sospechoso") != "si"]
        fecha = filas[0]["fecha"] if filas else por_ronda[r][0]["fecha"]
        for g in ("saco", "palet", "granel"):
            v = [float(f["eur_t_con_iva"]) for f in filas
                 if f["tipo"] == "destino" and GRUPOS.get(f["formato"]) == g]
            if v:
                mercado[g].append({"x": fecha, "y": round(mean(v), 2), "n": len(v), "ronda": r})
        v = [float(f["eur_t_sin_iva"]) for f in filas if f["tipo"] == "origen"]
        if v:
            mercado["origen"].append({"x": fecha, "y": round(mean(v), 2), "n": len(v), "ronda": r})
    for p in presupuestos or []:            # presupuestos de fábrica añadidos a mano
        y = _num(p.get("eur_t_sin_iva"))
        if y:
            mercado["origen"].append({"x": p["fecha"], "y": y, "n": 1, "ronda": "presupuesto",
                                      "nota": f"Presupuesto {p.get('fabricante', '')}"})
    mercado["origen"].sort(key=lambda d: d["x"])

    referencia = {
        "saco": [{"x": q["inicio"], "y": q["saco_eur_t"], "et": q["trimestre"]} for q in ipb],
        "palet": [{"x": q["inicio"], "y": q["palet_eur_t"], "et": q["trimestre"]} for q in ipb],
        "granel": [{"x": q["inicio"], "y": q["granel_medio_eur_t"], "et": q["trimestre"]} for q in ipb],
        "origen": [{"x": e["mes"] + "-01", "y": e["eur_t"], "et": e["mes"] + (" (previsión)" if e["prevision"] else "")}
                   for e in exw],
    }

    # --- tabla de la última ronda
    previo = {f["fuente_id"]: f for f in (por_ronda.get(penultima) or []) if f["estado"] == "ok"}
    filas_tabla = []
    for f in por_ronda.get(ultima, []):
        fila = {k: f.get(k, "") for k in ("fuente_id", "tienda", "nombre", "tipo", "formato", "region",
                                           "canal", "certificacion", "transporte", "url", "estado",
                                           "error", "disponible", "sospechoso", "metodo", "iva_incluido")}
        fila.update({"precio": _num(f.get("precio")), "kg": _num(f.get("kg")),
                     "eur_t": _num(f.get("eur_t_con_iva")), "eur_t_sin": _num(f.get("eur_t_sin_iva")),
                     "eur_saco": _num(f.get("eur_saco15_con_iva"))})
        p = previo.get(f["fuente_id"])
        fila["var_pct"] = (round((fila["precio"] - float(p["precio"])) / float(p["precio"]) * 100, 1)
                           if p and fila["precio"] else None)
        ref = av.referencia(ipb_v, f["formato"], ajustes) if f["tipo"] == "destino" else (exw_v or {}).get("eur_t")
        base = fila["eur_t"] if f["tipo"] == "destino" else fila["eur_t_sin"]
        fila["ref"] = ref
        fila["dev_pct"] = round((base - ref) / ref * 100, 1) if (base and ref) else None
        filas_tabla.append(fila)

    actual = por_ronda.get(ultima, [])
    medias = medias_por_formato(actual)
    medias_ant = medias_por_formato(por_ronda.get(penultima, []))
    m_sin = media_destino_sin_iva(actual)

    def kpi(fmt, ref_clave):
        g = [f for f in actual if f["estado"] == "ok" and f["tipo"] == "destino"
             and f.get("sospechoso") != "si" and GRUPOS.get(f["formato"]) == fmt]
        if not g:
            return None
        v = round(mean(float(x["eur_t_con_iva"]) for x in g), 2)
        ref = ipb_v.get(ref_clave) if ipb_v else None
        ant = [f for f in por_ronda.get(penultima, []) if f["estado"] == "ok" and f["tipo"] == "destino"
               and f.get("sospechoso") != "si" and GRUPOS.get(f["formato"]) == fmt]
        v_ant = round(mean(float(x["eur_t_con_iva"]) for x in ant), 2) if ant else None
        return {"valor": v, "n": len(g), "ref": ref,
                "dev_pct": round((v - ref) / ref * 100, 1) if ref else None,
                "var_pct": round((v - v_ant) / v_ant * 100, 1) if v_ant else None}

    kpis = {
        "saco": kpi("saco", "saco_eur_t"),
        "palet": kpi("palet", "palet_eur_t"),
        "granel": kpi("granel", "granel_medio_eur_t"),
        "exw": exw_v,
        "destino_sin_iva": m_sin,
        "margen": round(m_sin - exw_v["eur_t"], 2) if (m_sin and exw_v) else None,
        "leidos": sum(1 for f in actual if f["estado"] == "ok"),
        "total": len(actual),
    }

    return {
        "titulo": ajustes.get("panel", {}).get("titulo", "Monitor de precios del pellet"),
        "ultima_ronda": ultima,
        "num_rondas": len(rondas),
        "ipb_vigente": ipb_v,
        "exw_vigente": exw_v,
        "kpis": kpis,
        "mercado": mercado,
        "referencia": referencia,
        "tabla": filas_tabla,
        "alertas": list(reversed(estado.get("historial_alertas", [])))[:40],
        "reglas": conf_al.get("reglas", []),
        "medias": medias,
        "medias_ant": medias_ant,
    }


def generar(salida: Path, historico, ipb, exw, ajustes, conf_al, estado, presupuestos=None):
    salida.mkdir(parents=True, exist_ok=True)
    datos = construir_datos(historico, ipb, exw, ajustes, conf_al, estado, presupuestos)
    js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    html = PLANTILLA.read_text("utf-8").replace("/*__DATOS__*/null", js)
    (salida / "index.html").write_text(html, "utf-8")
    (salida / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, indent=1), "utf-8")
    (salida / ".nojekyll").write_text("", "utf-8")
    return datos
