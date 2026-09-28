"""clevertap_export.py v2 — CleverTap → MySQL mysql_bi_g
  Charged              → alex_clevertap_charged        (events.json; ~800/dia: filiation / ultragaz / gift card …)
  Notification Clicked → alex_clevertap_notif_click    (events.json; ~40 k/dia: base das "vendas assistidas" — piso, clique ≤ 24 h)
  counts/trends + top  → alex_clevertap_eventos_dia    (agregados diários: 8 eventos × {eventos, únicos} + aberturas OS / Push×InApp)

Os agregados saíram do clevertap.gs: cada chamada de counts/* leva ~30 s (resposta "partial" + poll) e o GAS tem 6 min por
execução e ~90 min/dia de gatilhos — o backfill não cabia. Aqui roda com 3 threads (limite de concorrência da conta).
O export do cursor tampouco cabia no UrlFetchApp (URL > 2 KB).
Usa o mesmo .env do toolkit: CLEVERTAP_ACCOUNT_ID, CLEVERTAP_PASSCODE, CLEVERTAP_REGION (us1),
GT7_DB_BI_HOST / PORT / USER / PASSWORD / NAME (alias bi = mysql_bi_g).

Uso:
  python clevertap_export.py daily                       # Charged D-3→D-1, Notification Clicked D-2→D-1, eventos_dia D-8→D-1
  python clevertap_export.py backfill 2026-01-01 2026-09-17 [charged|clicks]   # export dia a dia, retomável
  python clevertap_export.py day 2026-09-17 [charged|clicks]
  python clevertap_export.py eventos 2025-01-01 [ate] [--tops-desde 2026-06-01]  # agregados: trends em blocos de 1 ano, tops por dia
Como pipeline do gt7: copiar para claude-toolkit\\pipelines\\ e expor run(args) (abaixo) — `gt7 run clevertap_export --arg modo=daily`.
Agendar depois do clevertap.gs (10:20) via recarga_agregados.ps1 ou Agendador.
"""
import hashlib, json, os, re, sys, time, datetime as dt
import requests

# stdout redirecionado (Agendador / Start-Process) cai em cp1252 no Windows e o "→" do log quebrava o run: forçar UTF-8
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

try:
    from dotenv import load_dotenv
    for d in (os.path.dirname(os.path.abspath(__file__)), os.getcwd(), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")):
        for n in (".env", ".env.txt"):
            f = os.path.join(d, n)
            if os.path.isfile(f): load_dotenv(f, override=False)
except ImportError:
    pass

ACC, PASS = os.environ.get("CLEVERTAP_ACCOUNT_ID"), os.environ.get("CLEVERTAP_PASSCODE")
REG = os.environ.get("CLEVERTAP_REGION", "us1")
BASE = {"eu1": "https://api.clevertap.com"}.get(REG, f"https://{REG}.api.clevertap.com")
H_AUTH = {"X-CleverTap-Account-Id": ACC, "X-CleverTap-Passcode": PASS}
H_POST = dict(H_AUTH, **{"Content-Type": "application/json"})
BATCH = 5000
LOTE_SQL = 2000
JANELA = {"charged": 3, "clicks": 2}
EVENTO = {"charged": "Charged", "clicks": "Notification Clicked"}
TABELA = {"charged": "alex_clevertap_charged", "clicks": "alex_clevertap_notif_click"}


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- CleverTap

def ymd(d): return int(d.strftime("%Y%m%d"))


def exportar(evento, dia):
    """Gera os registros de um evento num dia (cursor → next_cursor). GET com cursor cru e só os headers de auth."""
    j, cursor = {}, None
    for tent in range(6):   # 28/09: 429 "Too many concurrent requests" no POST (limite por conta do CleverTap) -> esperar 60 s e repetir
        r = requests.post(f"{BASE}/1/events.json?batch_size={BATCH}&app=true&events=false&profile=true", headers=H_POST,
                          json={"event_name": evento, "from": ymd(dia), "to": ymd(dia)}, timeout=300)
        j = r.json()
        cursor = j.get("cursor")
        if cursor or j.get("code") != 429:
            break
        log(f"  429 no POST ({evento} {dia}) - tentativa {tent + 1}/6, aguardando 60 s")
        time.sleep(60)
    if not cursor:
        raise RuntimeError(f"events.json sem cursor: {json.dumps(j)[:200]}")
    while cursor:
        for tent in range(8):
            j = requests.get(f"{BASE}/1/events.json?cursor={cursor}", headers=H_AUTH, timeout=300).json()
            if j.get("code") == 2: time.sleep(15); continue           # "in progress"
            if j.get("code") == 429: time.sleep(30); continue
            break
        if j.get("status") != "success":
            raise RuntimeError(f"events.json GET: {json.dumps(j)[:200]}")
        for rec in j.get("records", []): yield rec
        cursor = j.get("next_cursor")


# ---------------------------------------------------------------- parse

def md5(s): return hashlib.md5(s.encode("utf-8")).hexdigest()


def ts_sql(ts):
    s = str(ts or "")
    if len(s) != 14: return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}"


