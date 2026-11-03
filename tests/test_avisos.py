from pellet import notify
from pellet.alerts import Alerta


class Resp:
    ok, status_code, text = True, 200, ""


def test_telegram_y_issue(monkeypatch):
    enviados = []
    monkeypatch.setattr(notify.requests, "post", lambda url, **kw: enviados.append((url, kw)) or Resp())
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "yo/precios-pellet")
    al = [Alerta("k", "variacion_media", "importante", "Media del mercado (palet) sube 3.2 %", "392 → 405 €/t")]
    res = notify.enviar(al, {"telegram": True, "github_issue": True, "email": True}, "https://x.github.io/p/", "2026-11-03")
    assert res == {"telegram": True, "github_issue": True, "email": False}
    assert enviados[0][0] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert "sube 3.2 %" in enviados[0][1]["json"]["text"] and "https://x.github.io/p/" in enviados[0][1]["json"]["text"]
    assert enviados[1][0].endswith("/repos/yo/precios-pellet/issues")
