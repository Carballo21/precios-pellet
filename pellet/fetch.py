"""Descarga de páginas con pausas, robots.txt, reintentos y Playwright de respaldo."""
from __future__ import annotations

import logging
import random
import time
from urllib import robotparser
from urllib.parse import urlparse, urlunparse

import requests

log = logging.getLogger(__name__)


class Descargador:
    def __init__(self, ajustes: dict):
        a = ajustes.get("descarga", {})
        self.pausa = (a.get("pausa_min", 3), a.get("pausa_max", 7))
        self.timeout = a.get("timeout", 30)
        self.reintentos = a.get("reintentos", 2)
        self.respetar_robots = a.get("respetar_robots_txt", True)
        self.usar_playwright = a.get("playwright_si_falla", True)
        self.ua = a.get("user_agent", "Mozilla/5.0")
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
        })
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._ultimo_por_host: dict[str, float] = {}
        self._navegador = None
        self._pw = None

    # ------------------------------------------------------------ robots.txt
    def permitido(self, url: str) -> bool:
        if not self.respetar_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=self.timeout)
                if r.status_code >= 400:
                    rp = None          # sin robots.txt = todo permitido
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.ua, url)

    # ------------------------------------------------------------ cortesía
    def _esperar(self, url: str):
        host = urlparse(url).netloc
        ultimo = self._ultimo_por_host.get(host)
        if ultimo is not None:
            espera = random.uniform(*self.pausa) - (time.time() - ultimo)
            if espera > 0:
                time.sleep(espera)
        self._ultimo_por_host[host] = time.time()

    # ------------------------------------------------------------ descarga
    def get(self, url: str) -> str:
        """Descarga con requests. Lanza excepción con mensaje claro si falla."""
        ultimo_error = None
        for intento in range(self.reintentos + 1):
            self._esperar(url)
            try:
                r = self.s.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    r.encoding = r.apparent_encoding if not r.encoding else r.encoding
                    return r.text
                ultimo_error = f"HTTP {r.status_code}"
                if r.status_code in (403, 404, 410):
                    break               # no tiene sentido reintentar
            except requests.RequestException as e:
                ultimo_error = type(e).__name__
            time.sleep(2 * (intento + 1))
        raise RuntimeError(ultimo_error or "error de descarga")

    def get_shopify(self, url: str) -> str | None:
        """Si la URL es de Shopify (/products/...), pide el JSON público .js"""
        p = urlparse(url)
        if "/products/" not in p.path:
            return None
        js = urlunparse(p._replace(path=p.path.rstrip("/") + ".js", query="", fragment=""))
        try:
            return self.get(js)
        except RuntimeError:
            return None

    def get_navegador(self, url: str, forzar: bool = False) -> str:
        """Descarga con un Chromium real (para webs que pintan el precio con JS)."""
        if not (self.usar_playwright or forzar):
            raise RuntimeError("Playwright desactivado")
        if self._navegador is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._navegador = self._pw.chromium.launch()
        self._esperar(url)
        ctx = self._navegador.new_context(user_agent=self.ua, locale="es-ES")
        try:
            pag = ctx.new_page()
            pag.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
            try:
                pag.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            return pag.content()
        finally:
            ctx.close()

    def cerrar(self):
        if self._navegador is not None:
            self._navegador.close()
            self._pw.stop()
            self._navegador = None
