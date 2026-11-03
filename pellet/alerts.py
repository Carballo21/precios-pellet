"""Evaluación de las reglas de alarma configuradas en config/alertas.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean

from . import avebiom as av

def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


FORMATO_TXT = {"saco": "saco 15 kg", "palet": "palet", "bigbag": "big bag", "granel": "granel"}


@dataclass
class Alerta:
    clave: str
    regla: str
    nivel: str          # info | aviso | importante
    titulo: str
    detalle: str = ""

    def texto(self) -> str:
        icono = {"info": "ℹ️", "aviso": "⚠️", "importante": "🚨"}.get(self.nivel, "•")
        return f"{icono} {self.titulo}" + (f"\n   {self.detalle}" if self.detalle else "")


def _validas(filas):
    return [f for f in filas if f.get("estado") == "ok"]


def medias_por_formato(filas, tipo="destino") -> dict[str, dict]:
    """Media de €/t con IVA por formato (solo lecturas válidas no sospechosas)."""
    grupos: dict[str, list] = {}
    for f in _validas(filas):
        if f["tipo"] != tipo or f.get("sospechoso") == "si":
            continue
        grupos.setdefault(f["formato"], []).append(f)
    out = {}
    for fmt, g in grupos.items():
        out[fmt] = {
            "media_con_iva": round(mean(float(x["eur_t_con_iva"]) for x in g), 2),
            "media_sin_iva": round(mean(float(x["eur_t_sin_iva"]) for x in g), 2),
            "n": len(g),
        }
    return out


def media_destino_sin_iva(filas) -> float | None:
    v = [float(f["eur_t_sin_iva"]) for f in _validas(filas)
         if f["tipo"] == "destino" and f.get("sospechoso") != "si"]
    return round(mean(v), 2) if v else None


def marcar_sospechosos(filas, ipb_fila, ajustes, reglas):
    """Marca lecturas muy por debajo del índice (posible web fraudulenta)."""
    regla = next((r for r in reglas if r["tipo"] == "posible_fraude" and r.get("activa", True)), None)
    pct = (regla or {}).get("pct_bajo_avebiom", 35)
    for f in filas:
        f["sospechoso"] = "no"
        if f.get("estado") != "ok":
            continue
        ref = av.referencia(ipb_fila, f["formato"], ajustes)
        if ref and float(f["eur_t_con_iva"]) < ref * (1 - pct / 100):
            f["sospechoso"] = "si"


def evaluar(actual, anterior, ipb_fila, exw_fila, ajustes, conf, estado) -> list[Alerta]:
    reglas = [r for r in conf.get("reglas", []) if r.get("activa", True)]
    al: list[Alerta] = []
    previo = {f["fuente_id"]: f for f in _validas(anterior)}

    for r in reglas:
        t = r["tipo"]

        if t == "variacion_punto":
            u = r.get("umbral_pct", 5)
            for f in _validas(actual):
                p = previo.get(f["fuente_id"])
                if not p:
                    continue
                a, b = float(p["precio"]), float(f["precio"])
                if a <= 0:
                    continue
                var = (b - a) / a * 100
                if abs(var) >= u:
                    sube = var > 0
                    al.append(Alerta(
                        f"vp:{f['fuente_id']}:{'+' if sube else '-'}:{b}", t,
                        "aviso",
                        f"{f['tienda']} · {f['nombre']}: {'sube' if sube else 'baja'} {abs(var):.1f} %",
                        f"{a:.2f} € → {b:.2f} €  ({f['eur_t_con_iva']} €/t con IVA)"))

        elif t == "variacion_media":
            u = r.get("umbral_pct", 3)
            ma, mb = medias_por_formato(anterior), medias_por_formato(actual)
            for fmt, v in mb.items():
                if fmt in ma and ma[fmt]["media_con_iva"] > 0:
                    var = (v["media_con_iva"] - ma[fmt]["media_con_iva"]) / ma[fmt]["media_con_iva"] * 100
                    if abs(var) >= u:
                        al.append(Alerta(
                            f"vm:{fmt}:{'+' if var > 0 else '-'}:{v['media_con_iva']}", t, "importante",
                            f"Media del mercado ({FORMATO_TXT.get(fmt, fmt)}) {'sube' if var > 0 else 'baja'} {abs(var):.1f} %",
                            f"{ma[fmt]['media_con_iva']} → {v['media_con_iva']} €/t con IVA ({v['n']} puntos)"))

        elif t == "desviacion_avebiom" and ipb_fila:
            u = r.get("umbral_pct", 10)
            for fmt, v in medias_por_formato(actual).items():
                ref = av.referencia(ipb_fila, fmt, ajustes)
                if not ref:
                    continue
                dev = (v["media_con_iva"] - ref) / ref * 100
                if abs(dev) >= u:
                    al.append(Alerta(
                        f"da:{fmt}:{ipb_fila['trimestre']}:{'+' if dev > 0 else '-'}", t, "aviso",
                        f"Mercado {FORMATO_TXT.get(fmt, fmt)} {dev:+.1f} % frente a AVEBIOM {ipb_fila['trimestre']}",
                        f"Media {v['media_con_iva']} €/t vs índice {ref} €/t"))

        elif t == "precio_objetivo":
            for f in _validas(actual):
                if f["tipo"] != "destino" or f.get("sospechoso") == "si":
                    continue
                fmt = f["formato"]
                if fmt == "saco" and r.get("max_eur_saco15") is not None:
                    ok = float(f["eur_saco15_con_iva"]) <= r["max_eur_saco15"]
                    val = f"{float(f['eur_saco15_con_iva']):.2f} €/saco"
                elif fmt == "palet" and r.get("max_eur_t_palet") is not None:
                    ok = float(f["eur_t_con_iva"]) <= r["max_eur_t_palet"]
                    val = f"{f['eur_t_con_iva']} €/t"
                elif fmt in ("granel", "bigbag") and r.get("max_eur_t_granel") is not None:
                    ok = float(f["eur_t_con_iva"]) <= r["max_eur_t_granel"]
                    val = f"{f['eur_t_con_iva']} €/t"
                else:
                    continue
                if ok:
                    al.append(Alerta(f"po:{f['fuente_id']}:{f['precio']}", t, "info",
                                     f"Precio objetivo: {f['tienda']} · {f['nombre']} a {val}",
                                     f["url"]))

        elif t == "margen_origen_destino" and exw_fila:
            m = media_destino_sin_iva(actual)
            if m is not None:
                margen = m - exw_fila["eur_t"]
                if margen >= r.get("max_eur_t", 160):
                    al.append(Alerta(f"mo:{exw_fila['mes']}:{round(margen)}", t, "aviso",
                                     f"Diferencial destino − origen: {margen:.0f} €/t",
                                     f"Media destino sin IVA {m} €/t · EXW AVEBIOM {exw_fila['mes']} ≈ {exw_fila['eur_t']} €/t"))

        elif t == "posible_fraude":
            for f in actual:
                if f.get("sospechoso") == "si":
                    al.append(Alerta(f"pf:{f['fuente_id']}:{f['precio']}", t, "importante",
                                     f"Precio sospechosamente bajo en {f['tienda']} ({f['eur_t_con_iva']} €/t)",
                                     "Comprueba que la web es legítima antes de comprar: " + f["url"]))

        elif t == "sin_stock":
            sin = [f for f in _validas(actual) if f.get("disponible") == "no"]
            if len(sin) >= r.get("min_puntos", 6):
                al.append(Alerta(f"ss:{len(sin)}", t, "aviso",
                                 f"{len(sin)} puntos de venta sin existencias",
                                 ", ".join(sorted({f['tienda'] for f in sin}))))

        elif t == "fallo_scraper":
            n = r.get("fallos_consecutivos", 2)
            for fid, veces in estado.get("fallos", {}).items():
                if veces == n:
                    f = next((x for x in actual if x["fuente_id"] == fid), {})
                    al.append(Alerta(f"fs:{fid}:{_ahora():%Y-%m-%d}", t, "aviso",
                                     f"El lector de «{f.get('tienda', fid)} · {f.get('nombre', '')}» falla {n} veces seguidas",
                                     f"Último error: {f.get('error', '')}. Revisa la URL o configura un selector."))
    return al


def filtrar_enfriamiento(alertas, estado, dias, ahora=None):
    ahora = ahora or _ahora()
    enviados = estado.setdefault("alertas_enviadas", {})
    nuevas = []
    for a in alertas:
        ultima = enviados.get(a.clave)
        if ultima and ahora - datetime.fromisoformat(ultima) < timedelta(days=dias):
            continue
        enviados[a.clave] = ahora.isoformat(timespec="seconds")
        nuevas.append(a)
    # Limpieza de claves viejas
    limite = ahora - timedelta(days=max(dias, 1) * 10)
    for k in [k for k, v in enviados.items() if datetime.fromisoformat(v) < limite]:
        del enviados[k]
    return nuevas