def data_(v):
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(v or "")); return m.group(1) if m else None


def cpf_de(p):
    for x in list(p.get("all_identities") or []) + [p.get("identity")]:
        if re.fullmatch(r"\d{11}", str(x or "")): return str(x)
    return None


def linhas_charged(rec):
    p = rec.get("profile") or {}; pd = p.get("profileData") or {}; ep = rec.get("event_props") or {}; sp = rec.get("session_props") or {}
    ts = ts_sql(rec.get("ts"))
    if not ts: return []
    prods = [it.get("Items|product") or it.get("product") or "" for it in (rec.get("items") or [])] or [""]
    return [(md5(f"{p.get('objectId')}|{rec.get('ts')}|{prod}|{ep.get('CT Session Id')}"), ts[:10], ts, str(p.get("objectId") or ""),
             str(p.get("identity") or "")[:80] or None, cpf_de(p), (p.get("email") or None), (str(p.get("phone")) if p.get("phone") else None),
             prod[:80] or None, (ep.get("paymentMethod") or None), p.get("platform"), p.get("app_version"), pd.get("plan"), pd.get("franchise"),
             data_(pd.get("filiation_date") or pd.get("data_filiacao")), pd.get("cluster_rfv"), pd.get("uf"), pd.get("cidade"), pd.get("adimplencia"),
             sp.get("session_source"), ep.get("CT Session Id")) for prod in prods]


COLS_CHARGED = ("row_key, dia, ts, object_id, identity, cpf, email, phone, product, payment_method, platform, app_version, plan, franchise, "
                "filiation_date, cluster_rfv, uf, cidade, adimplencia, session_source, ct_session_id")


def linhas_click(rec):
    p = rec.get("profile") or {}; ep = rec.get("event_props") or {}
    ts = ts_sql(rec.get("ts"))
    if not ts: return []
    wz = str(ep.get("wzrk_id") or "")
    camp = wz.split("_")[0] if wz and wz != "-1" else None
    extras = {k: v for k, v in ep.items() if k not in ("wzrk_id", "wzrk_pivot", "wzrk_c2a", "Campaign type", "CT Session Id",
                                                        "CT App Version", "CT Source", "CT Latitude", "CT Longitude")}
    return [(md5(f"{p.get('objectId')}|{rec.get('ts')}|{wz}|{ep.get('wzrk_c2a')}"), ts[:10], ts, str(p.get("objectId") or ""), cpf_de(p),
             wz[:40] or None, camp, (ep.get("Campaign type") or None), str(ep.get("wzrk_c2a") or "")[:200] or None,
             (ep.get("wzrk_pivot") or None), p.get("platform"), json.dumps(extras, ensure_ascii=False)[:1000] if extras else None)]


COLS_CLICK = "row_key, dia, ts, object_id, cpf, wzrk_id, campaign_id, campaign_type, c2a, pivot, platform, props"

