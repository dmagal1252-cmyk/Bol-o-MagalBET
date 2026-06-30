"""
MagalBET — backend Flask
========================
Serve o front-end (index.html) e expõe dois endpoints que o JS consome:

  GET /api/apostadores          -> {"apostadores": [{"name","br","jp"}, ...]}
  GET /api/apostadores?debug=1  -> inclui "tentativas" com o diagnóstico de cada URL
  GET /api/placar               -> {"state","br","jp","clock","detail","kickoff","completed"}

O Python busca a planilha (com pandas) e o placar (ESPN) do lado do servidor,
então o navegador não esbarra em CORS. O parser PROCURA a linha de cabeçalho
(NOME/BRASIL/JAPÃO), então funciona mesmo com um título/banner acima dela.

Variáveis de ambiente (opcionais): SHEET_ID, SHEET_GID, PORT.
"""

import io
import os
import time
import unicodedata

import pandas as pd
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------- config
SHEET_ID = os.environ.get("SHEET_ID", "1TmzlKRFlDtFZXgZxNpQff8bLY1lWU7tkeVn9lPwV9Fo")
SHEET_GID = os.environ.get("SHEET_GID", "")
_gid = f"&gid={SHEET_GID}" if SHEET_GID else ""

SHEET_URLS = [
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv{_gid}",
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv{_gid}",
]
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
UA = {"User-Agent": "Mozilla/5.0 (MagalBET/1.0)"}

# ---------------------------------------------------------------- cache simples
_cache = {}


def cache_get(key, ttl):
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def cache_set(key, value):
    _cache[key] = (time.time(), value)


# ---------------------------------------------------------------- apostadores (pandas)
def _norm(s):
    """Tira BOM, acento e espaços; deixa MAIUSCULO. 'JAPAO' / BOM+'NOME' -> 'JAPAO' / 'NOME'."""
    s = (str(s) if s is not None else "").replace("\ufeff", "").strip().upper()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _parse_matrix(text):
    """Lê o CSV como matriz, ACHA a coluna NOME e lê a partir dela.
    BRASIL/JAPAO são localizados na mesma linha do cabeçalho; se não
    aparecerem, assume as duas colunas seguintes à de NOME."""
    df = pd.read_csv(io.StringIO(text), header=None, dtype=str,
                     keep_default_na=False, engine="python")
    rows = df.values.tolist()

    def is_nome(c):
        # casa "NOME" exato ou grudado num título, ex.: "BOLAO MAGALHAES NOME"
        return c == "NOME" or c.endswith(" NOME")

    hdr = c_nome = c_br = c_jp = None
    for idx, row in enumerate(rows):
        cells = [_norm(c) for c in row]
        for j, c in enumerate(cells):
            if is_nome(c):
                hdr, c_nome = idx, j
                c_br = cells.index("BRASIL") if "BRASIL" in cells else j + 1
                c_jp = cells.index("JAPAO") if "JAPAO" in cells else j + 2
                break
        if hdr is not None:
            break
    if hdr is None:
        achei = [_norm(c) for c in (rows[0] if rows else [])]
        return None, f"nao achei a coluna NOME. 1a linha: {achei}"

    def cell(row, i):
        return str(row[i]).strip() if (i is not None and i < len(row)) else ""

    out = []
    for row in rows[hdr + 1:]:
        name = cell(row, c_nome)
        if not name:
            continue
        try:
            br = int(float(cell(row, c_br)))
            jp = int(float(cell(row, c_jp)))
        except (ValueError, TypeError):
            continue
        out.append({"name": name, "br": br, "jp": jp})

    return (out or None), f"{len(out)} apostadores (NOME na linha {hdr + 1}, coluna {c_nome})"


def fetch_bettors():
    """Retorna (lista | None, tentativas[])."""
    attempts = []
    for url in SHEET_URLS:
        try:
            r = requests.get(url, headers=UA, timeout=8)
            text = r.content.decode("utf-8-sig", errors="replace")  # remove BOM
            info = {"url": url, "status": r.status_code,
                    "content_type": r.headers.get("content-type", ""), "tamanho": len(text)}
            if r.status_code != 200:
                attempts.append({**info, "nota": "status != 200"})
                continue
            head = text[:300].lstrip().lower()
            if head.startswith("<!doctype html") or head.startswith("<html"):
                attempts.append({**info, "nota": "veio HTML (planilha provavelmente NAO esta publica)"})
                continue
            data, nota = _parse_matrix(text)
            attempts.append({**info, "nota": nota})
            if data:
                return data, attempts
        except Exception as e:  # noqa: BLE001
            attempts.append({"url": url, "erro": repr(e)})
    return None, attempts


@app.route("/api/apostadores")
def apostadores():
    cached = cache_get("bettors", 60)
    if cached is not None:
        return jsonify({"apostadores": cached})
    data, attempts = fetch_bettors()
    if not data:
        payload = {"error": "sheet_unavailable", "apostadores": []}
        if request.args.get("debug"):
            payload["tentativas"] = attempts
        return jsonify(payload), 502
    cache_set("bettors", data)
    resp = {"apostadores": data}
    if request.args.get("debug"):
        resp["tentativas"] = attempts
    return jsonify(resp)


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
                    "state": t.get("state"),
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
    cached = cache_get("placar", 20)
    if cached is not None:
        return jsonify(cached)
    data = fetch_placar()
    if data is None:
        return jsonify({"error": "espn_unavailable"}), 502
    cache_set("placar", data)
    return jsonify(data)


# ---------------------------------------------------------------- front-end
@app.route("/")
def index():
    return send_from_directory(app.root_path, "index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
