"""Índices de referencia de AVEBIOM: consumidor (IPB trimestral) y fábrica (EXW mensual)."""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path


def cargar_ipb(ruta: Path) -> list[dict]:
    filas = []
    with open(ruta, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            saco = float(r["saco_eur"])
            vol = float(r["granel_volquete_eur_t"])
            cis = float(r["granel_cisterna_eur_t"])
            filas.append({
                "trimestre": r["trimestre"],
                "inicio": r["inicio"],
                "saco_eur": saco,
                "saco_eur_t": round(saco / 15 * 1000, 2),
                "palet_eur_t": float(r["palet_eur_t"]),
                "granel_volquete_eur_t": vol,
                "granel_cisterna_eur_t": cis,
                "granel_medio_eur_t": round((vol + cis) / 2, 2),
                "iva": float(r["iva"]),
                "fuente": r["fuente"],
            })
    return sorted(filas, key=lambda x: x["inicio"])


def cargar_exw(ruta: Path, base_eur_t: float) -> list[dict]:
    filas = []
    with open(ruta, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pct = float(r["indice_pct"])
            filas.append({
                "mes": r["mes"],
                "indice_pct": pct,
                "eur_t": round(pct / 100 * base_eur_t, 2),
                "prevision": r.get("prevision", "no") == "si",
                "fuente": r.get("fuente", ""),
            })
    return sorted(filas, key=lambda x: x["mes"])


def ipb_vigente(ipb: list[dict], dia: date) -> dict | None:
    """Último trimestre publicado que empieza en o antes de `dia`."""
    vig = None
    for r in ipb:
        if r["inicio"] <= dia.isoformat():
            vig = r
    return vig or (ipb[-1] if ipb else None)


def exw_vigente(exw: list[dict], dia: date, incluir_prevision=False) -> dict | None:
    mes = dia.strftime("%Y-%m")
    vig = None
    for r in exw:
        if r["prevision"] and not incluir_prevision:
            continue
        if r["mes"] <= mes:
            vig = r
    return vig


def referencia(ipb_fila: dict, formato: str, ajustes: dict) -> float | None:
    clave = ajustes.get("avebiom", {}).get("comparar", {}).get(formato)
    return ipb_fila.get(clave) if (ipb_fila and clave) else None


def enlaces_pdf(html: str) -> list[str]:
    """Enlaces a PDFs de índices de pellet en la página de AVEBIOM."""
    urls = set(re.findall(r'https?://[^"\'\s>]+\.pdf', html, re.I))
    return sorted(u for u in urls if re.search(r"pellet|exw|ipb", u, re.I))
