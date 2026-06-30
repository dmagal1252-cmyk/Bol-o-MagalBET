"""
MagalBET — backend Flask
========================
Serve o front-end (index.html) e expõe dois endpoints que o JS consome:

  GET /api/apostadores  -> {"apostadores": [{"name","br","jp"}, ...]}
  GET /api/placar       -> {"state","br","jp","clock","detail","kickoff","completed"}

Como o navegador fala só com ESTE servidor (mesma origem), não há problema de CORS:
quem busca a planilha do Google e o placar da ESPN é o Python, do lado do servidor.

Configuração por variáveis de ambiente (todas opcionais):
  SHEET_ID   -> id da planilha do Google (padrão: a do bolão)
  SHEET_GID  -> gid de uma aba específica (padrão: 1ª aba)
  PORT       -> porta (definida automaticamente por Render/Railway/Heroku)
"""

import csv
import io
import os
import time

import requests
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # libera o uso da API também a partir de outra origem, se você hospedar o HTML à parte

# ---------------------------------------------------------------- config
SHEET_ID = os.environ.get("SHEET_ID", "1TmzlKRFlDtFZXgZxNpQff8bLY1lWU7tkeVn9lPwV9Fo")
SHEET_GID = os.environ.get("SHEET_GID", "")
_gid = f"&gid={SHEET_GID}" if SHEET_GID else ""
_gid_exp = f"&gid={SHEET_GID}" if SHEET_GID else ""

SHEET_URLS = [
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv{_gid}",
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv{_gid_exp}",
]
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"

UA = {"User-Agent": "MagalBET/1.0 (+https://github.com)"}

# ---------------------------------------------------------------- cache simples em memória
_cache = {}


def cached(key, ttl, producer):
    """Evita martelar a planilha/ESPN a cada request: guarda o resultado por `ttl` segundos."""
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    value = producer()
    # só cacheia resultados bons (não cacheia falha, pra tentar de novo no próximo request)
    if value is not None:
        _cache[key] = (now, value)
    return value


# ---------------------------------------------------------------- apostadores (planilha)
def _norm(s):
    import unicodedata
    s = (s or "").strip().upper()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def fetch_bettors():
    for url in SHEET_URLS:
        try:
            r = requests.get(url, headers=UA, timeout=8)
            if r.status_code != 200 or not r.text.strip():
                continue
            rows = list(csv.reader(io.StringIO(r.text)))
            if not rows:
                continue
            header = [_norm(c) for c in rows[0]]
            try:
                i_name = header.index("NOME")
                i_br = header.index("BRASIL")
                i_jp = header.index("JAPAO")
            except ValueError:
                continue
            out = []
            for row in rows[1:]:
                if len(row) <= max(i_name, i_br, i_jp):
                    continue
                name = (row[i_name] or "").strip()
                try:
                    br = int((row[i_br] or "").strip())
                    jp = int((row[i_jp] or "").strip())
                except ValueError:
                    continue
                if name:
                    out.append({"name": name, "br": br, "jp": jp})
            if out:
                return out
        except requests.RequestException:
            continue
    return None


@app.route("/api/apostadores")
def apostadores():
    data = cached("bettors", 60, fetch_bettors)
    if not data:
        return jsonify({"error": "sheet_unavailable", "apostadores": []}), 502
    return jsonify({"apostadores": data})


# ---------------------------------------------------------------- placar (ESPN)
def fetch_placar():
    try:
        r = requests.get(ESPN_URL, headers=UA, timeout=8)
        r.raise_for_status()
        data = r.json()
        for ev in data.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            competitors = comp.get("competitors", [])
            abbrs = {c.get("team", {}).get("abbreviation") for c in competitors}
            if "BRA" in abbrs and "JPN" in abbrs:
                bra = next(c for c in competitors if c["team"]["abbreviation"] == "BRA")
                jpn = next(c for c in competitors if c["team"]["abbreviation"] == "JPN")
                st = ev.get("status") or comp.get("status") or {}
                t = st.get("type", {})
                return {
                    "state": t.get("state"),          # pre | in | post
                    "br": int(bra.get("score") or 0),
                    "jp": int(jpn.get("score") or 0),
                    "clock": st.get("displayClock"),
                    "detail": t.get("shortDetail"),
                    "kickoff": ev.get("date"),
                    "completed": bool(t.get("completed")),
                }
        return {"state": "none"}
    except (requests.RequestException, ValueError, StopIteration):
        return None


@app.route("/api/placar")
def placar():
    data = cached("placar", 20, fetch_placar)
    if data is None:
        return jsonify({"error": "espn_unavailable"}), 502
    return jsonify(data)


# ---------------------------------------------------------------- front-end
@app.route("/")
def index():
    return send_from_directory(app.root_path, "index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
