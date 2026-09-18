"""Login simples via sessao Flask, no lugar do pop-up nativo de HTTP
Basic Auth do navegador. A protecao continua sendo server-side (nada
sob `base_pathname` e servido sem sessao autenticada) - so a UI de
login passa a ser uma pagina do proprio app em vez do dialogo do Chrome.
"""

from __future__ import annotations

import os
import secrets
from datetime import timedelta

from flask import Flask, redirect, request, session

_USERNAME = os.environ.get("DASH_AUTH_USERNAME", "symrise")
_PASSWORD = os.environ.get("DASH_AUTH_PASSWORD", "Kantar@2025")
_SESSION_LIFETIME = timedelta(days=7)

_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kantar Worldpanel - Dashboard</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    background: linear-gradient(135deg, #f4f6f5 0%, #e8ede9 100%);
  }}
  .card {{
    background: #fff; padding: 40px 36px; border-radius: 12px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.08); width: 320px; text-align: center;
  }}
  .card img {{ height: 34px; margin-bottom: 18px; }}
  .card h1 {{ font-size: 16px; margin: 0 0 22px; color: #222; font-weight: 600; }}
  .card input {{
    width: 100%; padding: 10px 12px; margin-bottom: 12px; border: 1px solid #d7dbd8;
    border-radius: 6px; font-size: 14px;
  }}
  .card input:focus {{ outline: none; border-color: #1E8E5A; }}
  .card button {{
    width: 100%; padding: 11px; margin-top: 6px; background: #1E8E5A; color: #fff;
    border: none; border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer;
  }}
  .card button:hover {{ background: #197a4c; }}
  .error {{ color: #C23B3B; font-size: 13px; margin: -8px 0 14px; }}
</style>
</head>
<body>
  <form class="card" method="post">
    <img src="{logo_url}" alt="Symrise">
    <h1>Kantar Worldpanel - Dashboard</h1>
    {error_html}
    <input type="text" name="username" placeholder="Usuário" autofocus required>
    <input type="password" name="password" placeholder="Senha" required>
    <button type="submit">Entrar</button>
  </form>
</body>
</html>"""


def init_auth(server: Flask, base_pathname: str) -> None:
    server.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    server.permanent_session_lifetime = _SESSION_LIFETIME
    # cookie "Secure" so em producao (subpath configurado + HTTPS via nginx);
    # localmente (base_pathname == "/", http puro) precisa ficar sem, senao
    # o navegador descarta o cookie de sessao.
    server.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=base_pathname != "/")

    base = base_pathname.rstrip("/")  # "" quando base_pathname == "/"
    login_path = f"{base}/login"
    logout_path = f"{base}/logout"
    assets_prefix = f"{base_pathname}assets/"

    @server.route(login_path, methods=["GET", "POST"])
    def login():
        error_html = ""
        if request.method == "POST":
            if request.form.get("username") == _USERNAME and request.form.get("password") == _PASSWORD:
                session.permanent = True
                session["authenticated"] = True
                return redirect(request.args.get("next") or base_pathname)
            error_html = '<p class="error">Usuário ou senha inválidos.</p>'
        return _LOGIN_PAGE.format(logo_url=f"{assets_prefix}symrise_logo.png", error_html=error_html)

    @server.route(logout_path)
    def logout():
        session.clear()
        return redirect(login_path)

    @server.before_request
    def require_login():
        path = request.path
        if path == login_path or path.startswith(assets_prefix):
            return None
        if not path.startswith(base):
            return None  # fora do namespace do app (ex.: healthcheck externo)
        if not session.get("authenticated"):
            return redirect(f"{login_path}?next={path}")
        return None