DDL = {
    "charged": f"""CREATE TABLE IF NOT EXISTS {TABELA['charged']} (
  row_key CHAR(32) NOT NULL, dia DATE NOT NULL, ts DATETIME NOT NULL, object_id VARCHAR(64) NOT NULL,
  identity VARCHAR(80) NULL, cpf CHAR(11) NULL, email VARCHAR(160) NULL, phone VARCHAR(20) NULL,
  product VARCHAR(80) NULL, payment_method VARCHAR(60) NULL, platform VARCHAR(16) NULL, app_version VARCHAR(20) NULL,
  plan VARCHAR(30) NULL, franchise VARCHAR(120) NULL, filiation_date DATE NULL, cluster_rfv VARCHAR(80) NULL, uf VARCHAR(4) NULL,
  cidade VARCHAR(80) NULL, adimplencia VARCHAR(30) NULL, session_source VARCHAR(60) NULL, ct_session_id BIGINT NULL,
  inserido_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (row_key), KEY ix_dia (dia, product), KEY ix_obj (object_id, ts), KEY ix_cpf (cpf)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    "clicks": f"""CREATE TABLE IF NOT EXISTS {TABELA['clicks']} (
  row_key CHAR(32) NOT NULL, dia DATE NOT NULL, ts DATETIME NOT NULL, object_id VARCHAR(64) NOT NULL, cpf CHAR(11) NULL,
  wzrk_id VARCHAR(40) NULL, campaign_id VARCHAR(20) NULL, campaign_type VARCHAR(20) NULL, c2a VARCHAR(200) NULL, pivot VARCHAR(40) NULL,
  platform VARCHAR(16) NULL, props VARCHAR(1000) NULL, inserido_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (row_key), KEY ix_dia (dia, campaign_type), KEY ix_obj (object_id, ts), KEY ix_camp (campaign_id, dia)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
}
PARSER = {"charged": (linhas_charged, COLS_CHARGED), "clicks": (linhas_click, COLS_CLICK)}



# ---------------------------------------------------------------- agregados (counts/trends, counts/top)

from concurrent.futures import ThreadPoolExecutor

EVENTOS_DIA = ["App Installed", "App Launched", "Charged", "Notification Sent", "Push Impressions",
               "Notification Viewed", "Notification Clicked", "UTM Visited"]
TOPS = [("Notification Clicked", "event_properties", "Campaign type", 10),
        ("App Launched", "technographics", "OS", 5),
        ("App Installed", "technographics", "OS", 5),
        ("Charged", "technographics", "OS", 5)]
TABELA_EV = "alex_clevertap_eventos_dia"
DDL_EV = f"""CREATE TABLE IF NOT EXISTS {TABELA_EV} (
  dia DATE NOT NULL, evento VARCHAR(60) NOT NULL, dimensao VARCHAR(40) NOT NULL DEFAULT '(total)',
  valor_dim VARCHAR(80) NOT NULL DEFAULT '(total)', eventos BIGINT NULL, usuarios BIGINT NULL,
  inserido_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (dia, evento, dimensao, valor_dim), KEY ix_ev (evento, dia)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
POLL_S = 15
TOPS_DESDE_PADRAO = "2026-06-01"   # aberturas diárias só daqui em diante (4 chamadas/dia); trends desde 2025-01-01


def counts(path, body):
    """POST em counts/*.json; 'partial' → GET ?req_id= a cada POLL_S (a doc pede 30 s; 15 s com 3 threads não deu 429)."""
    for tent in range(4):
        r = requests.post(f"{BASE}{path}", headers=H_POST, json=body, timeout=180)
        j = r.json()
        for _ in range(40):
            if not (j.get("status") == "partial" and j.get("req_id")): break
            time.sleep(POLL_S)
            j = requests.get(f"{BASE}{path}", headers=H_AUTH, params={"req_id": j["req_id"]}, timeout=180).json()
        if j.get("status") == "success": return j
        if r.status_code == 429 or j.get("code") == 429: time.sleep(30); continue
        raise RuntimeError(f"{path} {json.dumps(body)[:100]} → {json.dumps(j)[:200]}")
    raise RuntimeError(f"{path}: 429 persistente")


def iso(n): s = str(n); return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def item_trend(ev, ini, fim):
    """1 evento, janela ≤ 1 ano → linhas (dia, evento, '(total)', '(total)', eventos, usuarios)."""
    body = {"event_name": ev, "from": ymd(ini), "to": ymd(fim), "groups": {"d": {"trend_type": "daily"}}}
    tot = counts("/1/counts/trends.json", body).get("d", {})
    uni = counts("/1/counts/trends.json", dict(body, unique=True)).get("d", {})
    return [(iso(k), ev, "(total)", "(total)", v, uni.get(k)) for k, v in tot.items()]


def item_top(t, dia):
    ev, tipo, prop, n = t
    j = counts("/1/counts/top.json", {"event_name": ev, "from": ymd(dia), "to": ymd(dia),
                                      "groups": {"g": {"property_type": tipo, "name": prop, "top_n": n}}})
    out = []
    for m in (j.get("g") or {}).values():
        for v, c in m.items(): out.append((dia.isoformat(), ev, prop, v or "(vazio)", c, None))
    return out


def gravar_eventos(conn, linhas, janelas):
    """janelas = {(evento, dimensao): (ini, fim)} → DELETE só do que foi coletado + INSERT, numa transação."""
    conn.ping(reconnect=True)          # a coleta leva minutos e o RDS derruba a conexão ociosa
    with conn.cursor() as cur:
        cur.execute(DDL_EV)
        for (ev, dim), (ini, fim) in janelas.items():
            cur.execute(f"DELETE FROM {TABELA_EV} WHERE dia BETWEEN %s AND %s AND evento=%s AND dimensao=%s", (ini, fim, ev, dim))
        sql = (f"INSERT INTO {TABELA_EV} (dia, evento, dimensao, valor_dim, eventos, usuarios) VALUES (%s,%s,%s,%s,%s,%s)"
               " ON DUPLICATE KEY UPDATE eventos=VALUES(eventos), usuarios=VALUES(usuarios), atualizado_em=CURRENT_TIMESTAMP")
        for i in range(0, len(linhas), LOTE_SQL): cur.executemany(sql, linhas[i:i + LOTE_SQL])
    conn.commit()


def carregar_eventos(conn, ini, fim, tops_desde=None):
    """Trends (blocos ≤ 365 d) + tops por dia (a partir de tops_desde), 3 threads; grava por bloco. Devolve nº de linhas."""
    t0 = time.time(); total = 0
    # trends em blocos de até 1 ano
    d = ini
    while d <= fim:
        f = min(d + dt.timedelta(days=364), fim)
        with ThreadPoolExecutor(max_workers=3) as ex:
            res = list(ex.map(lambda ev: item_trend(ev, d, f), EVENTOS_DIA))
        linhas = [l for r in res for l in r]
        gravar_eventos(conn, linhas, {(ev, "(total)"): (d.isoformat(), f.isoformat()) for ev in EVENTOS_DIA})
        total += len(linhas); log(f"eventos  trends {d} → {f}: {len(linhas)} linhas · {time.time() - t0:.0f} s")
        d = f + dt.timedelta(days=1)
    # tops por dia
    td = max(ini, dt.date.fromisoformat(tops_desde)) if tops_desde else ini
    dias = [td + dt.timedelta(days=k) for k in range((fim - td).days + 1)]
    for i in range(0, len(dias), 10):                       # grava a cada 10 dias (40 chamadas)
        bloco = dias[i:i + 10]; tarefas = [(t, dia) for dia in bloco for t in TOPS]
        with ThreadPoolExecutor(max_workers=3) as ex:
            res = list(ex.map(lambda td_: item_top(*td_), tarefas))
        linhas = [l for r in res for l in r]
        gravar_eventos(conn, linhas, {(t[0], t[2]): (bloco[0].isoformat(), bloco[-1].isoformat()) for t in TOPS})
        total += len(linhas); log(f"eventos  tops   {bloco[0]} → {bloco[-1]}: {len(linhas)} linhas · {time.time() - t0:.0f} s")
    return total


# ---------------------------------------------------------------- MySQL

def conn_bi():
    import pymysql
    return pymysql.connect(host=os.environ["GT7_DB_BI_HOST"], port=int(os.environ.get("GT7_DB_BI_PORT", 3306)),
                           user=os.environ["GT7_DB_BI_USER"], password=os.environ["GT7_DB_BI_PASSWORD"],
                           database=os.environ.get("GT7_DB_BI_NAME", "mysql_bi_g"), charset="utf8mb4", autocommit=False)


def carregar_dia(tipo, dia, conn):
    """Exporta o evento do dia e regrava o dia numa transação (DELETE + INSERT em lotes). Devolve nº de linhas."""
    parser, cols = PARSER[tipo]
    t0 = time.time(); linhas = []; n_rec = 0
    for rec in exportar(EVENTO[tipo], dia):
        n_rec += 1; linhas.extend(parser(rec))
    ph = ",".join(["%s"] * len(cols.split(",")))
    sql = f"INSERT INTO {TABELA[tipo]} ({cols}) VALUES ({ph}) ON DUPLICATE KEY UPDATE dia=VALUES(dia)"
    conn.ping(reconnect=True)
    with conn.cursor() as cur:
        cur.execute(DDL[tipo])
        cur.execute(f"DELETE FROM {TABELA[tipo]} WHERE dia = %s", (dia.isoformat(),))
        for i in range(0, len(linhas), LOTE_SQL):
            cur.executemany(sql, linhas[i:i + LOTE_SQL])
    conn.commit()
    log(f"{tipo:8s} {dia}: {n_rec} registros → {len(linhas)} linhas · {time.time() - t0:.0f} s")
    return len(linhas)


def run(args=None):
    """Entrada para o gt7: args = {'modo': 'daily'|'backfill'|'day', 'de': 'AAAA-MM-DD', 'ate': 'AAAA-MM-DD', 'tipo': 'charged|clicks'}"""
    args = args or {}
    modo = args.get("modo", "daily"); tipos = [args["tipo"]] if args.get("tipo") else ["charged", "clicks"]
    ontem = dt.date.today() - dt.timedelta(days=1)
    conn = conn_bi()
    try:
        if modo == "daily":
            for tipo in tipos:
                for k in range(JANELA[tipo], 0, -1):
                    carregar_dia(tipo, dt.date.today() - dt.timedelta(days=k), conn)
            if not args.get("tipo"):
                carregar_eventos(conn, ontem - dt.timedelta(days=7), ontem)          # eventos_dia D-8 → D-1
        elif modo == "eventos":
            d, fim = dt.date.fromisoformat(args["de"]), dt.date.fromisoformat(args.get("ate") or ontem.isoformat())
            carregar_eventos(conn, d, fim, args.get("tops_desde", TOPS_DESDE_PADRAO))
        elif modo == "day":
            d = dt.date.fromisoformat(args["de"])
            for tipo in tipos: carregar_dia(tipo, d, conn)
        elif modo == "backfill":
            d, fim = dt.date.fromisoformat(args["de"]), dt.date.fromisoformat(args.get("ate") or ontem.isoformat())
            while d <= fim:
                for tipo in tipos: carregar_dia(tipo, d, conn)
                d += dt.timedelta(days=1)
        else:
            raise SystemExit("modo: daily | day <dia> | backfill <de> [ate] | eventos <de> [ate]")
    finally:
        conn.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "daily":
        run({"modo": "daily", "tipo": a[1] if len(a) > 1 else None})
    elif a[0] == "day":
        run({"modo": "day", "de": a[1], "tipo": a[2] if len(a) > 2 else None})
    elif a[0] == "backfill":
        run({"modo": "backfill", "de": a[1], "ate": a[2] if len(a) > 2 and re.match(r"\d{4}-", a[2]) else None,
             "tipo": next((x for x in a[2:] if x in ("charged", "clicks")), None)})
    elif a[0] == "eventos":
        td = a[a.index("--tops-desde") + 1] if "--tops-desde" in a else TOPS_DESDE_PADRAO
        run({"modo": "eventos", "de": a[1], "ate": a[2] if len(a) > 2 and re.match(r"\d{4}-", a[2]) else None, "tops_desde": td})
    else:
        raise SystemExit(__doc__)
