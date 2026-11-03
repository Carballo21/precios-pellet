"""Envío de avisos: Telegram, email y issue de GitHub. Todo gratis."""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

import requests

log = logging.getLogger(__name__)


def componer(alertas, url_panel: str | None, fecha: str) -> tuple[str, str]:
    titulo = f"🔔 Pellet · {len(alertas)} alerta{'s' if len(alertas) != 1 else ''} · {fecha}"
    cuerpo = "\n\n".join(a.texto() for a in alertas)
    if url_panel:
        cuerpo += f"\n\n📊 Panel: {url_panel}"
    return titulo, cuerpo


def telegram(titulo, cuerpo) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        log.info("Telegram sin configurar (faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False
    texto = f"{titulo}\n\n{cuerpo}"
    ok = True
    for i in range(0, len(texto), 3900):          # límite de Telegram: 4096
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": texto[i:i + 3900],
                                "disable_web_page_preview": True}, timeout=20)
        ok &= r.ok
        if not r.ok:
            log.warning("Telegram respondió %s: %s", r.status_code, r.text[:200])
    return ok


def email(titulo, cuerpo) -> bool:
    host, user, pwd, to = (os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "EMAIL_TO"))
    if not (host and user and pwd and to):
        log.info("Email sin configurar")
        return False
    port = int(os.getenv("SMTP_PORT", "587"))
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = titulo, user, to
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                s.login(user, pwd)
                s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls()
                s.login(user, pwd)
                s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.warning("Fallo al enviar email: %s", e)
        return False


def github_issue(titulo, cuerpo) -> bool:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not (token and repo):
        log.info("Issue de GitHub sin configurar (solo funciona dentro de GitHub Actions)")
        return False
    r = requests.post(f"https://api.github.com/repos/{repo}/issues",
                      headers={"Authorization": f"Bearer {token}",
                               "Accept": "application/vnd.github+json"},
                      json={"title": titulo, "body": cuerpo, "labels": ["alerta-pellet"]},
                      timeout=20)
    if not r.ok:
        log.warning("GitHub respondió %s: %s", r.status_code, r.text[:200])
    return r.ok


def enviar(alertas, canales: dict, url_panel: str | None, fecha: str) -> dict:
    if not alertas:
        return {}
    titulo, cuerpo = componer(alertas, url_panel, fecha)
    print("\n" + titulo + "\n" + cuerpo + "\n")
    res = {}
    if canales.get("telegram"):
        res["telegram"] = telegram(titulo, cuerpo)
    if canales.get("email"):
        res["email"] = email(titulo, cuerpo)
    if canales.get("github_issue"):
        res["github_issue"] = github_issue(titulo, cuerpo)
    return res
