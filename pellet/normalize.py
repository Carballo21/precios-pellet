"""Paso de cualquier precio a unidades comparables (€/t, €/saco 15 kg, con/sin IVA)."""
from __future__ import annotations

from datetime import date


def tipo_iva(ajustes: dict, dia: date) -> float:
    tramos = sorted(ajustes.get("iva", [{"desde": "2000-01-01", "tipo": 0.21}]),
                    key=lambda t: t["desde"])
    tipo = tramos[0]["tipo"]
    for t in tramos:
        if str(t["desde"]) <= dia.isoformat():
            tipo = t["tipo"]
    return float(tipo)


def normalizar(precio: float, fuente: dict, iva_declarado: bool | None,
               ajustes: dict, dia: date) -> dict:
    """Devuelve los precios equivalentes y el estado de cordura."""
    kg = float(fuente["kg"])
    iva = tipo_iva(ajustes, dia)
    lleva_iva = iva_declarado if iva_declarado is not None else fuente.get("iva_incluido", True)
    con = precio if lleva_iva else precio * (1 + iva)
    sin = con / (1 + iva)
    eur_t_con = con / kg * 1000
    eur_t_sin = sin / kg * 1000
    lim = ajustes.get("cordura_eur_t", {"min": 120, "max": 1500})
    anomalo = not (lim["min"] <= eur_t_con <= lim["max"])
    return {
        "iva_incluido": bool(lleva_iva),
        "eur_t_con_iva": round(eur_t_con, 2),
        "eur_t_sin_iva": round(eur_t_sin, 2),
        "eur_saco15_con_iva": round(eur_t_con * 15 / 1000, 3),
        "anomalo": anomalo,
    }
