import streamlit as st
import pandas as pd
import numpy as np
import datetime
import plotly.express as px
import json
import urllib.request
import ssl
import warnings
import logging

# Mute Prophet console spam to keep Streamlit logs clean
warnings.filterwarnings("ignore")
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

try:
    from prophet import Prophet
    from prophet.utilities import regressor_coefficients
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False

# --- 1. CONFIGURE PAGE & AUTHENTICATION ---
st.set_page_config(page_title="Vendas Dashboard", page_icon="📊", layout="wide")

def check_password():
    if st.session_state.get("password_correct", False):
        return True
    st.title("🔒 Dashboard Login")
    password = st.text_input("Please enter the password:", type="password")
    if password:
        if password == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            st.rerun() 
        else:
            st.error("😕 Password incorrect. Please try again.")
    return False

if not check_password():
    st.stop()

# --- 2. GLOBAL FORMATTING & HELPERS ---
def format_br(num): return f"{int(num):,}".replace(",", ".")
def format_money(num): return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_delta_str(curr, prev):
    if prev > 0:
        delta = ((curr - prev) / prev) * 100
        return f"{'+' if delta > 0 else ''}{delta:.1f}%"
    elif prev == 0 and curr > 0:
        return "+100.0%"
    return "N/A"

def fmt_val_delta(curr, prev):
    if prev == 0 and curr == 0:
        return "0 (N/A)"
    v_str = format_br(prev)
    d_str = get_delta_str(curr, prev)
    return f"{v_str} ({d_str})"

def fmt_val_delta_money(curr, prev):
    if prev == 0 and curr == 0:
        return "R$ 0,00 (N/A)"
    v_str = format_money(prev)
    d_str = get_delta_str(curr, prev)
    return f"{v_str} ({d_str})"

def fmt_goal(actual, goal, is_money=False):
    if goal <= 0:
        return "N/A"
    pct = (actual / goal) * 100
    val_str = format_money(goal) if is_money else format_br(goal)
    return f"{val_str} ({pct:.1f}%)"

def color_deltas(val):
    if not isinstance(val, str) or '(' not in val:
        return ''
    try:
        pct_str = val.split('(')[1].split('%')[0].replace('+', '')
        if pct_str == 'N/A': return ''
        pct = float(pct_str)
        intensity = min(abs(pct) / 50.0, 1.0)
        alpha = 0.1 + (intensity * 0.35) 
        if pct > 0:
            return f'background-color: rgba(39, 174, 96, {alpha}); color: #000;'
        elif pct < 0:
            return f'background-color: rgba(231, 76, 60, {alpha}); color: #000;'
    except Exception:
        pass
    return ''


def _delta_bg(cell, is_eff=False):
    """Parse a 'valor (±X%...)' string and return an rgba background.
    Green = good, red = bad. For efficiency metrics (CPL/CPA) lower is good
    (is_eff=True); otherwise higher is good. Empty for N/A / 0% / non-delta cells."""
    if not isinstance(cell, str) or '(' not in cell:
        return ''
    try:
        pct_str = cell.split('(')[1].split('%')[0].replace('+', '').strip()
        if pct_str in ('N/A', ''):
            return ''
        pct = float(pct_str)
    except Exception:
        return ''
    if pct == 0:
        return ''
    intensity = min(abs(pct) / 50.0, 1.0)
    alpha = 0.12 + intensity * 0.33
    good = (pct < 0) if is_eff else (pct > 0)
    rgb = "39,174,96" if good else "231,76,60"
    return f"rgba({rgb},{alpha:.2f})"


def render_metric_table(rows, cols):
    """Render a metric/summary table as styled HTML with a typographic hierarchy.
    cols[0] is the label column; remaining columns are right-aligned values. Each row
    may carry '_level' (0/1/2 -> bold band / indented / lighter+more-indented) and
    '_is_eff' (controls delta-coloring direction on 'vs ' columns). N/A cells render
    as an em-dash. Uses inline styles only, so Streamlit's HTML sanitizer keeps them."""
    label_key = cols[0]
    val_cols = cols[1:]
    head = [f"<th style='text-align:left;padding:9px 12px;font-size:10.5px;font-weight:600;color:#64748b;"
            f"text-transform:uppercase;letter-spacing:.05em;border-bottom:2px solid #e2e8f0;'>{label_key}</th>"]
    for c in val_cols:
        head.append(f"<th style='text-align:right;padding:9px 12px;font-size:10.5px;font-weight:600;color:#64748b;"
                    f"text-transform:uppercase;letter-spacing:.05em;border-bottom:2px solid #e2e8f0;'>{c}</th>")
    body = []
    for r in rows:
        lvl = r.get('_level', 0)
        is_eff = r.get('_is_eff', False)
        if lvl == 0:
            bg, weight, tcolor, fsize, btop = "#eef2f7", "700", "#0f172a", "13px", "border-top:2px solid #cbd5e1;"
        elif lvl == 1:
            bg, weight, tcolor, fsize, btop = "#f8fafc", "600", "#334155", "12.5px", "border-top:1px solid #e8edf3;"
        else:
            bg, weight, tcolor, fsize, btop = "#ffffff", "400", "#64748b", "12px", "border-top:1px solid #f1f5f9;"
        pad = 12 + lvl * 22
        cells = [f"<td style='text-align:left;padding:7px 12px;padding-left:{pad}px;font-weight:{weight};"
                 f"color:{tcolor};font-size:{fsize};{btop}white-space:nowrap;'>{r.get(label_key, '')}</td>"]
        for c in val_cols:
            raw = r.get(c, '')
            disp = '—' if (not isinstance(raw, str) or raw.strip() in ('N/A', '')) else raw
            bgc = _delta_bg(raw, is_eff) if c.startswith('vs ') else ''
            bgcss = f"background-color:{bgc};" if bgc else ''
            cells.append(f"<td style='text-align:right;padding:7px 12px;font-size:{fsize};color:#0f172a;"
                         f"{btop}{bgcss}white-space:nowrap;'>{disp}</td>")
        body.append(f"<tr style='background:{bg};'>" + "".join(cells) + "</tr>")
    return ("<div style='overflow-x:auto;border:1px solid #e2e8f0;border-radius:8px;'>"
            "<table style='border-collapse:collapse;width:100%;"
            "font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;'>"
            "<thead><tr>" + "".join(head) + "</tr></thead>"
            "<tbody>" + "".join(body) + "</tbody></table></div>")


def parse_br_float(val):
    """Robust string->float for messy DB values.
    Numeric columns (incl. MySQL DOUBLE -> numpy float) pass straight through;
    text columns (e.g. `Investimento Total`) may hold BR or US numbers, with or
    without R$. Crucially handles dot-thousands like 1.500.000 / 150.000 that the
    previous parser turned into 0.0 / 150.0."""
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):            # covers numpy.float64 (DOUBLE cols)
        return float(val)

    s = str(val).upper().replace('R$', '').replace('$', '')
    s = ''.join(s.split())                        # strip ALL whitespace (incl. NBSP)
    if s in ['', '-', 'NAN', 'NONE', 'NULL']:
        return 0.0

    neg = s.startswith('-')
    s = s.lstrip('+-')

    if '.' in s and ',' in s:
        # Both separators present: the LAST one is the decimal mark.
        if s.rfind(',') > s.rfind('.'):           # BR  1.500.000,50
            s = s.replace('.', '').replace(',', '.')
        else:                                     # US  1,500,000.50
            s = s.replace(',', '')
    elif ',' in s:
        # Comma(s) only. BR uses comma as the decimal; >1 comma -> US thousands.
        s = s.replace(',', '') if s.count(',') > 1 else s.replace(',', '.')
    elif '.' in s:
        # Dot(s) only -- the case the old parser got wrong.
        if s.count('.') > 1:                      # 1.500.000 -> thousands
            s = s.replace('.', '')
        else:
            head, tail = s.rsplit('.', 1)
            if len(tail) == 3:                    # 150.000 / 1.500 -> BR thousands
                s = head + tail
            # else genuine decimal (150.50, 1.5) -> leave as-is

    try:
        out = float(s)
    except ValueError:
        return 0.0
    return -out if neg else out

# --- 3. DATABASE CONNECTIONS & DATA LOADERS ---
try:
    conn = st.connection("mysql", type="sql")
except Exception as e:
    st.error(f"Failed to connect to the database: {e}")
    st.stop()

def cquery(sql, *args, **kwargs):
    """Substituto do conn.query (R8, 26/08). O conn.query do Streamlit chama engine.connect() sem fechar: a conexão
    só volta ao QueuePool quando o garbage collector roda, e com ~30 queries no start (Python 3.14) o pool
    (5 + 10 overflow) esgota → TimeoutError após 30 s → loaders vazios → "tabela não disponível". Aqui a conexão
    é devolvida na saída do with. O cache continua sendo o st.cache_data dos loaders (ttl/show_spinner são ignorados).
    Diagnóstico: diagnostics/pool_check.py."""
    from sqlalchemy import text as _sa_text
    kwargs.pop('ttl', None)
    kwargs.pop('show_spinner', None)
    with conn._instance.connect() as _c:
        return pd.read_sql(_sa_text(sql), _c, *args, **kwargs)

@st.cache_data(ttl=86400) 
def get_brazil_geojson():
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url_geo = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
        with urllib.request.urlopen(url_geo, context=ctx) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

brazil_geo = get_brazil_geojson()

@st.cache_data(ttl=43200)
def load_calendar():
    try:
        query = "SELECT data AS data_ref, eh_dia_util AS is_dia_util, CASE WHEN COALESCE(is_uno,0)+COALESCE(is_uno_premios,0)+COALESCE(is_uno_cashback,0)+COALESCE(is_uno_50_mens,0) > 0 THEN 1 ELSE 0 END AS promo_uno, COALESCE(is_duo,0) AS promo_dupla FROM dim_calendario"
        cal = cquery(query)
        cal['data_ref'] = pd.to_datetime(cal['data_ref'])
        return cal
    except Exception:
        dr = pd.date_range(start='2020-01-01', end='2030-12-31')
        return pd.DataFrame({'data_ref': dr, 'is_dia_util': (dr.weekday < 5).astype(int), 'promo_uno': 0, 'promo_dupla': 0})

@st.cache_data(ttl=43200) 
def load_data():
    # 3 full years back: the "Último 1 Ano" view compares against ~2 years prior,
    # so it needs history reaching ~3 years back, otherwise the "vs Ano Passado"
    # columns silently read 0 because the rows were never loaded.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    # RESUMO_VENDAS_DIARIAS now carries NOME_FRANQUIA, so franchise sales have one row
    # per franquia per (date, uf, tipo). This view only needs uf/tipo totals, so we
    # SUM + GROUP BY in SQL to collapse the franquia grain back to the original shape
    # (identical numbers, ~tens of thousands of rows instead of millions). Without this
    # the 3-year read of the exploded table is large enough to trip a DB read timeout.
    query = (f"SELECT data_venda, uf, tipo_venda, SUM(Vendas) AS Vendas "
             f"FROM RESUMO_VENDAS_DIARIAS WHERE data_venda >= '{start_history}' "
             f"GROUP BY data_venda, uf, tipo_venda")
    try:
        df = cquery(query)
    except Exception:
        return pd.DataFrame(columns=['data_venda', 'uf', 'tipo_venda', 'Vendas'])
    df['data_venda'] = pd.to_datetime(df['data_venda'])
    df['tipo_venda'] = df['tipo_venda'].fillna("Não Informado").astype(str).str.strip().str.title()
    return df

@st.cache_data(ttl=43200) 
def load_invest_data():
    # See load_data: 3 years back so the YoY ("vs Ano Passado") comparisons have data.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    query = f"SELECT data_investimento, canal, plataforma, branding, leads, venda, vol_leads, vol_vendas FROM RESUMO_INVESTIMENTO_DIARIO WHERE data_investimento >= '{start_history}'"
    try:
        df_inv = cquery(query)
        df_inv['data_investimento'] = pd.to_datetime(df_inv['data_investimento'])
        df_inv['canal'] = df_inv['canal'].fillna("Não Informado").astype(str).str.strip().str.title()
        return df_inv
    except Exception:
        return pd.DataFrame(columns=['data_investimento', 'canal', 'plataforma', 'branding', 'leads', 'venda', 'vol_leads', 'vol_vendas'])

@st.cache_data(ttl=43200)
def load_goals_data():
    try:
        query = "SELECT * FROM alex_metas"
        df_goals = cquery(query)
        if df_goals.empty: return pd.DataFrame()
        
        df_goals.columns = df_goals.columns.str.strip()
        
        # Data_Corrigida is ISO text ("2026-06-01 00:00:00"). dayfirst=True was a
        # latent bug: on first-of-month rows it read the MONTH as the day and the
        # "01" day as the month, collapsing EVERY row onto January (so any month
        # other than January matched no goal). Parse strictly as ISO 8601.
        df_goals['Data_Corrigida'] = pd.to_datetime(df_goals['Data_Corrigida'].astype(str).str.strip(), format='ISO8601', errors='coerce')
        df_goals = df_goals.dropna(subset=['Data_Corrigida'])
        df_goals['mes_ano'] = df_goals['Data_Corrigida'].dt.to_period('M').dt.to_timestamp()
        
        # Aggressively force ALL metric columns to be clean floats to prevent TypeErrors
        for col in df_goals.columns:
            if col not in ['Data_Corrigida', 'mes_ano']:
                df_goals[col] = df_goals[col].apply(parse_br_float)
                
        # SCALE FIX (load-bearing): the numeric/DOUBLE target columns were imported
        # from Brazilian-formatted text, so a value like "257.917" (= 257,917) was
        # truncated by the DOUBLE type into 257.917. When the column max looks ~1000x
        # too small, restore it. This only works for targets < 1,000,000 -- multi-dot
        # values like "1.600.000" can't survive a DOUBLE at all, which is exactly why
        # `Investimento Total` is a VARCHAR (parsed correctly by parse_br_float above).
        # Proper fix: store these as real numbers upstream, then delete this block.
        if 'CDT (Total)' in df_goals.columns and df_goals['CDT (Total)'].max() > 0 and df_goals['CDT (Total)'].max() < 1000:
            for col in df_goals.columns:
                if col not in ['Data_Corrigida', 'mes_ano', 'Investimento Total'] and pd.api.types.is_numeric_dtype(df_goals[col]):
                    df_goals[col] = df_goals[col] * 1000
                    
        # R7: colunas de LEADS/DOWNLOADS truncadas (26/08). Elas sofrem a mesma truncagem do DOUBLE mesmo quando
        # 'CDT (Total)' está certo (ex.: 'Leads unicos Total' = 217.625 em vez de 217.625 mil), o que fazia a
        # meta de leads da aba Investimento virar ~200 e o % passar de 50.000%. Corrige coluna a coluna.
        # Fix definitivo: gravar essas metas como inteiros (ou VARCHAR, como 'Investimento Total') no alex_metas.
        for col in ['Leads únicos site', 'Leads únicos APP', 'Leads unicos Total', 'Leads transbordado', 'Download APP']:
            if col in df_goals.columns and pd.api.types.is_numeric_dtype(df_goals[col]):
                _mx = df_goals[col].max()
                if pd.notna(_mx) and 0 < _mx < 1000:
                    df_goals[col] = df_goals[col] * 1000
        return df_goals
    except Exception as e:
        st.error(f"Erro no módulo de metas: {e}")
        return pd.DataFrame()

# =============================================================================
# 4. IN-APP PROPHET FORECASTING ENGINE (v3.14)
# =============================================================================
TRAINING_START = {
    # franquias frozen to 2025-09-01 (removes the +11% day-1 bias). Kept in sync
    # with the FORECAST_ENTRIES override so it can't revert to the biased
    # 18-month window if that override is ever dropped.
    "franquias":      "2025-09-01",
    "website":        "2025-09-01",
    "app do filiado": "2025-09-01",
    "televendas":     "2025-09-01",
    "mgm":            "2026-02-01",
    "outros":         "2025-01-01",
}
APP_SPEND_START = "2026-02-28"
MEGA_CAMPAIGNS = ["2026-04-22"]

TUNED = {
    "franquias": {'weekly_fourier': 5, 'cps': 0.05, 'hps': 1.0, 'seasonality_mode': 'multiplicative', 'use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'is_saturday_prior_scale': 100.0},
    "website": {'weekly_fourier': 5, 'cps': 0.05, 'hps': 1.0, 'seasonality_mode': 'additive', 'use_peak_season': True, 'spend_lag': 0, 'spend_prior_scale': 2.0, 'is_saturday_prior_scale': 10.0, 'spend_lookback_weeks': 2},
    "app do filiado": {'weekly_fourier': 3, 'cps': 0.05, 'hps': 1.0, 'seasonality_mode': 'multiplicative', 'use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'is_saturday_prior_scale': 10.0},
    "televendas": {'weekly_fourier': 5, 'cps': 0.05, 'hps': 10.0, 'seasonality_mode': 'additive', 'use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'is_saturday_prior_scale': 10.0},
    "mgm": {'weekly_fourier': 5, 'cps': 0.3, 'hps': 1.0, 'seasonality_mode': 'multiplicative', 'use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'is_saturday_prior_scale': 100.0},
    "outros": {'weekly_fourier': 5, 'cps': 0.15, 'hps': 1.0, 'seasonality_mode': 'additive', 'use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'is_saturday_prior_scale': 100.0},
}

_DEFAULTS = {
    'use_spend': False, 'working_days': 7, 'floor': 5, 'weekly_fourier': 3,
    'cps': 0.1, 'hps': 1.0, 'seasonality_mode': 'additive', 'use_peak_season': False,
    'spend_lag': 0, 'spend_prior_scale': 0.5, 'is_saturday_prior_scale': 100.0,
    'force_nonnegative_spend': False, 'spend_lookback_weeks': 8,
    'spend_source': None, 'include_in_total': True,
    'growth': 'linear', 'changepoint_range': 0.8,
}

FORECAST_ENTRIES = {
    "franquias":  {'tuned': 'franquias',  'data_channel': 'franquias',  'use_spend': False, 'working_days': 5, 'floor': 10, 'spend_source': None,          'include_in_total': True, 'training_start': '2025-09-01', 'overrides': {'cps': 0.05, 'seasonality_mode': 'additive', 'hps': 5.0, 'weekly_fourier': 5}},
    "website":    {'tuned': 'website',     'data_channel': 'website',     'use_spend': True,  'working_days': 7, 'floor': 50, 'spend_source': 'spend_total', 'include_in_total': True, 'force_nonnegative_spend': True},
    "televendas": {'tuned': 'televendas',  'data_channel': 'televendas',  'use_spend': False, 'working_days': 5, 'floor': 10, 'spend_source': None,          'include_in_total': True},
    "app do filiado (no-spend)": {'tuned': 'app do filiado', 'data_channel': 'app do filiado', 'use_spend': False, 'working_days': 7, 'floor': 20, 'training_start': '2025-09-01', 'spend_source': None, 'include_in_total': True, 'overrides': {'cps': 0.15}},
    "app do filiado (spend)":    {'tuned': 'app do filiado', 'data_channel': 'app do filiado', 'use_spend': True,  'working_days': 7, 'floor': 20, 'training_start': APP_SPEND_START, 'spend_source': 'spend_total2', 'include_in_total': False, 'force_nonnegative_spend': True, 'overrides': {'cps': 0.05, 'spend_lag': 0, 'spend_lookback_weeks': 8}},
    "mgm":        {'tuned': 'mgm',        'data_channel': 'mgm',        'use_spend': False, 'working_days': 7, 'floor': 5,  'spend_source': None,          'include_in_total': True, 'overrides': {'seasonality_mode': 'additive', 'cps': 0.05}},
    "outros":     {'tuned': 'outros',     'data_channel': 'outros',     'use_spend': False, 'working_days': 7, 'floor': 5,  'spend_source': None,          'include_in_total': True},
}

def _build_channel_configs():
    cfgs = {}
    for label, entry in FORECAST_ENTRIES.items():
        tuned = TUNED.get(entry["tuned"], {})
        overrides = entry.get("overrides", {})
        structural = {k: v for k, v in entry.items() if k not in ("tuned", "overrides")}
        cfgs[label] = {**_DEFAULTS, **tuned, **structural, **overrides}
    return cfgs

channel_configs = _build_channel_configs()

ALL_HOLIDAY_NAMES = ["ano_novo", "tiradentes", "dia_trabalho", "independencia", "nossa_senhora", "finados", "proclamacao_republica", "natal", "fim_mes", "dia_pagamento", "carnaval", "sexta_santa", "corpus_christi", "mega_campanha"]
HOLIDAYS_BY_CHANNEL = {
    "franquias": ["ano_novo", "tiradentes", "dia_trabalho", "independencia", "nossa_senhora", "finados", "proclamacao_republica", "natal", "fim_mes", "carnaval", "sexta_santa", "corpus_christi"],
    "website": ALL_HOLIDAY_NAMES, "app do filiado": ALL_HOLIDAY_NAMES, "televendas": ALL_HOLIDAY_NAMES,
    "mgm": ["carnaval", "fim_mes", "dia_pagamento"], "outros": ALL_HOLIDAY_NAMES,
}
SPEND_LOOKBACK_WEEKS = 8
SPEND_SCENARIOS = {
    "balanced":     {"quantile": 0.50, "scale": 1.00},
}

def make_holidays(years):
    records = []
    for y in years:
        records += [
            {"ds": f"{y}-01-01", "holiday": "ano_novo"}, {"ds": f"{y}-04-21", "holiday": "tiradentes"},
            {"ds": f"{y}-05-01", "holiday": "dia_trabalho"}, {"ds": f"{y}-09-07", "holiday": "independencia"},
            {"ds": f"{y}-10-12", "holiday": "nossa_senhora"}, {"ds": f"{y}-11-02", "holiday": "finados"},
            {"ds": f"{y}-11-15", "holiday": "proclamacao_republica"}, {"ds": f"{y}-12-25", "holiday": "natal"},
        ]
        for month in range(1, 13):
            last_day = pd.Timestamp(year=y, month=month, day=1) + pd.offsets.MonthEnd(0)
            if pd.Timestamp("2025-01-01") <= last_day <= pd.Timestamp("2026-12-31"):
                records.append({"ds": str(last_day.date()), "holiday": "fim_mes", "lower_window": -2, "upper_window": 0})
            day5 = pd.Timestamp(year=y, month=month, day=5)
            if pd.Timestamp("2025-01-01") <= day5 <= pd.Timestamp("2026-12-31"):
                records.append({"ds": str(day5.date()), "holiday": "dia_pagamento", "lower_window": -1, "upper_window": 2})
    moveable = [
        {"ds": "2025-03-03", "holiday": "carnaval"}, {"ds": "2025-03-04", "holiday": "carnaval"},
        {"ds": "2026-02-16", "holiday": "carnaval"}, {"ds": "2026-02-17", "holiday": "carnaval"},
        {"ds": "2025-04-18", "holiday": "sexta_santa"}, {"ds": "2026-04-03", "holiday": "sexta_santa"},
        {"ds": "2025-06-19", "holiday": "corpus_christi"}, {"ds": "2026-06-04", "holiday": "corpus_christi"},
    ]
    mega = [{"ds": d, "holiday": "mega_campanha"} for d in MEGA_CAMPAIGNS]
    h = pd.DataFrame(records + moveable + mega)
    h["ds"] = pd.to_datetime(h["ds"])
    for col in ["lower_window", "upper_window"]: h[col] = h.get(col, 0).fillna(0).astype(int)
    return h

def get_channel_holidays(channel, holidays):
    names = HOLIDAYS_BY_CHANNEL.get(channel, ALL_HOLIDAY_NAMES)
    return holidays[holidays["holiday"].isin(names)].reset_index(drop=True)

def add_working_day(df, working_days):
    df = df.copy()
    if working_days == 5: df["is_working_day"] = (df["ds"].dt.dayofweek < 5).astype(int)
    elif working_days == 6: df["is_working_day"] = (df["ds"].dt.dayofweek < 6).astype(int)
    else: df["is_working_day"] = 1
    return df

def add_calendar_regressors(df):
    df = df.copy()
    df["is_saturday"]    = (df["ds"].dt.dayofweek == 5).astype(int)
    df["day_22"]         = (df["ds"].dt.day == 22).astype(int)
    df["late_month"]     = df["ds"].dt.day.isin([26, 27, 28, 29]).astype(int)
    df["month_end_peak"] = df["ds"].dt.day.isin([30, 31]).astype(int)
    df["peak_season"]    = df["ds"].dt.month.isin([4, 5]).astype(int)
    return df

def build_prophet(config, holidays_df):
    growth = config.get("growth", "linear")
    kwargs = dict(
        growth=growth,
        yearly_seasonality=False, daily_seasonality=False, weekly_seasonality=False,
        holidays=holidays_df,
        holidays_prior_scale=config["hps"],
        changepoint_prior_scale=config["cps"],
        seasonality_mode=config.get("seasonality_mode", "additive"),
        interval_width=0.90,
        mcmc_samples=0
    )
    if growth != "flat":
        kwargs["changepoint_range"] = config.get("changepoint_range", 0.8)
        
    m = Prophet(**kwargs)
    m.add_seasonality(name="weekly", period=7, fourier_order=config["weekly_fourier"])
    m.add_regressor("is_saturday", standardize=False, prior_scale=config.get("is_saturday_prior_scale", 100.0))
    m.add_regressor("day_22", standardize=False, prior_scale=10.0)
    m.add_regressor("late_month", standardize=False, prior_scale=10.0)
    m.add_regressor("month_end_peak", standardize=False, prior_scale=10.0)
    if config.get("use_peak_season", False):
        m.add_regressor("peak_season", standardize=False, prior_scale=10.0)
    if config["use_spend"]:
        m.add_regressor("spend_workday", standardize=True, prior_scale=config.get("spend_prior_scale", 0.5))
    return m

def train_cols_for(config):
    cols = ["ds", "y", "is_saturday", "day_22", "late_month", "month_end_peak"]
    if config.get("use_peak_season", False): cols.append("peak_season")
    if config["use_spend"]: cols.append("spend_workday")
    return cols

def forecast_future_spend(df_channel, future_dates, quantile, scale, weeks_back=SPEND_LOOKBACK_WEEKS):
    max_ds = pd.Timestamp(df_channel["ds"].max())
    cutoff = max_ds - pd.Timedelta(weeks=weeks_back)
    recent = df_channel[df_channel["ds"] > cutoff].copy()
    if recent.empty: recent = df_channel.copy()
    recent["dow"] = recent["ds"].dt.dayofweek
    profile = recent.groupby("dow")["spend_channel"].quantile(quantile)
    fallback = float(profile.mean()) if len(profile) else 0.0

    fut = pd.DataFrame({"ds": pd.to_datetime(future_dates)})
    fut["dow"] = fut["ds"].dt.dayofweek
    fut["spend_channel"] = fut["dow"].map(profile).fillna(fallback).astype(float) * scale
    return fut[["ds", "spend_channel"]]

def attach_lagged_spend_workday(future, df_history, lag_days, working_days):
    hist, fut = df_history[["ds", "spend_channel"]].copy(), future[["ds", "spend_channel"]].copy()
    combined = pd.concat([hist, fut], ignore_index=True).sort_values("ds").reset_index(drop=True)
    combined = add_working_day(combined, working_days)
    combined["spend_workday"] = combined["spend_channel"] * combined["is_working_day"]
    if lag_days > 0: combined["spend_workday"] = combined["spend_workday"].shift(lag_days).fillna(0)
    out = future.copy()
    out["spend_workday"] = out["ds"].map(combined.set_index("ds")["spend_workday"]).fillna(0).astype(float)
    return out

def apply_floors(forecast, config, sat_floor, sun_floor):
    forecast = forecast.copy()
    forecast["yhat"] = forecast["yhat"].clip(lower=config["floor"])
    forecast.loc[forecast["ds"].dt.dayofweek == 5, "yhat"] = forecast.loc[forecast["ds"].dt.dayofweek == 5, "yhat"].clip(lower=sat_floor)
    forecast.loc[forecast["ds"].dt.dayofweek == 6, "yhat"] = forecast.loc[forecast["ds"].dt.dayofweek == 6, "yhat"].clip(lower=sun_floor)
    return forecast

@st.cache_data(ttl=43200, show_spinner="Gerando previsões de vendas (Prophet)...")
def generate_prophet_forecast(ref_date_str):
    if not PROPHET_AVAILABLE: return pd.DataFrame()
    
    # Train only on data up to the reference date so the forecast horizon starts
    # exactly at ref_date+1 (matching the `ds > ref_datetime` display filter) and
    # never trains on a partial "today". This also makes ref_date_str a real cache
    # key rather than incidental.
    try:
        df_raw = cquery(f"SELECT ds, channel_group, y, spend_total, spend_total2 FROM vw_prophet_input WHERE y IS NOT NULL AND ds <= '{ref_date_str}' ORDER BY ds")
    except Exception:
        try:
            df_raw = cquery(f"SELECT ds, channel_group, y, spend_total FROM vw_prophet_input WHERE y IS NOT NULL AND ds <= '{ref_date_str}' ORDER BY ds")
        except Exception:
            return pd.DataFrame()
        
    if df_raw.empty: return pd.DataFrame()

    df_raw["ds"] = pd.to_datetime(df_raw["ds"])
    df_raw["y"] = pd.to_numeric(df_raw["y"], errors="coerce").fillna(0)
    df_raw["spend_total"] = pd.to_numeric(df_raw["spend_total"], errors="coerce").fillna(0)
    if "spend_total2" not in df_raw.columns:
        df_raw["spend_total2"] = 0.0
    df_raw["spend_total2"] = pd.to_numeric(df_raw["spend_total2"], errors="coerce").fillna(0)

    # Double-load band-aid REMOVED: vw_prophet_input is corrected at the source,
    # so y / spend_total / spend_total2 are read as-is (no halving of 2025-10 or
    # 2026-05). Left as a breadcrumb in case a double-load ever recurs.

    holidays = make_holidays(years=[2025, 2026])
    all_production_forecasts = []
    
    for channel, config in channel_configs.items():
        np.random.seed(42)
        
        data_channel = config.get("data_channel", channel)
        train_start = config.get("training_start", TRAINING_START.get(data_channel))
        in_total = config.get("include_in_total", True)
        
        df_channel = df_raw[df_raw["channel_group"] == data_channel].copy()
        df_channel = df_channel[df_channel["ds"] >= pd.Timestamp(train_start)].sort_values("ds").reset_index(drop=True)
        if len(df_channel) < 60: continue
            
        src = config.get("spend_source")
        if config["use_spend"] and src and src in df_channel.columns:
            df_channel["spend_channel"] = pd.to_numeric(df_channel[src], errors="coerce").fillna(0.0)
        else:
            df_channel["spend_channel"] = 0.0

        df_channel = add_working_day(df_channel, config["working_days"])
        df_channel = add_calendar_regressors(df_channel)
        df_channel["spend_workday_base"] = df_channel["spend_channel"] * df_channel["is_working_day"]

        holidays_ch = get_channel_holidays(data_channel, holidays)
        
        if config["use_spend"] and config.get("force_nonnegative_spend", False):
            df_channel["spend_workday"] = df_channel["spend_workday_base"].shift(config.get("spend_lag", 0)).fillna(0)
            try:
                m_check = build_prophet(config, holidays_ch)
                m_check.fit(df_channel[train_cols_for(config)])
                coefs = regressor_coefficients(m_check)
                spend_row = coefs[coefs["regressor"] == "spend_workday"]
                if not spend_row.empty and float(spend_row["coef"].iloc[0]) < 0:
                    config = {**config, "use_spend": False}
            except Exception:
                pass

        lag = config.get("spend_lag", 0)
        df_channel["spend_workday"] = df_channel["spend_workday_base"].shift(lag).fillna(0) if config["use_spend"] else df_channel["spend_workday_base"]

        sat_data = df_channel[df_channel["ds"].dt.dayofweek == 5]["y"]
        sun_data = df_channel[df_channel["ds"].dt.dayofweek == 6]["y"]
        sat_floor = int(sat_data.quantile(0.10)) if len(sat_data) > 0 else 0
        sun_floor = int(sun_data.quantile(0.25)) if len(sun_data) > 0 else 0

        cap_limit = df_channel["y"].quantile(0.98)
        exempt = ((df_channel["day_22"] == 1) | (df_channel["late_month"] == 1) | (df_channel["month_end_peak"] == 1) | df_channel["ds"].isin(holidays_ch["ds"]))
        df_channel["y"] = np.where((df_channel["y"] > cap_limit) & (~exempt), cap_limit, df_channel["y"])

        cols = train_cols_for(config)
        m_prod = build_prophet(config, holidays_ch)
        m_prod.fit(df_channel[cols])

        PROD_HORIZON = 365
        base_future = m_prod.make_future_dataframe(periods=PROD_HORIZON, freq="D", include_history=False)
        base_future = add_calendar_regressors(base_future)
        base_future = add_working_day(base_future, config["working_days"])

        def _finalize_forecast(forecast, scenario_name, spend_assumed_series):
            f = apply_floors(forecast, config, sat_floor, sun_floor)
            # Re-map the channel label back to its pure historical database name so the dashboard parses it correctly
            f["channel_group"] = data_channel.title()
            f["scenario"] = scenario_name
            f["spend_assumed"] = spend_assumed_series
            return f

        channel_lookback = int(config.get("spend_lookback_weeks", 8))
        
        # Only attach to final dashboard output if it's meant to be included in company totals
        if in_total:
            if config["use_spend"]:
                for scenario_name, scen in SPEND_SCENARIOS.items():
                    future = base_future.copy()
                    spend_fut = forecast_future_spend(df_channel, future["ds"], quantile=scen["quantile"], scale=scen["scale"], weeks_back=channel_lookback)
                    future = future.merge(spend_fut, on="ds", how="left")
                    future = attach_lagged_spend_workday(future, df_channel[["ds", "spend_channel"]], lag_days=lag, working_days=config["working_days"])
                    forecast = m_prod.predict(future)
                    all_production_forecasts.append(_finalize_forecast(forecast, scenario_name, future["spend_channel"].values))
            else:
                forecast = m_prod.predict(base_future)
                for scenario_name in SPEND_SCENARIOS:
                    all_production_forecasts.append(_finalize_forecast(forecast.copy(), scenario_name, 0.0))

    if all_production_forecasts:
        final_df = pd.concat(all_production_forecasts, ignore_index=True)
        return final_df
    return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner="Carregando previsões pré-calculadas...")
def load_stored_forecast():
    # Use the most recent stored Prophet snapshot (written by propheta.py to
    # FORECAST_VENDAS_CANAL) instead of training Prophet live on every load — this is
    # what makes initialization fast. Snapshots are keyed by (run_date, model_version);
    # we take the latest run (newest run_date, then newest generated_at to handle a
    # same-day re-run) and keep only channels flagged included=1, which matches the old
    # live output (it only emitted the channels that count toward company totals).
    # Returns the same columns the live forecast did, so it's a drop-in for df_fcst.
    try:
        d = cquery("""
            SELECT ds, channel_group, scenario, yhat, yhat_lower, yhat_upper,
                   spend_assumed, run_date, generated_at
            FROM FORECAST_VENDAS_CANAL
            WHERE included = 1
              AND (run_date, model_version, generated_at) = (
                  SELECT run_date, model_version, generated_at
                  FROM FORECAST_VENDAS_CANAL
                  ORDER BY run_date DESC, generated_at DESC
                  LIMIT 1)
        """)
    except Exception:
        return pd.DataFrame()
    if d.empty:
        return pd.DataFrame()
    d['ds'] = pd.to_datetime(d['ds'])
    d['channel_group'] = d['channel_group'].astype(str)
    d['scenario'] = d['scenario'].astype(str)
    for c in ['yhat', 'yhat_lower', 'yhat_upper', 'spend_assumed']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0)
    return d

@st.cache_data(ttl=43200, show_spinner="Carregando custos de campanhas...")
def load_campaign_costs():
    # Per-campaign daily cost across the three paid platforms. campaign_name here
    # matches alex_ga_vendas.session_campaign_name (confirmed), so cost and purchase
    # events join on the campaign name.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    parts = []
    for tbl, plat in [("alex_google_campaigns", "Google"),
                      ("alex_meta_campaigns", "Meta"),
                      ("alex_tiktok_campaigns", "TikTok")]:
        try:
            part = cquery(f"SELECT `date`, `campaign_name`, `cost` FROM {tbl} WHERE `date` >= '{start_history}'")
            part['plataforma'] = plat
            parts.append(part)
        except Exception:
            pass
    # R26: Jampp (DSP de app; alex_jampp_campaigns, GAS jampp.gs). Custo em BRL (spend_brl = USD × câmbio do mês:
    # fechamento Jampp > PTAX fim de mês > último fechamento); somado por campanha (a tabela é por grupo).
    try:
        part = cquery("SELECT `date`, `campaign_name`, SUM(COALESCE(`spend_brl`, 0)) AS `cost` FROM alex_jampp_campaigns "
                      f"WHERE `date` >= '{start_history}' GROUP BY 1, 2")
        part['plataforma'] = 'Jampp'
        parts.append(part)
    except Exception:
        pass
    if not parts:
        return pd.DataFrame(columns=['date', 'campaign_name', 'cost', 'plataforma'])
    out = pd.concat(parts, ignore_index=True)
    out['date'] = pd.to_datetime(out['date'])
    out['cost'] = pd.to_numeric(out['cost'], errors='coerce').fillna(0.0)
    out['campaign_name'] = out['campaign_name'].astype(str)
    return out

@st.cache_data(ttl=43200, show_spinner="Carregando eventos de compra (GA)...")
def load_ga_vendas():
    # Canonical purchase-event source, by campaign + source/medium.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    try:
        out = cquery("SELECT `date`, `session_campaign_name`, `session_source_medium`, `conversions` "
                         f"FROM alex_ga_vendas WHERE `date` >= '{start_history}'")
    except Exception:
        return pd.DataFrame(columns=['date', 'session_campaign_name', 'session_source_medium', 'conversions'])
    out['date'] = pd.to_datetime(out['date'])
    out['conversions'] = pd.to_numeric(out['conversions'], errors='coerce').fillna(0.0)
    out['session_campaign_name'] = out['session_campaign_name'].astype(str)
    out['session_source_medium'] = out['session_source_medium'].astype(str)
    return out

@st.cache_data(ttl=43200, show_spinner="Carregando eventos de lead (GA)...")
def load_ga_leads():
    # Canonical lead-event source — mirrors load_ga_vendas but from alex_ga_leads.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    try:
        out = cquery("SELECT `date`, `session_campaign_name`, `session_source_medium`, `conversions` "
                         f"FROM alex_ga_leads WHERE `date` >= '{start_history}'")
    except Exception:
        return pd.DataFrame(columns=['date', 'session_campaign_name', 'session_source_medium', 'conversions'])
    out['date'] = pd.to_datetime(out['date'])
    out['conversions'] = pd.to_numeric(out['conversions'], errors='coerce').fillna(0.0)
    out['session_campaign_name'] = out['session_campaign_name'].astype(str)
    out['session_source_medium'] = out['session_source_medium'].astype(str)
    return out

@st.cache_data(ttl=43200, show_spinner="Carregando leads do Meta...")
def load_meta_leads():
    # Meta's own lead metric. alex_meta_campaigns has PRIMARY KEY (date, campaign_name),
    # so this is exactly one row per campaign per day — no source/medium fan-out. Used as
    # the Meta leads source instead of GA (GA has one row per campaign PER source/medium,
    # so joining this single value onto GA would multiply it).
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    try:
        d = cquery("SELECT `date`, `campaign_name`, COALESCE(`on_facebook_leads`, 0) AS leads "
                       f"FROM alex_meta_campaigns WHERE `date` >= '{start_history}'")
    except Exception:
        return pd.DataFrame(columns=['date', 'campaign_name', 'leads'])
    d['date'] = pd.to_datetime(d['date'])
    d['campaign_name'] = d['campaign_name'].astype(str)
    d['leads'] = pd.to_numeric(d['leads'], errors='coerce').fillna(0.0)
    return d

# App-sale columns: the ad platforms track in-app filiações in their OWN conversion
# columns; GA (web) never sees them, so %download% campaigns read 0 if sourced from GA.
# These two constants are the single place to change the column if a diagnostic shows the
# data lives elsewhere (e.g. Meta 'messaging_conversations_started', TikTok 'purchase_events').
APP_SALES_COL_META   = "mobile_app_purchases"
APP_SALES_COL_TIKTOK = "unique_purchases"

@st.cache_data(ttl=43200, show_spinner="Carregando vendas do App...")
def load_app_sales():
    # App (filiação) sales for %download% campaigns, summed from the ad platforms' own app
    # conversion columns (Meta + TikTok). One row per (date, campaign_name) per source.
    # Mirrors RESUMO_INVESTIMENTO_DIARIO blocks 6 & 7 so Campanhas and Investimento agree.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    frames = []
    for table, col in [("alex_meta_campaigns", APP_SALES_COL_META),
                       ("alex_tiktok_campaigns", APP_SALES_COL_TIKTOK)]:
        try:
            f = cquery(
                f"SELECT `date`, `campaign_name`, COALESCE(`{col}`, 0) AS purchases "
                f"FROM {table} WHERE LOWER(`campaign_name`) LIKE '%download%' "
                f"AND `date` >= '{start_history}'")
            frames.append(f)
        except Exception:
            pass
    if not frames:
        return pd.DataFrame(columns=['date', 'campaign_name', 'purchases'])
    d = pd.concat(frames, ignore_index=True)
    d['date'] = pd.to_datetime(d['date'])
    d['campaign_name'] = d['campaign_name'].astype(str)
    d['purchases'] = pd.to_numeric(d['purchases'], errors='coerce').fillna(0.0)
    return d

@st.cache_data(ttl=43200)
def load_franquia_sales():
    # Franchise-level daily sales for the UF franchise map (point D). Reads the new
    # NOME_FRANQUIA column on RESUMO_VENDAS_DIARIAS; isolated from load_data() so the
    # core df pipeline is untouched. Returns empty if the column isn't deployed yet.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    try:
        # The map only needs distinct franquias and summed Vendas per UF over the
        # period, so collapse tipo_venda in SQL (one row per date/uf/franquia) to keep
        # the read small despite the franquia-grain row count.
        q = ("SELECT data_venda, uf, NOME_FRANQUIA, SUM(Vendas) AS Vendas "
             f"FROM RESUMO_VENDAS_DIARIAS WHERE data_venda >= '{start_history}' "
             "AND NOME_FRANQUIA IS NOT NULL AND TRIM(NOME_FRANQUIA) <> '' "
             "GROUP BY data_venda, uf, NOME_FRANQUIA")
        d = cquery(q)
        d['data_venda'] = pd.to_datetime(d['data_venda'])
        d['uf'] = d['uf'].astype(str).str.upper().str.strip()
        d['NOME_FRANQUIA'] = d['NOME_FRANQUIA'].astype(str).str.strip()
        d['Vendas'] = pd.to_numeric(d['Vendas'], errors='coerce').fillna(0)
        return d
    except Exception:
        return pd.DataFrame(columns=['data_venda', 'uf', 'NOME_FRANQUIA', 'Vendas'])

# =============================================================================
# NEW LOADERS — dados novos da planilha "Ad Sources & Events" já importados no
# banco: CRM WhatsApp/SMS (GA), mensageria Zenvia e métricas de plataforma para
# o funil piloto. Todos degradam para DataFrame vazio se a tabela não existir.
# =============================================================================
@st.cache_data(ttl=43200, show_spinner="Carregando leads/vendas de CRM (Wpp/SMS)...")
def load_crm_wpp_sms():
    # Leads e vendas atribuídos a CRM (WhatsApp/SMS) via GA — tabelas novas
    # alex_crm_wpp_sms_leads / alex_crm_wpp_sms_vendas. As fontes aqui são
    # whatsapp/sms/crm, DISJUNTAS de alex_ga_leads (que só traz fontes pagas
    # "* / cpc"), então os leads podem ser SOMADOS aos pagos sem dupla contagem.
    # Já alex_ga_vendas INCLUI 'whatsapp / MKT_DIRETO' — ao somar vendas CRM,
    # remova antes as linhas CRM de alex_ga_vendas (ver aba Funil).
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    out = {}
    for key, tbl in [('leads', 'alex_crm_wpp_sms_leads'), ('vendas', 'alex_crm_wpp_sms_vendas')]:
        try:
            d = cquery(f"SELECT `date`, `session_campaign_name`, `session_source_medium`, "
                           f"`event_count` FROM {tbl} WHERE `date` >= '{start_history}'")
            d['date'] = pd.to_datetime(d['date'])
            d['event_count'] = pd.to_numeric(d['event_count'], errors='coerce').fillna(0)
            d['session_campaign_name'] = d['session_campaign_name'].astype(str)
            d['session_source_medium'] = d['session_source_medium'].astype(str)
        except Exception:
            d = pd.DataFrame(columns=['date', 'session_campaign_name', 'session_source_medium', 'event_count'])
        out[key] = d
    return out['leads'], out['vendas']

@st.cache_data(ttl=43200, show_spinner="Carregando mensageria (Zenvia)...")
def load_zenvia():
    # Disparos e custo de mensageria por remetente/dia (alex_zenvia_sender).
    # É o custo de CRM que faltava no banco — usado na aba Campanhas (CRM) e
    # no bloco CRM & Mensageria da aba Investimento.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 3, month=1, day=1)
    try:
        d = cquery("SELECT report_date, sender_name, total_messages, total_price "
                       f"FROM alex_zenvia_sender WHERE report_date >= '{start_history}'")
        d['report_date'] = pd.to_datetime(d['report_date'])
        d['total_messages'] = pd.to_numeric(d['total_messages'], errors='coerce').fillna(0)
        d['total_price'] = pd.to_numeric(d['total_price'], errors='coerce').fillna(0.0)
        d['sender_name'] = d['sender_name'].astype(str)
        return d
    except Exception:
        return pd.DataFrame(columns=['report_date', 'sender_name', 'total_messages', 'total_price'])

CRM_INVEST_COLS = ['data_investimento', 'canal', 'plataforma', 'branding', 'leads', 'venda', 'vol_leads', 'vol_vendas']

def build_crm_invest_rows():
    """Linhas de investimento do canal/plataforma 'CRM' no formato de RESUMO_INVESTIMENTO_DIARIO, para que o
    CRM entre nos filtros, na tabela e nos gráficos da aba Investimento (R5, 26/08).
      - custo = mensageria Zenvia (alex_zenvia_sender.total_price, todos os remetentes), lançado na categoria
        'venda' (disparos de conversão/reimpacto; o Zenvia não abre branding/leads/venda);
      - vol_leads / vol_vendas = eventos GA atribuídos a whatsapp/sms/crm (alex_crm_wpp_sms_*), DISJUNTOS das
        fontes pagas — somam sem dupla contagem.
    RESUMO_INVESTIMENTO_DIARIO não tem linhas de CRM (conferido em 26/08), então nada é contado duas vezes.
    Sem tabelas → DataFrame vazio (a aba fica como antes)."""
    zen = load_zenvia()
    crm_leads, crm_vendas = load_crm_wpp_sms()
    parts = []
    if not zen.empty:
        parts.append(zen.groupby('report_date')['total_price'].sum().rename('venda'))
    if not crm_leads.empty:
        parts.append(crm_leads.groupby('date')['event_count'].sum().rename('vol_leads'))
    if not crm_vendas.empty:
        parts.append(crm_vendas.groupby('date')['event_count'].sum().rename('vol_vendas'))
    if not parts:
        return pd.DataFrame(columns=CRM_INVEST_COLS)
    out = pd.concat(parts, axis=1)
    out.index = pd.to_datetime(out.index)
    out.index.name = 'data_investimento'
    out = out.sort_index().fillna(0.0).astype(float)
    for c in ['branding', 'leads', 'venda', 'vol_leads', 'vol_vendas']:
        if c not in out.columns:
            out[c] = 0.0
    out = out.reset_index()
    out['canal'] = 'CRM'
    out['plataforma'] = 'CRM'
    return out[CRM_INVEST_COLS]

@st.cache_data(ttl=43200, show_spinner="Carregando métricas de plataforma (funil)...")
def load_platform_daily():
    # Impressões/cliques/custo por dia+campanha+plataforma — topo do funil piloto.
    start_history = datetime.date.today().replace(year=datetime.date.today().year - 2, month=1, day=1)
    parts = []
    for tbl, plat, clicks_col in [("alex_google_campaigns", "Google", "clicks"),
                                  ("alex_meta_campaigns", "Meta", "clicks_all"),
                                  ("alex_tiktok_campaigns", "TikTok", "clicks")]:
        try:
            p = cquery(f"SELECT `date`, `campaign_name`, `cost`, `impressions`, "
                           f"`{clicks_col}` AS clicks FROM {tbl} WHERE `date` >= '{start_history}'")
            p['plataforma'] = plat
            parts.append(p)
        except Exception:
            pass
    try:  # R26: Jampp (BRL via spend_brl; por campanha)
        p = cquery("SELECT `date`, `campaign_name`, SUM(COALESCE(`spend_brl`, 0)) AS `cost`, SUM(`impressions`) AS `impressions`, "
                   f"SUM(`clicks`) AS clicks FROM alex_jampp_campaigns WHERE `date` >= '{start_history}' GROUP BY 1, 2")
        p['plataforma'] = 'Jampp'
        parts.append(p)
    except Exception:
        pass
    if not parts:
        return pd.DataFrame(columns=['date', 'campaign_name', 'cost', 'impressions', 'clicks', 'plataforma'])
    d = pd.concat(parts, ignore_index=True)
    d['date'] = pd.to_datetime(d['date'])
    for c in ['cost', 'impressions', 'clicks']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0)
    d['campaign_name'] = d['campaign_name'].astype(str)
    return d

CHECKOUT_FUNNEL_COLS = ['active_users',
                        'generate_lead', 'add_shipping_info', 'add_payment_info', 'purchase',
                        'generate_lead_users', 'add_shipping_info_users', 'add_payment_info_users',
                        'purchase_users']

@st.cache_data(ttl=43200, show_spinner="Carregando funil do checkout (site)...")
def _load_checkout_funnel_raw():
    # Funil do Website Checkout — tabela alex_ga_checkout_funnel (uma linha por dia),
    # alimentada pelo Apps Script Checkout_Funnel.gs (planilha "Ad Sources & Events").
    # Desde 25/08 cada etapa tem eventCount (colunas sem sufixo) E activeUsers
    # (colunas *_users). Colunas podem ser NULL — preserve NaN para a aba
    # distinguir "sem dados" de zero. SELECT * mantém compatibilidade caso a
    # tabela ainda não tenha as colunas novas.
    # Só o SELECT é cacheado: uma falha levanta exceção e NÃO fica presa no cache por 12 h.
    d = cquery("SELECT * FROM alex_ga_checkout_funnel", ttl=0)
    d['date'] = pd.to_datetime(d['date'])
    for c in CHECKOUT_FUNNEL_COLS:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    return d

def load_checkout_funnel():
    """Wrapper sem cache: em caso de erro devolve DataFrame vazio e guarda a mensagem real
    em st.session_state['_err_checkout_funnel'] para a aba exibir."""
    try:
        d = _load_checkout_funnel_raw()
        st.session_state.pop('_err_checkout_funnel', None)
        return d
    except Exception as e:
        st.session_state['_err_checkout_funnel'] = f"{type(e).__name__}: {str(e)[:400]}"
        return pd.DataFrame(columns=['date'] + CHECKOUT_FUNNEL_COLS)

# Fragmentos de session_source_medium que identificam tráfego CRM no GA.
# Compartilhado entre a aba Campanhas e a aba Funil (Piloto).
CRM_SOURCE_PATTERNS_GLOBAL = ['whatsapp', 'sms', 'crm']

def crm_source_mask(dfx, col='session_source_medium'):
    s = dfx[col].astype(str).str.lower()
    m = pd.Series(False, index=dfx.index)
    for pat in CRM_SOURCE_PATTERNS_GLOBAL:
        m = m | s.str.contains(pat, na=False, regex=False)
    return m

# Call the cached data loaders
df_cal = load_calendar()
df_raw = load_data()
df_invest_raw = load_invest_data()
# Canal/plataforma CRM (Zenvia + GA Wpp/SMS) entra na mesma base da aba Investimento (R5). As barras
# globais de ritmo (🎯) continuam só com mídia paga — ver tab3.
_crm_inv_rows = build_crm_invest_rows()
if not _crm_inv_rows.empty:
    df_invest_raw = pd.concat([df_invest_raw, _crm_inv_rows], ignore_index=True)
    for _c in ['branding', 'leads', 'venda', 'vol_leads', 'vol_vendas']:
        df_invest_raw[_c] = pd.to_numeric(df_invest_raw[_c], errors='coerce').fillna(0.0)
df_goals = load_goals_data()

if df_raw.empty:
    st.error(
        "⚠️ **RESUMO_VENDAS_DIARIAS não retornou nenhuma venda** (tabela vazia ou sem dados "
        "nos últimos 3 anos). Por isso todas as vendas aparecem como 0 — não é um erro do "
        "dashboard. Repopule a tabela: rode `CALL SP_Atualizar_Resumo_Vendas();` (recupera a "
        "janela recente) ou o backfill completo a partir de NOMINAL_VENDAS se a tabela estiver "
        "totalmente vazia."
    )

df = pd.merge(df_raw, df_cal, left_on='data_venda', right_on='data_ref', how='left')
df_invest = pd.merge(df_invest_raw, df_cal, left_on='data_investimento', right_on='data_ref', how='left')

df['is_dia_util'] = df['is_dia_util'].fillna(1)
df_invest['is_dia_util'] = df_invest['is_dia_util'].fillna(1)

# --- 5. DEFINING BUSINESS AGGREGATES & LINEAR GOALS ---
dig_list = ['website', 'app do filiado']
out_list = ['mgm', 'digital b2b2c', 'cdt sonhos', 'cdt sonhos maistodos', 'b2b2c', 'carlinhos maia', 'influenciadores', 'tutti']
tv_list  = ['televendas']
nac_list = dig_list + out_list + tv_list
fra_list = ['porta a porta', 'link do vendedor', 'app do vendedor']

group_map = {
    'Digital': dig_list,
    'Franquias': fra_list,
    'Outros': out_list,
    'Nacional': nac_list,
    'CDT': nac_list + fra_list
}

prophet_map = {
    'porta a porta': 'Franquias',
    'link do vendedor': 'Franquias',
    'app do vendedor': 'Franquias',
    'website': 'Website',
    'app do filiado': 'App Do Filiado',
    'televendas': 'Televendas',
    'mgm': 'Mgm',
    'digital b2b2c': 'Outros',
    'cdt sonhos': 'Outros',
    'cdt sonhos maistodos': 'Outros',
    'b2b2c': 'Outros',
    'carlinhos maia': 'Outros',
    'influenciadores': 'Outros',
    'tutti': 'Outros'
}

def get_prorated_goal(df_goals_db, start_d, end_d, column_name):
    if df_goals_db.empty or column_name not in df_goals_db.columns:
        return 0.0
    
    total_goal = 0.0
    current_d = start_d
    while current_d <= end_d:
        month_mask = (df_goals_db['mes_ano'] == current_d.replace(day=1))
        if month_mask.any():
            month_goal = df_goals_db.loc[month_mask, column_name].iloc[0]
            if pd.notna(month_goal):
                days_in_month = pd.Period(current_d, freq='M').days_in_month
                total_goal += float(month_goal) / float(days_in_month)
        current_d += pd.Timedelta(days=1)
    return float(total_goal)

# Maps a chart group / channel label to its target column(s) in alex_metas.
GOAL_COL_MAP = {
    'Digital': ['Site', 'App'],
    'Franquias': ['Franquias'],
    'Outros': ['Outros', 'B2b2c Digital'],
    'Nacional': ['Canais Nacionais'],
    'CDT': ['CDT (Total)'],
    'Website': ['Site'],
    'App Do Filiado': ['App'],
    'Televendas': ['Televendas'],
    'Porta A Porta': ['PAP'],
    'Link Do Vendedor': ['Link do Vendedor'],
    'App Do Vendedor': ['App do Vendedor'],
    'Digital B2B2C': ['B2b2c Digital']
}

def get_goal_for_group(start_d, end_d, grupo_nome):
    cols = GOAL_COL_MAP.get(grupo_nome.strip(), [])
    return sum(get_prorated_goal(df_goals, start_d, end_d, c) for c in cols)

def build_goal_trend(grupo, t_start, t_end, cumulative):
    """Daily (or cumulative) target line for a group over [t_start, t_end], shaped
    like get_trend_data's output so it can be concatenated straight into the trend
    chart. In cumulative mode the line ramps to the FULL-period target: its endpoint
    is the total goal and its value at 'today' is the proportional (parcial) goal.
    The per-day rate is month-aware, so multi-month periods ramp correctly."""
    cols = GOAL_COL_MAP.get(grupo.strip(), [])
    if df_goals.empty or not cols:
        return pd.DataFrame()
    days = pd.date_range(t_start, t_end, freq='D')
    daily_vals = []
    for d in days:
        day_total = 0.0
        mask = (df_goals['mes_ano'] == d.replace(day=1))
        if mask.any():
            row = df_goals.loc[mask].iloc[0]
            dim = pd.Period(d, freq='M').days_in_month
            for c in cols:
                v = row.get(c)
                if pd.notna(v):
                    day_total += float(v) / dim
        daily_vals.append(day_total)
    out = pd.DataFrame({'data_venda': days, 'Vendas': daily_vals})
    if cumulative:
        out['Vendas'] = out['Vendas'].cumsum()
    out['Grupo'] = grupo
    out['Dia'] = (out['data_venda'] - t_start).dt.days + 1
    out['Traço'] = grupo + " (Meta)"
    out['Data_Real'] = out['data_venda']
    return out

def get_agg_sums(df_slice, is_forecast=False):
    if df_slice.empty:
        return {'Digital': 0, 'Franquias': 0, 'Outros': 0, 'Nacional': 0, 'CDT': 0}
    
    col_chan = 'channel_group' if is_forecast else 'tipo_venda'
    col_val = 'yhat' if is_forecast else 'Vendas'

    dig = df_slice[df_slice[col_chan].str.lower().isin(dig_list)][col_val].sum()
    out = df_slice[df_slice[col_chan].str.lower().isin(out_list)][col_val].sum()
    nac = df_slice[df_slice[col_chan].str.lower().isin(nac_list)][col_val].sum()
    fra = df_slice[df_slice[col_chan].str.lower().isin(fra_list)][col_val].sum()
    cdt = df_slice[col_val].sum() 
    return {'Digital': dig, 'Franquias': fra, 'Outros': out, 'Nacional': nac, 'CDT': cdt}

def get_channel_sums(df_slice, is_forecast=False):
    if df_slice.empty: return {}
    col_chan = 'channel_group' if is_forecast else 'tipo_venda'
    col_val = 'yhat' if is_forecast else 'Vendas'
    return df_slice.groupby(df_slice[col_chan].str.lower())[col_val].sum().to_dict()

def get_fcst_agg_sums(df_fcst_slice):
    if df_fcst_slice.empty:
        return {'Digital': 0, 'Franquias': 0, 'Outros': 0, 'Nacional': 0, 'CDT': 0}
    
    df_f = df_fcst_slice.copy()
    df_f['cg'] = df_f['channel_group'].str.title()
    
    dig = df_f[df_f['cg'].isin(['Website', 'App Do Filiado'])]['yhat'].sum()
    out = df_f[df_f['cg'].isin(['Mgm', 'Outros'])]['yhat'].sum()
    nac = df_f[df_f['cg'].isin(['Website', 'App Do Filiado', 'Mgm', 'Outros', 'Televendas'])]['yhat'].sum()
    fra = df_f[df_f['cg'].isin(['Franquias'])]['yhat'].sum()
    cdt = df_f['yhat'].sum()
    
    return {'Digital': dig, 'Franquias': fra, 'Outros': out, 'Nacional': nac, 'CDT': cdt}

# --- 6. GLOBAL SIDEBAR (TIME & CALENDAR LOGIC) ---
st.sidebar.title("🎛️ Controles Globais")

now_utc = datetime.datetime.now(datetime.timezone.utc)
now_sp = now_utc - datetime.timedelta(hours=3)

# Anchor "today" to the latest day actually present in the data, capped at yesterday so a
# partial same-day load never counts as a complete day. The old clock-based rule showed
# "today-2" before 11:30, which silently EXCLUDED the most recent day (e.g. 30/06) even
# when it was already loaded — making the whole dashboard read a day behind the table.
_yesterday = now_sp.date() - datetime.timedelta(days=1)
if not df.empty:
    reference_date = min(df['data_venda'].max().date(), _yesterday)
else:
    reference_date = _yesterday

st.sidebar.caption(f"🔄 **Dados até:** {reference_date.strftime('%d/%m/%Y')} "
                   f"(último dia completo na base)")
if st.sidebar.button("♻️ Recarregar dados (limpar cache)"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.divider()

view_option = st.sidebar.radio("Período de Análise:", [
    "Semana Atual", "Mês Atual", "Ano Atual", "Última Semana", "Último Mês",
    "Selecionar Período"
])

# Custom date range: two pickers that override the preset above.
custom_start = custom_end = None
if view_option == "Selecionar Período":
    _default_start = reference_date.replace(day=1)
    cds_col, cde_col = st.sidebar.columns(2)
    custom_start = cds_col.date_input("Data inicial:", value=_default_start, key='custom_start')
    custom_end = cde_col.date_input("Data final:", value=reference_date, key='custom_end')
    if custom_start > custom_end:
        st.sidebar.error("A data inicial não pode ser maior que a data final — invertendo.")
        custom_start, custom_end = custom_end, custom_start

filtro_dias = st.sidebar.radio("Dias de Operação:", [
    "Todos os dias", "Apenas Dias Úteis", "Apenas Fins de Semana/Feriados"
])

if filtro_dias == "Apenas Dias Úteis":
    df = df[df['is_dia_util'] == 1]
    df_invest = df_invest[df_invest['is_dia_util'] == 1]
elif filtro_dias == "Apenas Fins de Semana/Feriados":
    df = df[df['is_dia_util'] == 0]
    df_invest = df_invest[df_invest['is_dia_util'] == 0]

# --- UNIFIED DATE LOGIC ---
ref_datetime = pd.to_datetime(reference_date)

df_fcst = load_stored_forecast()

# Keep the forecast under the SAME "Dias de Operação" filter as the actuals, so
# the "Total Projetado" reconciliation and the accumulated chart compare like
# with like. Previously the forecast always included every day, which overstated
# projected totals whenever a weekday/weekend filter was active.
if not df_fcst.empty and filtro_dias != "Todos os dias":
    _cal_flags = df_cal[['data_ref', 'is_dia_util']].rename(columns={'data_ref': 'ds'})
    df_fcst = df_fcst.merge(_cal_flags, on='ds', how='left')
    # Future dates beyond dim_calendario: fall back to weekday (Sat/Sun = non-working).
    df_fcst['is_dia_util'] = df_fcst['is_dia_util'].fillna(
        (df_fcst['ds'].dt.dayofweek < 5).astype(int)
    )
    keep_flag = 1 if filtro_dias == "Apenas Dias Úteis" else 0
    df_fcst = df_fcst[df_fcst['is_dia_util'] == keep_flag].drop(columns=['is_dia_util'])

if view_option == "Semana Atual": proj_days = 7
elif view_option == "Mês Atual": proj_days = 30
elif view_option == "Ano Atual": proj_days = 365
elif view_option == "Última Semana": proj_days = 7
elif view_option == "Último Mês": proj_days = 30
elif view_option == "Selecionar Período": proj_days = (custom_end - custom_start).days + 1
else: proj_days = 365

if view_option == "Semana Atual":
    c_s = ref_datetime - pd.to_timedelta(ref_datetime.weekday(), unit='D')
    c_e = c_s + pd.DateOffset(days=6)
    p_s, p_e = c_s - pd.DateOffset(weeks=1), c_e - pd.DateOffset(weeks=1)
    l_s, l_e = c_s - pd.DateOffset(weeks=52), c_e - pd.DateOffset(weeks=52)
elif view_option == "Mês Atual":
    c_s = ref_datetime.replace(day=1)
    c_e = c_s + pd.DateOffset(months=1) - pd.DateOffset(days=1)
    p_s = c_s - pd.DateOffset(months=1)
    p_e = c_s - pd.DateOffset(days=1)
    l_s = c_s - pd.DateOffset(years=1)
    l_e = l_s + pd.DateOffset(months=1) - pd.DateOffset(days=1)
elif view_option == "Ano Atual":
    c_s = ref_datetime.replace(month=1, day=1)
    c_e = c_s + pd.DateOffset(years=1) - pd.DateOffset(days=1)
    p_s, p_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
    l_s, l_e = p_s, p_e 
elif view_option == "Última Semana":
    c_s = ref_datetime - pd.to_timedelta(ref_datetime.weekday(), unit='D') - pd.DateOffset(weeks=1)
    c_e = c_s + pd.DateOffset(days=6)
    p_s, p_e = c_s - pd.DateOffset(weeks=1), c_e - pd.DateOffset(weeks=1)
    l_s, l_e = c_s - pd.DateOffset(weeks=52), c_e - pd.DateOffset(weeks=52)
elif view_option == "Último Mês":
    c_s = ref_datetime.replace(day=1) - pd.DateOffset(months=1)
    c_e = ref_datetime.replace(day=1) - pd.DateOffset(days=1)
    p_s = c_s - pd.DateOffset(months=1)
    p_e = c_s - pd.DateOffset(days=1)
    l_s = c_s - pd.DateOffset(years=1)
    l_e = l_s + pd.DateOffset(months=1) - pd.DateOffset(days=1)
elif view_option == "Selecionar Período":
    c_s, c_e = pd.to_datetime(custom_start), pd.to_datetime(custom_end)
    _plen = (c_e - c_s).days + 1
    p_e = c_s - pd.DateOffset(days=1)
    p_s = p_e - pd.DateOffset(days=_plen - 1)
    l_s, l_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
else: 
    c_s, c_e = ref_datetime - pd.DateOffset(years=1) + pd.DateOffset(days=1), ref_datetime
    p_s, p_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
    l_s, l_e = c_s - pd.DateOffset(years=2), c_e - pd.DateOffset(years=2)

# For a custom range that ends in the past, cap the effective "today" used for the
# partial/elapsed split at the range end. No-op for the presets (there c_e >= today).
ref_datetime = min(ref_datetime, c_e)

days_elapsed = (ref_datetime - c_s).days
p_partial = min(p_s + pd.DateOffset(days=days_elapsed), p_e)
l_partial = min(l_s + pd.DateOffset(days=days_elapsed), l_e)

def get_period_stats(start_d, end_d_partial, end_d_full):
    total_days = (end_d_full - start_d).days + 1
    elapsed_days = (end_d_partial - start_d).days + 1
    wd_total = df_cal[(df_cal['data_ref'] >= start_d) & (df_cal['data_ref'] <= end_d_full)]['is_dia_util'].sum()
    wd_elapsed = df_cal[(df_cal['data_ref'] >= start_d) & (df_cal['data_ref'] <= end_d_partial)]['is_dia_util'].sum()
    return total_days, elapsed_days, wd_total, wd_elapsed

t_days_c, e_days_c, w_tot_c, w_ela_c = get_period_stats(c_s, ref_datetime, c_e)
t_days_p, e_days_p, w_tot_p, w_ela_p = get_period_stats(p_s, p_partial, p_e)
t_days_l, e_days_l, w_tot_l, w_ela_l = get_period_stats(l_s, l_partial, l_e)


# --- UI: TABS FOR ORGANIZATION ---
st.title("📊 Vendas Dashboard")
if not PROPHET_AVAILABLE:
    st.warning("⚠️ O pacote `prophet` não está instalado no ambiente. O modelo de previsão de Vendas baseado em IA não será executado.")

# ---- loaders compartilhados entre abas (definidos ANTES das abas para que 📞, 💰 e 🧲 leiam a mesma fonte) ----
_AQ_COLS = ['mes', 'secao', 'dim', 'metrica', 'valor', 'atualizado_em']


@st.cache_data(ttl=43200)
def _load_aq_raw():
    d = cquery("SELECT mes, secao, dim, metrica, valor, atualizado_em FROM alex_aq_dash_mes", ttl=0)
    d['mes'] = pd.to_datetime(d['mes'])
    d['valor'] = pd.to_numeric(d['valor'], errors='coerce')
    return d


def load_aq():
    try:
        return _load_aq_raw(), None
    except Exception as e:
        return pd.DataFrame(columns=_AQ_COLS), f"{type(e).__name__}: {str(e)[:400]}"


@st.cache_data(ttl=43200)
def _load_crm_cpa_raw():
    g = cquery("""SELECT report_date AS dia, ROUND(SUM(total_cost), 2) AS gasto_zenvia,
                         ROUND(SUM(CASE WHEN status IN ('Enviada','Entregue','Lida')
                                        THEN total_messages ELSE 0 END) * 0.32, 2) AS gasto_bd
                  FROM alex_zenvia_template_status
                  WHERE UPPER(template_name) LIKE '%%GT7%%'
                  GROUP BY 1""", ttl=0)
    v = cquery("""SELECT date AS dia, SUM(event_count) AS vendas_ga,
                         SUM(CASE WHEN session_campaign_name LIKE '%%crm%%' THEN event_count ELSE 0 END) AS vendas_crm
                  FROM alex_crm_wpp_sms_vendas GROUP BY 1""", ttl=0)
    l = cquery("SELECT date AS dia, SUM(event_count) AS leads FROM alex_crm_wpp_sms_leads GROUP BY 1", ttl=0)
    d = g.merge(v, on='dia', how='outer').merge(l, on='dia', how='outer')
    d = d.fillna(0)
    d['dia'] = pd.to_datetime(d['dia'])
    return d.sort_values('dia')


def load_crm_cpa():
    try:
        return _load_crm_cpa_raw(), None
    except Exception as e:
        return pd.DataFrame(columns=['dia', 'gasto', 'vendas', 'leads', 'gasto_bd', 'gasto_zenvia', 'vendas_ga', 'vendas_bd']), f"{type(e).__name__}: {str(e)[:300]}"


_FUNIL_COLS = ['dia', 'canal', 'gt7', 'enviadas', 'entregues', 'lidas', 'nao_disparadas', 'custo']


@st.cache_data(ttl=43200)
def _load_crm_funil_raw():
    """Funil de entrega dos disparos (R28, 15/09): dia × canal × escopo a partir de alex_zenvia_template_status.
    Cada mensagem aparece UMA vez, no status final — por isso o funil é cumulativo:
      enviadas  = Enviada(2) + Entregue(3) + Lida(4) + Não Entregue(6)   (saíram da plataforma)
      entregues = Entregue(3) + Lida(4)                                  (Lida implica entrega)
      lidas     = Lida(4)                                                (só WhatsApp tem leitura)
      nao_disparadas = Pendente(1) + Erro(5) + Descadastrados(8)         (não saíram; custo zero)
    canal pelo NOME do template: 'SMS' no nome → SMS, o resto → WhatsApp. No sender_name o SMS só aparece em rótulos
    compostos ('SMS | CDT Relacionamento - 9713' — sender_id compartilhado), e todo template SMS tem zero Lida,
    o que valida a regra. gt7 = 1 quando o nome contém 'GT7' (Instância Aquisição — mesmo recorte do CPA acima)."""
    d = cquery("""SELECT report_date AS dia,
                         CASE WHEN template_name LIKE '%%SMS%%' THEN 'SMS' ELSE 'WhatsApp' END AS canal,
                         CASE WHEN UPPER(template_name) LIKE '%%GT7%%' THEN 1 ELSE 0 END AS gt7,
                         SUM(CASE WHEN status_code IN (2, 3, 4, 6) THEN total_messages ELSE 0 END) AS enviadas,
                         SUM(CASE WHEN status_code IN (3, 4) THEN total_messages ELSE 0 END) AS entregues,
                         SUM(CASE WHEN status_code = 4 THEN total_messages ELSE 0 END) AS lidas,
                         SUM(CASE WHEN status_code IN (1, 5, 8) THEN total_messages ELSE 0 END) AS nao_disparadas,
                         SUM(total_cost) AS custo
                  FROM alex_zenvia_template_status
                  GROUP BY 1, 2, 3""", ttl=0)
    for c in ['enviadas', 'entregues', 'lidas', 'nao_disparadas', 'custo']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0).astype(float)
    d['gt7'] = pd.to_numeric(d['gt7'], errors='coerce').fillna(0).astype(int)
    d['canal'] = d['canal'].astype(str)
    d['dia'] = pd.to_datetime(d['dia'])
    return d.sort_values('dia')


def load_crm_funil():
    try:
        return _load_crm_funil_raw(), None
    except Exception as e:
        return pd.DataFrame(columns=_FUNIL_COLS), f"{type(e).__name__}: {str(e)[:300]}"


tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab10, tab11 = st.tabs(["📈 Desempenho de Vendas", "🗺️ Mapa Regional (UF)", "💰 Investimento", "📣 Campanhas", "🌐 Site", "📞 Televendas", "📱 App", "📨 CRM", "🧲 Aquisição", "🧭 Funil Ponta a Ponta"])

# =====================================================================
# TAB 1: DESEMPENHO DE VENDAS
# =====================================================================
with tab1:
    st.header("Visão Integrada de Vendas")
    st.info(f"**Status do Período ({view_option}):** Decorridos **{e_days_c} de {t_days_c} dias** no calendário. | **Dias Úteis Decorridos:** Atual: {w_ela_c} | Anterior: {w_ela_p} | Ano Passado: {w_ela_l}")

    df_slice_c = df[(df['data_venda'] >= c_s) & (df['data_venda'] <= ref_datetime)]
    df_slice_pp = df[(df['data_venda'] >= p_s) & (df['data_venda'] <= p_partial)]
    df_slice_pf = df[(df['data_venda'] >= p_s) & (df['data_venda'] <= p_e)]
    df_slice_lp = df[(df['data_venda'] >= l_s) & (df['data_venda'] <= l_partial)]
    df_slice_lf = df[(df['data_venda'] >= l_s) & (df['data_venda'] <= l_e)]

    agg_c = get_agg_sums(df_slice_c)
    agg_pp = get_agg_sums(df_slice_pp)
    agg_pf = get_agg_sums(df_slice_pf)
    agg_lp = get_agg_sums(df_slice_lp)
    agg_lf = get_agg_sums(df_slice_lf)
    
    ch_c = get_channel_sums(df_slice_c)
    ch_pp = get_channel_sums(df_slice_pp)
    ch_pf = get_channel_sums(df_slice_pf)
    ch_lp = get_channel_sums(df_slice_lp)
    ch_lf = get_channel_sums(df_slice_lf)

    # Dynamic Sales Goal Progress Bar
    goal_vendas = get_prorated_goal(df_goals, c_s, ref_datetime, 'CDT (Total)')
    pct_goal = agg_c['CDT'] / goal_vendas if goal_vendas > 0 else 0
    st.markdown(f"🎯 **Progresso da Meta de Vendas (CDT):** {format_br(agg_c['CDT'])} / {format_br(goal_vendas)} atingidos (**{pct_goal*100:.1f}%**)")
    st.progress(min(max(pct_goal, 0.0), 1.0))
    st.divider()

    st.subheader("Análise Detalhada por Canal")
    
    # Per-group expand toggles — click a group to reveal/hide its channels in the table below.
    # st.button triggers a soft rerun (session_state survives), so the toggle takes effect on
    # this same run and the row loop below rebuilds with the updated set — no page reload, so
    # the sidebar period, filters and every other widget keep their state.
    sales_expanded = st.session_state.setdefault('sales_expanded', set())
    _sales_groups = ['Digital', 'Franquias', 'Outros', 'Nacional', 'CDT']
    st.caption("Clique num grupo para expandir/recolher seus canais:")
    _exp_cols = st.columns(len(_sales_groups))
    for _i, _g in enumerate(_sales_groups):
        _lbl_g = "CDT (Total)" if _g == 'CDT' else _g
        _icon = "▾" if _g in sales_expanded else "▸"
        if _exp_cols[_i].button(f"{_icon} {_lbl_g}", key=f"sales_exp_{_g}", use_container_width=True):
            sales_expanded.symmetric_difference_update({_g})

    if not df_fcst.empty:
        mostrar_previsao = st.checkbox("Incluir Projeção de Vendas (Tabela)")
        if 'generated_at' in df_fcst.columns and df_fcst['generated_at'].notna().any():
            _fc_when = pd.to_datetime(df_fcst['generated_at']).max()
            st.caption(f"📦 Previsão pré-calculada (cenário *balanced*), gerada em {_fc_when:%d/%m/%Y %H:%M}.")
        if mostrar_previsao:
            horizonte_previsao_tabela = st.radio("Horizonte da Previsão (Tabela):", ["Fim do Período Atual", f"Próximos {proj_days} Dias"], horizontal=True, key="horiz_tabela")
    else:
        mostrar_previsao = False

    if mostrar_previsao and not df_fcst.empty:
        if horizonte_previsao_tabela == "Fim do Período Atual" and c_e > ref_datetime:
            fcst_end_date = c_e
        else:
            # Period already finished -> project proj_days forward instead of an empty window.
            fcst_end_date = ref_datetime + pd.DateOffset(days=proj_days)
            
        df_f_slice = df_fcst[(df_fcst['scenario'] == 'balanced') & 
                             (df_fcst['ds'] > ref_datetime) & 
                             (df_fcst['ds'] <= fcst_end_date)]
        agg_fcst_faltante = get_fcst_agg_sums(df_f_slice)
    else:
        agg_fcst_faltante = {g: 0 for g in group_map.keys()}

    rows = []
    for grupo in ['Digital', 'Franquias', 'Outros', 'Nacional', 'CDT']:
        nome_exibicao = "CDT (Total)" if grupo == 'CDT' else grupo

        meta_parc = get_goal_for_group(c_s, ref_datetime, grupo)
        meta_tot = get_goal_for_group(c_s, c_e, grupo)

        row_dict = {
            'Grupo': nome_exibicao,
            '_level': 0,
            '_is_eff': False,
            'Atual': format_br(agg_c[grupo]),
            'Meta (Parcial)': fmt_goal(agg_c[grupo], meta_parc),
            'Meta (Total)': fmt_goal(agg_c[grupo], meta_tot),
            'vs Anterior (Parcial)': fmt_val_delta(agg_c[grupo], agg_pp[grupo]),
            'vs Anterior (Total)': fmt_val_delta(agg_c[grupo], agg_pf[grupo]),
            'vs Ano Passado (Parcial)': fmt_val_delta(agg_c[grupo], agg_lp[grupo]),
            'vs Ano Passado (Total)': fmt_val_delta(agg_c[grupo], agg_lf[grupo]),
        }
        if mostrar_previsao:
            falt_val = agg_fcst_faltante[grupo]
            row_dict['Previsão (Faltante)'] = format_br(falt_val)
            row_dict['Previsão (Total Projetado)'] = format_br(agg_c[grupo] + falt_val)
        rows.append(row_dict)
        
        if grupo in sales_expanded:
            for ch in group_map[grupo]:
                v_c, v_pp, v_pf, v_lp, v_lf = ch_c.get(ch, 0), ch_pp.get(ch, 0), ch_pf.get(ch, 0), ch_lp.get(ch, 0), ch_lf.get(ch, 0)
                
                v_f_faltante = 0
                if mostrar_previsao:
                    parent_c = agg_c[grupo]
                    if parent_c > 0:
                        v_f_faltante = (v_c / parent_c) * agg_fcst_faltante[grupo]
                        
                if v_c == 0 and v_pp == 0 and v_pf == 0 and v_lp == 0 and v_lf == 0 and v_f_faltante == 0: continue 
                
                ch_m_parc = get_goal_for_group(c_s, ref_datetime, ch.title())
                ch_m_tot = get_goal_for_group(c_s, c_e, ch.title())
                
                ch_dict = {
                    'Grupo': ch.title(),
                    '_level': 1,
                    '_is_eff': False,
                    'Atual': format_br(v_c),
                    'Meta (Parcial)': fmt_goal(v_c, ch_m_parc),
                    'Meta (Total)': fmt_goal(v_c, ch_m_tot),
                    'vs Anterior (Parcial)': fmt_val_delta(v_c, v_pp),
                    'vs Anterior (Total)': fmt_val_delta(v_c, v_pf),
                    'vs Ano Passado (Parcial)': fmt_val_delta(v_c, v_lp),
                    'vs Ano Passado (Total)': fmt_val_delta(v_c, v_lf),
                }
                if mostrar_previsao:
                    ch_dict['Previsão (Faltante)'] = format_br(v_f_faltante)
                    ch_dict['Previsão (Total Projetado)'] = format_br(v_c + v_f_faltante)
                rows.append(ch_dict)
                
    display_cols = ['Grupo', 'Atual', 'Meta (Parcial)', 'Meta (Total)', 'vs Anterior (Parcial)', 'vs Anterior (Total)']
    if view_option != "Ano Atual":
        display_cols.extend(['vs Ano Passado (Parcial)', 'vs Ano Passado (Total)'])
    if mostrar_previsao:
        display_cols.extend(['Previsão (Faltante)', 'Previsão (Total Projetado)'])

    st.markdown(render_metric_table(rows, display_cols), unsafe_allow_html=True)

    col_pie, col_trend = st.columns([1, 2])
    
    with col_pie:
        st.markdown("**Representatividade**")
        tipo_visao_pizza = st.radio("Nível de Visualização:", ["Grupos (Exclusivos CDT)", "Canais Específicos"], horizontal=True, key='pie_rad')
        
        if tipo_visao_pizza == "Grupos (Exclusivos CDT)":
            v_dig = df_slice_c[df_slice_c['tipo_venda'].str.lower().isin(dig_list)]['Vendas'].sum()
            v_tv = df_slice_c[df_slice_c['tipo_venda'].str.lower().isin(tv_list)]['Vendas'].sum()
            v_out = df_slice_c[df_slice_c['tipo_venda'].str.lower().isin(out_list)]['Vendas'].sum()
            v_fra = df_slice_c[df_slice_c['tipo_venda'].str.lower().isin(fra_list)]['Vendas'].sum()
            sum_known = v_dig + v_tv + v_out + v_fra
            v_rest = max(0, df_slice_c['Vendas'].sum() - sum_known)
            
            pie_data = [
                {'Categoria': 'Digital', 'Vendas': v_dig},
                {'Categoria': 'Televendas', 'Vendas': v_tv},
                {'Categoria': 'Outros', 'Vendas': v_out},
                {'Categoria': 'Franquias', 'Vendas': v_fra}
            ]
            if v_rest > 0: pie_data.append({'Categoria': 'Restante', 'Vendas': v_rest})
            df_pie = pd.DataFrame(pie_data)
        else:
            df_pie = df_slice_c.groupby('tipo_venda')['Vendas'].sum().reset_index()
            df_pie.rename(columns={'tipo_venda': 'Categoria'}, inplace=True)
            
        df_pie = df_pie[df_pie['Vendas'] > 0]
        
        if not df_pie.empty:
            fig_pie = px.pie(df_pie, names='Categoria', values='Vendas', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label', hovertemplate="<b>%{label}</b><br>Vendas: %{value}<extra></extra>")
            fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_pie, use_container_width=True, key='pie_chart_t1')
        else:
            st.info("Sem dados para o gráfico de pizza.")
            
    with col_trend:
        st.markdown("**Tendência Diária / Acumulada**")
        
        col_gt1, col_gt2, col_gt3 = st.columns(3)
        tipo_visao_tend = col_gt1.radio("Nível de Visualização:", ["Grupos de Canais", "Canais Específicos"], horizontal=True, key='tend_rad')
        tipo_graf_tend = col_gt2.radio("Soma do Gráfico:", ["Por Período", "Acumulado"], horizontal=True)
        escala_tend = col_gt3.radio("Escala:", ["Diário", "Semanal", "Mensal"], horizontal=True, key='t1_scale')
        
        if tipo_visao_tend == "Grupos de Canais":
            canais_grafico = st.multiselect("Selecione os Grupos:", options=['Digital', 'Franquias', 'Outros', 'Nacional', 'CDT'], default=['CDT'], key='t1_grp_sel')
        else:
            opcoes_ch_raw = sorted([str(c).title() for c in df_slice_c['tipo_venda'].unique()])
            canais_grafico = st.multiselect("Selecione os Canais:", options=opcoes_ch_raw, default=opcoes_ch_raw[:3] if opcoes_ch_raw else [], key='t1_can_sel')
            
        col_g1, col_g2, col_g3 = st.columns(3)
        show_prev = col_g1.checkbox("Comparar c/ Anterior")
        show_last_yr = col_g2.checkbox("Comparar c/ Ano Passado")
        
        if not df_fcst.empty:
            show_forecast_chart = col_g3.checkbox("Mostrar Previsão no Gráfico")
            if show_forecast_chart:
                horizonte_grafico = st.radio("Horizonte da Previsão (Gráfico):", ["Fim do Período Atual", f"Próximos {proj_days} Dias"], horizontal=True, key="horiz_grafico")
        else:
            show_forecast_chart = False

        show_metas = False
        if not df_goals.empty:
            show_metas = st.checkbox(
                "🎯 Mostrar Metas (Parcial + Total)", value=False, key='t1_show_metas',
                help="Linha tracejada da meta por grupo selecionado: o ponto final é a meta TOTAL "
                     "do período e onde a linha está 'hoje' é a meta PARCIAL (proporcional aos dias "
                     "decorridos). Use junto com 'Mostrar Previsão' para ver se a projeção termina "
                     "acima ou abaixo da meta total, e se as vendas atuais já alcançaram a meta parcial."
            )

        def get_trend_data(t_start, t_end, label_suffix, max_actual_date=None, is_forecast_src=False):
            if is_forecast_src:
                if df_fcst.empty or not max_actual_date: return pd.DataFrame()
                
                if horizonte_grafico == "Fim do Período Atual" and c_e > max_actual_date:
                    fcst_end_d = c_e
                else:
                    # "Fim do Período Atual" on an already-finished period has no future days
                    # (the window would be empty and the line would silently vanish), so
                    # project proj_days forward instead. Keeps the chart forecast independent
                    # of the table forecast and always visible when toggled.
                    fcst_end_d = max_actual_date + pd.DateOffset(days=proj_days)
                
                df_t = df_fcst[(df_fcst['scenario'] == 'balanced') & 
                               (df_fcst['ds'] > max_actual_date) & 
                               (df_fcst['ds'] <= fcst_end_d)].copy()
                df_t.rename(columns={'channel_group': 'tipo_venda', 'yhat': 'Vendas', 'ds': 'data_venda'}, inplace=True)
            else:
                end_bound = min(t_end, max_actual_date) if max_actual_date else t_end
                df_t = df[(df['data_venda'] >= t_start) & (df['data_venda'] <= end_bound)]
            
            if df_t.empty: return pd.DataFrame()
            
            res_dfs = []
            
            if tipo_visao_tend == "Grupos de Canais":
                if 'CDT' in canais_grafico:
                    d = df_t.groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'CDT'
                    res_dfs.append(d)
                if 'Nacional' in canais_grafico:
                    d = df_t[df_t['tipo_venda'].str.title().isin(['Website', 'App Do Filiado', 'Televendas', 'Mgm', 'Outros'])].groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'Nacional'
                    res_dfs.append(d)
                if 'Franquias' in canais_grafico:
                    d = df_t[df_t['tipo_venda'].str.title() == 'Franquias'].groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'Franquias'
                    res_dfs.append(d)
                if 'Digital' in canais_grafico:
                    d = df_t[df_t['tipo_venda'].str.title().isin(['Website', 'App Do Filiado'])].groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'Digital'
                    res_dfs.append(d)
                if 'Outros' in canais_grafico:
                    d = df_t[df_t['tipo_venda'].str.title().isin(['Mgm', 'Outros'])].groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'Outros'
                    res_dfs.append(d)
            else:
                for ch in canais_grafico:
                    if is_forecast_src:
                        p_parent = prophet_map.get(ch.lower(), 'Outros')
                        df_hist = df[(df['data_venda'] >= c_s) & (df['data_venda'] <= ref_datetime)]
                        child_sum = df_hist[df_hist['tipo_venda'].str.lower() == ch.lower()]['Vendas'].sum()
                        parent_children = [k for k, v in prophet_map.items() if v == p_parent]
                        parent_sum = df_hist[df_hist['tipo_venda'].str.lower().isin(parent_children)]['Vendas'].sum()
                        
                        share = child_sum / parent_sum if parent_sum > 0 else 0
                        
                        d = df_t[df_t['tipo_venda'].str.title() == p_parent.title()].copy()
                        if not d.empty and share > 0:
                            d = d.groupby('data_venda')['Vendas'].sum().reset_index()
                            d['Vendas'] = d['Vendas'] * share
                            d['Grupo'] = ch.title()
                            res_dfs.append(d)
                    else:
                        d = df_t[df_t['tipo_venda'].str.title() == ch.title()].copy()
                        if not d.empty:
                            d = d.groupby(['data_venda', 'tipo_venda'])['Vendas'].sum().reset_index()
                            d.rename(columns={'tipo_venda': 'Grupo'}, inplace=True)
                            d['Grupo'] = d['Grupo'].str.title()
                            res_dfs.append(d)

            if not res_dfs: return pd.DataFrame()
            
            res = pd.concat(res_dfs).reset_index(drop=True)
            res['Dia'] = (res['data_venda'] - t_start).dt.days + 1
            res['Traço'] = res['Grupo'] + label_suffix
            res['Data_Real'] = res['data_venda']
            res = res.sort_values(['Grupo', 'Dia']).reset_index(drop=True)
            
            return res

        def bucketize_trend(dfx, anchor):
            """Reagrupa as linhas diárias do gráfico em baldes de calendário
            (semana iniciando na SEGUNDA, ou mês civil), preservando o eixo
            ordinal do período: o balde nº 1 é o primeiro balde do período de
            CADA traço, então Anterior / Ano Passado / Previsão / Meta seguem
            sobrepostos. Baldes cortados (início/fim do período ou dados até
            ontem) recebem o sufixo '(parcial)' no hover."""
            if escala_tend == "Diário" or dfx.empty:
                return dfx
            b = dfx.copy()
            anchor = pd.Timestamp(anchor)
            if escala_tend == "Semanal":
                b['_bucket'] = b['Data_Real'] - pd.to_timedelta(b['Data_Real'].dt.weekday, unit='D')
                anchor_b = anchor - pd.Timedelta(days=int(anchor.weekday()))
            else:  # Mensal
                b['_bucket'] = b['Data_Real'].dt.to_period('M').dt.to_timestamp()
                anchor_b = anchor.to_period('M').to_timestamp()
            g = (b.groupby(['Traço', 'Grupo', '_bucket'], as_index=False)
                   .agg(Vendas=('Vendas', 'sum'), _ndias=('Data_Real', 'nunique')))
            if escala_tend == "Semanal":
                g['Dia'] = ((g['_bucket'] - anchor_b).dt.days // 7) + 1
                g['_esperado'] = 7
                g['Data_Str'] = "Sem. de " + g['_bucket'].dt.strftime('%d/%m/%Y')
            else:
                g['Dia'] = ((g['_bucket'].dt.year - anchor_b.year) * 12
                            + (g['_bucket'].dt.month - anchor_b.month)) + 1
                g['_esperado'] = g['_bucket'].dt.days_in_month
                g['Data_Str'] = g['_bucket'].dt.strftime('%m/%Y')
            g.loc[g['_ndias'] < g['_esperado'], 'Data_Str'] += " (parcial)"
            g['Data_Real'] = g['_bucket']
            g['data_venda'] = g['_bucket']
            g = g.sort_values(['Traço', 'Dia']).reset_index(drop=True)
            return g[['data_venda', 'Grupo', 'Vendas', 'Dia', 'Traço', 'Data_Real', 'Data_Str']]

        df_main = get_trend_data(c_s, c_e, "", max_actual_date=ref_datetime)
        plot_dfs = [bucketize_trend(df_main, c_s)] if not df_main.empty else []
        
        if show_prev:
            df_prev_plot = get_trend_data(p_s, p_e, " (Anterior)")
            if not df_prev_plot.empty: plot_dfs.append(bucketize_trend(df_prev_plot, p_s))
            
        if show_last_yr and view_option != "Ano Atual":
            df_last_plot = get_trend_data(l_s, l_e, " (Ano Passado)")
            if not df_last_plot.empty: plot_dfs.append(bucketize_trend(df_last_plot, l_s))
            
        if show_forecast_chart:
            df_fcst_plot = get_trend_data(c_s, c_e, " (Previsão)", max_actual_date=ref_datetime, is_forecast_src=True)
            if not df_fcst_plot.empty:
                if escala_tend == "Diário" and not df_main.empty:
                    last_points = []
                    for g in df_fcst_plot['Grupo'].unique():
                        g_main = df_main[df_main['Grupo'] == g]
                        if not g_main.empty:
                            last_row = g_main.iloc[-1].copy()
                            last_row['Traço'] = last_row['Grupo'] + " (Previsão)"
                            last_points.append(pd.DataFrame([last_row]))
                    if last_points:
                        df_fcst_plot = pd.concat(last_points + [df_fcst_plot], ignore_index=True).sort_values(['Grupo', 'Dia']).reset_index(drop=True)
                plot_dfs.append(bucketize_trend(df_fcst_plot, c_s))

        if plot_dfs:
            df_plot_trend = pd.concat(plot_dfs).reset_index(drop=True)
            
            if tipo_graf_tend == "Acumulado":
                last_hist_map = {}
                first_fcst_val_map = {}
                
                if not df_main.empty:
                    for g in df_main['Grupo'].unique():
                        g_m = df_main[df_main['Grupo'] == g]
                        # We are already inside the "Acumulado" branch, so this is
                        # always the period sum (the prior ternary's other arm was dead).
                        last_hist_map[g] = g_m['Vendas'].sum()
                
                df_plot_trend['Vendas'] = df_plot_trend.groupby('Traço')['Vendas'].cumsum()
                
                if show_forecast_chart and not df_fcst_plot.empty:
                    for g in df_fcst_plot['Grupo'].unique():
                        trace_name = g + " (Previsão)"
                        mask = df_plot_trend['Traço'] == trace_name
                        if mask.any():
                            first_fcst_val_map[g] = (df_plot_trend.loc[mask, 'Vendas'].iloc[0]
                                                     if escala_tend == "Diário" else 0.0)
                
                def boost_fcst(row):
                    if "(Previsão)" in row['Traço']:
                        g = row['Grupo']
                        return row['Vendas'] - first_fcst_val_map.get(g, 0) + last_hist_map.get(g, 0)
                    return row['Vendas']
                    
                df_plot_trend['Vendas'] = df_plot_trend.apply(boost_fcst, axis=1)

            # Target overlays (parcial + total). Added AFTER the cumulative/boost
            # transform above so the goal line is never double-accumulated.
            if show_metas:
                cumulative_mode = (tipo_graf_tend == "Acumulado")
                if escala_tend == "Diário":
                    meta_dfs = [build_goal_trend(g, c_s, c_e, cumulative_mode) for g in canais_grafico]
                else:
                    meta_dfs = []
                    for g in canais_grafico:
                        m = build_goal_trend(g, c_s, c_e, False)
                        if m.empty:
                            continue
                        m = bucketize_trend(m, c_s)
                        if cumulative_mode:
                            m['Vendas'] = m.groupby('Traço')['Vendas'].cumsum()
                        meta_dfs.append(m)
                meta_dfs = [m for m in meta_dfs if not m.empty]
                if meta_dfs:
                    df_plot_trend = pd.concat([df_plot_trend] + meta_dfs, ignore_index=True)

            df_plot_trend['Formatado'] = df_plot_trend['Vendas'].apply(format_br)
            if escala_tend == "Diário":
                df_plot_trend['Data_Str'] = df_plot_trend['Data_Real'].dt.strftime('%d/%m/%Y')
            
            fig_trend = px.line(df_plot_trend, x='Dia', y='Vendas', color='Traço', markers=True,
                                custom_data=['Formatado', 'Data_Str'])
            
            for trace in fig_trend.data:
                if "(Anterior)" in trace.name or "(Ano Passado)" in trace.name:
                    trace.line.dash = 'dash'
                    trace.opacity = 0.5
                elif "(Previsão)" in trace.name:
                    trace.line.dash = 'dot'
                elif "(Meta)" in trace.name:
                    trace.line.dash = 'longdash'
                    trace.line.width = 3
                    trace.mode = 'lines'
                    
            _hover_lbl = "Data Original" if escala_tend == "Diário" else "Período"
            fig_trend.update_traces(hovertemplate="<b>" + _hover_lbl + ": %{customdata[1]}</b><br>Vendas: %{customdata[0]}<extra></extra>")
            _eixo_x = {"Diário": "Dias Decorridos", "Semanal": "Semanas do Período",
                       "Mensal": "Meses do Período"}[escala_tend]
            fig_trend.update_layout(margin=dict(t=10, b=0, l=0, r=0), xaxis_title=_eixo_x, yaxis_title=f"Vendas ({tipo_graf_tend})")
            if escala_tend != "Diário":
                fig_trend.update_xaxes(dtick=1)

            # On-chart value annotations for a single selected group: current sales
            # (actual, at "today"), predicted sales (forecast, at the horizon end) and the
            # target. Works in BOTH Acumulado and Diário; single-group-only to stay readable.
            if show_metas and len(canais_grafico) == 1:
                is_cum = (tipo_graf_tend == "Acumulado")
                _tr = df_plot_trend['Traço'].astype(str)
                _act = df_plot_trend[~_tr.str.contains("(", regex=False)]          # actual (no suffix)
                _fc = df_plot_trend[_tr.str.endswith(" (Previsão)")]               # forecast
                _mt = df_plot_trend[_tr.str.endswith(" (Meta)")]                   # target line
                C_ACT, C_FC, C_META = "#1f5fbf", "#5b9bd5", "#d62728"

                if not _act.empty:
                    r_a = _act.loc[_act['Dia'].idxmax()]
                    fig_trend.add_annotation(x=r_a['Dia'], y=r_a['Vendas'],
                                             text=f"Vendas hoje: {format_br(r_a['Vendas'])}",
                                             showarrow=True, arrowhead=2, ax=0, ay=32,
                                             font=dict(color=C_ACT, size=11),
                                             bordercolor=C_ACT, borderwidth=1, bgcolor="rgba(255,255,255,0.9)")
                if not _fc.empty:
                    r_f = _fc.loc[_fc['Dia'].idxmax()]
                    _lbl = "Previsão fim" if is_cum else "Previsão"
                    fig_trend.add_annotation(x=r_f['Dia'], y=r_f['Vendas'],
                                             text=f"{_lbl}: {format_br(r_f['Vendas'])}",
                                             showarrow=True, arrowhead=2, ax=0, ay=32,
                                             font=dict(color=C_FC, size=11),
                                             bordercolor=C_FC, borderwidth=1, bgcolor="rgba(255,255,255,0.9)")
                if is_cum:
                    g_ann = canais_grafico[0]
                    mp_ann = get_goal_for_group(c_s, ref_datetime, g_ann)
                    mt_ann = get_goal_for_group(c_s, c_e, g_ann)
                    def _ord_eixo(ts):
                        ts = pd.Timestamp(ts)
                        if escala_tend == "Semanal":
                            _a = pd.Timestamp(c_s) - pd.Timedelta(days=int(pd.Timestamp(c_s).weekday()))
                            _t = ts - pd.Timedelta(days=int(ts.weekday()))
                            return (_t - _a).days // 7 + 1
                        if escala_tend == "Mensal":
                            return (ts.year - c_s.year) * 12 + (ts.month - c_s.month) + 1
                        return (ts - c_s).days + 1
                    x_now = _ord_eixo(ref_datetime)
                    x_end = _ord_eixo(c_e)
                    if mp_ann > 0:
                        fig_trend.add_annotation(x=x_now, y=mp_ann, text=f"Meta hoje: {format_br(mp_ann)}",
                                                 showarrow=True, arrowhead=2, ax=0, ay=-35,
                                                 font=dict(color=C_META, size=11),
                                                 bordercolor=C_META, borderwidth=1, bgcolor="rgba(255,255,255,0.9)")
                    if mt_ann > 0:
                        fig_trend.add_annotation(x=x_end, y=mt_ann, text=f"Meta total: {format_br(mt_ann)}",
                                                 showarrow=True, arrowhead=2, ax=0, ay=-35,
                                                 font=dict(color=C_META, size=11),
                                                 bordercolor=C_META, borderwidth=1, bgcolor="rgba(255,255,255,0.9)")
                elif not _mt.empty:
                    r_m = _mt.loc[_mt['Dia'].idxmax()]
                    fig_trend.add_annotation(x=r_m['Dia'], y=r_m['Vendas'],
                                             text=f"Meta/dia: {format_br(r_m['Vendas'])}",
                                             showarrow=True, arrowhead=2, ax=0, ay=-32,
                                             font=dict(color=C_META, size=11),
                                             bordercolor=C_META, borderwidth=1, bgcolor="rgba(255,255,255,0.9)")

            # Goal summary — moved ABOVE the chart (previously sat below it).
            if show_metas:
                meta_txt = []
                for g in canais_grafico:
                    mp = get_goal_for_group(c_s, ref_datetime, g)
                    mt = get_goal_for_group(c_s, c_e, g)
                    if mt > 0:
                        meta_txt.append(f"**{g}** — parcial: {format_br(mp)} · total: {format_br(mt)}")
                if meta_txt:
                    st.markdown("🎯 **Metas do período** → " + "  |  ".join(meta_txt))

            st.plotly_chart(fig_trend, use_container_width=True, key='trend_chart_t1')
            if escala_tend != "Diário":
                st.caption("Semanas iniciam na segunda-feira. Baldes '(parcial)' não cobrem a "
                           "semana/mês inteiro (início ou fim do período, ou dados até ontem).")
        else:
            st.info("Sem dados para o gráfico de tendência.")

    # ---------------------------------------------------------------------
    # 📅 CALENDÁRIO DE VENDAS DO MÊS (R5, 26/08) — grade mensal seg→dom.
    # Independe do período da barra lateral (tem seletor de mês próprio), mas
    # respeita "Dias de Operação" porque lê o mesmo df / df_fcst filtrados.
    # Projeção do mês = realizado + previsão Prophet (balanced) dos dias que
    # faltam; sem previsão, ritmo médio diário. "Esperado até hoje" = projeção
    # distribuída LINEARMENTE pelos dias de operação do mês, até o último dia
    # com vendas registradas.
    # ---------------------------------------------------------------------
    st.divider()
    st.subheader("📅 Calendário de Vendas do Mês")

    _CAL_MESES_PT = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    _CAL_WD = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
    _cal_hoje = pd.Timestamp(reference_date)   # último dia completo na base (não depende do período)
    _CAL_GRUPOS = {'CDT (Total)': None, 'Nacional': nac_list, 'Digital': dig_list,
                   'Franquias': fra_list, 'Outros': out_list}
    _CAL_GRUPOS_FCST = {'CDT (Total)': None,
                        'Nacional': ['Website', 'App Do Filiado', 'Mgm', 'Outros', 'Televendas'],
                        'Digital': ['Website', 'App Do Filiado'],
                        'Franquias': ['Franquias'],
                        'Outros': ['Mgm', 'Outros']}

    def _cal_lbl_mes(ts):
        ts = pd.Timestamp(ts)
        return f"{_CAL_MESES_PT[ts.month - 1]}/{ts.year}"

    def _cal_filtra(dfx, sel):
        if sel in _CAL_GRUPOS:
            lst = _CAL_GRUPOS[sel]
            return dfx if lst is None else dfx[dfx['tipo_venda'].str.lower().isin(lst)]
        return dfx[dfx['tipo_venda'].str.lower() == sel.lower()]

    def _cal_fcst_serie(sel, d_ini_excl, d_fim):
        """Previsão Prophet (balanced) por dia para a seleção, em (d_ini_excl, d_fim]. Um canal específico
        recebe a fatia do seu grupo Prophet proporcional aos últimos 90 dias (mesma regra do gráfico)."""
        if df_fcst.empty:
            return pd.Series(dtype=float)
        f = df_fcst[(df_fcst['scenario'] == 'balanced') & (df_fcst['ds'] > d_ini_excl) & (df_fcst['ds'] <= d_fim)]
        if f.empty:
            return pd.Series(dtype=float)
        cg = f['channel_group'].str.title()
        if sel in _CAL_GRUPOS_FCST:
            lst = _CAL_GRUPOS_FCST[sel]
            f = f if lst is None else f[cg.isin(lst)]
            return f.groupby('ds')['yhat'].sum()
        p_parent = prophet_map.get(sel.lower())
        if p_parent is None:
            return pd.Series(dtype=float)
        hist = df[(df['data_venda'] > d_ini_excl - pd.Timedelta(days=90)) & (df['data_venda'] <= d_ini_excl)]
        child = hist[hist['tipo_venda'].str.lower() == sel.lower()]['Vendas'].sum()
        irmaos = [k for k, v in prophet_map.items() if v == p_parent]
        parent = hist[hist['tipo_venda'].str.lower().isin(irmaos)]['Vendas'].sum()
        share = (child / parent) if parent > 0 else 0.0
        return f[cg == p_parent.title()].groupby('ds')['yhat'].sum() * share

    def _cal_medias_semana(sel, m_start):
        """Média de vendas por dia da semana nas janelas de 12 e 3 meses ANTERIORES ao mês exibido (o mês em
        si fica fora). Denominador = dias com dados na base (respeita Dias de Operação)."""
        out = {}
        for lbl, n_m in (('12m', 12), ('3m', 3)):
            w0, w1 = m_start - pd.DateOffset(months=n_m), m_start - pd.Timedelta(days=1)
            base = df[(df['data_venda'] >= w0) & (df['data_venda'] <= w1)]
            n_dias = base.groupby(base['data_venda'].dt.weekday)['data_venda'].nunique()
            s = _cal_filtra(base, sel)
            tot = s.groupby(s['data_venda'].dt.weekday)['Vendas'].sum()
            out[lbl] = {wd: (float(tot.get(wd, 0.0)) / int(n_dias.get(wd, 0))) if int(n_dias.get(wd, 0)) > 0 else None
                        for wd in range(7)}
        return out

    def _cal_card(col, label, value, sub, accent="#166534"):
        col.markdown(
            f"<div style='border:1px solid #e2e8f0;border-left:4px solid {accent};border-radius:10px;"
            f"padding:9px 12px;background:#fff;'>"
            f"<div style='font-size:11px;color:#64748b;font-weight:600;'>{label}</div>"
            f"<div style='font-size:20px;font-weight:800;color:#0f172a;line-height:1.25;'>{value}</div>"
            f"<div style='font-size:11px;color:#94a3b8;line-height:1.35;'>{sub}</div></div>",
            unsafe_allow_html=True)

    def _cal_chip(atual, esperado):
        if esperado is None or esperado <= 0:
            return ""
        d = (atual - esperado) / esperado * 100
        bg, fg = ("#dcfce7", "#15803d") if d >= 0 else ("#fee2e2", "#b91c1c")
        d_txt = f"{d:+.1f}%".replace('.', ',')
        return (f"<span style='background:{bg};color:{fg};font-weight:700;font-size:11px;padding:1px 7px;"
                f"border-radius:10px;white-space:nowrap;vertical-align:middle;'>{d_txt}</span>")

    def _cal_render(sel, m_start, mostrar_medias, dia_ref_cmp=None):
        """KPIs + grade de um mês para a seleção. Devolve dict com os números (a 2ª janela usa para comparar)."""
        m_start = pd.Timestamp(m_start)
        m_end = m_start + pd.offsets.MonthEnd(0)
        base_m = df[(df['data_venda'] >= m_start) & (df['data_venda'] <= m_end)]
        por_dia = _cal_filtra(base_m, sel).groupby('data_venda')['Vendas'].sum()
        last_day = None if base_m.empty else min(base_m['data_venda'].max(), _cal_hoje)
        if last_day is not None and last_day < m_start:
            last_day = None
        # dias de operação do mês (respeitando o filtro da barra lateral)
        cal_m = df_cal[(df_cal['data_ref'] >= m_start) & (df_cal['data_ref'] <= m_end)]
        if filtro_dias == "Apenas Dias Úteis":
            cal_m = cal_m[cal_m['is_dia_util'] == 1]
        elif filtro_dias == "Apenas Fins de Semana/Feriados":
            cal_m = cal_m[cal_m['is_dia_util'] == 0]
        if cal_m.empty:
            n_tot = int(m_end.day)
            n_ela = int(last_day.day) if last_day is not None else 0
        else:
            n_tot = int(len(cal_m))
            n_ela = int((cal_m['data_ref'] <= last_day).sum()) if last_day is not None else 0
        atual = float(por_dia[por_dia.index <= last_day].sum()) if last_day is not None else 0.0
        completo = last_day is not None and last_day >= m_end
        corte = last_day if last_day is not None else (m_start - pd.Timedelta(days=1))
        fc = pd.Series(dtype=float) if completo else _cal_fcst_serie(sel, corte, m_end)
        if completo:
            proj, metodo = atual, None
        elif not fc.empty:
            proj, metodo = atual + float(fc.sum()), "Prophet"
        else:
            ritmo = (atual / n_ela) if n_ela > 0 else 0.0
            proj, metodo = atual + ritmo * max(n_tot - n_ela, 0), "ritmo médio"
        esperado = (proj * n_ela / n_tot) if n_tot > 0 else 0.0
        meta = get_goal_for_group(m_start, m_end, 'CDT' if sel == 'CDT (Total)' else sel)

        # ---- KPIs ----
        k1, k2, k3 = st.columns(3)
        if completo:
            _cal_card(k1, f"Total do mês · {_cal_lbl_mes(m_start)}", format_br(atual),
                      f"{n_tot} dias de operação · média {format_br(round(atual / n_tot if n_tot else 0))}/dia")
            if dia_ref_cmp is not None:
                ate = float(por_dia[pd.DatetimeIndex(por_dia.index).day <= dia_ref_cmp].sum()) if not por_dia.empty else 0.0
                _cal_card(k2, f"Até o dia {dia_ref_cmp:02d} (comparável)", format_br(ate),
                          "mesmos dias do mês da janela principal", accent="#5b9bd5")
            else:
                _cal_card(k2, "Projeção do mês", format_br(round(proj)), "mês encerrado — igual ao realizado", accent="#5b9bd5")
        else:
            d_txt = last_day.strftime('%d/%m') if last_day is not None else "—"
            _cal_card(k1, f"Vendas até {d_txt}", f"{format_br(atual)} {_cal_chip(atual, esperado)}",
                      f"Esperado até {d_txt} (linear): <b>{format_br(round(esperado))}</b> · {n_ela} de {n_tot} dias")
            if metodo == "Prophet":
                _sub2 = f"realizado + previsão Prophet dos {n_tot - n_ela} dias restantes"
            else:
                _sub2 = (f"realizado + ritmo médio ({format_br(round(atual / n_ela if n_ela else 0))}/dia) "
                         f"nos {n_tot - n_ela} dias restantes (sem previsão Prophet)")
            _cal_card(k2, f"Projeção do mês · {_cal_lbl_mes(m_start)}", format_br(round(proj)), _sub2, accent="#5b9bd5")
        if meta > 0:
            _pct_meta = f"{proj / meta * 100:.1f}%".replace('.', ',')
            _cal_card(k3, "Meta do mês", format_br(round(meta)),
                      f"{'realizado' if completo else 'projeção'} = {_pct_meta} da meta", accent="#d62728")
        else:
            _cal_card(k3, "Meta do mês", "—", "sem meta cadastrada para esta seleção", accent="#cbd5e1")

        # ---- grade ----
        medias = _cal_medias_semana(sel, m_start) if mostrar_medias else None
        _pm = df_cal[(df_cal['data_ref'] >= m_start) & (df_cal['data_ref'] <= m_end)]
        _promo_uno = set(_pm[_pm['promo_uno'] == 1]['data_ref']) if 'promo_uno' in _pm.columns else set()
        _promo_dupla = set(_pm[_pm['promo_dupla'] == 1]['data_ref']) if 'promo_dupla' in _pm.columns else set()
        max_v = float(por_dia.max()) if not por_dia.empty else 0.0
        cells = []
        for wd in range(7):
            extra = ""
            if medias:
                _f = lambda v: "—" if v is None else format_br(round(v))
                extra = (f"<div style='font-size:10px;color:#64748b;font-weight:500;line-height:1.35;'>"
                         f"12m: {_f(medias['12m'][wd])}<br>3m: {_f(medias['3m'][wd])}</div>")
            cells.append(f"<div style='text-align:center;padding:2px 0 4px;'>{extra}"
                         f"<div style='font-size:11.5px;font-weight:700;color:#334155;'>{_CAL_WD[wd]}</div></div>")
        for _ in range(int(m_start.weekday())):
            cells.append("<div></div>")
        for d in range(1, int(m_end.day) + 1):
            ts = m_start + pd.Timedelta(days=d - 1)
            passado = last_day is not None and ts <= last_day
            v = por_dia.get(ts)
            style = "border:1px solid #e2e8f0;border-radius:8px;padding:5px 6px;min-height:52px;background:#fff;"
            if ts in _promo_dupla:
                style += "border-left:6px solid #2563eb;"
            elif ts in _promo_uno:
                style += "border-left:6px solid #f59e0b;"
            num = f"<div style='font-size:10.5px;color:#64748b;font-weight:600;'>{d:02d}</div>"
            if passado:
                if v is None:
                    val = "<div style='font-size:13px;color:#cbd5e1;'>—</div>"
                    style += "background:#f8fafc;"
                else:
                    a = 0.08 + 0.55 * (float(v) / max_v if max_v > 0 else 0.0)
                    style += f"background:rgba(22,101,52,{a:.2f});"
                    val = f"<div style='font-size:14px;font-weight:800;color:#0f172a;'>{format_br(v)}</div>"
                if ts == last_day:
                    style += "outline:2px solid #166534;outline-offset:-2px;"
            else:
                style += "border-style:dashed;background:#fcfcfd;"
                fv = fc.get(ts) if not fc.empty else None
                if fv is not None and not pd.isna(fv):
                    val = f"<div style='font-size:12px;font-style:italic;color:#94a3b8;'>≈ {format_br(round(fv))}</div>"
                else:
                    val = "<div style='font-size:12px;color:#e2e8f0;'>·</div>"
            cells.append(f"<div style='{style}'>{num}{val}</div>")
        st.markdown("<div style='display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-top:6px;'>"
                    + "".join(cells) + "</div>", unsafe_allow_html=True)
        return {'last_day': last_day, 'n_ela': n_ela, 'completo': completo, 'atual': atual, 'proj': proj}

    if df.empty:
        st.info("Sem vendas na base para montar o calendário.")
    else:
        _cal_opts_ch = sorted({str(c).title() for c in df['tipo_venda'].dropna().unique()})
        _cal_opcoes = list(_CAL_GRUPOS.keys()) + [c for c in _cal_opts_ch if c not in _CAL_GRUPOS]
        _cal_meses = sorted(set(pd.to_datetime(df['data_venda'].dt.to_period('M').dt.to_timestamp().unique()))
                            | {_cal_hoje.to_period('M').to_timestamp()}, reverse=True)
        cc1, cc2, cc3, cc4 = st.columns([1.4, 1, 1, 1.3])
        _cal_sel = cc1.selectbox("Tipo de venda (grupo ou canal):", _cal_opcoes, index=0, key='t1_cal_sel')
        _cal_m1 = cc2.selectbox("Mês principal:", _cal_meses, index=0, format_func=_cal_lbl_mes, key='t1_cal_m1')
        _cal_m2 = cc3.selectbox("Comparar com:", _cal_meses, index=min(1, len(_cal_meses) - 1),
                                format_func=_cal_lbl_mes, key='t1_cal_m2')
        _cal_avg = cc4.toggle("Média por dia da semana (12 m / 3 m)", value=False, key='t1_cal_avg',
                              help="Mostra, acima de cada dia da semana, a média de vendas daquele dia nos 12 e nos "
                                   "3 meses anteriores ao mês exibido (o próprio mês fica fora do cálculo).")
        colA, colB = st.columns(2)
        with colA:
            st.markdown(f"**Mês principal — {_cal_lbl_mes(_cal_m1)}**")
            _r1 = _cal_render(_cal_sel, _cal_m1, _cal_avg)
        with colB:
            st.markdown(f"**Comparação — {_cal_lbl_mes(_cal_m2)}**")
            _dia_cmp = _r1['last_day'].day if (_r1['last_day'] is not None and not _r1['completo']) else None
            _cal_render(_cal_sel, _cal_m2, _cal_avg, dia_ref_cmp=_dia_cmp)
        st.caption(
            "Células verdes = vendas do dia (intensidade relativa ao melhor dia do mês); contorno verde = último dia "
            "com vendas registradas; células tracejadas = dias futuros, com a previsão Prophet do dia (≈) quando "
            "existe. **Esperado até hoje** = projeção do mês distribuída linearmente pelos dias de operação do mês. "
            "O calendário não segue o período da barra lateral, mas respeita o filtro **Dias de Operação** "
            "(dias excluídos aparecem como —). Na janela de comparação, *Até o dia N* soma os mesmos dias do mês "
            "da janela principal. **Faixa lateral amarela** = qualquer campanha **Uno** ativa (is_uno / prêmios / cashback / 50% mens.); **azul** = **Dupla** (is_duo) — dia com as duas fica azul. Flags da `dim_calendario`, preenchidas até abr/26; meses recentes dependem de atualização manual."
        )

# =====================================================================
# TAB 2: ANÁLISE GEOGRÁFICA COMPARATIVA
# =====================================================================
with tab2:
    st.header("Análise Geográfica Comparativa (UF)")
    st.markdown(f"**Período analisado:** {c_s.strftime('%d/%m/%Y')} a {ref_datetime.strftime('%d/%m/%Y')}")
    st.write("")
    
    col_map_left, col_map_right = st.columns(2)
    
    def render_map_column(col_obj, map_id, default_group):
        with col_obj:
            st.subheader(f"Mapa {map_id}")

            metrica_mapa = st.radio(
                "Métrica:", ["Vendas", "Crescimento %", "Nacional / Franquias"],
                horizontal=True, key=f"t2_met_{map_id}",
                help="Vendas: total no período. Crescimento %: variação vs período anterior "
                     "ou ano passado (verde = cresce, vermelho = cai, branco ~ estável). "
                     "Nacional / Franquias: quociente vendas nacionais / vendas de franquias por "
                     "UF — a cor usa a participação nacional (azul = mais nacional, vermelho = "
                     "mais franquia, branco ~ equilíbrio).")
            ratio_mode = (metrica_mapa == "Nacional / Franquias")
            growth_mode = (metrica_mapa == "Crescimento %")

            growth_base, b_s, b_e = None, None, None
            if growth_mode:
                growth_base = st.radio("Comparar com:", ["Período Anterior", "Ano Passado"],
                                       horizontal=True, key=f"t2_gbase_{map_id}")
                b_s, b_e = (l_s, l_e) if growth_base == "Ano Passado" else (p_s, p_e)
                st.caption(
                    f"**Atual** = vendas de {c_s:%d/%m/%Y} a {ref_datetime:%d/%m/%Y} (período selecionado). "
                    f"**Base** = {growth_base.lower()}, de {b_s:%d/%m/%Y} a {b_e:%d/%m/%Y}. "
                    f"Crescimento % = (Atual − Base) ÷ Base. Verde = cresceu, vermelho = caiu.")

            # Channel selector applies to Vendas & Crescimento %. The ratio uses fixed
            # buckets (franquias vs. todo o resto), so it ignores the channel selector.
            canais_mapa_alvo = []
            if not ratio_mode:
                tipo_filtro_mapa = st.radio("Nível de Filtro:", ["Grupos de Canais", "Canais Específicos"],
                                            horizontal=True, key=f"t2_rad_{map_id}")
                if tipo_filtro_mapa == "Grupos de Canais":
                    grupos_sel_mapa = st.multiselect("Selecione os Grupos:",
                        ['Digital', 'Franquias', 'Outros', 'Nacional', 'CDT'],
                        default=[default_group], key=f"t2_grp_sel_{map_id}")
                    for g in grupos_sel_mapa:
                        canais_mapa_alvo.extend(group_map[g])
                    canais_mapa_alvo = list(set(canais_mapa_alvo))
                else:
                    opcoes_canais_brutos = sorted([str(c) for c in df_raw['tipo_venda'].dropna().unique()])
                    canais_mapa_raw = st.multiselect("Selecione os Canais:", options=opcoes_canais_brutos,
                        default=opcoes_canais_brutos[:2] if opcoes_canais_brutos else [], key=f"t2_can_sel_{map_id}")
                    canais_mapa_alvo = [c.lower() for c in canais_mapa_raw]

            FRANQ_TIPOS = {'porta a porta', 'link do vendedor', 'app do vendedor'}

            def _uf_sum(d_start, d_end, tipos=None, franq=None):
                m = (df['data_venda'] >= d_start) & (df['data_venda'] <= d_end)
                d = df.loc[m, ['uf', 'tipo_venda', 'Vendas']].copy()
                tl = d['tipo_venda'].str.lower()
                if tipos is not None:
                    d = d[tl.isin(tipos)]
                elif franq is True:
                    d = d[tl.isin(FRANQ_TIPOS)]
                elif franq is False:
                    d = d[~tl.isin(FRANQ_TIPOS)]
                if d.empty:
                    return pd.Series(dtype=float)
                d['uf'] = d['uf'].str.upper()
                return d.groupby('uf')['Vendas'].sum()

            def _cap(series, lo, hi, default):
                s = series.replace([np.inf, -np.inf], np.nan).dropna().abs()
                if s.empty:
                    return default
                return min(hi, max(lo, float(s.quantile(0.9))))

            hover_extra, range_color = None, None
            if ratio_mode:
                nac = _uf_sum(c_s, ref_datetime, franq=False)
                fra = _uf_sum(c_s, ref_datetime, franq=True)
                mdf = pd.DataFrame({'nac': nac, 'fra': fra}).fillna(0.0)
                mdf.index.name = 'uf'; mdf = mdf.reset_index()
                _tot = mdf['nac'] + mdf['fra']
                mdf['share'] = np.where(_tot > 0, mdf['nac'] / _tot.replace(0, np.nan), np.nan)
                color_col, cscale, range_color = 'share', 'RdBu', [0.0, 1.0]
                def _ratio_txt(r):
                    if r['nac'] == 0 and r['fra'] == 0: return "—"
                    if r['fra'] == 0: return "∞ (só nac.)"
                    return f"{r['nac'] / r['fra']:.2f}".replace(".", ",")
                txt = mdf.apply(_ratio_txt, axis=1)
                hover_extra = mdf.apply(lambda r: f"Nac: {format_br(r['nac'])} · Franq: {format_br(r['fra'])}", axis=1)
                title_metric = "Nacional / Franquias"
                empty = _tot.sum() == 0
            elif growth_mode:
                curr = _uf_sum(c_s, ref_datetime, tipos=set(canais_mapa_alvo))
                base = _uf_sum(b_s, b_e, tipos=set(canais_mapa_alvo))
                mdf = pd.DataFrame({'curr': curr, 'base': base}).fillna(0.0)
                mdf.index.name = 'uf'; mdf = mdf.reset_index()
                mdf['val'] = (mdf['curr'] - mdf['base']) / mdf['base'].replace(0, np.nan) * 100.0
                color_col, cscale = 'val', 'RdYlGn'
                _r = _cap(mdf['val'], 30.0, 300.0, 100.0)
                range_color = [-_r, _r]
                txt = mdf['val'].apply(lambda v: "—" if pd.isna(v) else f"{v:+.1f}%".replace(".", ","))
                hover_extra = mdf.apply(lambda r: f"Atual: {format_br(r['curr'])} · Base ({growth_base.lower()}): {format_br(r['base'])}", axis=1)
                title_metric = f"Crescimento % ({growth_base})"
                empty = (mdf['curr'].sum() + mdf['base'].sum()) == 0
            else:  # Vendas
                cur = _uf_sum(c_s, ref_datetime, tipos=set(canais_mapa_alvo))
                mdf = cur.reset_index()
                mdf.columns = ['uf', 'val']
                color_col, cscale = 'val', 'Blues'
                _totv = mdf['val'].sum()
                txt = mdf['val'].apply(lambda v: (f"{format_br(v)} ({v / _totv * 100:.1f}%)" if _totv else format_br(v)))
                title_metric = "Vendas"
                empty = mdf.empty or mdf['val'].sum() == 0

            if empty:
                st.info("Nenhuma venda encontrada para os filtros selecionados.")
                return

            mdf = mdf.reset_index(drop=True)
            mdf['_txt'] = txt.values

            if brazil_geo:
                ck = dict(geojson=brazil_geo, locations='uf', featureidkey='properties.sigla',
                          color=color_col, color_continuous_scale=cscale)
                if range_color is not None:
                    ck['range_color'] = range_color
                fig_map = px.choropleth(mdf, **ck)
                fig_map.update_geos(fitbounds="locations", visible=False)
                if hover_extra is not None:
                    cd = np.stack([mdf['_txt'].to_numpy(), pd.Series(hover_extra).values], axis=-1)
                    fig_map.update_traces(customdata=cd,
                        hovertemplate="<b>%{location}</b><br>" + title_metric + ": %{customdata[0]}<br>%{customdata[1]}<extra></extra>")
                else:
                    fig_map.update_traces(customdata=mdf['_txt'].to_numpy(),
                        hovertemplate="<b>%{location}</b><br>" + title_metric + ": %{customdata}<extra></extra>")
                fig_map.update_layout(margin={"r": 0, "t": 20, "l": 0, "b": 0}, coloraxis_colorbar_title="")
                st.plotly_chart(fig_map, use_container_width=True, key=f"plotly_map_{map_id}")
            else:
                st.warning("Mapa do Brasil não carregado. Exibindo apenas barras.")

            bar = mdf.dropna(subset=[color_col]).sort_values(by=color_col, ascending=True)
            fig_bar_uf = px.bar(bar, x=color_col, y='uf', orientation='h',
                                title=f"Ranking por UF — {title_metric}", text='_txt')
            fig_bar_uf.update_traces(textposition='outside', cliponaxis=False,
                hovertemplate="<b>%{y}</b><br>" + title_metric + ": %{text}<extra></extra>")
            fig_bar_uf.update_layout(margin={"r": 80, "t": 40, "l": 0, "b": 0}, yaxis_title="", xaxis_title="")
            st.plotly_chart(fig_bar_uf, use_container_width=True, key=f"plotly_bar_{map_id}")

    render_map_column(col_map_left, "1", "Digital")
    render_map_column(col_map_right, "2", "Franquias")

    # =====================================================================
    # Franchise analysis by UF (point D): distinct franquias + avg sales/franquia
    # =====================================================================
    st.divider()
    st.subheader("🏪 Análise de Franquias por UF")
    st.caption(f"Franquias com vendas no período ({c_s.strftime('%d/%m/%Y')} → "
               f"{ref_datetime.strftime('%d/%m/%Y')}). Baseado em NOME_FRANQUIA do RESUMO_VENDAS_DIARIAS.")

    df_fr = load_franquia_sales()
    if df_fr.empty:
        st.info("Sem dados de franquia. Confirme que a coluna NOME_FRANQUIA foi adicionada ao "
                "RESUMO_VENDAS_DIARIAS (veja o SQL entregue) e que há vendas de franquia no período.")
    else:
        df_fr_p = df_fr[(df_fr['data_venda'] >= c_s) & (df_fr['data_venda'] <= ref_datetime)].copy()
        if df_fr_p.empty:
            st.info("Nenhuma venda de franquia no período selecionado.")
        else:
            fr_uf = (df_fr_p.groupby('uf')
                     .agg(n_franquias=('NOME_FRANQUIA', 'nunique'), vendas=('Vendas', 'sum'))
                     .reset_index())
            fr_uf['media_por_franquia'] = fr_uf['vendas'] / fr_uf['n_franquias'].replace(0, np.nan)

            def _franquia_map(col_obj, value_col, titulo, fmt, scale):
                with col_obj:
                    st.markdown(f"**{titulo}**")
                    if brazil_geo:
                        figm = px.choropleth(fr_uf, geojson=brazil_geo, locations='uf',
                                             featureidkey='properties.sigla', color=value_col,
                                             color_continuous_scale=scale)
                        figm.update_geos(fitbounds="locations", visible=False)
                        figm.update_traces(customdata=[fmt(v) for v in fr_uf[value_col]],
                                           hovertemplate="<b>%{location}</b><br>" + titulo + ": %{customdata}<extra></extra>")
                        figm.update_layout(margin={"r": 0, "t": 10, "l": 0, "b": 0}, coloraxis_colorbar_title="")
                        st.plotly_chart(figm, use_container_width=True, key=f"fr_map_{value_col}")
                    else:
                        st.warning("Mapa do Brasil não carregado; exibindo apenas o ranking.")
                    _rank = fr_uf.sort_values(value_col, ascending=True).copy()
                    _rank['txt'] = _rank[value_col].apply(fmt)
                    figb = px.bar(_rank, x=value_col, y='uf', orientation='h', text='txt')
                    figb.update_traces(textposition='outside', cliponaxis=False,
                                       hovertemplate="<b>%{y}</b><br>" + titulo + ": %{text}<extra></extra>")
                    figb.update_layout(margin={"r": 60, "t": 10, "l": 0, "b": 0}, yaxis_title="", xaxis_title="")
                    st.plotly_chart(figb, use_container_width=True, key=f"fr_bar_{value_col}")

            fr_col1, fr_col2 = st.columns(2)
            _franquia_map(fr_col1, 'n_franquias', "Franquias distintas por UF",
                          lambda v: format_br(v), "Greens")
            _franquia_map(fr_col2, 'media_por_franquia', "Vendas médias por franquia",
                          lambda v: f"{v:.1f}".replace(".", ","), "Blues")

            st.caption(f"Total no período: {format_br(int(fr_uf['vendas'].sum()))} vendas de franquia • "
                       f"{format_br(df_fr_p['NOME_FRANQUIA'].nunique())} franquias distintas (nacional) • "
                       f"{format_br(int(fr_uf['n_franquias'].sum()))} pares franquia×UF "
                       "(uma franquia em 2 UFs conta em cada uma).")


# =====================================================================
# TAB 3: ANÁLISE DE INVESTIMENTO
# =====================================================================
with tab3:
    st.header("Análise de Investimento")
    st.info(f"**Status do Período ({view_option}):** Decorridos **{e_days_c} de {t_days_c} dias** no calendário. | **Dias Úteis Decorridos:** Atual: {w_ela_c} | Anterior: {w_ela_p} | Ano Passado: {w_ela_l}")
    
    col_filt1, col_filt2, col_filt3 = st.columns(3)
    
    opcoes_canais_inv = sorted([str(c) for c in df_invest_raw['canal'].dropna().unique()])
    # CRM é opt-in: fica na lista, mas fora do padrão para não mudar os números de mídia paga sem pedir.
    _default_canais_inv = [c for c in opcoes_canais_inv if c != 'CRM']
    canais_invest = col_filt1.multiselect("Canal:", options=opcoes_canais_inv, default=_default_canais_inv, key='t3_can_inv')
    categorias_invest = col_filt2.multiselect("Categoria:", ["Branding", "Leads", "Venda"], default=["Branding", "Leads", "Venda"], key='t3_cat_inv')
    
    todas_plataformas = ["Google", "Meta", "TikTok", "Kwai", "Jampp", "Adsplay", "Actionpay", "CRM"]  # R26: Jampp (App; USD→BRL)
    plataformas_invest = col_filt3.multiselect("Plataforma:", todas_plataformas, default=todas_plataformas, key='t3_plat_inv')
    if 'CRM' in opcoes_canais_inv:
        _crm_on = ('CRM' in canais_invest) and ('CRM' in plataformas_invest)
        st.caption(
            ("ℹ️ **CRM ativo** nos filtros: " if _crm_on else "ℹ️ Selecione **CRM** em Canal *e* Plataforma para incluir: ")
            + "custo de mensageria **Zenvia** (todos os remetentes, lançado na categoria *Venda*) + leads e vendas "
              "atribuídos a **WhatsApp/SMS no GA**. Entra na tabela e nos gráficos como qualquer outra plataforma; "
              "o detalhe por remetente continua no bloco 📡 abaixo. As barras 🎯 globais seguem só com mídia paga."
        )
    
    df_inv_filt = df_invest[
        (df_invest['canal'].isin(canais_invest)) & 
        (df_invest['plataforma'].isin(plataformas_invest))
    ].copy()
    
    cat_cols = [c.lower() for c in categorias_invest]
    if cat_cols and not df_inv_filt.empty:
        df_inv_filt['Total_Investido'] = df_inv_filt[cat_cols].sum(axis=1)
    else:
        df_inv_filt['Total_Investido'] = 0

    st.divider()

    # Pre-compute Global Unfiltered Data for Pacing Progress Bars and Parent Table Rows
    # (sem CRM: a meta 'Investimento Total' é de mídia paga; o Zenvia não entra no ritmo global)
    df_invest_global = df_invest[df_invest['canal'] != 'CRM'].copy()
    available_cats_global = [c for c in ['branding', 'leads', 'venda'] if c in df_invest_global.columns]
    if available_cats_global and not df_invest_global.empty:
        df_invest_global['Total_Investido'] = df_invest_global[available_cats_global].sum(axis=1)
    else:
        df_invest_global['Total_Investido'] = 0

    def filter_inv_date(df_i, start, end):
        mask = (df_i['data_investimento'] >= start) & (df_i['data_investimento'] <= end)
        return df_i.loc[mask]

    def get_inv_metrics(df_slice, cat=None):
        if df_slice.empty: return 0, 0, 0, 0
        v_leads = df_slice['vol_leads'].sum()
        v_vendas = df_slice['vol_vendas'].sum()
        
        if cat:
            tot_inv = df_slice[cat].sum()
            cpl = tot_inv / v_leads if v_leads > 0 else 0
            cpa = tot_inv / v_vendas if v_vendas > 0 else 0
        else:
            tot_inv = df_slice['Total_Investido'].sum()
            cpl = tot_inv / v_leads if v_leads > 0 else 0
            cpa = tot_inv / v_vendas if v_vendas > 0 else 0
            
        return tot_inv, cpl, cpa, v_leads

    def compute_row(label, df_c, df_pp, df_pf, df_lp, df_lf, metric_idx, df_global=None, cat=None, goal_col=None, is_sub=False):
        m_c = get_inv_metrics(df_c, cat)[metric_idx]
        m_pp = get_inv_metrics(df_pp, cat)[metric_idx]
        m_pf = get_inv_metrics(df_pf, cat)[metric_idx]
        m_lp = get_inv_metrics(df_lp, cat)[metric_idx]
        m_lf = get_inv_metrics(df_lf, cat)[metric_idx]
        
        is_money = metric_idx in [0, 1, 2]
        
        pct_p = "N/A"
        pct_t = "N/A"
        
        # % shown = THIS row's Atual vs its prorated goal, so it matches the Atual column
        # (Atual / Meta). True global pacing across ALL channels — independent of the filters
        # above — is shown separately in the 🎯 progress bars at the top of the tab.
        if not is_sub and goal_col:
            meta_p = get_prorated_goal(df_goals, c_s, ref_datetime, goal_col)
            meta_t = get_prorated_goal(df_goals, c_s, c_e, goal_col)

            if meta_p > 0:
                val_str_p = format_money(meta_p) if is_money else format_br(meta_p)
                pct_p = f"{val_str_p} ({(m_c / meta_p * 100):.1f}%)"
            if meta_t > 0:
                val_str_t = format_money(meta_t) if is_money else format_br(meta_t)
                pct_t = f"{val_str_t} ({(m_c / meta_t * 100):.1f}%)"
        
        return {
            'Métrica': label,
            'Atual': format_money(m_c) if is_money else format_br(m_c),
            'Meta (Parcial)': pct_p,
            'Meta (Total)': pct_t,
            'vs Anterior (Parcial)': fmt_val_delta_money(m_c, m_pp) if is_money else fmt_val_delta(m_c, m_pp),
            'vs Anterior (Total)': fmt_val_delta_money(m_c, m_pf) if is_money else fmt_val_delta(m_c, m_pf),
            'vs Ano Passado (Parcial)': fmt_val_delta_money(m_c, m_lp) if is_money else fmt_val_delta(m_c, m_lp),
            'vs Ano Passado (Total)': fmt_val_delta_money(m_c, m_lf) if is_money else fmt_val_delta(m_c, m_lf),
            '_val_c': m_c,
            '_val_pf': m_pf,
            '_val_lf': m_lf,
            '_is_eff': True if metric_idx in [1, 2] else False
        }

    # High Level Bars (Global and Unshakeable)
    df_c_global = filter_inv_date(df_invest_global, c_s, ref_datetime)
    inv_global_total = df_c_global['Total_Investido'].sum()
    leads_global_total = df_c_global['vol_leads'].sum()

    goal_invest = get_prorated_goal(df_goals, c_s, ref_datetime, 'Investimento Total')
    pct_goal_inv = inv_global_total / goal_invest if goal_invest > 0 else 0
    
    goal_leads = get_prorated_goal(df_goals, c_s, ref_datetime, 'Leads unicos Total')
    pct_goal_leads = leads_global_total / goal_leads if goal_leads > 0 else 0

    col_gb1, col_gb2 = st.columns(2)
    with col_gb1:
        st.markdown(f"🎯 **Meta de Investimento Global:** {format_money(inv_global_total)} / {format_money(goal_invest)} utilizados (**{pct_goal_inv*100:.1f}%**)")
        st.progress(min(max(pct_goal_inv, 0.0), 1.0))
    with col_gb2:
        st.markdown(f"🎯 **Meta de Leads Global (Volume):** {format_br(leads_global_total)} / {format_br(goal_leads)} gerados (**{pct_goal_leads*100:.1f}%**)")
        st.progress(min(max(pct_goal_leads, 0.0), 1.0))
        
    st.divider()

    st.subheader("Indicadores de Eficiência")
    
    col_det1, col_det2 = st.columns(2)
    detalhe_plat = col_det1.checkbox("Mostrar detalhamento por plataforma", key='t3_det_plat')
    detalhe_tipo = col_det2.checkbox("Mostrar detalhamento por tipo de investimento", key='t3_det_tipo')
    
    df_c_inv = filter_inv_date(df_inv_filt, c_s, ref_datetime)
    df_pp_inv = filter_inv_date(df_inv_filt, p_s, p_partial)
    df_pf_inv = filter_inv_date(df_inv_filt, p_s, p_e)
    df_lp_inv = filter_inv_date(df_inv_filt, l_s, l_partial)
    df_lf_inv = filter_inv_date(df_inv_filt, l_s, l_e)

    metrics = [
        (0, '💸 Total Investido', 'Investimento Total'), 
        (1, '🎯 CPL (Custo por Lead)', None), 
        (2, '🛒 CPA (Custo por Venda)', None),
        (3, '📢 Leads (Volume)', 'Leads unicos Total')
    ]
    rows_inv = []

    for m_idx, m_name, m_goal in metrics:
        row_parent = compute_row(m_name, df_c_inv, df_pp_inv, df_pf_inv, df_lp_inv, df_lf_inv, m_idx, df_global=df_c_global, goal_col=m_goal)
        row_parent['_level'] = 0
        rows_inv.append(row_parent)

        if detalhe_plat and not detalhe_tipo:
            for plat in plataformas_invest:
                p_df_c = df_c_inv[df_c_inv['plataforma'] == plat]
                p_df_pp = df_pp_inv[df_pp_inv['plataforma'] == plat]
                p_df_pf = df_pf_inv[df_pf_inv['plataforma'] == plat]
                p_df_lp = df_lp_inv[df_lp_inv['plataforma'] == plat]
                p_df_lf = df_lf_inv[df_lf_inv['plataforma'] == plat]
                row_p = compute_row(str(plat), p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx, df_c_global, is_sub=True)
                if row_p['_val_c'] == 0 and row_p['_val_pf'] == 0 and row_p['_val_lf'] == 0: continue
                row_p['_level'] = 1
                rows_inv.append(row_p)

        elif detalhe_tipo and not detalhe_plat:
            for cat in cat_cols:
                row_c = compute_row(cat.title(), df_c_inv, df_pp_inv, df_pf_inv, df_lp_inv, df_lf_inv, m_idx, df_c_global, cat=cat, is_sub=True)
                if row_c['_val_c'] == 0 and row_c['_val_pf'] == 0 and row_c['_val_lf'] == 0: continue
                row_c['_level'] = 1
                rows_inv.append(row_c)

        elif detalhe_plat and detalhe_tipo:
            for plat in plataformas_invest:
                p_df_c = df_c_inv[df_c_inv['plataforma'] == plat]
                p_df_pp = df_pp_inv[df_pp_inv['plataforma'] == plat]
                p_df_pf = df_pf_inv[df_pf_inv['plataforma'] == plat]
                p_df_lp = df_lp_inv[df_lp_inv['plataforma'] == plat]
                p_df_lf = df_lf_inv[df_lf_inv['plataforma'] == plat]
                row_p = compute_row(str(plat), p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx, df_c_global, is_sub=True)
                if row_p['_val_c'] == 0 and row_p['_val_pf'] == 0 and row_p['_val_lf'] == 0: continue
                row_p['_level'] = 1
                rows_inv.append(row_p)
                for cat in cat_cols:
                    row_c = compute_row(cat.title(), p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx, df_c_global, cat=cat, is_sub=True)
                    if row_c['_val_c'] == 0 and row_c['_val_pf'] == 0 and row_c['_val_lf'] == 0: continue
                    row_c['_level'] = 2
                    rows_inv.append(row_c)
    
    display_cols_inv = ['Métrica', 'Atual', 'Meta (Parcial)', 'Meta (Total)', 'vs Anterior (Parcial)', 'vs Anterior (Total)']
    if view_option != "Ano Atual":
        display_cols_inv.extend(['vs Ano Passado (Parcial)', 'vs Ano Passado (Total)'])

    st.caption(
        "**Atual** = gasto realizado no período selecionado, respeitando os filtros acima. "
        "**Meta (Parcial)** = meta proporcional aos dias já decorridos; **Meta (Total)** = meta do período "
        "inteiro. O **% entre parênteses** é Atual ÷ Meta (o quanto da meta já foi gasto). Em períodos já "
        "encerrados, Parcial e Total coincidem. O ritmo **global** (todos os canais, sem filtro) está nas "
        "barras 🎯 no topo da aba."
    )
    st.markdown(render_metric_table(rows_inv, display_cols_inv), unsafe_allow_html=True)

    st.divider()

    st.subheader("Análise Gráfica")
    
    col_inv_t1, col_inv_t2 = st.columns(2)
    grafico_metrica = col_inv_t1.selectbox("Selecione a métrica para o gráfico:", 
                                   ["Total Investido", "CPL", "CPA", "Leads (Volume)", "Vendas (Volume)"], key='t3_met_sel')
    tipo_graf_tend_inv = col_inv_t2.radio("Visualização:", ["Diário", "Acumulado"], horizontal=True, key='t3_rad_tend')
    
    col_ig1, col_ig2 = st.columns(2)
    show_prev_inv = col_ig1.checkbox("Comparar c/ Anterior", key='t3_chk_prev')
    show_last_yr_inv = col_ig2.checkbox("Comparar c/ Ano Passado", key='t3_chk_last')

    def get_inv_trend_data(t_start, t_end, label_suffix, max_actual_date=None):
        end_bound = min(t_end, max_actual_date) if max_actual_date else t_end
        df_t = df_inv_filt[(df_inv_filt['data_investimento'] >= t_start) & (df_inv_filt['data_investimento'] <= end_bound)]
        if df_t.empty: return pd.DataFrame()
        
        grp = df_t.groupby('data_investimento')[['Total_Investido', 'leads', 'vol_leads', 'venda', 'vol_vendas']].sum().reset_index()
        grp = grp.sort_values('data_investimento')
        
        if tipo_graf_tend_inv == "Acumulado":
            grp['Total_Investido'] = grp['Total_Investido'].cumsum()
            grp['leads'] = grp['leads'].cumsum()
            grp['vol_leads'] = grp['vol_leads'].cumsum()
            grp['venda'] = grp['venda'].cumsum()
            grp['vol_vendas'] = grp['vol_vendas'].cumsum()
            
        if grafico_metrica == "Total Investido":
            grp['Y'] = grp['Total_Investido']
            grp['Formatado'] = grp['Y'].apply(format_money)
        elif grafico_metrica == "CPL":
            grp['Y'] = grp.apply(lambda r: r['leads'] / r['vol_leads'] if r['vol_leads'] > 0 else 0, axis=1)
            grp['Formatado'] = grp['Y'].apply(format_money)
        elif grafico_metrica == "CPA":
            grp['Y'] = grp.apply(lambda r: r['venda'] / r['vol_vendas'] if r['vol_vendas'] > 0 else 0, axis=1)
            grp['Formatado'] = grp['Y'].apply(format_money)
        elif grafico_metrica == "Leads (Volume)":
            grp['Y'] = grp['vol_leads']
            grp['Formatado'] = grp['Y'].apply(format_br)
        elif grafico_metrica == "Vendas (Volume)":
            grp['Y'] = grp['vol_vendas']
            grp['Formatado'] = grp['Y'].apply(format_br)
            
        grp['Dia'] = (grp['data_investimento'] - t_start).dt.days + 1
        grp['Traço'] = grafico_metrica + label_suffix
        grp['Data_Real'] = grp['data_investimento']
        
        return grp.reset_index(drop=True)

    plot_dfs_inv = []
    df_main_inv = get_inv_trend_data(c_s, c_e, "", max_actual_date=ref_datetime)
    if not df_main_inv.empty: plot_dfs_inv.append(df_main_inv)
    
    if show_prev_inv:
        df_prev_plot_inv = get_inv_trend_data(p_s, p_e, " (Anterior)")
        if not df_prev_plot_inv.empty: plot_dfs_inv.append(df_prev_plot_inv)
        
    if show_last_yr_inv and view_option != "Ano Atual":
        df_last_plot_inv = get_inv_trend_data(l_s, l_e, " (Ano Passado)")
        if not df_last_plot_inv.empty: plot_dfs_inv.append(df_last_plot_inv)

    if plot_dfs_inv:
        df_plot_trend_inv = pd.concat(plot_dfs_inv).reset_index(drop=True)
        df_plot_trend_inv['Data_Str'] = df_plot_trend_inv['Data_Real'].dt.strftime('%d/%m/%Y')
        
        fig_line = px.line(df_plot_trend_inv, x='Dia', y='Y', color='Traço', markers=True)
        
        for trace in fig_line.data:
            if "(Anterior)" in trace.name or "(Ano Passado)" in trace.name:
                trace.line.dash = 'dash'
                trace.opacity = 0.5
                
        fig_line.update_traces(hovertemplate="<b>Data Original: %{customdata[1]}</b><br>Valor: %{customdata[0]}<extra></extra>",
                                customdata=df_plot_trend_inv[['Formatado', 'Data_Str']])
        fig_line.update_layout(margin=dict(t=0, b=0, l=0, r=0), xaxis_title="Dias Decorridos", yaxis_title=f"{grafico_metrica} ({tipo_graf_tend_inv})")
        st.plotly_chart(fig_line, use_container_width=True, key='t3_trend_chart_new')
    else:
        st.info("Sem dados para o gráfico de tendência.")

    # ---- NOVO: CRM & Mensageria (Zenvia + Wpp/SMS), dados da planilha Ad Sources ----
    st.divider()
    with st.expander("📡 CRM & Mensageria — Zenvia + Wpp/SMS (dados novos)", expanded=False):
        st.caption(
            "Disparos e custo de mensageria (Zenvia) + leads e vendas atribuídos a CRM "
            "(WhatsApp/SMS via GA), no mesmo período da barra lateral. Comparação = período "
            "anterior (parcial equivalente)."
        )
        _crm_leads_t3, _crm_vendas_t3 = load_crm_wpp_sms()
        _zen_t3 = load_zenvia()

        def _per_t3(dfx, col, s, e):
            if dfx.empty:
                return dfx
            return dfx[(dfx[col] >= s) & (dfx[col] <= e)]

        _z_c = _per_t3(_zen_t3, 'report_date', c_s, ref_datetime)
        _z_p = _per_t3(_zen_t3, 'report_date', p_s, p_partial)
        _cl_c = _per_t3(_crm_leads_t3, 'date', c_s, ref_datetime)
        _cl_p = _per_t3(_crm_leads_t3, 'date', p_s, p_partial)
        _cv_c = _per_t3(_crm_vendas_t3, 'date', c_s, ref_datetime)
        _cv_p = _per_t3(_crm_vendas_t3, 'date', p_s, p_partial)

        _msgs_c = float(_z_c['total_messages'].sum()) if not _z_c.empty else 0.0
        _msgs_p = float(_z_p['total_messages'].sum()) if not _z_p.empty else 0.0
        _cost_c = float(_z_c['total_price'].sum()) if not _z_c.empty else 0.0
        _cost_p = float(_z_p['total_price'].sum()) if not _z_p.empty else 0.0
        _leads_c = float(_cl_c['event_count'].sum()) if not _cl_c.empty else 0.0
        _leads_p = float(_cl_p['event_count'].sum()) if not _cl_p.empty else 0.0
        _vend_c = float(_cv_c['event_count'].sum()) if not _cv_c.empty else 0.0
        _vend_p = float(_cv_p['event_count'].sum()) if not _cv_p.empty else 0.0
        _cpv_c = (_cost_c / _vend_c) if _vend_c > 0 else 0.0
        _cpv_p = (_cost_p / _vend_p) if _vend_p > 0 else 0.0

        if _zen_t3.empty and _crm_leads_t3.empty and _crm_vendas_t3.empty:
            st.info("Tabelas de CRM/Zenvia ainda não disponíveis no banco.")
        else:
            def _split_src_t3(dfx, prefix):
                if dfx.empty:
                    return 0.0
                s = dfx['session_source_medium'].astype(str).str.lower()
                return float(dfx.loc[s.str.startswith(prefix), 'event_count'].sum())

            rows_crm = [
                {'Métrica': '💬 Mensagens enviadas (Zenvia)', '_level': 0, '_is_eff': False,
                 'Atual': format_br(_msgs_c), 'vs Anterior (Parcial)': fmt_val_delta(_msgs_c, _msgs_p)},
                {'Métrica': '💸 Custo mensageria (Zenvia)', '_level': 0, '_is_eff': True,
                 'Atual': format_money(_cost_c), 'vs Anterior (Parcial)': fmt_val_delta_money(_cost_c, _cost_p)},
                {'Métrica': '📢 Leads CRM (Wpp/SMS)', '_level': 0, '_is_eff': False,
                 'Atual': format_br(_leads_c), 'vs Anterior (Parcial)': fmt_val_delta(_leads_c, _leads_p)},
                {'Métrica': 'WhatsApp', '_level': 1, '_is_eff': False,
                 'Atual': format_br(_split_src_t3(_cl_c, 'whatsapp')),
                 'vs Anterior (Parcial)': fmt_val_delta(_split_src_t3(_cl_c, 'whatsapp'), _split_src_t3(_cl_p, 'whatsapp'))},
                {'Métrica': 'SMS', '_level': 1, '_is_eff': False,
                 'Atual': format_br(_split_src_t3(_cl_c, 'sms')),
                 'vs Anterior (Parcial)': fmt_val_delta(_split_src_t3(_cl_c, 'sms'), _split_src_t3(_cl_p, 'sms'))},
                {'Métrica': '🛒 Vendas CRM (Wpp/SMS)', '_level': 0, '_is_eff': False,
                 'Atual': format_br(_vend_c), 'vs Anterior (Parcial)': fmt_val_delta(_vend_c, _vend_p)},
                {'Métrica': 'WhatsApp', '_level': 1, '_is_eff': False,
                 'Atual': format_br(_split_src_t3(_cv_c, 'whatsapp')),
                 'vs Anterior (Parcial)': fmt_val_delta(_split_src_t3(_cv_c, 'whatsapp'), _split_src_t3(_cv_p, 'whatsapp'))},
                {'Métrica': 'SMS', '_level': 1, '_is_eff': False,
                 'Atual': format_br(_split_src_t3(_cv_c, 'sms')),
                 'vs Anterior (Parcial)': fmt_val_delta(_split_src_t3(_cv_c, 'sms'), _split_src_t3(_cv_p, 'sms'))},
                {'Métrica': '🎯 Custo por venda CRM', '_level': 0, '_is_eff': True,
                 'Atual': format_money(_cpv_c), 'vs Anterior (Parcial)': fmt_val_delta_money(_cpv_c, _cpv_p)},
            ]
            st.markdown(render_metric_table(rows_crm, ['Métrica', 'Atual', 'vs Anterior (Parcial)']),
                        unsafe_allow_html=True)
            st.caption("ℹ️ O custo Zenvia é o total de mensageria (todos os disparos), não atribuído "
                       "por campanha — o custo por venda CRM é uma aproximação.")

            # ---- ponte com a aba 📨 CRM: o mesmo período, os dois recortes lado a lado ----
            _c8i, _c8i_err = load_crm_cpa()
            if not _c8i_err and not _c8i.empty:
                _c8i_c = _c8i[(_c8i['dia'] >= c_s) & (_c8i['dia'] <= ref_datetime)]
                _c8i_p = _c8i[(_c8i['dia'] >= p_s) & (_c8i['dia'] <= p_partial)]
                _gt7_zen_c, _gt7_zen_p = float(_c8i_c['gasto_zenvia'].sum()), float(_c8i_p['gasto_zenvia'].sum())
                _gt7_bd_c, _gt7_bd_p = float(_c8i_c['gasto_bd'].sum()), float(_c8i_p['gasto_bd'].sum())
                _gt7_v_c, _gt7_v_p = float(_c8i_c['vendas_ga'].sum()), float(_c8i_p['vendas_ga'].sum())
                rows_ponte = [
                    {'Métrica': '🏢 Mensageria da empresa — todos os remetentes (cobrado pela Zenvia)', '_level': 0, '_is_eff': True,
                     'Atual': format_money(_cost_c), 'vs Anterior (Parcial)': fmt_val_delta_money(_cost_c, _cost_p)},
                    {'Métrica': 'Instância Aquisição — templates GT7, cobrado (inclui Não Entregue)', '_level': 1, '_is_eff': True,
                     'Atual': format_money(_gt7_zen_c), 'vs Anterior (Parcial)': fmt_val_delta_money(_gt7_zen_c, _gt7_zen_p)},
                    {'Métrica': 'Instância Aquisição — régua da aba 📨 CRM (Enviada+Entregue+Lida × R$ 0,32)', '_level': 1, '_is_eff': True,
                     'Atual': format_money(_gt7_bd_c), 'vs Anterior (Parcial)': fmt_val_delta_money(_gt7_bd_c, _gt7_bd_p)},
                    {'Métrica': '🛒 Vendas mkt direto (GA4 · sessionSourceMedium contém mkt_direto) — régua da aba 📨', '_level': 0, '_is_eff': False,
                     'Atual': format_br(_gt7_v_c), 'vs Anterior (Parcial)': fmt_val_delta(_gt7_v_c, _gt7_v_p)},
                    {'Métrica': '🎯 CPA do CRM de Aquisição (régua da aba 📨)', '_level': 0, '_is_eff': True,
                     'Atual': format_money(_gt7_bd_c / _gt7_v_c if _gt7_v_c else 0.0),
                     'vs Anterior (Parcial)': fmt_val_delta_money(_gt7_bd_c / _gt7_v_c if _gt7_v_c else 0.0, _gt7_bd_p / _gt7_v_p if _gt7_v_p else 0.0)},
                ]
                st.markdown("**Ponte com a aba 📨 CRM (mesmo período):**")
                st.markdown(render_metric_table(rows_ponte, ['Métrica', 'Atual', 'vs Anterior (Parcial)']),
                            unsafe_allow_html=True)
                st.markdown(
                    "<div style='border-radius:12px;padding:12px 14px;background:#f8fafc;font-size:12.5px;color:#0f172a;line-height:1.5;'>"
                    "<b>Por que os dois números são tão diferentes.</b> O bloco acima soma <b>toda</b> a mensageria da empresa "
                    "(remetentes <i>CDT Relacionamento 9713</i>, <i>CDT Nacional 7537</i>, Energia de Todos, TIM/Tutti, SMS…): "
                    "em ago/26 foram ~1,03 milhão de mensagens e ~R$ 302 mil, dos quais ~90% são réguas de relacionamento e "
                    "engajamento com a base (retenção), não aquisição. A aba 📨 CRM e o relatório da Mesa olham só a "
                    "<b>Instância de Aquisição</b> (templates com 'GT7' no nome — ~108 mil mensagens em ago/26) e usam a régua da "
                    "BD_CRM: mensagens Enviada + Entregue + Lida × R$ 0,32 (a Zenvia cobra também as 'Não Entregue'; a Mesa não "
                    "conta). <b>Quando usar cada um:</b> este bloco para custo total de mensageria (orçamento/contrato Zenvia, "
                    "visão da empresa); a aba 📨 para CPA e CPL do marketing direto de aquisição (a régua do relatório mensal).</div>",
                    unsafe_allow_html=True)

            if not _z_c.empty:
                _top_send = (_z_c.groupby('sender_name')[['total_messages', 'total_price']]
                             .sum().sort_values('total_messages', ascending=False).head(8).reset_index())
                _top_send.columns = ['Remetente', 'Mensagens', 'Custo']
                _top_send['Mensagens'] = _top_send['Mensagens'].apply(format_br)
                _top_send['Custo'] = _top_send['Custo'].apply(format_money)
                st.markdown("**Top remetentes (Zenvia) no período:**")
                st.dataframe(_top_send, use_container_width=True, hide_index=True)

with tab4:
    st.markdown("## 📣 Análise de Campanhas")
    st.caption(f"Custo das plataformas pagas (Google/Meta/TikTok) + eventos de compra do GA, no período "
               f"da barra lateral ({c_s.strftime('%d/%m/%Y')} → {ref_datetime.strftime('%d/%m/%Y')}). "
               f"Volumes vêm sempre do GA; as tabelas de anúncio entram apenas com custo.")

    # session_source_medium fragments that identify CRM traffic in alex_ga_vendas.
    # Confirmed values: 'whatsapp / paidsocial', 'whatsapp / MKT_DIRETO', 'sms / MKT_DIRETO',
    # 'crmtestehubspot / crmtestehubspot'. ('(not set)' is GA's untagged bucket, excluded on
    # purpose; 'crmtestehubspot' looks like a test source — drop 'crm' to exclude it.)
    CRM_SOURCE_PATTERNS = ['whatsapp', 'sms', 'crm']
    GROUP_NAMES = ["Marketing Direto", "Campanhas de Venda", "Vendas Mídia", "Branding", "Leads"]

    camp_cost = load_campaign_costs()
    ga_vendas = load_ga_vendas()
    app_sales = load_app_sales()
    ga_leads = load_ga_leads()
    meta_leads = load_meta_leads()
    cmp_start, cmp_end = c_s, ref_datetime

    def _crm_mask_t4(df, col='session_source_medium'):
        s = df[col].astype(str).str.lower()
        m = pd.Series(False, index=df.index)
        for p in CRM_SOURCE_PATTERNS:
            m = m | s.str.contains(p, na=False, regex=False)
        return m

    def _name_has_t4(series_names, *subs):
        ln = series_names.astype(str).str.lower()
        m = pd.Series(False, index=series_names.index)
        for sub in subs:
            m = m | ln.str.contains(sub, na=False, regex=False)
        return m

    def _src_has_t4(srcs_set, *subs):
        return any(any(sub in s for s in srcs_set) for sub in subs)

    # ---- controls row 1: Canal | Plataforma | Conjunto ----
    col_cf0, col_cf1, col_cf2 = st.columns(3)
    canal_camp = col_cf0.selectbox("Canal:", ["Todos", "Website", "App do Filiado"], key='t4_canal')
    plataforma_camp = col_cf1.selectbox("Plataforma:", ["Google", "Meta", "TikTok", "CRM"], key='t4_plat')
    sel_opts = ["Campanhas individuais", "Todas", "Top 5", "Bottom 5"] + GROUP_NAMES
    sel_tipo = col_cf2.selectbox("Conjunto:", sel_opts, key='t4_seltype')

    crm_is_selected = (plataforma_camp == "CRM")
    group_mode = sel_tipo in GROUP_NAMES

    # ---- controls row 2: Métrica (own row so all options fit) ----
    if group_mode or not crm_is_selected:
        metric_opts = ["Custo", "CPA", "CPL", "Eventos de Compra", "Eventos de Lead"]
    else:
        metric_opts = ["Eventos de Compra", "Eventos de Lead"]
    metrica_camp = st.radio("Métrica:", metric_opts, horizontal=True, key='t4_metric')
    metric_col = {"Custo": "cost", "CPA": "cpa", "CPL": "cpl",
                  "Eventos de Compra": "purchases", "Eventos de Lead": "leads"}[metrica_camp]

    # ---- build the period-bounded campaign universe ----
    #   group_mode   -> cross-platform (group rules span platforms; e.g. affiliate cpc).
    #   CRM          -> GA rows matching CRM source patterns; no cost.
    #   paid (G/M/T) -> that platform's cost-table campaigns, plus their GA purchases.
    # Restricting to the selected period (and platform) is what hides campaigns with no
    # data in the window and campaigns from other platforms.
    ga_p = ga_vendas[(ga_vendas['date'] >= cmp_start) & (ga_vendas['date'] <= cmp_end)].copy()
    cost_p = camp_cost[(camp_cost['date'] >= cmp_start) & (camp_cost['date'] <= cmp_end)].copy()
    ga_leads_p = ga_leads[(ga_leads['date'] >= cmp_start) & (ga_leads['date'] <= cmp_end)].copy()
    meta_leads_p = meta_leads[(meta_leads['date'] >= cmp_start) & (meta_leads['date'] <= cmp_end)].copy()
    app_sales_p = app_sales[(app_sales['date'] >= cmp_start) & (app_sales['date'] <= cmp_end)].copy()
    # When the Plataforma is Meta, leads = GA-tracked leads + on_facebook_leads (Facebook
    # native lead forms, which GA generally can't see, so the two are largely disjoint).
    # on_facebook_leads is read at its native one-row-per-campaign grain (no GA join, so it
    # can't fan out) and summed onto the GA leads.
    meta_leads_mode = (plataforma_camp == "Meta") and not group_mode and not crm_is_selected

    if group_mode:
        cost_scope, ga_scope, ga_leads_scope = cost_p, ga_p, ga_leads_p
        app_scope = app_sales_p
    elif crm_is_selected:
        ga_scope = ga_p[_crm_mask_t4(ga_p)] if not ga_p.empty else ga_p
        ga_leads_scope = ga_leads_p[_crm_mask_t4(ga_leads_p)] if not ga_leads_p.empty else ga_leads_p
        cost_scope = cost_p.iloc[0:0]
        app_scope = app_sales_p.iloc[0:0]
    else:
        cost_scope = cost_p[cost_p['plataforma'] == plataforma_camp]
        _plat_names = set(cost_scope['campaign_name'].dropna().unique())
        ga_scope = ga_p[ga_p['session_campaign_name'].isin(_plat_names)] if not ga_p.empty else ga_p
        ga_leads_scope = ga_leads_p[ga_leads_p['session_campaign_name'].isin(_plat_names)] if not ga_leads_p.empty else ga_leads_p
        app_scope = app_sales_p[app_sales_p['campaign_name'].isin(_plat_names)] if not app_sales_p.empty else app_sales_p

    _cost_by = cost_scope.groupby('campaign_name')['cost'].sum() if not cost_scope.empty else pd.Series(dtype=float)
    _purch_by = ga_scope.groupby('session_campaign_name')['conversions'].sum() if not ga_scope.empty else pd.Series(dtype=float)
    # %download% campaigns: add the ad platforms' in-app conversions (GA can't see them).
    # Disjoint from GA web conversions, so summed — same pattern as the Meta-leads fix.
    _app_by = app_scope.groupby('campaign_name')['purchases'].sum() if not app_scope.empty else pd.Series(dtype=float)
    _purch_by = _purch_by.add(_app_by, fill_value=0)
    if meta_leads_mode:
        _ga_leads_by = (ga_leads_scope.groupby('session_campaign_name')['conversions'].sum()
                        if not ga_leads_scope.empty else pd.Series(dtype=float))
        _ml_scope = (meta_leads_p[meta_leads_p['campaign_name'].isin(_plat_names)]
                     if not meta_leads_p.empty else meta_leads_p)
        _fb_leads_by = (_ml_scope.groupby('campaign_name')['leads'].sum()
                        if not _ml_scope.empty else pd.Series(dtype=float))
        _leads_by = _ga_leads_by.add(_fb_leads_by, fill_value=0)   # GA + on_facebook_leads
    else:
        _leads_by = ga_leads_scope.groupby('session_campaign_name')['conversions'].sum() if not ga_leads_scope.empty else pd.Series(dtype=float)
    _src_by = (ga_scope.groupby('session_campaign_name')['session_source_medium']
               .apply(lambda s: set(x.lower() for x in s.dropna()))
               if not ga_scope.empty else pd.Series(dtype=object))

    _uni_names = sorted(set(_cost_by.index) | set(_purch_by.index) | set(_leads_by.index) | set(_app_by.index))
    uni = pd.DataFrame({'campaign_name': _uni_names})
    uni['cost'] = uni['campaign_name'].map(_cost_by).fillna(0.0)
    uni['purchases'] = uni['campaign_name'].map(_purch_by).fillna(0.0)
    uni['leads'] = uni['campaign_name'].map(_leads_by).fillna(0.0)
    uni['cpa'] = uni['cost'] / uni['purchases'].replace(0, np.nan)
    uni['cpl'] = uni['cost'] / uni['leads'].replace(0, np.nan)
    uni['srcs'] = uni['campaign_name'].map(lambda c: _src_by.get(c, set()))

    # Canal filter (App/Website) on the campaign universe — App = %download% campaigns,
    # Website = everything else. Applied before resolving the selected set, so the
    # Conjunto/Top-Bottom lists, the chart and the per-campaign table all respect it.
    if canal_camp != "Todos" and not uni.empty:
        _is_dl = uni['campaign_name'].str.lower().str.contains('download', na=False)
        uni = uni[_is_dl if canal_camp == "App do Filiado" else ~_is_dl].reset_index(drop=True)

    if group_mode:
        st.caption("ℹ️ Grupos predefinidos são **cross-plataforma** (a seleção de Plataforma é ignorada). "
                   "Agregação por nome de campanha; o custo vem só das tabelas pagas — afiliados (adsplay/"
                   "actionpay) e CRM não têm custo no banco, então entram apenas com eventos de compra.")

    if uni.empty:
        st.info(f"Nenhuma campanha com dados no período "
                f"({cmp_start.strftime('%d/%m/%Y')} → {cmp_end.strftime('%d/%m/%Y')}).")
    else:
        # ---- resolve the campaign set from the chosen "Conjunto" ----
        if sel_tipo == "Campanhas individuais":
            _opts = uni['campaign_name'].tolist()
            campanhas_sel = st.multiselect("Campanha(s):", options=_opts,
                                           default=_opts[:1], key='t4_camps')
        elif sel_tipo == "Todas":
            campanhas_sel = uni['campaign_name'].tolist()
        elif sel_tipo in ("Top 5", "Bottom 5"):
            _asc = (sel_tipo == "Bottom 5")
            campanhas_sel = (uni.dropna(subset=[metric_col]).sort_values(metric_col, ascending=_asc)
                             ['campaign_name'].head(5).tolist())
        elif sel_tipo == "Branding":
            campanhas_sel = uni.loc[_name_has_t4(uni['campaign_name'], 'branding'), 'campaign_name'].tolist()
        elif sel_tipo == "Leads":
            campanhas_sel = uni.loc[_name_has_t4(uni['campaign_name'], 'lead'), 'campaign_name'].tolist()
        elif sel_tipo == "Marketing Direto":
            campanhas_sel = uni.loc[uni['srcs'].map(lambda s: _src_has_t4(s, 'whatsapp / mkt_direto')),
                                    'campaign_name'].tolist()
        elif sel_tipo == "Vendas Mídia":
            campanhas_sel = uni.loc[uni['srcs'].map(lambda s: _src_has_t4(s, 'cpc')), 'campaign_name'].tolist()
        elif sel_tipo == "Campanhas de Venda":
            _mn = _name_has_t4(uni['campaign_name'], 'venda')
            _ms = uni['srcs'].map(lambda s: _src_has_t4(s, 'actionpay / cpc', 'adsplay / cpc'))
            campanhas_sel = uni.loc[_mn | _ms, 'campaign_name'].tolist()
        else:
            campanhas_sel = []

        if sel_tipo in ("Top 5", "Bottom 5"):
            st.caption(f"**{sel_tipo}** por {metrica_camp} → {len(campanhas_sel)} campanha(s).")
        elif sel_tipo == "Todas" or group_mode:
            st.caption(f"**{sel_tipo}** → {len(campanhas_sel)} campanha(s) no período.")

        # ---- controls row 2: Escala | Soma | Visualização ----
        col_cm1, col_cm2, col_cm3 = st.columns(3)
        escala_camp = col_cm1.radio("Escala:", ["Diário", "Semanal", "Mensal"], horizontal=True, key='t4_scale')
        acum_camp = col_cm2.radio("Soma:", ["Por Período", "Acumulado"], horizontal=True, key='t4_acum')
        ver_camp = col_cm3.radio("Visualização:", ["Agregado", "Por Campanha"], horizontal=True, key='t4_view')

        if crm_is_selected and not group_mode:
            st.caption("ℹ️ CRM não tem custo por campanha no banco — os cards usam o custo total de "
                       "mensageria (Zenvia, tabela nova alex_zenvia_sender) no período como aproximação; "
                       "eventos filtrados por session_source_medium.")

        if not campanhas_sel:
            st.info("Nenhuma campanha corresponde a esta seleção no período.")
        else:
            freq = {"Diário": "D", "Semanal": "W-MON", "Mensal": "MS"}[escala_camp]
            is_acum = (acum_camp == "Acumulado")
            per_campaign = (ver_camp == "Por Campanha")
            keys = ['campaign_name'] if per_campaign else []

            # cost from the (paid) scope; CRM-only selections have no cost
            if crm_is_selected and not group_mode:
                cost_f = pd.DataFrame(columns=['date', 'campaign_name', 'cost'])
            else:
                cost_f = cost_scope[cost_scope['campaign_name'].isin(campanhas_sel)].copy()

            # purchases + leads from the GA scopes (already platform/CRM-filtered above)
            purch_f = ga_scope[ga_scope['session_campaign_name'].isin(campanhas_sel)].copy()
            purch_f = purch_f.rename(columns={'session_campaign_name': 'campaign_name', 'conversions': 'purchases'})[['date', 'campaign_name', 'purchases']]
            _app_pf = app_scope[app_scope['campaign_name'].isin(campanhas_sel)].copy()
            if not _app_pf.empty:
                purch_f = pd.concat([purch_f, _app_pf[['date', 'campaign_name', 'purchases']]], ignore_index=True)
            if meta_leads_mode:
                _ga_lf = ga_leads_scope[ga_leads_scope['session_campaign_name'].isin(campanhas_sel)].copy()
                _ga_lf = _ga_lf.rename(columns={'session_campaign_name': 'campaign_name', 'conversions': 'leads'})
                _fb_lf = meta_leads_p[meta_leads_p['campaign_name'].isin(campanhas_sel)].copy()
                leads_f = pd.concat([_ga_lf[['date', 'campaign_name', 'leads']],
                                     _fb_lf[['date', 'campaign_name', 'leads']]], ignore_index=True)
            else:
                leads_f = ga_leads_scope[ga_leads_scope['session_campaign_name'].isin(campanhas_sel)].copy()
                leads_f = leads_f.rename(columns={'session_campaign_name': 'campaign_name', 'conversions': 'leads'})

            def _bucketize(dframe, col):
                if dframe.empty:
                    return pd.DataFrame(columns=keys + ['bucket', col])
                _gargs = dict(key='date', freq=freq)
                if freq.startswith('W'):
                    _gargs.update(closed='left', label='left')   # semana = segunda→domingo
                g = dframe.groupby(keys + [pd.Grouper(**_gargs)])[col].sum().reset_index()
                return g.rename(columns={'date': 'bucket'})

            cost_b = _bucketize(cost_f, 'cost')
            purch_b = _bucketize(purch_f, 'purchases')
            leads_b = _bucketize(leads_f, 'leads')
            merge_on = keys + ['bucket']
            data = pd.merge(cost_b, purch_b, on=merge_on, how='outer')
            data = pd.merge(data, leads_b, on=merge_on, how='outer')
            for _c in ['cost', 'purchases', 'leads']:
                if _c not in data.columns:
                    data[_c] = 0.0
            data[['cost', 'purchases', 'leads']] = data[['cost', 'purchases', 'leads']].fillna(0.0)
            data = data.sort_values(merge_on)

            if is_acum and not data.empty:
                _cum_cols = ['cost', 'purchases', 'leads']
                if per_campaign:
                    for _cc in _cum_cols:
                        data[_cc] = data.groupby('campaign_name')[_cc].cumsum()
                else:
                    for _cc in _cum_cols:
                        data[_cc] = data[_cc].cumsum()

            data['cpa'] = data['cost'] / data['purchases'].replace(0, np.nan)
            data['cpl'] = data['cost'] / data['leads'].replace(0, np.nan)
            metric_label = {"Custo": "Custo (R$)", "CPA": "CPA (R$)", "CPL": "CPL (R$)",
                            "Eventos de Compra": "Eventos de Compra", "Eventos de Lead": "Eventos de Lead"}[metrica_camp]

            # ---- summary metrics, ABOVE the chart, separated and colour-coded ----
            tot_cost = float(cost_f['cost'].sum()) if not cost_f.empty else 0.0
            tot_purch = float(purch_f['purchases'].sum()) if not purch_f.empty else 0.0
            tot_leads = float(leads_f['leads'].sum()) if not leads_f.empty else 0.0
            cpa_avg = (tot_cost / tot_purch) if tot_purch > 0 else None
            cpl_avg = (tot_cost / tot_leads) if tot_leads > 0 else None
            has_cost = not (crm_is_selected and not group_mode)

            def _metric_card(col, label, value, color):
                col.markdown(
                    f"<div style='border-left:5px solid {color};padding:4px 14px;margin-bottom:6px;'>"
                    f"<div style='font-size:0.78rem;color:#6b7280;text-transform:uppercase;letter-spacing:.03em'>{label}</div>"
                    f"<div style='font-size:1.4rem;font-weight:700;color:{color};line-height:1.25'>{value}</div></div>",
                    unsafe_allow_html=True)

            if has_cost:
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                _metric_card(mc1, "Custo total", format_money(tot_cost), "#2563eb")
                _metric_card(mc2, "Ev. de compra", format_br(tot_purch), "#16a34a")
                _metric_card(mc3, "CPA médio",
                             (format_money(cpa_avg) if cpa_avg is not None else "—"), "#d97706")
                _metric_card(mc4, "Ev. de lead", format_br(tot_leads), "#0891b2")
                _metric_card(mc5, "CPL médio",
                             (format_money(cpl_avg) if cpl_avg is not None else "—"), "#7c3aed")
            else:
                # CRM: sem custo por campanha, mas o custo TOTAL de mensageria (Zenvia)
                # do período dá um CPA/CPL aproximado — melhor que nada, e sinalizado.
                _zen_t4 = load_zenvia()
                _zen_p_t4 = (_zen_t4[(_zen_t4['report_date'] >= cmp_start) & (_zen_t4['report_date'] <= cmp_end)]
                             if not _zen_t4.empty else _zen_t4)
                _zen_cost = float(_zen_p_t4['total_price'].sum()) if not _zen_p_t4.empty else 0.0
                _zen_msgs = float(_zen_p_t4['total_messages'].sum()) if not _zen_p_t4.empty else 0.0
                _cpa_crm = (_zen_cost / tot_purch) if (tot_purch > 0 and _zen_cost > 0) else None
                _cpl_crm = (_zen_cost / tot_leads) if (tot_leads > 0 and _zen_cost > 0) else None
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                _metric_card(mc1, "Custo mensageria (Zenvia)", format_money(_zen_cost), "#2563eb")
                _metric_card(mc2, "Ev. de compra", format_br(tot_purch), "#16a34a")
                _metric_card(mc3, "CPA aprox.",
                             (format_money(_cpa_crm) if _cpa_crm is not None else "—"), "#d97706")
                _metric_card(mc4, "Ev. de lead", format_br(tot_leads), "#0891b2")
                _metric_card(mc5, "CPL aprox.",
                             (format_money(_cpl_crm) if _cpl_crm is not None else "—"), "#7c3aed")
                if _zen_msgs > 0:
                    st.caption(f"💬 {format_br(_zen_msgs)} mensagens enviadas (Zenvia) no período.")
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

            # ---- chart ----
            if data.empty or data[metric_col].dropna().empty:
                st.info("Sem dados para a combinação selecionada.")
            else:
                fig_camp = px.line(data, x='bucket', y=metric_col,
                                   color=('campaign_name' if per_campaign else None), markers=True)
                fig_camp.update_layout(margin=dict(t=10, b=0, l=0, r=0), xaxis_title=escala_camp,
                                       yaxis_title=f"{metric_label} ({acum_camp})", legend_title="Campanha")
                st.plotly_chart(fig_camp, use_container_width=True, key='t4_chart')

            # ---- per-campaign table (formato relatório VENDAS | Campanhas) ----
            # Impressões/Cliques vêm das tabelas de plataforma (load_platform_daily);
            # CTR = cliques/impressões; TX Conv. Leads = leads/cliques;
            # TX Conv. Vendas = vendas/cliques (mesmas definições do relatório BI).
            st.markdown("##### 📋 Detalhamento por campanha (período)")
            _pd_t4 = load_platform_daily()
            _pd_scope = (_pd_t4[(_pd_t4['date'] >= cmp_start) & (_pd_t4['date'] <= cmp_end)]
                         if not _pd_t4.empty else _pd_t4)
            if not group_mode and not crm_is_selected and not _pd_scope.empty:
                _pd_scope = _pd_scope[_pd_scope['plataforma'] == plataforma_camp]
            if not _pd_scope.empty:
                _pd_scope = _pd_scope[_pd_scope['campaign_name'].isin(campanhas_sel)]
            if not _pd_scope.empty:
                _ic_by = _pd_scope.groupby('campaign_name')[['impressions', 'clicks']].sum()
            else:
                _ic_by = pd.DataFrame(columns=['impressions', 'clicks'])

            _tbl = uni[uni['campaign_name'].isin(campanhas_sel)].copy()
            _tbl['impressions'] = _tbl['campaign_name'].map(_ic_by['impressions']) if not _ic_by.empty else np.nan
            _tbl['clicks'] = _tbl['campaign_name'].map(_ic_by['clicks']) if not _ic_by.empty else np.nan
            _tbl['ctr'] = _tbl['clicks'] / _tbl['impressions'].replace(0, np.nan)
            _tbl['tx_leads'] = _tbl['leads'] / _tbl['clicks'].replace(0, np.nan)
            _tbl['tx_vendas'] = _tbl['purchases'] / _tbl['clicks'].replace(0, np.nan)
            _tbl = _tbl[['campaign_name', 'impressions', 'clicks', 'cost', 'ctr',
                         'leads', 'cpl', 'tx_leads', 'purchases', 'cpa', 'tx_vendas']].rename(columns={
                'campaign_name': 'Campanha', 'impressions': 'Impressões', 'clicks': 'Cliques',
                'cost': 'Investimento', 'ctr': 'CTR', 'leads': 'Leads (GA4)', 'cpl': 'CPL',
                'tx_leads': 'TX Conv. Leads', 'purchases': 'Vendas (GA4)', 'cpa': 'CPA',
                'tx_vendas': 'TX Conv. Vendas'})
            _tbl = _tbl.sort_values('Investimento', ascending=False)

            _money_t = lambda v: format_money(v) if pd.notna(v) else "—"
            _int_t = lambda v: format_br(v) if pd.notna(v) else "—"
            _pct1_t = lambda v: (f"{v * 100:.1f}%".replace('.', ',') if pd.notna(v) else "—")
            _pct2_t = lambda v: (f"{v * 100:.2f}%".replace('.', ',') if pd.notna(v) else "—")

            def _scale_colors_t4(s, higher_is_better=False):
                # Escala verde→vermelho dentro da coluna (verde = melhor). Sem matplotlib:
                # interpola entre o verde (39,174,96) e o vermelho (231,76,60) do app.
                v = pd.to_numeric(s, errors='coerce')
                mn, mx = v.min(), v.max()
                out = []
                for x in v:
                    if pd.isna(x) or pd.isna(mn) or mx == mn:
                        out.append('')
                        continue
                    t = (x - mn) / (mx - mn)          # 0 = menor valor da coluna
                    if higher_is_better:
                        t = 1 - t                      # maior = melhor → verde
                    r = int(39 + (231 - 39) * t)
                    g = int(174 + (76 - 174) * t)
                    b = int(96 + (60 - 96) * t)
                    out.append(f'background-color: rgba({r},{g},{b},0.25)')
                return out

            _styled = (_tbl.style
                       .format({'Impressões': _int_t, 'Cliques': _int_t,
                                'Investimento': _money_t, 'CTR': _pct1_t,
                                'Leads (GA4)': _int_t, 'CPL': _money_t, 'TX Conv. Leads': _pct1_t,
                                'Vendas (GA4)': _int_t, 'CPA': _money_t, 'TX Conv. Vendas': _pct2_t})
                       .apply(_scale_colors_t4, subset=['CPA'])
                       .apply(lambda s: _scale_colors_t4(s, higher_is_better=True),
                              subset=['TX Conv. Vendas']))
            st.dataframe(_styled, use_container_width=True, hide_index=True)
            st.caption("Uma linha por campanha ativa no período (conjunto selecionado). Impressões/Cliques "
                       "das tabelas de plataforma (CRM não tem); Investimento das tabelas pagas; Leads/Vendas "
                       "e taxas do GA4. CTR = cliques÷impressões; TX Conv. Leads = leads÷cliques; "
                       "TX Conv. Vendas = vendas÷cliques. CPA colorido do menor (verde) ao maior (vermelho) "
                       "do conjunto. Clique num cabeçalho para ordenar.")

# =====================================================================
# TAB 5: SITE — funil do checkout (piloto) + visão site (abaixo)
# ---------------------------------------------------------------------
# Aba piloto para o uso diário do especialista de mídia. Funil do checkout
# do site (hosts adesao/solicite), com dados da tabela alex_ga_checkout_funnel
# (planilha "Ad Sources & Events" → Scripts/ga_checkout_funnel_to_mysql.py).
#
# Desde 25/08 cada etapa tem DUAS métricas, alternáveis na aba:
#   👤 Usuários ativos (GA4 activeUsers) — pessoas únicas por dia; visão padrão.
#   ⚡ Eventos (GA4 eventCount) — disparos; visão de CONTROLE para detectar
#      re-disparo em excesso numa etapa (ex.: retentativas de pagamento).
# A razão disparos/usuário aparece sob o nome de cada etapa (âmbar quando >1,3).
#
#   Etapa 0  Usuários ativos       <- active_users (totalUsers; só usuários)
#   Etapa 1  Início de checkout    <- generate_lead / generate_lead_users
#   Etapa 2  Dados de envio        <- add_shipping_info / add_shipping_info_users
#   Etapa 3  Dados de pagamento    <- add_payment_info / add_payment_info_users
#   Etapa 4  Compra (purchase)     <- purchase / purchase_users (site todo)
#
# Vendas CTN = RESUMO_VENDAS_DIARIAS (nominal) tipo_venda = Website, para
# reconciliação com o número oficial. Tudo aqui é ADITIVO às abas 1-4.
# =====================================================================
with tab5:
    st.markdown("## Performance do Funil de Vendas — Website Checkout")
    st.caption("🧪 **Aba piloto** — em teste para o uso diário do especialista de mídia. "
               "O período atual e o de comparação seguem os **Controles Globais** da barra lateral. "
               "Funil restrito ao checkout do site (hosts adesao/solicite). "
               "O mesmo funil aparece na aba 🧲 Aquisição (Funis por superfície · Site) **no grão mensal e em usuários**: com o "
               "período igual a meses inteiros os números coincidem; com dias/semanas, só aqui o corte é exato. Os **Leads Únicos do "
               "HubSpot** não entram neste funil — contam Contatos de todas as portas, não só o checkout.")

    # ---- linha de filtros (período | comparação | canal fixo | exportar) ----
    f5c1, f5c2, f5c3, f5c4 = st.columns([1.35, 1.35, 1, 0.8])

    def _period_box5(col, label, s, e):
        col.markdown(
            f"<div style='border:1px solid #e2e8f0;border-radius:10px;padding:7px 12px;background:#fff;'>"
            f"<div style='font-size:10.5px;color:#64748b;font-weight:600;'>{label}</div>"
            f"<div style='font-size:13px;color:#0f172a;font-weight:700;'>📅 {s.strftime('%d/%m/%Y')} a {e.strftime('%d/%m/%Y')}</div>"
            f"</div>", unsafe_allow_html=True)

    _period_box5(f5c1, "Período atual", c_s, ref_datetime)
    _period_box5(f5c2, "Comparar com (anterior, parcial)", p_s, p_partial)
    f5c3.markdown(
        "<div style='border:1px solid #bbf7d0;border-radius:10px;padding:7px 12px;background:#f0fdf4;'>"
        "<div style='font-size:10.5px;color:#166534;font-weight:600;'>Canal</div>"
        "<div style='font-size:13px;color:#14532d;font-weight:700;'>🌐 Website (checkout)</div>"
        "</div>", unsafe_allow_html=True)
    # f5c4 recebe o botão Exportar DEPOIS do cálculo (containers preservam a posição).

    metrica_f5 = st.radio("Métrica do funil:",
                          ["👤 Usuários ativos", "⚡ Eventos (controle)"],
                          horizontal=True, key='t5_metrica')
    modo_usuarios5 = metrica_f5.startswith("👤")

    # ---- dados ----
    ckt5 = load_checkout_funnel()

    # (ícone, rótulo, coluna de eventos ou None, coluna de usuários)
    CHECKOUT_STAGES5 = [
        ('👥', 'Etapa 0 · Usuários ativos', None, 'active_users'),
        ('📝', 'Etapa 1 · Início de checkout', 'generate_lead', 'generate_lead_users'),
        ('🚚', 'Etapa 2 · Dados de envio', 'add_shipping_info', 'add_shipping_info_users'),
        ('💳', 'Etapa 3 · Dados de pagamento', 'add_payment_info', 'add_payment_info_users'),
        ('🛒', 'Etapa 4 · Compra (purchase)', 'purchase', 'purchase_users'),
    ]

    def checkout_stage_values5(s, e):
        """Lista de (icone, rotulo, valor_ou_None, is_placeholder, disparos_por_usuario).
        O valor segue a métrica selecionada (usuários ou eventos); a Etapa 0 é
        sempre usuários (não é um evento). Coluna 100% NULA no período vira
        placeholder — nunca zero falso. A razão eventos/usuários é calculada
        quando ambas as métricas existem (controle de re-disparo)."""
        d = ckt5[(ckt5['date'] >= s) & (ckt5['date'] <= e)] if not ckt5.empty else ckt5
        out = []
        for ic, lbl, ev_col, us_col in CHECKOUT_STAGES5:
            col = us_col if (modo_usuarios5 or ev_col is None) else ev_col
            if d.empty or col not in d.columns or d[col].notna().sum() == 0:
                out.append((ic, lbl, None, True, None))
                continue
            val = float(d[col].sum(skipna=True))
            ratio = None
            if ev_col and ev_col in d.columns and us_col in d.columns:
                ev_sum = float(d[ev_col].sum(skipna=True))
                us_sum = float(d[us_col].sum(skipna=True))
                if us_sum > 0 and d[ev_col].notna().sum() > 0:
                    ratio = ev_sum / us_sum
            out.append((ic, lbl, val, False, ratio))
        return out

    stages_c5 = checkout_stage_values5(c_s, ref_datetime)
    stages_p5 = checkout_stage_values5(p_s, p_partial)
    prev_by_lbl5 = {lbl: v for _ic, lbl, v, ph, _rt in stages_p5 if not ph}

    _purchases_c5 = next((v for _i, l, v, ph, _rt in stages_c5
                          if l.endswith('Compra (purchase)') and not ph), 0.0) or 0.0
    _purchases_p5 = prev_by_lbl5.get('Etapa 4 · Compra (purchase)', 0.0)
    _metric_word5 = "usuários" if modo_usuarios5 else "eventos"

    def ctn_vendas5(s, e):
        d5 = df[(df['data_venda'] >= s) & (df['data_venda'] <= e)]
        if d5.empty:
            return 0.0
        return float(d5.loc[d5['tipo_venda'].str.lower().eq('website'), 'Vendas'].sum())

    ctn_c5 = ctn_vendas5(c_s, ref_datetime)
    ctn_p5 = ctn_vendas5(p_s, p_partial)

    if ckt5.empty:
        _err_ckt5 = st.session_state.get('_err_checkout_funnel')
        if _err_ckt5:
            st.error(f"⚠️ Falha ao ler `alex_ga_checkout_funnel` — a query levantou: `{_err_ckt5}`. "
                     "A leitura é refeita a cada rerun (o erro não fica em cache); se persistir, confira a conexão "
                     "em `.streamlit/secrets.toml` e rode `diagnostics/db_check.py`.")
        else:
            st.warning("⚠️ A tabela `alex_ga_checkout_funnel` existe mas está vazia. Confira a rodada do "
                       "Apps Script Checkout_Funnel.gs (planilha Ad Sources & Events).")

    # ---- helpers de formatação ----
    def _pct_br5(x, nd=1):
        if x is None:
            return "—"
        return f"{x * 100:.{nd}f}%".replace('.', ',')

    def _delta_pct5(curr, prev):
        if curr is None or prev is None or prev <= 0:
            return None
        return (curr - prev) / prev * 100

    def _delta_chip5(curr, prev):
        d = _delta_pct5(curr, prev)
        if d is None:
            return ""
        if abs(d) < 0.05:
            bg, fg = "#f1f5f9", "#475569"
        elif d > 0:
            bg, fg = "#dcfce7", "#15803d"
        else:
            bg, fg = "#fee2e2", "#b91c1c"
        sign = "+" if d > 0 else ""
        return (f"<span style='background:{bg};color:{fg};font-weight:700;font-size:11.5px;"
                f"padding:2px 8px;border-radius:10px;white-space:nowrap;'>{sign}{d:.0f}%</span>")

    def _ratio_html5(ratio):
        # Razão disparos/usuário: controle de re-disparo. Âmbar acima de 1,3.
        if ratio is None:
            return ""
        color = "#b45309" if ratio > 1.3 else "#94a3b8"
        weight = "700" if ratio > 1.3 else "600"
        r_txt = f"{ratio:.2f}".replace('.', ',')
        return (f"<div style='font-size:10.5px;color:{color};font-weight:{weight};'>"
                f"⚡ {r_txt} disp./usuário</div>")

    real_c5 = [(lbl, v) for _ic, lbl, v, ph, _rt in stages_c5 if not ph]
    top_lbl5, top_val_c5 = (real_c5[0] if real_c5 else ("", 0.0))
    top_val_p5 = prev_by_lbl5.get(top_lbl5, 0.0)
    conv_total_c5 = (_purchases_c5 / top_val_c5) if top_val_c5 > 0 else None
    conv_total_p5 = (_purchases_p5 / top_val_p5) if (top_val_p5 or 0) > 0 else None

    # Gargalo = menor taxa de conversão sequencial entre etapas com dados.
    gargalo_lbl5, gargalo_rate5 = "—", None
    for _i in range(1, len(real_c5)):
        _prev_lbl, _prev_v = real_c5[_i - 1]
        _lbl, _v = real_c5[_i]
        if _prev_v > 0:
            _r = _v / _prev_v
            if gargalo_rate5 is None or _r < gargalo_rate5:
                gargalo_rate5 = _r
                _n_prev = _prev_lbl.split('·')[0].strip()
                _n_cur = _lbl.split('·')[0].strip()
                gargalo_lbl5 = f"{_n_prev} → {_n_cur}"

    # ---- cards de KPI ----
    def _kpi_card5(col, icon, label, value_html, sub):
        col.markdown(
            f"<div style='border:1px solid #e2e8f0;border-radius:12px;padding:13px 15px;background:#fff;height:100%;'>"
            f"<div style='display:flex;align-items:center;gap:10px;'>"
            f"<div style='width:38px;height:38px;border-radius:50%;background:#166534;display:flex;"
            f"align-items:center;justify-content:center;font-size:17px;flex:0 0 38px;'>{icon}</div>"
            f"<div style='min-width:0;'>"
            f"<div style='font-size:11.5px;color:#64748b;font-weight:600;'>{label}</div>"
            f"<div style='font-size:21px;font-weight:800;color:#0f172a;line-height:1.2;'>{value_html}</div>"
            f"<div style='font-size:11px;color:#94a3b8;'>{sub}</div>"
            f"</div></div></div>", unsafe_allow_html=True)

    k1, k2, k3, k4 = st.columns(4)
    _kpi_card5(k1, "🛒", "Vendas CTN (Website, nominal)",
               f"{format_br(ctn_c5)} {_delta_chip5(ctn_c5, ctn_p5)}",
               f"Período anterior: {format_br(ctn_p5)}")
    _kpi_card5(k2, "📈", f"Compras GA ({_metric_word5})",
               f"{format_br(_purchases_c5)} {_delta_chip5(_purchases_c5, _purchases_p5)}",
               f"Período anterior: {format_br(_purchases_p5)}")
    _kpi_card5(k3, "📊", f"Conversão total (Etapa 0 → 4, {_metric_word5})",
               _pct_br5(conv_total_c5, 2),
               f"Período anterior: {_pct_br5(conv_total_p5, 2)}")
    _kpi_card5(k4, "❗", "Maior gargalo", gargalo_lbl5,
               "Menor taxa de conversão sequencial")
    st.caption("ℹ️ **Vendas CTN** = nominal oficial (RESUMO_VENDAS_DIARIAS, tipo Website). "
               "**Compras GA** = evento purchase do GA4 (site todo, sem filtro de host). "
               "Usuários no período = soma dos usuários únicos DIÁRIOS (quem visita em vários "
               "dias conta em cada dia); a régua de reconciliação GA × nominal continua sendo "
               "a diferença entre os dois cards.")

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    # ---- funil + conversão até a compra ----
    col_fun5, col_conv5 = st.columns([1.9, 1])

    GREEN_RAMP5 = ['#1e6b3c', '#2e8a4f', '#57a86f', '#8cc79e', '#c8e3cf']

    with col_fun5:
        _max_v5 = max((v for _lbl, v in real_c5), default=0.0)
        _tit_metr5 = "usuários ativos" if modo_usuarios5 else "eventos (controle)"
        _leg = (f"<div style='display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:8px;'>"
                f"<div style='font-size:15px;font-weight:800;color:#0f172a;margin-right:6px;'>Funil do checkout "
                f"<span style='font-size:11.5px;color:#166534;font-weight:700;'>· {_tit_metr5}</span></div>"
                f"<div style='font-size:11px;color:#475569;'><span style='display:inline-block;width:10px;height:10px;"
                f"background:#2e8a4f;border-radius:2px;margin-right:4px;'></span>Período atual "
                f"({c_s.strftime('%d/%m')}–{ref_datetime.strftime('%d/%m')})</div>"
                f"<div style='font-size:11px;color:#475569;'><span style='display:inline-block;width:10px;height:10px;"
                f"background:#94a3b8;border-radius:2px;margin-right:4px;'></span>Período anterior "
                f"({p_s.strftime('%d/%m')}–{p_partial.strftime('%d/%m')})</div>"
                f"<div style='margin-left:auto;font-size:10.5px;font-weight:700;color:#166534;'>Conversão sequencial"
                f"<span style='display:block;font-weight:600;color:#64748b;'>Atual | Anterior</span></div></div>")

        _rows_html5 = [_leg]
        _idx_real5 = 0
        _prev_c5 = None
        _prev_p5 = None
        for _ic, _lbl, _v, _ph, _rt in stages_c5:
            _label_cell = (f"<div style='flex:0 0 190px;display:flex;align-items:center;gap:8px;'>"
                           f"<div style='width:32px;height:32px;border-radius:8px;background:#14532d;display:flex;"
                           f"align-items:center;justify-content:center;font-size:15px;flex:0 0 32px;'>{_ic}</div>"
                           f"<div><div style='font-size:12.5px;font-weight:700;color:#0f172a;'>{_lbl}</div>"
                           f"{_ratio_html5(_rt)}</div></div>")
            if _ph:
                _bar = (f"<div style='flex:1;display:flex;justify-content:center;'>"
                        f"<div style='width:70%;border:2px dashed #cbd5e1;border-radius:8px;padding:7px 10px;"
                        f"text-align:center;color:#94a3b8;font-size:11.5px;'>sem dados desta métrica no "
                        f"período — verifique o refresh do Supermetrics e a rodada do script de importação</div></div>")
                _conv_cells = ("<div style='flex:0 0 60px;text-align:right;font-size:12px;color:#94a3b8;'>—</div>"
                               "<div style='flex:0 0 60px;text-align:right;font-size:12px;color:#94a3b8;'>—</div>")
            else:
                _vp = prev_by_lbl5.get(_lbl)
                _wid = (30 + 70 * (_v / _max_v5)) if _max_v5 > 0 else 30
                _bg = GREEN_RAMP5[min(_idx_real5, len(GREEN_RAMP5) - 1)]
                _fg = '#ffffff' if _idx_real5 < 2 else '#14532d'
                _sub_fg = 'rgba(255,255,255,.85)' if _idx_real5 < 2 else '#3f6212'
                _conv_at = (_v / _prev_c5) if (_prev_c5 and _prev_c5 > 0) else None
                _conv_an = ((_vp / _prev_p5) if (_vp is not None and _prev_p5 and _prev_p5 > 0) else None)
                _vp_txt = format_br(_vp) if _vp is not None else "—"
                _bar = (f"<div style='flex:1;display:flex;justify-content:center;'>"
                        f"<div style='width:{_wid:.1f}%;background:{_bg};border-radius:8px;padding:6px 12px;"
                        f"display:flex;align-items:center;justify-content:center;gap:10px;min-width:170px;'>"
                        f"<div style='text-align:center;'>"
                        f"<div style='font-size:16px;font-weight:800;color:{_fg};line-height:1.15;'>{format_br(_v)}</div>"
                        f"<div style='font-size:11px;color:{_sub_fg};'>{_vp_txt}</div></div>"
                        f"{_delta_chip5(_v, _vp)}</div></div>")
                _conv_cells = (f"<div style='flex:0 0 60px;text-align:right;font-size:12.5px;font-weight:700;"
                               f"color:#0f172a;'>{_pct_br5(_conv_at)}</div>"
                               f"<div style='flex:0 0 60px;text-align:right;font-size:12.5px;color:#64748b;'>"
                               f"{_pct_br5(_conv_an)}</div>")
                _prev_c5 = _v
                _prev_p5 = _vp if _vp is not None else None
                _idx_real5 += 1
            _rows_html5.append(f"<div style='display:flex;align-items:center;gap:10px;padding:5px 0;"
                               f"border-top:1px solid #f1f5f9;'>{_label_cell}{_bar}{_conv_cells}</div>")

        st.markdown("<div style='border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;background:#fff;'>"
                    + "".join(_rows_html5) + "</div>", unsafe_allow_html=True)
        st.caption("Fonte: GA4 (hosts adesao/solicite; Etapa 4 = site todo) via planilha Ad Sources & Events → "
                   "tabela `alex_ga_checkout_funnel`. **👤 Usuários** = pessoas únicas por dia (activeUsers); "
                   "**⚡ Eventos** = disparos (eventCount). A razão ⚡ disp./usuário sob cada etapa denuncia "
                   "re-disparo em excesso (âmbar acima de 1,3). Conversão sequencial calculada sobre a etapa "
                   "anterior com dados.")

    with col_conv5:
        _conv_rows5 = ["<div style='font-size:15px;font-weight:800;color:#0f172a;margin-bottom:10px;'>"
                       "Conversão até a compra</div>"]
        for _lbl, _v in real_c5[:-1]:
            _pct = (_purchases_c5 / _v) if _v > 0 else None
            _w = min((_pct or 0) * 100, 100)
            _short = _lbl.split('·')[0].strip()
            _conv_rows5.append(
                f"<div style='padding:7px 0;border-top:1px solid #f1f5f9;'>"
                f"<div style='display:flex;justify-content:space-between;align-items:baseline;'>"
                f"<div style='font-size:12.5px;color:#334155;font-weight:600;'>{_short} → Compra</div>"
                f"<div style='font-size:14px;font-weight:800;color:#0f172a;'>{_pct_br5(_pct, 2)}</div></div>"
                f"<div style='height:7px;background:#e5e7eb;border-radius:4px;margin-top:5px;'>"
                f"<div style='height:7px;width:{_w:.2f}%;background:#15803d;border-radius:4px;'></div></div></div>")
        st.markdown("<div style='border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;background:#fff;'>"
                    + "".join(_conv_rows5) + "</div>", unsafe_allow_html=True)

        # ---- card de insight automático ----
        _d_top5 = _delta_pct5(top_val_c5, top_val_p5)
        _d_ven5 = _delta_pct5(_purchases_c5, _purchases_p5)
        if _d_top5 is not None and _d_ven5 is not None:
            _ven_txt = f"{'+' if _d_ven5 > 0 else ''}{_d_ven5:.0f}%"
            if _d_top5 < 0 and _d_ven5 > 0:
                _insight5 = (f"O volume caiu no topo, mas as compras ({_metric_word5}) cresceram "
                             f"<b style='color:#15803d;'>{_ven_txt}</b> com melhora nas etapas finais do checkout.")
            elif _d_top5 >= 0 and _d_ven5 > 0:
                _insight5 = (f"Volume e compras cresceram — compras ({_metric_word5}) "
                             f"<b style='color:#15803d;'>{_ven_txt}</b> vs. período anterior.")
            elif _d_top5 >= 0 and _d_ven5 <= 0:
                _insight5 = (f"O topo do funil cresceu, mas as compras ({_metric_word5}) variaram "
                             f"<b style='color:#b91c1c;'>{_ven_txt}</b> — atenção às etapas finais "
                             f"(gargalo: {gargalo_lbl5}).")
            else:
                _insight5 = (f"Volume e compras em queda ({_ven_txt} em compras) — verifique aquisição "
                             f"e o gargalo {gargalo_lbl5}.")
            # Alerta de re-disparo: maior razão disparos/usuário do período atual.
            _worst_rt5 = max(((_rt, _lbl) for _ic, _lbl, _v, _ph, _rt in stages_c5 if _rt is not None),
                             default=(None, None))
            if _worst_rt5[0] is not None and _worst_rt5[0] > 1.3:
                _r_txt5 = f"{_worst_rt5[0]:.2f}".replace('.', ',')
                _insight5 += (f" ⚠️ <b>{_worst_rt5[1].split('·')[1].strip()}</b> está com "
                              f"{_r_txt5} disparos por usuário — possível re-disparo em excesso.")
            st.markdown(
                f"<div style='border-radius:12px;padding:16px;background:#ecfdf5;margin-top:12px;"
                f"display:flex;gap:12px;align-items:flex-start;'>"
                f"<div style='width:36px;height:36px;border-radius:50%;background:#166534;display:flex;"
                f"align-items:center;justify-content:center;font-size:16px;flex:0 0 36px;'>💡</div>"
                f"<div style='font-size:14px;color:#0f172a;line-height:1.5;'>{_insight5}</div></div>",
                unsafe_allow_html=True)

    # ---- exportação CSV (botão na linha de filtros, canto direito) ----
    # Sempre exporta AS DUAS métricas, independente da visão selecionada.
    def _stage_sums5(s, e):
        d = ckt5[(ckt5['date'] >= s) & (ckt5['date'] <= e)] if not ckt5.empty else ckt5
        out = {}
        for _ic, lbl, ev_col, us_col in CHECKOUT_STAGES5:
            for col in (ev_col, us_col):
                if col and (not d.empty) and col in d.columns and d[col].notna().sum() > 0:
                    out[col] = int(d[col].sum(skipna=True))
                elif col:
                    out[col] = None
        return out

    _sums_c5 = _stage_sums5(c_s, ref_datetime)
    _sums_p5 = _stage_sums5(p_s, p_partial)
    _exp_rows5 = []
    _prev_us5 = None
    for _ic, _lbl, _ev_col, _us_col in CHECKOUT_STAGES5:
        _us_c = _sums_c5.get(_us_col)
        _us_p = _sums_p5.get(_us_col)
        _ev_c = _sums_c5.get(_ev_col) if _ev_col else None
        _ev_p = _sums_p5.get(_ev_col) if _ev_col else None
        _pu_c = _sums_c5.get('purchase_users')
        _exp_rows5.append({
            'Etapa': _lbl,
            'Usuários (atual)': _us_c, 'Usuários (anterior)': _us_p,
            'Eventos (atual)': _ev_c, 'Eventos (anterior)': _ev_p,
            'Disparos/usuário (atual)': (round(_ev_c / _us_c, 3) if (_ev_c and _us_c) else None),
            'Conv. sequencial usuários (atual)': (round(_us_c / _prev_us5, 4)
                                                  if (_us_c is not None and _prev_us5) else None),
            'Conv. até compra usuários (atual)': (round(_pu_c / _us_c, 4)
                                                  if (_pu_c is not None and _us_c) else None),
        })
        if _us_c is not None:
            _prev_us5 = _us_c
    _exp_rows5.append({'Etapa': 'Vendas CTN (Website, nominal)',
                       'Usuários (atual)': int(ctn_c5), 'Usuários (anterior)': int(ctn_p5),
                       'Eventos (atual)': None, 'Eventos (anterior)': None,
                       'Disparos/usuário (atual)': None,
                       'Conv. sequencial usuários (atual)': None,
                       'Conv. até compra usuários (atual)': None})
    _exp_df5 = pd.DataFrame(_exp_rows5)
    f5c4.download_button(
        "⬆️ Exportar",
        _exp_df5.to_csv(index=False, sep=';', decimal=','),
        file_name=f"funil_checkout_{c_s.strftime('%Y%m%d')}_{ref_datetime.strftime('%Y%m%d')}.csv",
        mime="text/csv", use_container_width=True, key='t5_export')


# =====================================================================
# TAB 6: TELEVENDAS — Escallo × HubSpot × Talkerchat × NOMINAL
# ---------------------------------------------------------------------
# Aba aditiva às abas 1-5. Lê SOMENTE a tabela agregada mensal
# `alex_tv_dash_mes` (mes, secao, dim, metrica, valor), reconstruída pelo
# pipeline `gt7 run televendas_dash` (claude-toolkit/pipelines/televendas_dash.py).
# As varreduras pesadas (contacts/deals/NOMINAL/Talkerchat) rodam no pipeline,
# nunca aqui — a aba só soma meses e desenha.
#
# Granularidade = MÊS: o período dos Controles Globais é arredondado para os
# meses que ele toca (c_s → ref_datetime); o "período anterior" idem.
#
# Seções (sub-abas):
#   1 Escallo · Ativo      discados → alô ≥10s → negociação (inclui vendas) → venda tabulada → confirmada no CTN
#   2 Escallo · Receptivo  recebidas → alô → venda; nada volta ao CRM; vendas por tel-8 e tipo
#   3 Ganhos por porta     Negócio GANHO: tabulação (porta 1) × checkout (porta 2) × outros
#   4 Três réguas          GANHO × Contato (CTN) × NOMINAL_VENDAS — como ler
#   5 Pipeline CRM         LEAD → EM NEGOCIAÇÃO → CONTATO SEM SUCESSO → PERDIDO → GANHO + auditoria
#   6 Grupos A–D           entradas por grupo de roteamento (de-para em GRUPOS_CANAL abaixo)
#   7 Talkerchat           usuários únicos → com CPF → Lia/humano → compra → NOMINAL; sem Negócios
# =====================================================================
try:
    import cdt_theme  # tema visual (estilos A/B) — cdt_theme.py ao lado do app.py
    cdt_theme.register()
    _CDT_THEME = True
except Exception:
    _CDT_THEME = False

_TV_COLS = ['mes', 'secao', 'dim', 'metrica', 'valor', 'atualizado_em']


@st.cache_data(ttl=43200)
def _load_tv_dash_raw():
    # Só o SELECT é cacheado; uma falha levanta exceção (e portanto NÃO fica presa no cache por 12 h).
    d = cquery("SELECT mes, secao, dim, metrica, valor, atualizado_em FROM alex_tv_dash_mes", ttl=0)
    d['mes'] = pd.to_datetime(d['mes'])
    d['valor'] = pd.to_numeric(d['valor'], errors='coerce')
    return d


@st.cache_data(ttl=43200)
def _load_tv_dash_sem_raw():
    # Grão semanal (alex_tv_dash_sem, semana = segunda-feira); coluna renomeada para `mes` para reaproveitar os helpers.
    d = cquery("SELECT semana AS mes, secao, dim, metrica, valor, atualizado_em FROM alex_tv_dash_sem", ttl=0)
    d['mes'] = pd.to_datetime(d['mes'])
    d['valor'] = pd.to_numeric(d['valor'], errors='coerce')
    return d


def load_tv_dash():
    """Wrapper sem cache: devolve (mensal, semanal, erro). O semanal é opcional (a tabela pode não existir ainda)."""
    try:
        d_m = _load_tv_dash_raw()
    except Exception as e:
        return pd.DataFrame(columns=_TV_COLS), pd.DataFrame(columns=_TV_COLS), f"{type(e).__name__}: {str(e)[:400]}"
    try:
        d_w = _load_tv_dash_sem_raw()
    except Exception:
        d_w = pd.DataFrame(columns=_TV_COLS)
    return d_m, d_w, None



# R37 — dimensão de ramais do Escallo ativo (pipeline televendas_dash, seção s9): tipo do ramal, agente dominante do mês,
# IDPV(s) do vendedor em alex_idpvs e o número externo que o cliente vê. O e-mail do agente fica no banco, não na tela.
_TV_RAMAL_COLS = ['mes', 'ramal', 'tipo', 'cod_agente', 'nome_agente', 'vendedor', 'ligacoes', 'lig_com_agente', 'alo10',
                  'n_agentes', 'idpvs', 'n_idpv', 'numero_externo']
_TV_TIPO_RAMAL = {'humano': 'Operador humano', 'sistema': 'Linha de sistema (sem agente)', 'treinamento': 'Treinamento / qualidade',
                  'sem_login': 'Sem agente logado (baixo volume)', 'externo': 'Número externo (não é ramal)'}
_TV_TIPO_ORDEM = {'humano': 0, 'sistema': 1, 'treinamento': 2, 'sem_login': 3, 'externo': 4}


@st.cache_data(ttl=43200)
def _load_tv_ramal_dim_raw():
    d = cquery("SELECT mes, ramal, tipo, cod_agente, nome_agente, vendedor, ligacoes, lig_com_agente, alo10, n_agentes, "
               "idpvs, n_idpv, numero_externo FROM alex_tv_ramal_dim", ttl=0)
    d['mes'] = pd.to_datetime(d['mes'])
    for c in ('ligacoes', 'lig_com_agente', 'alo10', 'n_agentes', 'n_idpv'):
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0)
    d['ramal'] = d['ramal'].astype(str)
    return d


def _load_tv_ramal_dim():
    """Sem cache: a tabela pode não existir ainda → DataFrame vazio (a aba cai na heurística antiga)."""
    try:
        return _load_tv_ramal_dim_raw()
    except Exception:
        return pd.DataFrame(columns=_TV_RAMAL_COLS)


def _tv_nome_curto(nome):
    """'WEDNA LEYDIANNE MARQUES DA SILVA' → 'Wedna L. M. da Silva' (1º e último nomes inteiros; partículas minúsculas)."""
    if not nome or not isinstance(nome, str):
        return ""
    toks = [t for t in nome.strip().split() if t]
    if len(toks) <= 2:
        return " ".join(t.capitalize() for t in toks)
    part = {'DA', 'DE', 'DO', 'DAS', 'DOS', 'E', 'DI', 'DEL'}
    meio = [(t.lower() if t.upper() in part else t[0].upper() + ".") for t in toks[1:-1]]
    return " ".join([toks[0].capitalize()] + meio + [toks[-1].capitalize()])


# De-para canal de origem (primeiro_canal_de_origem) → grupo de roteamento da Jornada HubSpot.
# Ajuste aqui; não precisa rodar o pipeline de novo. Ordem importa (primeira regra que casa vence).
GRUPOS_CANAL = [
    # (teste no canal em minúsculas, grupo, rótulo)
    (lambda c: c.startswith('whatsapp'),                          'A', 'Whatsapp'),
    (lambda c: 'regional' in c,                                   'B', 'Regionais'),
    (lambda c: 'ruptura' in c,                                    'B', 'Ruptura'),
    (lambda c: c.startswith('facebook'),                          'A', 'Facebook Nacional'),
    (lambda c: 'parceri' in c or c.startswith('b2b2c'),           'A', 'Parcerias (B2B2C)'),
    (lambda c: c.startswith('site cdt') or 'great pages' in c,    'A', 'Checkout / Site'),
    (lambda c: 'google' in c,                                     'A', 'Google Ads'),
    (lambda c: 'cartão digital nacional' in c or 'cartao digital nacional' in c, 'C', 'Cartão Digital Nacional'),
    (lambda c: 'cartão digital' in c or 'cartao digital' in c,    'B', 'Cartão Digital'),
    (lambda c: c.startswith('franquia'),                          'B', 'Franquias'),
    (lambda c: 'olímpia' in c or 'olimpia' in c,                  'D', 'Olímpia'),
]
GRUPOS_REGRA = {
    'A': 'Whatsapp · Facebook Nacional · Parcerias · Checkout · Google Ads → 2h exclusivas no televendas; sem venda → distribuição. '
         'Marcador: data_de_entrada_no_fluxo_do_televendas (no Contato E no Negócio).',
    'B': 'Franquias · Regionais · Ruptura · Cartão Digital → direto à distribuição, sem passar pelo fluxo.',
    'C': 'Cartão Digital Nacional → exclusivo do televendas.',
    'D': 'Olímpia → 24h.',
    'Fora da regra': 'Canais sem regra de roteamento documentada (Importação, TIM lead-only, App, ChatBots, CDT Sonhos, Influenciadores, vazio…).',
}


def _tv_grupo(canal):
    c = (canal or '').strip().lower()
    if not c or c == '(vazio)':
        return 'Fora da regra', '(sem canal)'
    for test, g, lbl in GRUPOS_CANAL:
        if test(c):
            return g, lbl
    return 'Fora da regra', canal



# ---- R31 chips + diagrama em raias (movidos para cá em 18/09: a aba Televendas (tab6) usa _tv_raias/_tv_chip e roda
#      antes das abas 🧲/🧭 no fluxo do módulo; o bloco é o mesmo, só mudou de lugar) ----
_TV_CHIPS = {
    'contato':   ('🧑 Contato', '#dbeafe', '#1e3a8a', 'a pessoa no CRM (HubSpot)'),
    'negocio':   ('🤝 Negócio', '#fef3c7', '#92400e', 'a oportunidade aberta num pipeline (HubSpot)'),
    'ctn':       ('🪪 CPF × CTN', '#dcfce7', '#14532d', 'filiação no NOMINAL casada por CPF (venda real)'),
    'tel':       ('☎️ telefone', '#e2e8f0', '#334155', 'registro do discador (Escallo)'),
    'tel_ctn':   ('☎️ tel-8 × CTN', '#dcfce7', '#14532d', 'filiação no NOMINAL casada pelo telefone'),
    'ga':        ('👣 GA4', '#e2e8f0', '#334155', 'usuário do site (Google Analytics)'),
    'app':       ('📱 app', '#e2e8f0', '#334155', 'usuário / cadastro no lake do app'),
    'foto':      ('📷 no mês', '#f1f5f9', '#475569', 'evento dentro do mês, de qualquer coorte'),
    'foto_lead': ('📷 desde o lead', '#f1f5f9', '#475569', 'evento em qualquer data a partir do lead'),
    'filme':     ('🎬 coorte', '#ede9fe', '#4c1d95', 'quem virou lead no mês, seguido até hoje'),
}


def _tv_chip(key):
    """Um chip HTML (R31). Chave desconhecida → nada."""
    c = _TV_CHIPS.get(key)
    if not c:
        return ""
    brd = ";border:1px solid #cbd5e1" if key.startswith('foto') else (";border:1px solid #c4b5fd" if key == 'filme' else "")
    return (f"<span title='{c[3]}' style='display:inline-block;font-size:9.5px;font-weight:700;padding:1px 7px;border-radius:9px;"
            f"margin-left:4px;vertical-align:middle;white-space:nowrap;background:{c[1]};color:{c[2]}{brd};'>{c[0]}</span>")


def _tv_chips_legenda(keys):
    """Legenda de uma linha para os chips usados na aba (R31)."""
    parts = [f"{_tv_chip(k)} <span style='color:#475569;'>{_TV_CHIPS[k][3]}</span>" for k in keys if k in _TV_CHIPS]
    st.markdown("<div style='font-size:11px;color:#64748b;margin:2px 0 10px 0;line-height:2;'><b>Legenda dos funis</b> — "
                "o chip diz que OBJETO cada etapa conta e em que RÉGUA: " + " &nbsp;·&nbsp; ".join(parts) + "</div>",
                unsafe_allow_html=True)


def _tv_raias(modo, nums, title, subtitle=""):
    """Diagrama em raias (R31, opção B): onde cada número nasce — raias Contato / Negócio / CTN, tempo da esquerda para a
    direita — e as duas lentes: o corte vertical do mês (📷 fotografia, aba 🧲) e a linha horizontal da coorte (🎬 filme,
    aba 🧭). modo = 'foto' | 'filme' — a lente ativa fica em destaque, a outra esmaecida. nums = valores da janela."""
    n = lambda k: format_br(nums[k]) if nums.get(k) is not None else "—"
    pipe = (modo == 'pipeline'); foto = (modo in ('foto', 'pipeline'))  # pipeline (aba 3 · Funil HubSpot): entradas no período, lente foto
    band_fill, band_stroke = ("#e2e8f0", "#94a3b8") if foto else ("#f8fafc", "#e2e8f0")
    arr_col, arr_op = ("#7c3aed", "1") if not foto else ("#c4b5fd", "0.7")
    band_txt, arr_txt = ("#334155", "#4c1d95") if foto else ("#94a3b8", "#4c1d95")
    if not foto:
        band_txt = "#94a3b8"
    else:
        arr_txt = "#a78bfa"
    mes_lbl = subtitle or "mês"
    hdr = (f"<div style='display:flex;gap:14px;align-items:baseline;margin-bottom:4px;'>"
           f"<div style='font-size:15px;font-weight:800;color:#0f172a;'>{title}</div>"
           f"<div style='font-size:11px;color:#64748b;'>{subtitle}</div>"
           f"<div style='margin-left:auto;font-size:10.5px;font-weight:700;color:#166534;'>diagrama em raias · {'📷 entradas no período' if pipe else ('📷 fotografia' if foto else '🎬 filme')}</div></div>")
    svg = [f"<svg viewBox='0 0 1040 430' width='100%' style='max-width:1100px;display:block;' font-family=\"Source Sans 3, Segoe UI, Arial, sans-serif\">"
           "<defs><marker id='tvra' markerWidth='10' markerHeight='10' refX='8' refY='5' orient='auto'><path d='M0 0 L10 5 L0 10 z' fill='" + arr_col + "'/></marker></defs>",
           "<line x1='150' y1='40' x2='1010' y2='40' stroke='#cbd5e1' stroke-width='1.5'/>",
           "<text x='290' y='30' font-size='12' fill='#94a3b8' text-anchor='middle'>antes</text>",
           f"<text x='565' y='30' font-size='12' fill='#0f172a' text-anchor='middle' font-weight='700'>{mes_lbl}</text>",
           f"<text x='855' y='30' font-size='12' fill='#94a3b8' text-anchor='middle'>{'depois' if foto else 'depois (seguido até hoje)'}</text>",
           "<line x1='430' y1='34' x2='430' y2='46' stroke='#94a3b8'/><line x1='700' y1='34' x2='700' y2='46' stroke='#94a3b8'/>",
           f"<rect x='430' y='52' width='270' height='300' fill='{band_fill}' stroke='{band_stroke}' stroke-dasharray='4 3'/>",
           # raias
           "<rect x='10' y='62' width='130' height='60' rx='8' fill='#dbeafe'/><text x='75' y='88' font-size='12.5' font-weight='700' fill='#1e3a8a' text-anchor='middle'>🧑 Contato</text><text x='75' y='106' font-size='10' fill='#1e3a8a' text-anchor='middle'>a pessoa no CRM</text>",
           "<rect x='10' y='152' width='130' height='60' rx='8' fill='#fef3c7'/><text x='75' y='178' font-size='12.5' font-weight='700' fill='#92400e' text-anchor='middle'>🤝 Negócio</text><text x='75' y='196' font-size='10' fill='#92400e' text-anchor='middle'>oportunidade no pipeline</text>",
           "<rect x='10' y='242' width='130' height='60' rx='8' fill='#dcfce7'/><text x='75' y='268' font-size='12.5' font-weight='700' fill='#14532d' text-anchor='middle'>🪪 CTN · NOMINAL</text><text x='75' y='286' font-size='10' fill='#14532d' text-anchor='middle'>a filiação (venda real)</text>",
           "<line x1='150' y1='92' x2='1010' y2='92' stroke='#e2e8f0'/><line x1='150' y1='182' x2='1010' y2='182' stroke='#e2e8f0'/><line x1='150' y1='272' x2='1010' y2='272' stroke='#e2e8f0'/>"]

    def mk(x, y, col, lbl, val, note, above=True, anchor='middle', r=9):
        return (f"<circle cx='{x}' cy='{y}' r='{r}' fill='{col}'/>"
                f"<text x='{x}' y='{y - 18}' font-size='11' fill='{col}' text-anchor='{anchor}' font-weight='700'>{lbl}</text>"
                f"<text x='{x}' y='{y + 25}' font-size='13' fill='#0f172a' font-weight='800' text-anchor='{anchor}'>{val}</text>"
                f"<text x='{x}' y='{y + 38}' font-size='9.5' fill='#64748b' text-anchor='{anchor}'>{note}</text>")

    if pipe:
        svg += [
            mk(450, 92, '#1e3a8a', 'Contatos no fluxo', n('fluxo'), 'data_de_entrada_no_fluxo_do_televendas'),
            "<path d='M450 101 L450 173' stroke='#94a3b8' stroke-width='1.5' stroke-dasharray='3 3'/>",
            mk(450, 182, '#b45309', 'LEAD', n('lead'), 'Negócios criados'),
            "<line x1='459' y1='182' x2='521' y2='182' stroke='#b45309' stroke-width='2'/>",
            mk(530, 182, '#b45309', 'EM NEGOCIAÇÃO', n('neg'), 'régua 7 d'),
            "<line x1='539' y1='182' x2='601' y2='182' stroke='#b45309' stroke-width='2'/>",
            mk(610, 182, '#b45309', 'C. SEM SUCESSO', n('css'), 'régua 1 d 12 h'),
            "<line x1='619' y1='182' x2='681' y2='182' stroke='#b45309' stroke-width='2'/>",
            mk(690, 182, '#166534', 'GANHO', n('ganho'), 'tabulação ou checkout'),
            "<path d='M610 191 L610 236 L681 236' stroke='#991b1b' stroke-width='1.5' stroke-dasharray='3 3' fill='none'/>",
            mk(690, 236, '#991b1b', 'PERDIDO', n('perdido'), 'auto-redistribui', r=7),
            "<text x='440' y='292' font-size='10.5' fill='#166534'>GANHO por checkout vira filiação no NOMINAL — conciliação por CPF na aba 7 · Três réguas</text>",
        ]
    elif foto:
        svg += [
            mk(470, 92, '#1e3a8a', 'Leads Únicos', n('lu'), 'Contatos criados no mês'),
            "<path d='M470 101 L470 263' stroke='#94a3b8' stroke-width='1.5' stroke-dasharray='3 3'/>",
            "<path d='M470 140 L520 140 L520 173' stroke='#94a3b8' stroke-width='1.5' stroke-dasharray='3 3' fill='none'/>",
            mk(520, 182, '#b45309', 'Encaminhados', n('eng'), 'Negócios criados no pipeline'),
            "<line x1='529' y1='182' x2='671' y2='182' stroke='#b45309' stroke-width='2'/>",
            mk(680, 182, '#b45309', 'Transbordados', n('fra'), 'entrou em Distribuição/Validador'),
            mk(470, 272, '#166534', 'Vendas nas franquias', n('vf'), 'CPF do lead × NOMINAL, qualquer data ≥ lead'),
            "<line x1='700' y1='272' x2='985' y2='272' stroke='#166534' stroke-width='2' stroke-dasharray='6 4' opacity='0.5'/>",
            "<text x='985' y='262' font-size='9.5' fill='#166534' text-anchor='end' opacity='0.8'>a venda pode cair depois do mês → entra aqui</text>",
        ]
    else:
        svg += [
            mk(470, 92, '#1e3a8a', 'Leads criados', n('criados'), 'Contatos novos na coorte'),
            mk(600, 92, '#1e3a8a', 'Elegíveis', n('eleg'), 'definição de buckets', above=False),
            "<path d='M470 101 L470 182' stroke='#94a3b8' stroke-width='1.5' stroke-dasharray='3 3'/>",
            mk(470, 182, '#b45309', 'Esteira Televendas', n('tv'), 'entraram em LEAD', above=False),
            mk(600, 182, '#b45309', 'No pipeline Distribuição', n('pipe'), 'Distribuição / Sem CEP / Validador'),
            "<line x1='609' y1='182' x2='751' y2='182' stroke='#b45309' stroke-width='2'/>",
            mk(760, 182, '#b45309', 'Enviados à franquia', n('valid'), 'Validador — em qualquer data'),
            "<path d='M760 191 L760 230 L880 230 L880 263' stroke='#94a3b8' stroke-width='1.5' stroke-dasharray='3 3' fill='none'/>",
            mk(880, 272, '#166534', 'Venda na franquia', n('venda'), 'CPF × NOMINAL, porta a porta + link + app do vendedor'),
        ]
    # lentes
    if pipe:
        svg += [
            "<text x='565' y='340' font-size='12' fill='#334155' text-anchor='middle' font-weight='700'>📷 ENTRADAS NO PERÍODO: cada marcador conta quantos Negócios entraram no estágio dentro do período</text>",
            "<text x='565' y='356' font-size='10' fill='#94a3b8' text-anchor='middle'>um Negócio pode entrar em vários estágios; PERDIDO auto-redistribui (exceto 'sem interesse'); os estágios são fatias dos Negócios dos Contatos no fluxo</text>",
            "<rect x='745' y='58' width='262' height='84' rx='8' fill='#fffbeb' stroke='#fcd34d'/>",
            "<text x='757' y='77' font-size='11' fill='#92400e' font-weight='700'>Leitura das raias:</text>",
            "<text x='757' y='95' font-size='10.5' fill='#78350f'>🧑 o Contato entra no fluxo (workflow, 2 h exclusivas)</text>",
            "<text x='757' y='111' font-size='10.5' fill='#78350f'>🤝 vira Negócio em LEAD e sobe pela régua automática</text>",
            "<text x='757' y='127' font-size='10.5' fill='#78350f'>🏁 fecha em GANHO (porta 1 ou 2) ou PERDIDO</text>",
            "</svg>",
        ]
    else:
        svg += [
        f"<path d='M455 322 L990 322' stroke='{arr_col}' stroke-width='2.5' opacity='{arr_op}' marker-end='url(#tvra)'/>",
        f"<text x='460' y='340' font-size='12' fill='{arr_txt}' font-weight='700'>🎬 FILME (aba 🧭): quem virou lead no mês, seguido até hoje — {'lente desta aba' if not foto else 'a outra lente'}</text>",
        f"<text x='565' y='372' font-size='12' fill='{band_txt}' text-anchor='middle' font-weight='700'>📷 FOTOGRAFIA (aba 🧲): tudo que aconteceu dentro do mês, de quem quer que seja — {'lente desta aba' if foto else 'a outra lente'}</text>",
        "<text x='565' y='388' font-size='10' fill='#94a3b8' text-anchor='middle'>é a régua do Relatório Mensal: fecha com o mês e não muda depois</text>",
        # chamada
        "<rect x='745' y='58' width='262' height='84' rx='8' fill='#fffbeb' stroke='#fcd34d'/>",
        "<text x='757' y='77' font-size='11' fill='#92400e' font-weight='700'>Uma venda em outubro de um lead de setembro:</text>",
        "<text x='757' y='95' font-size='10.5' fill='#78350f'>📷 fotografia de setembro: só na linha Vendas (≥ lead)</text>",
        "<text x='757' y='111' font-size='10.5' fill='#78350f'>📷 fotografia de outubro: NÃO (o lead não é de outubro)</text>",
        "<text x='757' y='127' font-size='10.5' fill='#78350f'>🎬 filme da coorte de setembro: SIM, sempre</text>",
        "</svg>",
    ]
    cap = ("Contatos no fluxo nascem na raia de Contato (data de entrada no fluxo); LEAD, EM NEGOCIAÇÃO, CONTATO SEM SUCESSO, GANHO e "
           "PERDIDO são entradas de estágio na raia de Negócio, dentro do período — fatias dos Negócios dos Contatos no fluxo; a venda "
           "confirmada mora na raia do CTN e é conciliada na aba 7. Os números são os mesmos do funil.") if pipe else ("Cada linha do RMA nasce numa raia: Leads Únicos na de Contato (data de criação), Encaminhados e Transbordados na de Negócio "
           "(criação / entrada em Distribuição–Validador), Vendas na do CTN (filiação casada por CPF). A fotografia é o corte vertical (o mês); "
           "o filme é a linha horizontal de uma coorte. Os números são os da janela selecionada — os mesmos do funil."
           if foto else
           "Cada etapa da rota nasce numa raia: Leads criados e Elegíveis na de Contato (canal na criação), esteira Televendas e pipeline "
           "Distribuição/Validador na de Negócio, venda na do CTN (filiação casada por CPF). A coorte é seguida até a última carga — por isso "
           "os marcadores avançam para a direita do mês. Os números são os da coorte selecionada — os mesmos dos funis.")
    st.markdown("<div style='border:1px solid #e2e8f0;border-radius:12px;padding:12px 16px 8px 16px;background:#fff;'>" + hdr + "".join(svg)
                + f"<div style='font-size:10.5px;color:#64748b;margin-top:4px;'>{cap}</div></div>", unsafe_allow_html=True)

with tab6:
    st.markdown("## Televendas — Escallo × HubSpot × Talkerchat × NOMINAL")
    _tvd_m, _tvd_w, _tv_err = load_tv_dash()

    # ---- meses do período (as séries "mensais" usam sempre meses) ----
    _tv_m_ini = pd.Timestamp(c_s).to_period('M').to_timestamp()
    _tv_m_fim = pd.Timestamp(ref_datetime).to_period('M').to_timestamp()
    _tv_meses = pd.period_range(_tv_m_ini, _tv_m_fim, freq='M').to_timestamp()
    _tv_p_ini = pd.Timestamp(p_s).to_period('M').to_timestamp()
    _tv_p_fim = pd.Timestamp(p_partial).to_period('M').to_timestamp()
    _tv_meses_p = pd.period_range(_tv_p_ini, _tv_p_fim, freq='M').to_timestamp()
    _tv_meses_p = [m for m in _tv_meses_p if m not in set(_tv_meses)]  # sem sobreposição

    # ---- grão: semana (seg–dom) quando o período tem menos de 28 dias e o agregado semanal cobre as semanas;
    #      senão mês. KPIs, funis e notas seguem o grão; as séries "mensais" são sempre por mês. ----
    _tv_c_s, _tv_c_e = pd.Timestamp(c_s), pd.Timestamp(ref_datetime)
    _tv_sem_ini = _tv_c_s - pd.Timedelta(days=int(_tv_c_s.weekday()))
    _tv_sem_fim = _tv_c_e - pd.Timedelta(days=int(_tv_c_e.weekday()))
    _tv_semanas = list(pd.date_range(_tv_sem_ini, _tv_sem_fim, freq='7D'))
    _tv_periodo_curto = (_tv_c_e - _tv_c_s).days < 14   # Semana Atual ou intervalo personalizado de até 2 semanas
    _tv_tem_sem = (not _tvd_w.empty) and bool(_tvd_w['mes'].isin(_tv_semanas).any())
    if _tv_periodo_curto and _tv_tem_sem:
        _tv_grain = 'W'
        _tvd = _tvd_w
        _tv_per = _tv_semanas
        _tv_per_p = [w - pd.Timedelta(days=7 * len(_tv_semanas)) for w in _tv_semanas]
        _tv_per_lbl = (f"semana de {_tv_sem_ini:%d/%m} a {(_tv_sem_ini + pd.Timedelta(days=6)):%d/%m}" if len(_tv_semanas) == 1
                       else f"semanas de {_tv_sem_ini:%d/%m} a {(_tv_sem_fim + pd.Timedelta(days=6)):%d/%m}")
        _tv_per_p_lbl = (f"semana de {_tv_per_p[0]:%d/%m}" if len(_tv_per_p) == 1
                         else f"semanas de {_tv_per_p[0]:%d/%m} a {(_tv_per_p[-1] + pd.Timedelta(days=6)):%d/%m}")
    else:
        _tv_grain = 'M'
        _tvd = _tvd_m
        _tv_per = list(_tv_meses)
        _tv_per_p = list(_tv_meses_p)
        _tv_per_lbl = f"{_tv_m_ini:%m/%Y}–{_tv_m_fim:%m/%Y}" if _tv_m_ini != _tv_m_fim else f"{_tv_m_fim:%m/%Y}"
        _tv_per_p_lbl = (f"{_tv_per_p[0]:%m/%Y}–{_tv_per_p[-1]:%m/%Y}" if len(_tv_per_p) > 1
                         else (f"{_tv_per_p[0]:%m/%Y}" if _tv_per_p else ""))

    _tv_atual = _tvd_m['atualizado_em'].max() if not _tvd_m.empty else None
    _tv_atual_w = _tvd_w['atualizado_em'].max() if not _tvd_w.empty else None
    _tv_hdr1, _tv_hdr2 = st.columns([3, 1.2])
    if _tv_grain == 'W':
        _tv_hdr1.caption(
            f"Período: **{_tv_per_lbl}** — **grão semanal** (segunda a domingo), porque o período dos Controles Globais "
            f"tem até duas semanas. KPIs, funis e notas contam a(s) semana(s) inteira(s) até a última carga "
            f"(a semana corrente é parcial); leads do Escallo entram na semana do 1º contato. "
            + (f"Comparação: {_tv_per_p_lbl}. " if _tv_per_p else "")
            + "As séries 'mensais' continuam por mês. Fontes: ESCALLO_LEADS_MES · hubspot_contacts_raw / hubspot_deals_raw · "
              "v_alex_talkerchat · NOMINAL_VENDAS.")
    else:
        _tv_hdr1.caption(
            f"Período: **{_tv_per_lbl}** — **grão mensal** (meses tocados pelo período dos Controles Globais). "
            + (f"Comparação: {_tv_per_p_lbl}. " if _tv_per_p
               else "Sem mês anterior fora do período para comparar (os chips de variação ficam vazios). ")
            + "Períodos de até duas semanas (ex.: Semana Atual) usam o grão semanal quando o agregado semanal está carregado. "
              "Fontes: ESCALLO_LEADS_MES · hubspot_contacts_raw / hubspot_deals_raw · v_alex_talkerchat · NOMINAL_VENDAS.")
        if _tv_periodo_curto and not _tv_tem_sem:
            st.info("ℹ️ O período tem até duas semanas, mas o agregado semanal ainda não cobre essas semanas — mostrando o mês "
                    "inteiro. Rode `gt7 run televendas_dash` (grão MW: meses + últimas 8 semanas) ou "
                    "`gt7 run televendas_dash --arg grain=W --arg weeks=AAAA-MM-DD..AAAA-MM-DD` e recarregue os dados.")
    _tv_hdr2.markdown(
        "<div style='border:1px solid #e2e8f0;border-radius:10px;padding:7px 12px;background:#fff;'>"
        "<div style='font-size:10.5px;color:#64748b;font-weight:600;'>Agregado atualizado em</div>"
        f"<div style='font-size:13px;color:#0f172a;font-weight:700;'>🗓️ {pd.Timestamp(_tv_atual).strftime('%d/%m/%Y %H:%M') if _tv_atual is not None else '—'}</div>"
        f"<div style='font-size:10.5px;color:#64748b;'>semanal: {pd.Timestamp(_tv_atual_w).strftime('%d/%m %H:%M') if _tv_atual_w is not None else 'não carregado'}</div>"
        "</div>", unsafe_allow_html=True)

    if _tv_atual is not None and pd.Timestamp(_tv_atual).date() < reference_date:
        st.warning(f"⏳ O agregado `alex_tv_dash_mes` foi calculado em **{pd.Timestamp(_tv_atual):%d/%m/%Y %H:%M}** e a base vai até "
                   f"**{reference_date:%d/%m/%Y}** — o mês corrente (e o último mês, se a carga foi antes do fechamento) está "
                   "**parcial** aqui. Rode `gt7 run televendas_dash` no claude-toolkit e clique em ♻️ Recarregar dados. "
                   "A aba 🧲 Aquisição lê outro agregado (`alex_aq_dash_mes`), com a própria data de cálculo.")
    if _tv_err:
        st.error(f"⚠️ Falha ao ler `alex_tv_dash_mes` — a query levantou: `{_tv_err}`. "
                 "A leitura é refeita a cada rerun (o erro não fica em cache); se persistir, confira a conexão "
                 "em `.streamlit/secrets.toml` e rode `diagnostics/db_check.py`.")
    elif _tvd_m.empty:
        st.warning("⚠️ A tabela `alex_tv_dash_mes` existe mas está vazia. Rode "
                   "`gt7 run televendas_dash --arg nv=rebuild --arg audit=1` (claude-toolkit) e recarregue os dados.")

    # ---- helpers ----
    def _tv_val(secao, metrica, dim=None, meses=None):
        """Soma de `metrica` nos períodos do grão (default = período atual: meses ou semanas). None se não houver linha."""
        meses = _tv_per if meses is None else meses
        d = _tvd[(_tvd['secao'] == secao) & (_tvd['metrica'] == metrica) & (_tvd['mes'].isin(list(meses)))]
        if dim is not None:
            d = d[d['dim'] == dim]
        if d.empty:
            return None
        return float(d['valor'].sum(skipna=True))

    def _tv_serie(secao, metrica, dim=None, meses=None):
        """Série MENSAL (sempre do agregado por mês), para os gráficos de série."""
        meses = _tv_meses if meses is None else meses
        d = _tvd_m[(_tvd_m['secao'] == secao) & (_tvd_m['metrica'] == metrica) & (_tvd_m['mes'].isin(list(meses)))]
        if dim is not None:
            d = d[d['dim'] == dim]
        return d.groupby('mes', as_index=False)['valor'].sum().sort_values('mes')

    def _tv_pct(a, b, nd=1):
        if a is None or b is None or b <= 0:
            return "—"
        return f"{a / b * 100:.{nd}f}%".replace('.', ',')

    def _tv_n(x):
        return "—" if x is None else format_br(x)

    def _tv_delta(cur, prev):
        if cur is None or prev is None or prev <= 0:
            return ""
        d = (cur - prev) / prev * 100
        if abs(d) < 0.05:
            bg, fg = "#f1f5f9", "#475569"
        elif d > 0:
            bg, fg = "#dcfce7", "#15803d"
        else:
            bg, fg = "#fee2e2", "#b91c1c"
        return (f"<span style='background:{bg};color:{fg};font-weight:700;font-size:11.5px;"
                f"padding:2px 8px;border-radius:10px;white-space:nowrap;'>{'+' if d > 0 else ''}{d:.0f}%</span>")

    def _tv_kpi(col, icon, label, value_html, sub, color="#166534"):
        col.markdown(
            f"<div style='border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;background:#fff;height:100%;'>"
            f"<div style='display:flex;align-items:center;gap:10px;'>"
            f"<div style='width:36px;height:36px;border-radius:50%;background:{color};display:flex;"
            f"align-items:center;justify-content:center;font-size:16px;flex:0 0 36px;'>{icon}</div>"
            f"<div style='min-width:0;'>"
            f"<div style='font-size:11.5px;color:#64748b;font-weight:600;'>{label}</div>"
            f"<div style='font-size:20px;font-weight:800;color:#0f172a;line-height:1.2;'>{value_html}</div>"
            f"<div style='font-size:11px;color:#94a3b8;'>{sub}</div>"
            f"</div></div></div>", unsafe_allow_html=True)

    def _tv_note(html, bg="#ecfdf5", icon="💡"):
        st.markdown(
            f"<div style='border-radius:12px;padding:14px 16px;background:{bg};margin-top:10px;"
            f"display:flex;gap:12px;align-items:flex-start;'>"
            f"<div style='width:34px;height:34px;border-radius:50%;background:#166534;display:flex;"
            f"align-items:center;justify-content:center;font-size:15px;flex:0 0 34px;'>{icon}</div>"
            f"<div style='font-size:13.5px;color:#0f172a;line-height:1.55;'>{html}</div></div>",
            unsafe_allow_html=True)

    _TV_RAMP = ['#1e6b3c', '#2e8a4f', '#57a86f', '#8cc79e', '#c8e3cf', '#e5f0e8']

    def _tv_funil(title, stages, subtitle="", chips=None):
        """stages: lista de (icone, rotulo, valor, nota[, base]). Barra proporcional ao topo,
        chips (R31, opcional): lista com um item por etapa — lista de chaves de _TV_CHIPS (objeto contado e régua),
        renderizadas ao lado do rótulo; None/[] = sem chip.
        conversão sequencial (vs etapa anterior) e acumulada (vs topo).
        base (R30, opcional): índice da etapa que serve de denominador da % sequencial — use para FATIAS de uma
        etapa (subconjuntos irmãos, ex.: 'dos cadastros: freemium'). Uma fatia não vira o `prev` da etapa seguinte,
        então a próxima etapa em sequência continua sendo lida sobre a etapa-base."""
        stages = [tuple(s) + (None,) * (5 - len(s)) for s in stages]
        chips = list(chips or []) + [None] * (len(stages) - len(chips or []))
        vidx = [s[2] for s in stages]
        vals = [v for v in vidx if v is not None]
        top = vals[0] if vals else 0
        rows = [(f"<div style='display:flex;gap:14px;align-items:baseline;margin-bottom:8px;'>"
                 f"<div style='font-size:15px;font-weight:800;color:#0f172a;'>{title}</div>"
                 f"<div style='font-size:11px;color:#64748b;'>{subtitle}</div>"
                 f"<div style='margin-left:auto;font-size:10.5px;font-weight:700;color:#166534;'>seq. | do topo</div></div>")]
        prev = None
        for i, (ic, lbl, v, note, base) in enumerate(stages):
            den = (vidx[base] if base is not None and 0 <= base < len(vidx) else prev)
            _ch = "".join(_tv_chip(k) for k in (chips[i] or [])) if i < len(chips) else ""
            label = (f"<div style='flex:0 0 250px;display:flex;align-items:center;gap:8px;'>"
                     f"<div style='width:30px;height:30px;border-radius:8px;background:#14532d;display:flex;"
                     f"align-items:center;justify-content:center;font-size:14px;flex:0 0 30px;'>{ic}</div>"
                     f"<div><div style='font-size:12.5px;font-weight:700;color:#0f172a;'>{lbl}{_ch}</div>"
                     f"<div style='font-size:10.5px;color:#64748b;'>{note}</div></div></div>")
            if v is None:
                bar = ("<div style='flex:1;display:flex;justify-content:center;'><div style='width:60%;border:2px dashed #cbd5e1;"
                       "border-radius:8px;padding:6px 10px;text-align:center;color:#94a3b8;font-size:11.5px;'>sem dados</div></div>")
                conv = ("<div style='flex:0 0 58px;text-align:right;color:#94a3b8;'>—</div>"
                        "<div style='flex:0 0 58px;text-align:right;color:#94a3b8;'>—</div>")
            else:
                wid = (28 + 72 * (v / top)) if top > 0 else 28
                bg = _TV_RAMP[min(i, len(_TV_RAMP) - 1)]
                fg = '#ffffff' if i < 2 else '#14532d'
                bar = (f"<div style='flex:1;display:flex;justify-content:center;'>"
                       f"<div style='width:{wid:.1f}%;background:{bg};border-radius:8px;padding:6px 12px;min-width:120px;"
                       f"text-align:center;font-size:15px;font-weight:800;color:{fg};'>{format_br(v)}</div></div>")
                conv = (f"<div style='flex:0 0 58px;text-align:right;font-size:12.5px;font-weight:700;color:#0f172a;'>"
                        f"{_tv_pct(v, den) if den else '—'}</div>"
                        f"<div style='flex:0 0 58px;text-align:right;font-size:12.5px;color:#64748b;'>"
                        f"{_tv_pct(v, top) if i > 0 else '100%'}</div>")
                if base is None:
                    prev = v
            rows.append(f"<div style='display:flex;align-items:center;gap:10px;padding:5px 0;border-top:1px solid #f1f5f9;'>"
                        f"{label}{bar}{conv}</div>")
        st.markdown("<div style='border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;background:#fff;'>"
                    + "".join(rows) + "</div>", unsafe_allow_html=True)

    def _tv_fmt_k(v):
        """Rótulo curto para colunas: 35,7k · 123k · 842."""
        if v is None or pd.isna(v):
            return ""
        v = float(v)
        if abs(v) >= 100000:
            return f"{v / 1000:.0f}k"
        if abs(v) >= 1000:
            return f"{v / 1000:.1f}k".replace('.', ',')
        return format_br(v)

    def _tv_meses_grafico(key):
        """Janela dos gráficos mensais: últimos 3 meses (padrão) ou o ano inteiro até o fim do período.
        Um toggle por sub-aba; devolve a lista de meses."""
        _ano = st.toggle(f"Mostrar o ano inteiro (jan–{_tv_m_fim.strftime('%m/%Y')})", value=False, key=key,
                         help="Desligado: últimos 3 meses até o fim do período selecionado.")
        if _ano:
            return list(pd.period_range(pd.Timestamp(year=_tv_m_fim.year, month=1, day=1), _tv_m_fim, freq='M').to_timestamp())
        return list(pd.period_range(_tv_m_fim - pd.DateOffset(months=2), _tv_m_fim, freq='M').to_timestamp())

    # ---- estilos da casa (folheto 26/08): A = séries mensais em colunas e barras horizontais;
    #      B = gráficos de linha (taxas). Todos os gráficos de mesma natureza usam o mesmo estilo. ----
    _TV_CORES_A = ['#166534', '#57a86f', '#b45309', '#8cc79e', '#94a3b8', '#0f172a', '#c8e3cf']

    def _tv_titulo(title, subtitle="", style="A"):
        if _CDT_THEME:
            st.markdown(cdt_theme.header(title, subtitle, style), unsafe_allow_html=True)
        else:
            st.markdown(f"**{title}**" + (f"  \n<span style='color:#64748b;font-size:12px'>{subtitle}</span>" if subtitle else ""),
                        unsafe_allow_html=True)

    def _tv_fonte(texto):
        if texto:
            st.markdown(cdt_theme.fonte(texto) if _CDT_THEME else f"<div style='font-size:10.5px;color:#64748b;'>Fonte: {texto}</div>",
                        unsafe_allow_html=True)

    def _tv_chart_mensal(df_long, title, y_label="", stacked=True, pct=False, rotulos=False, subtitle="", fonte=""):
        """Série mensal em colunas — estilo A. df_long: colunas mes, serie, valor. rotulos=True escreve o valor (em k)
        sobre cada coluna (agrupado) ou dentro de cada segmento (empilhado)."""
        _tv_titulo(title, subtitle, "A")
        if df_long.empty:
            st.caption("sem série mensal para o período.")
            return
        d = df_long.copy()
        d['mes'] = pd.to_datetime(d['mes']).dt.strftime('%m/%Y')
        if rotulos:
            d['rotulo'] = d['valor'].map(_tv_fmt_k)
        fig = px.bar(d, x='mes', y='valor', color='serie', barmode='stack' if stacked else 'group',
                     text='rotulo' if rotulos else None, color_discrete_sequence=_TV_CORES_A,
                     template='cdt_a' if _CDT_THEME else 'plotly_white')
        if rotulos:
            if stacked:
                fig.update_traces(textposition='inside', insidetextanchor='middle', textfont_size=10.5,
                                  textfont_color='#ffffff')
            else:
                fig.update_traces(textposition='outside', textfont_size=11, cliponaxis=False)
        fig.update_layout(height=330, xaxis_title='', yaxis_title=y_label, legend_title_text='',
                          uniformtext_minsize=9, uniformtext_mode='hide' if stacked else 'show')
        if pct:
            fig.update_yaxes(ticksuffix='%')
        st.plotly_chart(fig, use_container_width=True)
        _tv_fonte(fonte)

    def _tv_linhas_mensal(df_long, title, y_label="", pct=False, rotulos=False, subtitle=""):
        """Gráfico de linhas (taxas e réguas) — estilo B: sem legenda, nome da série na ponta da linha."""
        _tv_titulo(title, subtitle, "B")
        if df_long.empty:
            st.caption("sem série mensal para o período.")
            return
        d = df_long.copy()
        d['mes'] = pd.to_datetime(d['mes']).dt.strftime('%m/%Y')
        if rotulos:
            d['rotulo'] = d['valor'].map(lambda v: "" if pd.isna(v) else (f"{v:.1f}%".replace('.', ',') if pct else _tv_fmt_k(v)))
        fig = px.line(d, x='mes', y='valor', color='serie', markers=True,
                      text='rotulo' if rotulos else None, color_discrete_sequence=_TV_CORES_A,
                      template='cdt_b' if _CDT_THEME else 'plotly_white')
        fig.update_traces(line_width=2.5, marker_size=7)
        if rotulos:
            fig.update_traces(textposition='top center', textfont_size=11, mode='lines+markers+text')
        fig.update_layout(height=320, xaxis_title='', yaxis_title=y_label, legend_title_text='')
        if pct:
            fig.update_yaxes(ticksuffix='%')
        if _CDT_THEME:
            cdt_theme.rotular_pontas(fig)
        else:
            fig.update_layout(legend=dict(orientation='h', y=-0.25, title_text=''))
        st.plotly_chart(fig, use_container_width=True)

    def _tv_long(secao, metricas, dim=None, labels=None, meses=None):
        """Série mensal longa para várias métricas (colunas mes, serie, valor)."""
        parts = []
        for m in metricas:
            s = _tv_serie(secao, m, dim, meses=meses)
            s['serie'] = (labels or {}).get(m, m)
            parts.append(s)
        return pd.concat(parts) if parts else pd.DataFrame(columns=['mes', 'serie', 'valor'])

    _tv_tabs = st.tabs(["📵 1 · Escallo Ativo", "📲 2 · Escallo Receptivo", "🧭 3 · Funil HubSpot (Contatos)",
                        "💬 4 · Talkerchat", "📟 5 · Por telefone da empresa", "🚪 6 · Ganhos por porta",
                        "📏 7 · Três réguas", "🔀 8 · Grupos A–D"])

    # =================================================================
    # 1 · ESCALLO ATIVO
    # =================================================================
    with _tv_tabs[0]:
        S = 's1_ativo'
        leads = _tv_val(S, 'leads'); lig = _tv_val(S, 'ligacoes'); alo = _tv_val(S, 'alo10')
        classif = _tv_val(S, 'classif'); negoc = _tv_val(S, 'negoc'); venda = _tv_val(S, 'venda')
        venda_conf = _tv_val(S, 'venda_conf'); conf_tel8 = _tv_val(S, 'conf_tel8')
        piso_l = _tv_val(S, 'piso_leads'); piso_c = _tv_val(S, 'piso_conf')
        leads_p = _tv_val(S, 'leads', meses=_tv_per_p); alo_p = _tv_val(S, 'alo10', meses=_tv_per_p)
        venda_p = _tv_val(S, 'venda', meses=_tv_per_p)
        gap = (alo - classif) if (alo is not None and classif is not None) else None

        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "📞", "Leads discados (ativo)", f"{_tv_n(leads)} {_tv_delta(leads, leads_p)}",
                (f"{_tv_n(lig)} ligações · " + f"{lig / leads:.2f}".replace('.', ',') + " por lead") if leads and lig else "")
        _tv_kpi(k2, "🗣️", "Alô humano (≥ 10 s)", f"{_tv_pct(alo, leads)} {_tv_delta(alo, alo_p)}",
                f"{_tv_n(alo)} leads falaram")
        _tv_kpi(k3, "📝", "Gap alô × classificado", f"{_tv_pct(gap, alo)}",
                f"{_tv_n(gap)} falaram ≥10 s e não receberam estágio ({_tv_n(classif)} classificados)", color="#b45309")
        _tv_kpi(k4, "✅", "Venda tabulada → confirmada no CTN", f"{_tv_pct(venda_conf, venda)} {_tv_delta(venda, venda_p)}",
                f"{_tv_n(venda)} tabuladas 'venda' · {_tv_n(venda_conf)} com filiação no NOMINAL (tel-8)")

        c1, c2 = st.columns([1.9, 1])
        with c1:
            _tv_funil("Funil Escallo · discagem ativa", [
                ("📞", "Leads discados", leads, "1 linha por telefone × mês (ESCALLO_LEADS_MES, tipo ATIVO)"),
                ("🗣️", "Alô humano ≥ 10 s", alo, "tempoConversa ≥ 10 s em alguma ligação do mês"),
                ("🤝", "Fase de negociação (inclui as vendas)", (negoc or 0) + (venda or 0) if (negoc is not None or venda is not None) else None,
                 "negociacao · agendado · venda_travada + venda — toda venda passou pela negociação"),
                ("💰", "Venda (tabulação do operador)", venda, "melhor_estagio = venda"),
                ("✅", "Confirmada no CTN (NOMINAL)", venda_conf, "tel-8 com DT_FILIACAO entre 1º contato e último + 14 d"),
            ], subtitle=_tv_per_lbl)
            st.caption("Fonte: ESCALLO_LEADS_MES (REL003 ativo + REL086 classificação; carga diária 8h). "
                       "'Confirmada' usa o telefone (tel-8) porque o Escallo não captura CPF — é teto de influência, não atribuição.")
            # ---- R37: quem fez o 1º contato do mês — operador humano × linha de sistema (s9_tipo; agente logado no REL003) ----
            if _tv_grain == 'M':
                _h_l = _tv_val('s9_tipo', 'leads', dim='humano'); _s_l = _tv_val('s9_tipo', 'leads', dim='sistema')
                if _h_l is not None or _s_l is not None:
                    _h_a = _tv_val('s9_tipo', 'alo10', dim='humano'); _s_a = _tv_val('s9_tipo', 'alo10', dim='sistema')
                    _h_v = _tv_val('s9_tipo', 'venda', dim='humano'); _s_v = _tv_val('s9_tipo', 'venda', dim='sistema')
                    _o_l = sum(v for v in (_tv_val('s9_tipo', 'leads', dim=d) for d in ('treinamento', 'sem_login', 'externo')) if v)
                    _t_l = (_h_l or 0) + (_s_l or 0) + _o_l
                    _tv_note(
                        f"<b>Quem fez o 1º contato do mês com cada lead</b> (agente logado no ramal, REL003): "
                        f"<b>operador humano</b> {_tv_n(_h_l)} leads ({_tv_pct(_h_l, _t_l)}) · alô {_tv_pct(_h_a, _h_l)} · "
                        f"{_tv_n(_h_v)} vendas tabuladas &nbsp;|&nbsp; <b>linha de sistema</b> (ramal sem agente — discador/URA, ex. 9902) "
                        f"{_tv_n(_s_l)} leads ({_tv_pct(_s_l, _t_l)}) · alô {_tv_pct(_s_a, _s_l)} · {_tv_n(_s_v)} vendas tabuladas"
                        + (f" &nbsp;|&nbsp; treinamento / sem login / nº externo {_tv_n(_o_l)} leads" if _o_l else "")
                        + ". O 'alô ≥ 10 s' da linha de sistema é o cliente ouvindo uma gravação ou validação, não uma conversa — "
                        "por isso a taxa de alô dela costuma ser <i>maior</i> que a dos operadores. Detalhe por ramal e por vendedor "
                        "na sub-aba 📟 5.", bg="#f8fafc", icon="🎧")
            # ---- ponte com a régua do relatório (aba 🧲 · s8_mesa): mesma população, outra pergunta ----
            if _tv_grain == 'M':
                _aq6, _aq6_err = load_aq()
                _m8 = _aq6[(_aq6['secao'] == 's8_mesa') & (_aq6['dim'] == 'televendas') & (_aq6['mes'].isin(list(_tv_per)))] if not _aq6_err else pd.DataFrame()
                if not _m8.empty:
                    def _v8(met):
                        d = _m8[_m8['metrica'] == met]
                        return float(d['valor'].sum()) if not d.empty else None
                    _d8, _a8, _v8m, _t8 = _v8('discados'), _v8('alo10'), _v8('vendas_mes'), _v8('vendas_mes_tv')
                    _at8 = pd.Timestamp(_m8['atualizado_em'].max())
                    _tv_note(
                        f"<b>Régua do relatório mensal (aba 🧲 Aquisição, mesmos meses):</b> {_tv_n(_d8)} discados · {_tv_n(_a8)} alôs ≥ 10 s · "
                        f"<b>{_tv_n(_v8m)} filiaram no mês</b> ({_tv_pct(_v8m, _d8)} dos discados; qualquer tipo de venda no NOMINAL, "
                        f"cruzamento por tel-8 no mesmo mês-calendário) · <b>{_tv_n(_t8)}</b> com tipo_venda TELEVENDAS ({_tv_pct(_t8, _v8m)}). "
                        f"Escada de atribuição (R34): após o 1º contato {_tv_n(_v8('vendas_apos'))} · conversaram (alô ≥ 10 s) e filiaram "
                        f"{_tv_n(_v8('vendas_alo'))} · tipo TELEVENDAS com alô {_tv_n(_v8('vendas_alo_tv'))}. "
                        f"Agregado calculado em {_at8:%d/%m %H:%M}.<br>"
                        "<b>Por que difere do funil acima:</b> o funil Escallo conta o que a <i>operação registrou</i> (tabulação 'venda' do "
                        "operador e a confirmação dessa tabulação no CTN na janela do contato + 14 d); a régua do relatório conta "
                        "<i>quem filiou</i> entre os discados, por qualquer porta (site, MGM, campo, televendas). Use o funil Escallo para "
                        "gerir a operação (aproveitamento do discador, gap de tabulação, qualidade do registro); use a régua do relatório "
                        "para o resultado de negócio e para bater com o Relatório Mensal de Aquisição.",
                        bg="#f8fafc", icon="🧲")
                elif not _aq6_err:
                    st.caption("ℹ️ Régua do relatório (aba 🧲, s8_mesa) sem dados para estes meses — rode `gt7 run aquisicao_dash --arg only=s8`.")
        with c2:
            # esperado só pela coincidência: vendas tabuladas × taxa do piso; efeito líquido = confirmadas − esperado
            _piso_rate = (piso_c / piso_l) if (piso_c is not None and piso_l) else None
            _esp_piso = (venda * _piso_rate) if (venda is not None and _piso_rate is not None) else None
            _liq = (venda_conf - _esp_piso) if (venda_conf is not None and _esp_piso is not None) else None
            _tv_note(
                f"<b>Disciplina de registro.</b> {_tv_pct(classif, alo)} dos alôs recebem um estágio; "
                f"<b>{_tv_pct(gap, alo)}</b> ({_tv_n(gap)}) falaram ≥10 s e ficaram sem classificação. "
                f"Tudo que se mede depois do alô (negociação, venda) é piso, não medição.<br><br>"
                f"<b>Teto × piso — como ler a 'confirmação por telefone'.</b> Confirmar por tel-8 só diz que o telefone "
                f"discado aparece com uma filiação no NOMINAL dentro da janela — <i>não</i> diz que o televendas vendeu. "
                f"Por isso comparamos três taxas:<br>"
                f"• <b>Teto</b> ({_tv_pct(conf_tel8, leads)}): a lista inteira. É o máximo que a discagem pode ter influenciado.<br>"
                f"• <b>Piso</b> ({_tv_pct(piso_c, piso_l)}): a mesma taxa só nos leads em que <i>ninguém falou com o cliente</i> "
                f"(sem contato / não classificado). Sem conversa, essas filiações vieram de outros canais — é a coincidência "
                f"natural da lista (o mailing contém gente que já ia comprar pelo site, por indicação, pelo campo).<br>"
                f"• <b>Sinal</b> ({_tv_pct(venda_conf, venda)}): leads que o operador tabulou como 'venda'.<br>"
                f"Leitura: teto e piso quase iguais → discar a lista, em média, quase não muda a chance de filiar; "
                f"a distância entre 'venda' e o piso é o que a tabulação realmente enxerga. "
                + (f"Das {_tv_n(venda_conf)} vendas tabuladas e confirmadas, ~{_tv_n(_esp_piso)} seriam esperadas só pela "
                   f"coincidência do piso — sobram <b>~{_tv_n(_liq)}</b> que a ligação explica de fato."
                   if _liq is not None else ""))
        _mg1 = _tv_meses_grafico('t6_s1_ano')
        _tv_chart_mensal(_tv_long(S, ['leads', 'alo10', 'classif', 'venda'], meses=_mg1,
                                  labels={'leads': 'Leads discados', 'alo10': 'Alô ≥10 s', 'classif': 'Classificados', 'venda': 'Venda tabulada'}),
                         "Série mensal — discagem ativa", stacked=False, rotulos=True, fonte="ESCALLO_LEADS_MES (REL003 + REL086)")
        # % mensal
        _s1 = _tv_serie(S, 'leads', meses=_mg1).rename(columns={'valor': 'leads'})
        for m_, lbl_ in [('alo10', 'Alô ≥10 s'), ('classif', 'Classificados')]:
            _x = _tv_serie(S, m_, meses=_mg1).rename(columns={'valor': m_})
            _s1 = _s1.merge(_x, on='mes', how='left')
        _pl = []
        for m_, lbl_ in [('alo10', '% alô ≥10 s'), ('classif', '% classificados')]:
            _t = _s1[['mes']].copy(); _t['serie'] = lbl_; _t['valor'] = (_s1[m_] / _s1['leads'] * 100).round(2)
            _pl.append(_t)
        _tv_linhas_mensal(pd.concat(_pl), "Taxa de alô e de classificação por mês (%)", pct=True, rotulos=True)

    # =================================================================
    # 2 · ESCALLO RECEPTIVO
    # =================================================================
    with _tv_tabs[1]:
        S = 's2_receptivo'
        r_leads = _tv_val(S, 'leads'); r_alo = _tv_val(S, 'alo10'); r_classif = _tv_val(S, 'classif')
        r_venda = _tv_val(S, 'venda'); r_venda_conf = _tv_val(S, 'venda_conf'); r_conf = _tv_val(S, 'conf_tel8')
        r_leads_p = _tv_val(S, 'leads', meses=_tv_per_p); r_conf_p = _tv_val(S, 'conf_tel8', meses=_tv_per_p)
        crm_tel8 = _tv_val('s2_crm', 'tel8s'); crm_no = _tv_val('s2_crm', 'no_crm'); crm_deal = _tv_val('s2_crm', 'com_deal')
        crm_v = _tv_val('s2_crm', 'tel8_venda'); crm_v_no = _tv_val('s2_crm', 'venda_no_crm'); crm_v_deal = _tv_val('s2_crm', 'venda_com_deal')
        # vendas confirmadas por tipo_venda (NOMINAL)
        _t2 = _tvd[(_tvd['secao'] == 's2_tipo') & (_tvd['metrica'] == 'vendas') & (_tvd['mes'].isin(list(_tv_per)))]
        _t2 = _t2.groupby('dim', as_index=False)['valor'].sum().sort_values('valor', ascending=False)
        _tot_tipo = float(_t2['valor'].sum()) if not _t2.empty else None
        _tv_tipo = float(_t2.loc[_t2['dim'] == 'televendas', 'valor'].sum()) if not _t2.empty else None

        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "📲", "Ligações recebidas (leads receptivos)", f"{_tv_n(r_leads)} {_tv_delta(r_leads, r_leads_p)}",
                f"alô ≥10 s em {_tv_pct(r_alo, r_leads)} · classificados {_tv_pct(r_classif, r_leads)}")
        _tv_kpi(k2, "🚫", "Existem no CRM (Contato/Lead por tel-8)", f"{_tv_pct(crm_no, crm_tel8)}",
                f"com Negócio vinculado: {_tv_pct(crm_deal, crm_tel8)} — a ligação receptiva não cria nem move o Negócio", color="#b45309")
        _tv_kpi(k3, "🔎", "Vendas encontradas para esses telefones", f"{_tv_pct(r_conf, r_leads)} {_tv_delta(r_conf, r_conf_p)}",
                f"{_tv_n(r_conf)} tel-8 com filiação no NOMINAL na janela (qualquer canal)")
        _tv_kpi(k4, "🏷️", "…das quais creditadas ao televendas (IDPV)", f"{_tv_pct(_tv_tipo, _tot_tipo)}",
                f"{_tv_n(_tv_tipo)} de {_tv_n(_tot_tipo)} vendas casadas com tipo_venda = TELEVENDAS no NOMINAL (humanos + bots GT7)")

        c1, c2 = st.columns([1.9, 1])
        with c1:
            _tv_funil("Funil Escallo · receptivo", [
                ("📲", "Ligações recebidas (leads)", r_leads, "tipo RECEPTIVO = 1ª interação do mês foi do cliente (REL002)"),
                ("🗣️", "Alô humano ≥ 10 s", r_alo, "tempoConversa ≥ 10 s"),
                ("📝", "Classificados pelo operador", r_classif, "alo_classificado = 1"),
                ("💰", "Venda (tabulação)", r_venda, "melhor_estagio = venda"),
                ("✅", "Confirmada no CTN", r_venda_conf, "tel-8 × NOMINAL na janela"),
            ], subtitle=_tv_per_lbl)
            if not _t2.empty:
                _t2c = _t2.copy(); _t2c['pct'] = _t2c['valor'] / _t2c['valor'].sum() * 100
                _t2c['mes'] = 'período'; _t2c['serie'] = _t2c['dim']
                _tv_titulo("Vendas casadas (tel-8) por canal creditado — receptivo",
                           f"tipo_venda gravado pelo CTN no NOMINAL · {_tv_per_lbl}", "A")
                _t2c['cor'] = _t2c['dim'].map(lambda x: '#166534' if str(x).lower() == 'televendas' else '#8cc79e')
                fig = px.bar(_t2c, x='valor', y='dim', orientation='h',
                             text=_t2c.apply(lambda r: f"{format_br(r['valor'])} · " + f"{r['pct']:.1f}".replace('.', ',') + "%", axis=1),
                             template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='outside', cliponaxis=False, marker_color=_t2c['cor'].tolist(), textfont_size=11.5)
                fig.update_layout(height=340, margin=dict(l=125, r=80, t=10, b=30), xaxis_title='', yaxis_title='', showlegend=False,
                                  xaxis=dict(showgrid=True, gridcolor='#d9dde3', showline=False, ticks=''),
                                  yaxis=dict(autorange='reversed', side='left', showgrid=False, tickfont=dict(size=12, color='#0f172a')))
                st.plotly_chart(fig, use_container_width=True)
                st.markdown(
                    "<div style='font-size:12.5px;color:#334155;line-height:1.5;'>"
                    "<b>Venda casada (tel-8) — como é contada.</b> Para cada telefone que ligou no mês abrimos uma <b>janela de "
                    "contato</b>: do <b>1º contato</b> (a primeira ligação desse telefone com o televendas no mês — no receptivo, a "
                    "primeira vez que o cliente ligou; coluna <code>primeiro_contato</code>) até o <b>último contato + 14 dias</b> "
                    "(a última ligação do telefone no mês, coluna <code>ultimo_contato</code>, mais duas semanas). Se esse telefone "
                    "— casado pelos <b>8 últimos dígitos</b>, porque o Escallo não captura CPF — aparece no NOMINAL_VENDAS com uma "
                    "filiação dentro dessa janela, a venda é 'casada' com a ligação.<br>"
                    "<b>Por que a janela.</b> Uma filiação <i>anterior</i> ao 1º contato não pode ter sido causada pela ligação; "
                    "os <b>+14 dias</b> cobrem o tempo típico entre a conversa e a adesão (link enviado, pagamento, retorno do "
                    "cliente) sem esticar a ponto de casar vendas que já não têm relação com o atendimento. É um corte: janelas "
                    "mais longas casam mais vendas, mas cada vez menos ligadas à ligação — a análise de influência (J2) usa 90 dias "
                    "para medir 'toque em algum momento'; aqui, 14 dias medem 'o atendimento resultou em venda'.<br>"
                    "<b>O que o gráfico mostra.</b> É coincidência telefone × venda, de <b>qualquer canal</b> — não é conversão do "
                    "receptivo. O eixo traz o <code>tipo_venda</code> que o CTN gravou para cada venda casada. Só a fatia "
                    "<b>'televendas'</b> tem IDPV do canal (venda convertida <i>e</i> creditada ao televendas — inclui os bots "
                    "GT7 Lia/Nora/Cris, que têm IDPV de televendas). As demais ('website', 'mgm', 'porta a porta'…) são vendas que "
                    "<b>passaram pelo televendas, foram trabalhadas ou influenciadas por ele, mas não necessariamente convertidas "
                    "por ele</b>: o cliente falou com o televendas e fechou por outro caminho (site, indicação, campo), e o CTN "
                    "creditou esse outro canal.</div>", unsafe_allow_html=True)
        with c2:
            _tv_note(
                f"<b>O receptivo não retroalimenta o CRM.</b> Só {_tv_pct(crm_no, crm_tel8)} dos telefones que ligaram "
                f"existem como Lead/Contato no HubSpot e {_tv_pct(crm_deal, crm_tel8)} têm um Negócio — e o Negócio, quando existe, "
                f"não é movido pela ligação (Bloco 7 da Jornada: o receptivo não cria nem movimenta Negócio).<br><br>"
                f"<b>Vendas encontradas.</b> {_tv_n(r_conf)} telefones ({_tv_pct(r_conf, r_leads)}) aparecem com filiação no NOMINAL; "
                f"dessas vendas, {_tv_pct(crm_v_no, crm_v)} têm Lead no CRM e {_tv_pct(crm_v_deal, crm_v)} têm Negócio. "
                f"Apenas <b>{_tv_pct(_tv_tipo, _tot_tipo)}</b> foram registradas pelo CTN com IDPV de televendas "
                f"(tipo_venda = TELEVENDAS); o restante foi creditado a outros canais (site, MGM, campo…) — vendas trabalhadas "
                f"ou influenciadas pelo televendas, não necessariamente convertidas por ele.",
                bg="#fff7ed", icon="⚠️")
        _mg2 = _tv_meses_grafico('t6_s2_ano')
        _tv_chart_mensal(_tv_long(S, ['leads', 'alo10', 'venda', 'conf_tel8'], meses=_mg2,
                                  labels={'leads': 'Ligações recebidas', 'alo10': 'Alô ≥10 s', 'venda': 'Venda tabulada', 'conf_tel8': 'Vendas casadas (tel-8)'}),
                         "Série mensal — receptivo", stacked=False, rotulos=True, fonte="ESCALLO_LEADS_MES (REL002)")

    # =================================================================
    # 6 · GANHOS POR PORTA
    # =================================================================
    with _tv_tabs[5]:
        S = 's3_portas'
        g_tot = _tv_val(S, 'ganhos_total'); g = _tv_val(S, 'ganhos')
        p1 = _tv_val(S, 'porta1_tabulacao'); p2 = _tv_val(S, 'porta2_checkout')
        po = _tv_val(S, 'outro_canal'); ps = _tv_val(S, 'sem_venda_registrada')
        g_p = _tv_val(S, 'ganhos_total', meses=_tv_per_p)
        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "🏁", "Negócios GANHO no período", f"{_tv_n(g_tot)} {_tv_delta(g_tot, g_p)}",
                f"entradas em NEGÓCIO GANHO (hs_v2_date_entered_961121698); {_tv_n(g)} com CPF")
        _tv_kpi(k2, "☎️", "Porta 1 · venda fechada pelo operador", f"{_tv_pct(p1, g)}",
                f"{_tv_n(p1)} — o CTN gravou canal_de_venda = TELEVENDAS no Contato, ou o Escallo tem tabulação 'venda' (tel-8)")
        _tv_kpi(k3, "🛒", "Porta 2 · cliente fechou sozinho (checkout)", f"{_tv_pct(p2, g)}",
                f"{_tv_n(p2)} — o CTN gravou WEBSITE/MGM no Contato, ou o último formulário foi o Checkout Etapa 4", color="#2e8a4f")
        _tv_kpi(k4, "❓", "Outros canais · sem venda registrada", f"{_tv_pct(po, g)} · {_tv_pct(ps, g)}",
                f"{_tv_n(po)} campo/app/outros · {_tv_n(ps)} sem rastro de venda", color="#94a3b8")

        c1, c2 = st.columns([1.9, 1])
        with c1:
            _mg3 = _tv_meses_grafico('t6_s3_ano')
            _tv_chart_mensal(_tv_long(S, ['porta1_tabulacao', 'porta2_checkout', 'outro_canal', 'sem_venda_registrada'], dim='ganho', meses=_mg3,
                                      labels={'porta1_tabulacao': 'Porta 1 · tabulação', 'porta2_checkout': 'Porta 2 · checkout',
                                              'outro_canal': 'Outros canais', 'sem_venda_registrada': 'Sem venda registrada'}),
                             "Negócios GANHO por porta de fechamento", subtitle="por mês de entrada em GANHO; só Negócios com CPF",
                             rotulos=True, fonte="hubspot_deals_raw × hubspot_contacts_raw × Escallo × NOMINAL")
            _comp = [
                ('Contato com canal_de_venda = TELEVENDAS (CTN)', _tv_val(S, 'cv_televendas')),
                ('Contato com canal_de_venda = WEBSITE', _tv_val(S, 'cv_website')),
                ('Contato com canal_de_venda = MGM', _tv_val(S, 'cv_mgm')),
                ('Contato com canal_de_venda = campo (PAP / link / app do vendedor)', _tv_val(S, 'cv_campo')),
                ('Contato sem canal_de_venda', _tv_val(S, 'cv_vazio')),
                ('Último formulário do Contato = [CTN] Negócio Ganho', _tv_val(S, 'rcen_ctn')),
                ('Último formulário do Contato = [Checkout] Etapa 4', _tv_val(S, 'rcen_etapa4')),
                ('Telefone aparece no Escallo no mês (ou anterior)', _tv_val(S, 'escallo_rastro')),
                ('… com tabulação "venda" no Escallo', _tv_val(S, 'escallo_tab_venda')),
                ('… com venda casada por tel-8 (Escallo × NOMINAL)', _tv_val(S, 'escallo_venda_casada')),
                ('CPF do Negócio com filiação no NOMINAL (−60 d / +90 d)', _tv_val(S, 'conf_nominal')),
                ('Negócio com data_de_filiacao preenchida', _tv_val(S, 'deal_filiacao')),
            ]
            _rows = [{'Componente': a, 'Negócios': (format_br(b) if b is not None else '—'),
                      '% dos GANHO c/ CPF': _tv_pct(b, g), '_level': 0, '_is_eff': False} for a, b in _comp]
            st.markdown(render_metric_table(_rows, ['Componente', 'Negócios', '% dos GANHO c/ CPF']), unsafe_allow_html=True)
        with c2:
            _tv_note(
                "<b>O que são as 'portas'.</b> No HubSpot, cada oportunidade do televendas é um <b>Negócio</b> (um card no "
                "pipeline). Quando a pessoa se filia, esse Negócio vai para o estágio <b>GANHO</b> — mas ele chega lá por dois "
                "caminhos bem diferentes, e o HubSpot não registra qual foi. Reconstruímos a 'porta' pelos rastros que a venda "
                "deixa no Contato, no Escallo e no NOMINAL:<br><br>"
                "<b>☎️ Porta 1 · venda fechada pelo operador (tabulação).</b> O atendente do televendas fechou a adesão na "
                "ligação ou no WhatsApp e registrou ('tabulou') o resultado como <i>venda</i> no Escallo; ao gravar a filiação, "
                "o CTN marca o Contato com <code>canal_de_venda = TELEVENDAS</code>. É a venda que o televendas de fato fez.<br>"
                "<b>🛒 Porta 2 · cliente fechou sozinho (checkout).</b> A pessoa concluiu a adesão por conta própria no site "
                "(formulário 'Checkout – Etapa 4') ou por indicação (MGM). O CTN grava <code>canal_de_venda = WEBSITE</code> ou "
                "<code>MGM</code> no Contato e a automação do CRM move o Negócio para GANHO — mesmo que ninguém do televendas "
                "tenha falado com ela. Reconhecemos esta porta pelo canal gravado ou, quando ele está vazio, pelo último "
                "formulário preenchido ser a Etapa 4 do checkout.<br>"
                "<b>Outros canais:</b> o CTN creditou a venda ao campo/app (porta a porta, link ou app do vendedor…), ou "
                "existe filiação no NOMINAL sem nenhum dos rastros acima.<br>"
                "<b>Sem venda registrada:</b> Negócio marcado como GANHO sem rastro algum de filiação (ganho 'de processo').<br>"
                "Cada Negócio entra em uma única porta, nesta ordem de prioridade: porta 1 → porta 2 → outros → sem venda.<br><br>"
                f"<b>Por que importa.</b> O estágio GANHO mistura vendas do televendas com fechamentos self-service: no período, "
                f"<b>{_tv_pct(p2, g)}</b> dos ganhos com CPF são porta 2 e <b>{_tv_pct(p1, g)}</b> porta 1. Para medir o que o "
                "televendas vendeu, use a porta 1 (ou a régua NOMINAL TELEVENDAS, sub-aba 4); GANHO sozinho mede processo.<br><br>"
                "Cobertura: <code>hubspot_deals_raw</code> guarda Negócios modificados desde 13/05/2026 — "
                "meses anteriores a maio são piso.")

    # =================================================================
    # 7 · TRÊS RÉGUAS DA VENDA
    # =================================================================
    with _tv_tabs[6]:
        S = 's4_reguas'
        ganho = _tv_val('s3_portas', 'ganhos_total'); ganho_conf = _tv_val('s3_portas', 'conf_nominal')
        fil = _tv_val(S, 'filiacoes_contato'); fil_tv = _tv_val(S, 'filiacoes_fluxo_tv')
        fil_tv_antes = _tv_val(S, 'filiacoes_fluxo_antes'); fil_cv = _tv_val(S, 'filiacoes_canal_venda_tv')
        fil_cv_pre = _tv_val(S, 'filiacoes_canal_venda_preenchido')
        nom_tv = _tv_val(S, 'nominal_televendas'); nom_tot = _tv_val(S, 'nominal_total')
        esc_cas = _tv_val(S, 'escallo_casadas_por_mes_venda'); esc_at = _tv_val(S, 'escallo_casadas_ativo'); esc_re = _tv_val(S, 'escallo_casadas_receptivo')

        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "🏁", "Régua 1 · NEGÓCIO GANHO (HubSpot)", _tv_n(ganho),
                f"{_tv_pct(ganho_conf, _tv_val('s3_portas', 'ganhos'))} confirmados no NOMINAL por CPF (−60 d/+90 d)")
        _tv_kpi(k2, "👤", "Régua 2 · Contato filiado via CTN (todos os canais)", _tv_n(fil),
                f"{_tv_n(fil_tv_antes)} entraram no fluxo TV antes de filiar ({_tv_pct(fil_tv_antes, fil)}) · "
                f"{_tv_n(fil_cv)} com canal_de_venda = TELEVENDAS ({_tv_pct(fil_cv, fil)})", color="#2e8a4f")
        _tv_kpi(k3, "📒", "Régua 3 · NOMINAL_VENDAS · TELEVENDAS", _tv_n(nom_tv),
                f"{_tv_pct(nom_tv, nom_tot)} das {_tv_n(nom_tot)} vendas do período (1 por CPF + data)", color="#0f172a")
        _tv_kpi(k4, "☎️", "Vendas casadas com o Escallo (tel-8)", _tv_n(esc_cas),
                f"ativo {_tv_n(esc_at)} · receptivo {_tv_n(esc_re)} — por mês da venda", color="#b45309")

        c1, c2 = st.columns([1.9, 1])
        with c1:
            _mg4 = _tv_meses_grafico('t6_s4_ano')
            _l4 = pd.concat([
                _tv_long('s3_portas', ['ganhos_total'], meses=_mg4, labels={'ganhos_total': 'Negócios GANHO'}),
                _tv_long(S, ['filiacoes_fluxo_antes'], meses=_mg4, labels={'filiacoes_fluxo_antes': 'Contatos no fluxo antes de filiar'}),
                _tv_long(S, ['filiacoes_canal_venda_tv'], meses=_mg4, labels={'filiacoes_canal_venda_tv': 'Contatos c/ canal_de_venda TV'}),
                _tv_long(S, ['nominal_televendas'], meses=_mg4, labels={'nominal_televendas': 'NOMINAL TELEVENDAS'}),
                _tv_long(S, ['escallo_casadas_por_mes_venda'], meses=_mg4, labels={'escallo_casadas_por_mes_venda': 'Escallo · casadas (tel-8)'}),
            ])
            _tv_linhas_mensal(_l4, "As réguas da venda por mês", rotulos=True,
                              subtitle="resultado (NOMINAL) · influência (Contatos no fluxo antes / Escallo tel-8) · processo (Negócios GANHO)")
            _rows4 = [
                {'Régua': 'Negócios em GANHO (processo do CRM)', 'Valor': _tv_n(ganho), '_level': 0, '_is_eff': False},
                {'Régua': '… confirmados no NOMINAL por CPF (−60 d / +90 d)', 'Valor': _tv_n(ganho_conf), '_level': 1, '_is_eff': False},
                {'Régua': 'Contatos com data_de_filiacao (CTN, qualquer canal)', 'Valor': _tv_n(fil), '_level': 0, '_is_eff': False},
                {'Régua': '… com data de entrada no fluxo do televendas (qualquer momento)', 'Valor': _tv_n(fil_tv), '_level': 1, '_is_eff': False},
                {'Régua': '… que entraram no fluxo ANTES de filiar (influência plausível)', 'Valor': _tv_n(fil_tv_antes), '_level': 1, '_is_eff': False},
                {'Régua': '… que entraram no fluxo DEPOIS de filiar (já cliente / reimpacto)', 'Valor': _tv_n((fil_tv or 0) - (fil_tv_antes or 0)) if fil_tv is not None else '—', '_level': 2, '_is_eff': False},
                {'Régua': f'… com canal_de_venda = TELEVENDAS ({_tv_pct(fil_cv_pre, fil)} dos filiados têm canal preenchido)', 'Valor': _tv_n(fil_cv), '_level': 1, '_is_eff': False},
                {'Régua': 'NOMINAL_VENDAS · tipo_venda TELEVENDAS (régua-mestra)', 'Valor': _tv_n(nom_tv), '_level': 0, '_is_eff': False},
                {'Régua': '… NOMINAL_VENDAS · total do período (1 por CPF + data)', 'Valor': _tv_n(nom_tot), '_level': 1, '_is_eff': False},
                {'Régua': 'Escallo · vendas casadas por tel-8 (teto de influência)', 'Valor': _tv_n(esc_cas), '_level': 0, '_is_eff': False},
            ]
            st.markdown(render_metric_table(_rows4, ['Régua', 'Valor']), unsafe_allow_html=True)
        with c2:
            _tv_note(
                "<b>Como ler as três réguas.</b><br>"
                "<b>1 · Negócio GANHO</b> mede <i>processo</i>: quantos Negócios o CRM fechou como ganho. Ele subconta a venda "
                "(o CTN escreve a filiação no <b>Contato</b>, não no Negócio) e inclui ganhos sem venda.<br>"
                "<b>2 · Contato filiado (CTN)</b> é onde a venda realmente chega ao HubSpot: <code>data_de_filiacao</code> + "
                "<code>canal_de_venda</code>. Use 'entrou no fluxo ANTES de filiar' para <i>influência</i> e 'canal_de_venda = TELEVENDAS' para "
                "<i>atribuição</i>. Atenção: a maior parte das datas de entrada no fluxo é posterior à filiação — são clientes "
                "reimpactados / '[Televendas] É cliente', não influência. Ressalva: CPF sem Contato prévio é apagado pelo CTN (viés de sobrevivência).<br>"
                "<b>3 · NOMINAL_VENDAS</b> é a régua-mestra (oficial, 1 por CPF + data). "
                "'TELEVENDAS' é o que a empresa credita ao canal — o <code>tipo_venda</code> vem do CTN e reúne os IDPVs dos "
                "operadores (voz e 'Atendimento WhatsApp') e dos bots GT7 (Lia, Nora, Cris); em jun–ago/26 a Lia sozinha "
                "respondeu por ~38% do canal. A linha do Escallo (tel-8) é o teto do que o canal pode ter influenciado.<br><br>"
                "Regra prática: <b>resultado</b> = NOMINAL TELEVENDAS; <b>influência</b> = Contatos filiados que entraram no fluxo antes "
                "de filiar (ou Escallo tel-8, como teto); <b>processo</b> = Negócios GANHO. Nunca somar as três.")

    # =================================================================
    # 5 · PIPELINE CRM
    # =================================================================
    with _tv_tabs[2]:
        S = 's5_pipeline'
        _stages = ['LEAD', 'EM NEGOCIAÇÃO', 'CONTATO SEM SUCESSO', 'PERDIDO', 'GANHO']
        _ent = {s_: _tv_val(S, 'entradas', dim=s_) for s_ in _stages}
        fluxo = _tv_val('s5_fluxo', 'entradas_fluxo'); fluxo_funil = _tv_val('s5_fluxo', 'entradas_com_funil_preenchido')
        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "🚪", "Contatos que entraram no fluxo", _tv_n(fluxo),
                f"data_de_entrada_no_fluxo_do_televendas no período · {_tv_pct(fluxo_funil, fluxo)} com funil_de_contatos preenchido")
        _tv_kpi(k2, "🧩", "Entradas em LEAD (Negócio)", _tv_n(_ent['LEAD']),
                f"{_tv_pct(_ent['LEAD'], fluxo)} dos Contatos do fluxo viraram um Negócio em LEAD no período")
        _tv_kpi(k3, "🤝", "Entradas em EM NEGOCIAÇÃO", _tv_n(_ent['EM NEGOCIAÇÃO']),
                f"CONTATO SEM SUCESSO: {_tv_n(_ent['CONTATO SEM SUCESSO'])}", color="#2e8a4f")
        _tv_kpi(k4, "🏁", "GANHO · PERDIDO", f"{_tv_n(_ent['GANHO'])} · {_tv_n(_ent['PERDIDO'])}",
                f"ganho/(ganho+perdido) = {_tv_pct(_ent['GANHO'], (_ent['GANHO'] or 0) + (_ent['PERDIDO'] or 0))}", color="#0f172a")

        c1, c2 = st.columns([1.9, 1])
        with c1:
            # 18/09: todos os estágios (PERDIDO incluído) como fatias dos Negócios dos Contatos no fluxo; toggle de raias (R31) como na aba 🧲
            _t5_raias = st.toggle("🗺️ Ver como diagrama de raias — onde cada número nasce", value=False, key='t5_raias',
                                  help="Alternativa ao funil: Contatos no fluxo na raia de Contato, entradas por estágio na raia de Negócio, "
                                       "venda confirmada na raia do CTN — os mesmos números do funil.")
            if _t5_raias:
                _tv_raias('pipeline', {'fluxo': fluxo, 'lead': _ent['LEAD'], 'neg': _ent['EM NEGOCIAÇÃO'], 'css': _ent['CONTATO SEM SUCESSO'],
                                       'ganho': _ent['GANHO'], 'perdido': _ent['PERDIDO']},
                          "Pipeline CDT - Lead Televendas · entradas por estágio", _tv_per_lbl)
            else:
                _tv_funil("Pipeline CDT - Lead Televendas · Negócios dos Contatos no fluxo, por estágio", [
                    ("🚪", "Contatos no fluxo do televendas", fluxo, "Contato: data_de_entrada_no_fluxo_do_televendas no período"),
                    ("🤝", "Negócios associados (entraram em LEAD)", _ent['LEAD'], "Negócio criado no pipeline · hs_v2_date_entered_961121694 · seq. = % dos Contatos"),
                    ("🔁", "↳ estágio EM NEGOCIAÇÃO", _ent['EM NEGOCIAÇÃO'], "…961121695 (régua 7 d) · seq. = % dos Negócios", 1),
                    ("📵", "↳ estágio CONTATO SEM SUCESSO", _ent['CONTATO SEM SUCESSO'], "…961121696 (régua 1 d 12 h) · seq. = % dos Negócios", 1),
                    ("🏁", "↳ estágio GANHO", _ent['GANHO'], "…961121698 — porta 1 (tabulação) ou porta 2 (checkout) · seq. = % dos Negócios", 1),
                    ("❌", "↳ estágio PERDIDO", _ent['PERDIDO'], "…961121697 — auto-redistribui (exceto 'sem interesse') · seq. = % dos Negócios", 1),
                ], subtitle="os estágios são fatias dos Negócios dos Contatos no fluxo (um Negócio pode entrar em vários no período) · do topo = % dos Contatos")  # sem chips: _tv_chip só é definido mais abaixo no módulo (abas 🧲/🧭)
            _mg5 = _tv_meses_grafico('t6_s5_ano')
            _tv_chart_mensal(pd.concat([_tv_serie(S, 'entradas', dim=s_, meses=_mg5).assign(serie=s_) for s_ in _stages]),
                             "Entradas por estágio, por mês", stacked=False, rotulos=True,
                             subtitle="hs_v2_date_entered_* do pipeline CDT - Lead Televendas", fonte="hubspot_deals_raw")
            # estoque por estágio no FIM do período selecionado (último mês ou última semana do grão); o período
            # corrente equivale ao estoque de agora. Compara com o fim do período anterior.
            _est_all = _tvd[(_tvd['secao'] == 's5_estoque') & (_tvd['metrica'] == 'estoque')]
            _p_fim = _tv_per[-1]
            _p_fim_ant = _tv_per_p[-1] if _tv_per_p else None
            _est = _est_all[_est_all['mes'] == _p_fim].groupby('dim', as_index=False)['valor'].sum()
            if _est.empty and not _est_all.empty:
                _p_fim = _est_all['mes'].max()   # agregado antigo (só carimbo do último mês)
                _est = _est_all[_est_all['mes'] == _p_fim].groupby('dim', as_index=False)['valor'].sum()
            if not _est.empty:
                _est = _est[_est['dim'].isin(_stages)].set_index('dim').reindex(_stages).fillna(0).reset_index()
                _est_ant = (_est_all[_est_all['mes'] == _p_fim_ant].groupby('dim')['valor'].sum() if _p_fim_ant is not None else pd.Series(dtype=float))
                _hoje = pd.Timestamp(reference_date)
                _fim_data = (_p_fim + pd.offsets.MonthEnd(0)) if _tv_grain == 'M' else (_p_fim + pd.Timedelta(days=6))
                _fim_lbl = "hoje (última carga)" if _fim_data >= _hoje else _fim_data.strftime('%d/%m/%Y')
                _col_est = f"Estágio · estoque em {_fim_lbl}"
                _rows5 = []
                for _, r in _est.iterrows():
                    _va = float(_est_ant.get(r['dim'], 0)) if not _est_ant.empty else None
                    _rows5.append({_col_est: r['dim'], 'Negócios': format_br(r['valor']),
                                   'vs fim do período anterior': (f"{format_br(_va)} {_tv_delta(r['valor'], _va)}" if _va else '—'),
                                   '_level': 0, '_is_eff': False})
                st.markdown(render_metric_table(_rows5, [_col_est, 'Negócios', 'vs fim do período anterior']), unsafe_allow_html=True)
                st.caption("Estoque = em que estágio cada Negócio do pipeline CDT - Lead Televendas estava no fim do período: o estágio "
                           "atual, se já estava nele naquela data; senão o último estágio em que tinha entrado até lá (empate → o mais "
                           "avançado); Negócio já criado mas sem data de estágio conta como LEAD. É uma foto, não um fluxo: todo período "
                           "que inclui hoje mostra a mesma foto (última carga) — o que muda com o período é a data da foto (períodos "
                           "passados) e a coluna de comparação (fim da semana anterior no grão semanal; fim do mês anterior no mensal). "
                           "GANHO e PERDIDO são finais e só acumulam; LEAD, EM NEGOCIAÇÃO e CONTATO SEM SUCESSO são o estoque vivo. Se a "
                           "base de Negócios não recebeu movimentação entre duas datas, os estoques saem iguais. Cobertura: Negócios "
                           "modificados desde 13/05/2026.")
        with c2:
            # auditoria funil_de_contatos × data_de_entrada
            _aud = _tvd_m[(_tvd_m['secao'] == 's5_audit')]
            if not _aud.empty:
                _aud = _aud[_aud['mes'] == _aud['mes'].max()].pivot_table(index='dim', columns='metrica', values='valor', aggfunc='sum').fillna(0)
                _tot_ent = float(_aud['com_entrada_fluxo'].sum())
                _is_tv = _aud.index.str.contains(r'\[Televendas\]', regex=True)
                _is_fe = _aud.index.str.contains('Fora do Expediente', case=False)
                _is_vz = _aud.index == '(vazio)'
                _tv_share = float(_aud.loc[_is_tv, 'com_entrada_fluxo'].sum())
                _fe_share = float(_aud.loc[_is_fe, 'com_entrada_fluxo'].sum())
                _vz_share = float(_aud.loc[_is_vz, 'com_entrada_fluxo'].sum())
                _tv_rot_tot = float(_aud.loc[_is_tv, 'contatos'].sum())
                _tv_note(
                    "<b>Auditoria: <code>funil_de_contatos_para_o_televendas</code> × <code>data_de_entrada_no_fluxo_do_televendas</code>.</b><br>"
                    f"Dos Contatos com data de entrada no fluxo, <b>{_tv_pct(_tv_share, _tot_ent)}</b> carregam um rótulo "
                    f"[Televendas] do funil, {_tv_pct(_fe_share, _tot_ent)} 'Fora do expediente – criado direto para distribuição', "
                    f"{_tv_pct(_vz_share, _tot_ent)} estão sem rótulo e o restante recebeu um segmento de exclusão. "
                    f"No sentido inverso, {_tv_pct(_tv_share, _tv_rot_tot)} dos rótulos [Televendas] têm data de entrada.<br><br>"
                    "<b>Como ler a aba.</b> A régua confiável de <i>quem entrou</i> é a data de entrada (marcador do workflow); "
                    "o <code>funil_de_contatos</code> descreve o <i>estado</i> em que o Contato foi deixado (criado, é cliente, "
                    "telefone incorreto…) e cobre ~80–90% das entradas — use-o para explicar, não para contar. "
                    "As entradas em LEAD abaixo do fluxo mostram quantos Contatos viraram Negócio; o Negócio sobe para "
                    "EM NEGOCIAÇÃO/CONTATO SEM SUCESSO pela régua automática e fecha em GANHO por tabulação ou checkout.",
                    bg="#f8fafc", icon="🔍")
                with st.expander("Detalhe da auditoria por rótulo do funil"):
                    _a2 = _aud.reset_index().rename(columns={'dim': 'funil_de_contatos_para_o_televendas'})
                    _a2['% com entrada'] = (_a2['com_entrada_fluxo'] / _a2['contatos'] * 100).round(1)
                    _a2 = _a2.sort_values('com_entrada_fluxo', ascending=False)
                    st.dataframe(_a2[['funil_de_contatos_para_o_televendas', 'contatos', 'com_entrada_fluxo', '% com entrada', 'filiados']],
                                 use_container_width=True, hide_index=True)
            else:
                _tv_note("A auditoria <code>funil_de_contatos</code> × <code>data_de_entrada</code> ainda não foi gravada: "
                         "rode o pipeline com <code>--arg audit=1</code> (varredura completa de Contatos, ~4 min).", bg="#fff7ed", icon="⚠️")
            _tv_note(
                "<b>Vocabulário.</b> O CRM fecha 'CPF cadastrado' e 'pagamento não autorizado' como PERDIDO; "
                "no Escallo esses casos aparecem como já_cliente / venda_travada (informação, não perda). "
                "PERDIDO auto-redistribui (exceto 'sem interesse'). Cobertura de Negócios a partir de 13/05/2026.",
                bg="#f8fafc", icon="ℹ️")

    # =================================================================
    # 8 · GRUPOS A–D
    # =================================================================
    with _tv_tabs[7]:
        _c6 = _tvd[(_tvd['secao'] == 's6_canal') & (_tvd['mes'].isin(list(_tv_per)))]
        if _c6.empty:
            st.info("Sem linhas de canal para o período.")
        else:
            _w6 = _c6.pivot_table(index='dim', columns='metrica', values='valor', aggfunc='sum').fillna(0).reset_index()
            _w6[['grupo', 'canal_regra']] = _w6['dim'].apply(lambda c: pd.Series(_tv_grupo(c)))
            _cols6 = ['contatos', 'no_fluxo', 'enviados_engaj', 'distribuidos_franquia', 'filiados', 'com_cpf']
            for c_ in _cols6:
                if c_ not in _w6.columns:
                    _w6[c_] = 0.0
            _g6 = _w6.groupby('grupo')[_cols6].sum()
            _ordem = ['A', 'B', 'C', 'D', 'Fora da regra']
            _g6 = _g6.reindex(_ordem).fillna(0)
            k = st.columns(5)
            for i, g_ in enumerate(_ordem):
                r_ = _g6.loc[g_]
                _tv_kpi(k[i], {'A': '🅰️', 'B': '🅱️', 'C': '🅲', 'D': '🅳', 'Fora da regra': '❔'}[g_],
                        f"Grupo {g_}" if g_ != 'Fora da regra' else "Fora da regra",
                        format_br(r_['contatos']),
                        f"no fluxo {_tv_pct(r_['no_fluxo'], r_['contatos'])} · engaj. {_tv_pct(r_['enviados_engaj'], r_['contatos'])} · "
                        f"filiados {_tv_pct(r_['filiados'], r_['contatos'])}",
                        color={'A': '#166534', 'B': '#2e8a4f', 'C': '#57a86f', 'D': '#8cc79e', 'Fora da regra': '#94a3b8'}[g_])
            _rows6 = []
            for g_ in _ordem:
                r_ = _g6.loc[g_]
                _rows6.append({'Grupo / canal': (f"Grupo {g_}" if g_ != 'Fora da regra' else 'Fora da regra'), 'Contatos criados': format_br(r_['contatos']),
                               'No fluxo TV': f"{format_br(r_['no_fluxo'])} ({_tv_pct(r_['no_fluxo'], r_['contatos'])})",
                               'Enviados p/ Engajamento': f"{format_br(r_['enviados_engaj'])} ({_tv_pct(r_['enviados_engaj'], r_['contatos'])})",
                               'Distribuídos p/ franquia': f"{format_br(r_['distribuidos_franquia'])} ({_tv_pct(r_['distribuidos_franquia'], r_['contatos'])})",
                               'Filiados': f"{format_br(r_['filiados'])} ({_tv_pct(r_['filiados'], r_['contatos'])})",
                               '_level': 0, '_is_eff': False})
                _sub = _w6[_w6['grupo'] == g_].groupby('canal_regra')[_cols6].sum().sort_values('contatos', ascending=False)
                for cr_, s_ in _sub.iterrows():
                    _rows6.append({'Grupo / canal': cr_, 'Contatos criados': format_br(s_['contatos']),
                                   'No fluxo TV': f"{format_br(s_['no_fluxo'])} ({_tv_pct(s_['no_fluxo'], s_['contatos'])})",
                                   'Enviados p/ Engajamento': f"{format_br(s_['enviados_engaj'])} ({_tv_pct(s_['enviados_engaj'], s_['contatos'])})",
                                   'Distribuídos p/ franquia': f"{format_br(s_['distribuidos_franquia'])} ({_tv_pct(s_['distribuidos_franquia'], s_['contatos'])})",
                                   'Filiados': f"{format_br(s_['filiados'])} ({_tv_pct(s_['filiados'], s_['contatos'])})",
                                   '_level': 1, '_is_eff': False})
            st.markdown(render_metric_table(_rows6, ['Grupo / canal', 'Contatos criados', 'No fluxo TV',
                                                     'Enviados p/ Engajamento', 'Distribuídos p/ franquia', 'Filiados']),
                        unsafe_allow_html=True)
            with st.expander("Regra de roteamento de cada grupo (Jornada HubSpot)"):
                for g_ in _ordem:
                    st.markdown(f"**{g_}** — {GRUPOS_REGRA.get(g_, '')}")
            _faltam = [lbl for _t, g_, lbl in GRUPOS_CANAL if lbl not in set(_w6['canal_regra'])]
            st.caption("Contagem = Contatos CRIADOS no período (createdate), agrupados por `primeiro_canal_de_origem` "
                       "(fallback: 1º valor de `canal_de_origem_detalhada`). 'No fluxo TV' = data_de_entrada_no_fluxo_do_televendas; "
                       "'Engajamento' = data_do_primeiro_envio_para_instancia_de_engajamento; 'franquia' = data_de_distribuicao / id_franquia_distribuida. "
                       + (f"Sem valor de origem correspondente no período: {', '.join(_faltam)}. " if _faltam else "")
                       + "De-para editável em GRUPOS_CANAL (app.py).")
            _tv_note(
                "<b>Leitura.</b> Grupo A deve mostrar alta entrada no fluxo (2 h exclusivas do televendas); Grupo B deve "
                "mostrar entrada baixa no fluxo e alto envio para Engajamento/franquia (vai direto à distribuição). "
                "Onde a regra não se cumpre — por exemplo Regionais entrando no fluxo, ou Whatsapp com envio baixo — "
                "é o roteamento (workflow DEAL CREATE, id 1637561194) que precisa ser conferido, não o dado.",
                bg="#f8fafc", icon="🧭")
            with st.expander("Canais de origem no período (detalhe)"):
                st.markdown(
                    "**Como ler esta tabela.** Cada linha é um valor de `primeiro_canal_de_origem` do HubSpot (o 1º canal gravado no "
                    "Contato), com os Contatos **criados no período** e por onde eles passaram — sempre como *contagem acumulada até "
                    "hoje*, não só dentro do período:<br>"
                    "• **grupo / canal_regra** — a que grupo de roteamento da Jornada (A–D) o canal foi mapeado pelo de-para "
                    "`GRUPOS_CANAL` do app.py, e o rótulo da regra que casou (\"Fora da regra\" = nenhuma regra documentada).<br>"
                    "• **contatos** — Contatos criados no período com esse 1º canal (`createdate`).<br>"
                    "• **no_fluxo** — desses, quantos têm `data_de_entrada_no_fluxo_do_televendas` (entraram nas 2 h exclusivas do "
                    "televendas). Esperado alto no Grupo A e ~0 no B.<br>"
                    "• **enviados_engaj** — quantos têm `data_do_primeiro_envio_para_instancia_de_engajamento` (Negócio criado no "
                    "pipeline de Distribuição e entregue à instância de Engajamento).<br>"
                    "• **distribuidos_franquia** — quantos têm `data_de_distribuicao` ou `id_franquia_distribuida` (chegaram a uma "
                    "franquia; é o marcador do RMA 'encaminhados para franquias').<br>"
                    "• **filiados** — quantos têm `data_de_filiacao` (viraram cliente, por qualquer canal de venda).<br>"
                    "• **com_cpf** — quantos têm `cpf_norm` (só esses cruzam com o NOMINAL).<br>"
                    "As colunas **%** dividem cada marcador por *contatos*. Leitura típica: um canal do Grupo A com `% no fluxo` baixo, "
                    "ou um canal do Grupo B com `% no fluxo` alto (ex.: Facebook - Regional), é o roteamento (workflow DEAL CREATE) "
                    "que está fora da regra — não o dado. `% filiados` compara a qualidade dos canais dentro do mesmo período "
                    "(meses recentes têm menos tempo para filiar).", unsafe_allow_html=True)
                _d6 = _w6.sort_values('contatos', ascending=False)[['grupo', 'canal_regra', 'dim'] + _cols6].copy()
                _d6 = _d6.rename(columns={'dim': 'primeiro_canal_de_origem'})
                for _c, _lbl in [('no_fluxo', '% no fluxo'), ('enviados_engaj', '% engaj.'), ('distribuidos_franquia', '% franquia'),
                                 ('filiados', '% filiados'), ('com_cpf', '% com CPF')]:
                    _d6[_lbl] = (_d6[_c] / _d6['contatos'].replace(0, pd.NA) * 100).astype(float).round(1)
                st.dataframe(_d6, use_container_width=True, hide_index=True)

    # =================================================================
    # 7 · TALKERCHAT (fonte: API pública — alex_talkerchat_api, desde 16/09/2026)
    # -----------------------------------------------------------------
    # Seções do pipeline (televendas_dash.py, s7): s7_talkerchat (funil + CRM + NOMINAL) · s7_tempos (mediana/p90/média
    # em minutos: espera até humano, duração humano, duração bot) · s7_atendente (dim = atendente) · s7_hora (dim = 'D-HH')
    # · s7_motivo (dim = 'id · motivo') · s7_estoque (retrato dos tickets abertos, por status, gravado no período corrente).
    # Grão: segue _tvd (semana quando o período é curto). Frescor D-1 (tkcDaily 06h + tkcWorker 10 min; recarga 11:00).
    # =================================================================
    with _tv_tabs[3]:
        S = 's7_talkerchat'
        tk = _tv_val(S, 'tickets'); tl = _tv_val(S, 'leads'); tlc_id = _tv_val(S, 'leads_contato'); tcpf = _tv_val(S, 'com_cpf')
        th = _tv_val(S, 'leads_humano'); tk_h = _tv_val(S, 'tickets_humano'); tk_b = _tv_val(S, 'tickets_bot')
        tk_sac = _tv_val(S, 'tickets_sac'); tk_lia = _tv_val(S, 'tickets_lia'); tl_sac = _tv_val(S, 'leads_sac')  # 18/09: triagem → SAC × Lia vendas
        tcomp = _tv_val(S, 'compras'); tlia = _tv_val(S, 'compras_lia'); thum = _tv_val(S, 'compras_humano')
        tlc = _tv_val(S, 'leads_compra'); tpar = _tv_val(S, 'pares_compra_cpf'); tconf = _tv_val(S, 'compras_confirmadas')
        tab_per = _tv_val(S, 'abertos')
        tcrm_l = _tv_val(S, 'leads_cpf'); tcrm_c = _tv_val(S, 'com_contato_hs'); tcrm_d = _tv_val(S, 'com_deal_criado_no_mes'); tcrm_dq = _tv_val(S, 'com_deal_qualquer_epoca')
        tl_p = _tv_val(S, 'leads', meses=_tv_per_p); tk_p = _tv_val(S, 'tickets', meses=_tv_per_p); tcomp_p = _tv_val(S, 'compras', meses=_tv_per_p)
        tbot = (tl - th) if (tl is not None and th is not None) else None
        _tk_api = tk_b is not None  # seções novas presentes? (senão o agregado ainda é o do export antigo)

        def _tv_min(v):
            """Minutos → texto curto: 45 s · 12 min · 1h05 · 2,3 d."""
            if v is None or pd.isna(v):
                return "—"
            v = float(v)
            if v < 1:
                return f"{v * 60:.0f} s"
            if v < 60:
                return f"{v:.0f} min"
            if v < 60 * 24:
                return f"{int(v // 60)}h{int(v % 60):02d}"
            return f"{v / 1440:.1f} d".replace('.', ',')

        def _tv_tempo(name, stat='med', meses=None):
            """Estatística de tempo (minutos) do período: exata em um período; em vários, média das
            estatísticas ponderada pelo nº de tickets (n) de cada período."""
            meses = _tv_per if meses is None else meses
            d = _tvd[(_tvd['secao'] == 's7_tempos') & (_tvd['mes'].isin(list(meses)))]
            v = d[d['metrica'] == f'{name}_{stat}_min'][['mes', 'valor']]
            n = d[d['metrica'] == f'{name}_n'][['mes', 'valor']].rename(columns={'valor': 'n'})
            m = v.merge(n, on='mes')
            m = m[m['valor'].notna() & (m['n'] > 0)]
            if m.empty:
                return None
            return float((m['valor'] * m['n']).sum() / m['n'].sum())

        def _tv_pivot7(secao, meses=None):
            meses = _tv_per if meses is None else meses
            d = _tvd[(_tvd['secao'] == secao) & (_tvd['mes'].isin(list(meses)))]
            if d.empty:
                return pd.DataFrame()
            return d.pivot_table(index='dim', columns='metrica', values='valor', aggfunc='sum').fillna(0).reset_index()

        if not _tk_api:
            st.warning("⚠️ O agregado ainda não tem as seções da API do Talkerchat (s7_tempos, s7_atendente, s7_hora, s7_motivo, "
                       "s7_estoque). Rode `gt7 run televendas_dash --arg only=s7 --arg nv=skip` (claude-toolkit) e recarregue os dados.")

        # ---- KPIs linha 1: volume e conversão ----
        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "💬", "Usuários únicos (tel-8) no período", f"{_tv_n(tl)} {_tv_delta(tl, tl_p)}",
                (f"{_tv_n(tk)} tickets {_tv_delta(tk, tk_p)} · " + f"{tk / tl:.2f}".replace('.', ',') + " por usuário"
                 + (f" · {_tv_n(tlc_id)} contatos (contact_id)" if tlc_id is not None else "")) if tk and tl else "")
        _tv_kpi(k2, "🪪", "Qualificados (com CPF)", f"{_tv_pct(tcpf, tl)}", f"{_tv_n(tcpf)} usuários com CPF capturado nas mensagens")
        if tk_sac is not None:  # agregado já traz a separação triagem → SAC × Lia vendas (18/09)
            _tv_kpi(k3, "🤖", "Lia (vendas) × triagem → SAC × humano — tickets",
                    f"{_tv_pct(tk_lia, tk)} · {_tv_pct(tk_sac, tk)} · {_tv_pct(tk_h, tk)}",
                    f"{_tv_n(tk_lia)} Lia · {_tv_n(tk_sac)} triagem → SAC · {_tv_n(tk_h)} com atendente · "
                    f"usuários: {_tv_pct(tl_sac, tl)} barrados na triagem (CPF já cadastrado)", color="#2e8a4f")
        else:
            _tv_kpi(k3, "🤖", "Só bot (Lia) × humano — tickets", f"{_tv_pct(tk_b, tk)} · {_tv_pct(tk_h, tk)}",
                    f"{_tv_n(tk_b)} só Lia · {_tv_n(tk_h)} com atendente · usuários: {_tv_pct(tbot, tl)} só Lia", color="#2e8a4f")
        _tv_kpi(k4, "🛒", "Compras reportadas → confirmadas", f"{_tv_n(tcomp)} {_tv_delta(tcomp, tcomp_p)}",
                f"Lia {_tv_pct(tlia, tcomp)} · humano {_tv_pct(thum, tcomp)} · {_tv_pct(tconf, tpar)} confirmadas no NOMINAL (CPF ±3 d)")

        # ---- KPIs linha 2: tempos e estoque ----
        _esp = _tv_tempo('espera'); _esp90 = _tv_tempo('espera', 'p90')
        _dur_h = _tv_tempo('duracao_humano'); _dur_h90 = _tv_tempo('duracao_humano', 'p90')
        _dur_b = _tv_tempo('duracao_bot'); _dur_b90 = _tv_tempo('duracao_bot', 'p90')
        _est = _tvd[_tvd['secao'] == 's7_estoque']
        _est_dt = None
        if not _est.empty:
            _est_dt = _est['atualizado_em'].max() if 'atualizado_em' in _est.columns else None
            _est = _est[_est['mes'] == _est['mes'].max()].pivot_table(index='dim', columns='metrica', values='valor',
                                                                       aggfunc='sum').fillna(0).reset_index()
        _est_tot = float(_est['abertos'].sum()) if (not _est.empty and 'abertos' in _est.columns) else None
        _est_ant = float(_est['de_dias_anteriores'].sum()) if (not _est.empty and 'de_dias_anteriores' in _est.columns) else None
        _est_att = float(_est['com_atendente'].sum()) if (not _est.empty and 'com_atendente' in _est.columns) else None
        k5, k6, k7, k8 = st.columns(4)
        _tv_kpi(k5, "⏱️", "Espera até um humano assumir (mediana)", _tv_min(_esp),
                f"p90 {_tv_min(_esp90)} · criado → opened_at, só tickets com atendente", color="#b45309")
        _tv_kpi(k6, "🧑‍💼", "Duração do atendimento humano (mediana)", _tv_min(_dur_h),
                f"p90 {_tv_min(_dur_h90)} · opened_at → closed_at", color="#b45309")
        _tv_kpi(k7, "🤖", "Duração da conversa só com a Lia (mediana)", _tv_min(_dur_b),
                f"p90 {_tv_min(_dur_b90)} · criado → closed_at, attended_by_bot", color="#2e8a4f")
        _tv_kpi(k8, "📥", "Estoque de tickets abertos (hoje)", _tv_n(_est_tot),
                (f"{_tv_n(_est_ant)} de dias anteriores · {_tv_n(_est_att)} já com atendente · "
                 f"{_tv_n(tab_per)} criados no período ainda abertos"
                 + (f" · retrato {pd.Timestamp(_est_dt):%d/%m %H:%M}" if _est_dt is not None else "")), color="#0f172a")

        # ---- funil + série mensal + notas ----
        c1, c2 = st.columns([1.9, 1])
        with c1:
            _tv_funil("Funil Talkerchat (WhatsApp)", [
                ("💬", "Tickets", tk, "conversas criadas no período (created_at, fuso BRT)"),
                ("👤", "Usuários únicos", tl, f"telefone_key (tel-8)" + (f" · {_tv_n(tlc_id)} por contact_id" if tlc_id is not None else "")),
                ("🪪", "Qualificados (CPF)", tcpf, "CPF capturado nas mensagens (~75% de acerto) · seq. = % dos usuários únicos"),
                ("🧑‍💼", "Chegaram a um humano", th, "usuários com agent_id em algum ticket — fatia dos usuários únicos (seq. = % deles)", 1),
                ("🛒", "Compra reportada (usuários)", tlc, f"close_reason = 'Compra reportada' · {_tv_n(tcomp)} tickets"),
                ("✅", "Confirmadas no NOMINAL", tconf, "pares CPF × âncora (fechamento) ±3 d"),
            ], subtitle=_tv_per_lbl)
            _mg7 = _tv_meses_grafico('t6_s7_ano')
            _tv_chart_mensal(_tv_long(S, ['tickets_lia', 'tickets_sac', 'tickets_humano'] if tk_sac is not None else ['tickets_bot', 'tickets_humano'], meses=_mg7,
                                      labels={'tickets_lia': 'Lia (vendas)', 'tickets_sac': 'Triagem → SAC', 'tickets_bot': 'Só Lia (bot)', 'tickets_humano': 'Com atendente humano'}),
                             "Tickets por mês — Lia × triagem → SAC × humano" if tk_sac is not None else "Tickets por mês — bot × humano",
                             subtitle="close_reason 4 (Transferido para SAC) = triagem · agent_id = humano · resto = Lia" if tk_sac is not None else "attended_by_bot / agent_id da API",
                             stacked=True, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api)")
            _tv_chart_mensal(_tv_long(S, ['compras_lia', 'compras_humano'], meses=_mg7,
                                      labels={'compras_lia': 'Compras Lia (bot)', 'compras_humano': 'Compras humano'}),
                             "Compras reportadas por mês — Lia × humano", subtitle="close_reason = 'Compra reportada'",
                             stacked=True, rotulos=True, fonte="API Talkerchat (alex_talkerchat_api)")
        with c2:
            _tv_note(
                (f"<b>Bot × humano de verdade.</b> O <code>attended_by_bot</code> da API marca {_tv_pct(tk_b, tk)} dos tickets como 'só bot', "
                 f"mas isso mistura duas fases do mesmo número: a <b>triagem</b> (roteiro fixo — apresentação da Lia → pede o CPF → se já está na base, "
                 f"responde 'CPF já cadastrado' e fecha como <i>Transferido para SAC</i>) e a <b>conversa de vendas</b> da Lia. Separando pelo motivo de "
                 f"fechamento: <b>{_tv_pct(tk_lia, tk)}</b> Lia vendas · <b>{_tv_pct(tk_sac, tk)}</b> triagem → SAC · <b>{_tv_pct(tk_h, tk)}</b> com atendente "
                 f"(<code>agent_id</code>). Não há campo de handover na API — a assinatura está só nas mensagens ('Vou conectar você com um consultor "
                 f"especializado' → humano). Amostra de 520 tickets (18/09): dentro da fatia Lia, ~14 pp são clientes que não responderam após o roteiro; "
                 f"conversas reais com a Lia ≈ 39% do total. Nas compras, a Lia responde por {_tv_pct(tlia, tcomp)}.<br><br>"
                 if tk_sac is not None else
                 f"<b>Bot × humano de verdade.</b> {_tv_pct(tk_b, tk)} dos tickets foram atendidos só pela Lia "
                 f"(<code>attended_by_bot</code>, campo da API — a etiqueta 'Venda Lia' do export antigo oscilava e zerou em ago/26); "
                 f"{_tv_pct(tk_h, tk)} tiveram um atendente humano. Por usuário: {_tv_pct(tbot, tl)} só falaram com a Lia no período. "
                 f"Nas compras, a Lia responde por {_tv_pct(tlia, tcomp)}.<br><br>") +
                f"<b>A falha: nenhum Negócio é criado.</b> Dos {_tv_n(tcrm_l)} usuários com CPF, {_tv_pct(tcrm_c, tcrm_l)} existem como "
                f"Contato no HubSpot, mas só <b>{_tv_pct(tcrm_d, tcrm_l)}</b> tiveram um Negócio criado no período da conversa "
                f"({_tv_pct(tcrm_dq, tcrm_l)} têm algum Negócio em qualquer época). O Talkerchat não está integrado ao CRM (L2).",
                bg="#fff7ed", icon="⚠️")
            _tv_note(
                "<b>Fonte: API pública do Talkerchat</b> (<code>alex_talkerchat_api</code>, carga GAS: <code>tkcDaily</code> 06h + "
                "<code>tkcWorker</code> a cada 10 min; frescor D-1, histórico desde 16/04/2026). Horários em America/Sao_Paulo — "
                "o export CSV antigo gravava UTC como hora local (heatmap deslocado 3 h). "
                "Perdas em relação ao export: etiquetas, equipe e CEP não vêm pela API; o CPF é lido das mensagens "
                "(<code>cpf_source = 'messages'</code>, ~75% dos tickets com motivo de compra/cadastro) até a D3 expor o campo. "
                "Compras confirmadas por CPF ±3 dias no NOMINAL.",
                bg="#f8fafc", icon="ℹ️")

        # ---- Fases da conversa (18/09): triagem × Lia vendas × humano — estimativa por AMOSTRA de mensagens (s7_fases,
        #      pipeline tkc_fases). Só existe no agregado mensal: em grão semanal usa os meses tocados pelo período. ----
        def _tv_fase(m):
            _s = _tv_serie('s7_fases', m)
            return float(_s['valor'].sum()) if not _s.empty else None

        def _tv_fase_max(m):
            _s = _tv_serie('s7_fases', m)
            return float(_s['valor'].max()) if not _s.empty else None
        _f_trg = _tv_fase('fase_bot_triagem'); _f_vnd = _tv_fase('fase_bot_vendas')
        if _f_trg is not None and _f_vnd is not None:
            _f_tot = _tv_fase('amostra_tickets'); _f_n = _tv_fase('amostra_n'); _f_bot = _f_trg + _f_vnd
            _f_hum = (_tv_fase('fase_humano') or 0) + (_tv_fase('fase_handover_humano') or 0)
            _f_sr = _tv_fase('fase_triagem_sem_resp'); _f_cv = _tv_fase('fase_triagem_conversa'); _f_sac = _tv_fase('fase_triagem_sac')
            _f_zero = _tv_fase('fase_zero_msgs'); _f_lv = _tv_fase('fase_lia_vendas'); _f_lsr = _tv_fase('fase_lia_sem_roteiro')
            _f_hnd = _tv_fase('fase_handover_humano')
            _q_cpf = _tv_fase('qual_cpf'); _q_sr = _tv_fase('qual_sales_ready'); _q_bot = _tv_fase('qual_sr_bot'); _q_hum = _tv_fase('qual_sr_humano')
            _e_v = _tv_fase_max('erro_bot_vendas_pp'); _e_s = _tv_fase_max('erro_sales_ready_pp')
            _pp = lambda v: ("±" + f"{v:.1f}".replace('.', ',') + " pp") if v is not None else ""
            st.markdown("---")
            _tv_titulo("Bot × humano de verdade — fases da conversa",
                       f"estimativa por amostra de mensagens da API ({_tv_n(_f_n)} tickets lidos · {_tv_n(_f_tot)} tickets nos meses tocados pelo período) · "
                       f"bot total = attended_by_bot; triagem = roteiro + CPF; vendas = Lia depois do handover", "A")
            f1, f2, f3, f4 = st.columns(4)
            _tv_kpi(f1, "🤖", "Bot — total (attended_by_bot)", f"{_tv_n(_f_bot)} · {_tv_pct(_f_bot, _f_tot)}",
                    f"= triagem + vendas · agregado exato: {_tv_n(tk_b)} tickets ({_tv_pct(tk_b, tk)})", color="#94a3b8")
            _tv_kpi(f2, "🛂", "Bot — triagem (conversa preliminar)", f"{_tv_n(_f_trg)} · {_tv_pct(_f_trg, _f_tot)}",
                    f"sem resposta {_tv_n(_f_sr)} · conversou sem desfecho {_tv_n(_f_cv)} · CPF já cadastrado → SAC {_tv_n(_f_sac)} · vazios {_tv_n(_f_zero)}",
                    color="#86b58f")
            _tv_kpi(f3, "💚", "Bot — vendas (Lia após o handover)", f"{_tv_n(_f_vnd)} · {_tv_pct(_f_vnd, _f_tot)} {_pp(_e_v)}",
                    f"link de adesão após o CPF {_tv_n(_f_lv)} · conversa livre sem roteiro (continuação / fluxo antigo) {_tv_n(_f_lsr)}",
                    color="#2e8a4f")
            _tv_kpi(f4, "🧑‍💼", "Humano", f"{_tv_n(_f_hum)} · {_tv_pct(_f_hum, _f_tot)}",
                    f"com atendente (agent_id) {_tv_n(_f_hum - (_f_hnd or 0))} · handover sem atendente {_tv_n(_f_hnd)} · exato: {_tv_n(tk_h)} ({_tv_pct(tk_h, tk)})",
                    color="#166534")
            _tv_chart_mensal(_tv_long('s7_fases', ['fase_triagem_sem_resp', 'fase_zero_msgs', 'fase_triagem_conversa', 'fase_triagem_sac',
                                                       'fase_lia_vendas', 'fase_lia_sem_roteiro', 'fase_handover_humano', 'fase_humano'], meses=_mg7,
                                          labels={'fase_triagem_sem_resp': 'Triagem · sem resposta', 'fase_zero_msgs': 'Triagem · vazio',
                                                  'fase_triagem_conversa': 'Triagem · conversou sem desfecho', 'fase_triagem_sac': 'Triagem · CPF já cadastrado → SAC',
                                                  'fase_lia_vendas': 'Lia vendas · link após CPF', 'fase_lia_sem_roteiro': 'Lia vendas · sem roteiro',
                                                  'fase_handover_humano': 'Handover sem atendente', 'fase_humano': 'Humano'}),
                                 "Fases por mês — estimativa", subtitle="amostra estratificada por motivo de fechamento × agent_id; contagens = proporção da amostra × tamanho do grupo",
                                 stacked=True, rotulos=True, fonte="API Talkerchat (mensagens) · pipeline tkc_fases")
            g1, g2 = st.columns([1.9, 1])
            with g1:
                _tv_funil("Qualificação → sales-ready → distribuição", [
                    ("💬", "Tickets", _f_tot, "base da estimativa (meses tocados pelo período)"),
                    ("🪪", "Informaram o CPF (qualificados)", _q_cpf, "CPF nas mensagens ou desfecho da triagem"),
                    ("✅", "Sales-ready", _q_sr, f"CPF não cadastrado → segue para venda (Lia ou humano) · erro amostral {_pp(_e_s)}"),
                    ("🤖", "↳ distribuídos para a Lia", _q_bot, "link de adesão enviado pela Lia · seq. = % dos sales-ready", 2),
                    ("🧑‍💼", "↳ distribuídos para humano", _q_hum, "'Vou conectar você com um consultor…' ou atendente · seq. = % dos sales-ready", 2),
                ], subtitle="estimativa por amostra de mensagens · as duas últimas linhas são fatias dos sales-ready (o resto ficou sem desfecho)")
            with g2:
                _tv_note(f"<b>Como ler.</b> A API não tem campo de handover; o pipeline <code>tkc_fases</code> lê as mensagens de uma amostra "
                         f"(40 tickets por motivo de fechamento × mês) e classifica pelo roteiro: apresentação da Lia → pedido de CPF → desfecho "
                         f"('já está cadastrado' = SAC · 'ainda não é filiado' + link = Lia vendas · 'Vou conectar você com um consultor' = humano). "
                         f"Erro amostral (95%) da fatia Lia vendas: {_pp(_e_v)} no mês. Atualizar: <code>gt7 run tkc_fases --arg meses=AAAA-MM --arg refresh=1</code>.",
                         bg="#f8fafc", icon="ℹ️")

        if _tk_api:
            # ---- tempos: série mensal (mediana) + tabela ----
            st.markdown("---")
            t1, t2 = st.columns([1.9, 1])
            with t1:
                _tv_linhas_mensal(_tv_long('s7_tempos', ['espera_med_min', 'duracao_humano_med_min', 'duracao_bot_med_min'], meses=_mg7,
                                           labels={'espera_med_min': 'Espera até humano', 'duracao_humano_med_min': 'Duração humano',
                                                   'duracao_bot_med_min': 'Duração só Lia'}),
                                  "Tempos por mês — mediana em minutos", y_label="min", rotulos=True,
                                  subtitle="espera: created_at → opened_at · duração humano: opened_at → closed_at · Lia: created_at → closed_at")
            with t2:
                _rows_t = []
                for _nm, _lbl in [('espera', 'Espera até humano assumir'), ('duracao_humano', 'Duração atendimento humano'),
                                  ('duracao_bot', 'Duração conversa só Lia')]:
                    _rows_t.append({'Tempo': _lbl, 'Mediana': _tv_min(_tv_tempo(_nm, 'med')), 'p90': _tv_min(_tv_tempo(_nm, 'p90')),
                                    'Média': _tv_min(_tv_tempo(_nm, 'avg')),
                                    'Tickets': _tv_n(_tv_val('s7_tempos', f'{_nm}_n'))})
                st.markdown(f"**Tempos no período** <span style='color:#64748b;font-size:12px'>({_tv_per_lbl})</span>", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(_rows_t), use_container_width=True, hide_index=True)
                st.caption("Mediana e p90 calculados por período no MySQL (ROW_NUMBER); em vários períodos, ponderados pelo nº de "
                           "tickets. A média é sensível a tickets esquecidos abertos por dias — use a mediana para comparar meses.")

            # ---- ranking de atendentes ----
            st.markdown("---")
            _ag = _tv_pivot7('s7_atendente')
            if _ag.empty:
                st.caption("sem tickets com atendente no período.")
            else:
                for _c in ['tickets', 'leads', 'compras', 'espera_avg_min', 'duracao_avg_min']:
                    if _c not in _ag.columns:
                        _ag[_c] = 0.0
                # médias por atendente somadas em vários períodos: refaz ponderando por tickets
                _agl = _tvd[(_tvd['secao'] == 's7_atendente') & (_tvd['mes'].isin(list(_tv_per)))]
                if not _agl.empty and len(_tv_per) > 1:
                    _w = _agl.pivot_table(index=['dim', 'mes'], columns='metrica', values='valor', aggfunc='sum').fillna(0).reset_index()
                    for _c in ['espera_avg_min', 'duracao_avg_min']:
                        if _c in _w.columns:
                            _w[_c + '_w'] = _w[_c] * _w['tickets']
                            _s = _w.groupby('dim')[[_c + '_w', 'tickets']].sum()
                            _ag = _ag.drop(columns=[_c]).merge((_s[_c + '_w'] / _s['tickets'].where(_s['tickets'] > 0)).rename(_c).reset_index(), on='dim', how='left')
                _ag['taxa'] = (_ag['compras'] / _ag['tickets'].where(_ag['tickets'] > 0) * 100).astype(float)
                _ag = _ag.sort_values(['compras', 'tickets'], ascending=False).reset_index(drop=True)
                _n_ag = len(_ag)
                r1, r2 = st.columns([1.2, 1])
                with r1:
                    _tv_titulo("Ranking de atendentes — compras reportadas", f"{_n_ag} atendentes com ticket no período · {_tv_per_lbl}", "A")
                    _top = _ag.head(15).copy()
                    _top['rotulo'] = _top.apply(lambda r: f"{format_br(r['compras'])} · {r['taxa']:.1f}%".replace('.', ',') if pd.notna(r['taxa']) else format_br(r['compras']), axis=1)
                    fig_ag = px.bar(_top.iloc[::-1], x='compras', y='dim', orientation='h', text='rotulo',
                                    color_discrete_sequence=[_TV_CORES_A[0]], template='cdt_a' if _CDT_THEME else 'plotly_white')
                    fig_ag.update_traces(textposition='outside', cliponaxis=False, textfont_size=11)
                    fig_ag.update_layout(height=max(320, 26 * len(_top) + 80), xaxis_title='compras reportadas', yaxis_title='',
                                         showlegend=False, margin=dict(r=90))
                    st.plotly_chart(fig_ag, use_container_width=True)
                    _tv_fonte("API Talkerchat (alex_talkerchat_api) · rótulo = compras · taxa (compras / tickets)")
                with r2:
                    st.markdown("**Tabela completa**")
                    _tab = _ag[['dim', 'tickets', 'leads', 'compras', 'taxa', 'espera_avg_min', 'duracao_avg_min']].copy()
                    _tab['taxa'] = _tab['taxa'].round(1)
                    _tab['espera_avg_min'] = _tab['espera_avg_min'].map(_tv_min)
                    _tab['duracao_avg_min'] = _tab['duracao_avg_min'].map(_tv_min)
                    _tab = _tab.rename(columns={'dim': 'Atendente', 'tickets': 'Tickets', 'leads': 'Usuários', 'compras': 'Compras',
                                                'taxa': 'Taxa %', 'espera_avg_min': 'Espera média', 'duracao_avg_min': 'Duração média'})
                    st.dataframe(_tab, use_container_width=True, hide_index=True, height=max(320, 26 * len(_top) + 80))
                    st.caption("Só tickets com atendente (agent_id). Espera = criado → assumido; duração = assumido → fechado; "
                               "médias por atendente (ponderadas por tickets quando o período tem mais de um mês/semana).")

            # ---- heatmap dia × hora ----
            st.markdown("---")
            _hr = _tv_pivot7('s7_hora')
            h1, h2 = st.columns([3, 1])
            with h2:
                _hm_m = st.radio("Métrica do mapa", ["Tickets criados", "Compras reportadas", "% com humano"],
                                 key='t6_s7_hm', horizontal=False)
            with h1:
                _tv_titulo("Mapa de calor — dia da semana × hora de criação do ticket",
                           f"{_tv_per_lbl} · horário de Brasília (America/Sao_Paulo)", "A")
                if _hr.empty:
                    st.caption("sem dados de hora no período.")
                else:
                    _hr['d'] = _hr['dim'].str.slice(0, 1).astype(int)
                    _hr['h'] = _hr['dim'].str.slice(2, 4).astype(int)
                    for _c in ['tickets', 'compras', 'humano']:
                        if _c not in _hr.columns:
                            _hr[_c] = 0.0
                    if _hm_m == "Tickets criados":
                        _hr['z'] = _hr['tickets']; _fmt = ".0f"; _cs = ['#f0fdf4', '#166534']
                    elif _hm_m == "Compras reportadas":
                        _hr['z'] = _hr['compras']; _fmt = ".0f"; _cs = ['#fffbeb', '#b45309']
                    else:
                        _hr['z'] = (_hr['humano'] / _hr['tickets'].where(_hr['tickets'] > 0) * 100).astype(float); _fmt = ".0f"; _cs = ['#f8fafc', '#0f172a']
                    _z = _hr.pivot_table(index='d', columns='h', values='z', aggfunc='sum').reindex(index=range(7), columns=range(24))
                    _dias = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
                    fig_hm = px.imshow(_z.values, x=[f"{h:02d}h" for h in range(24)], y=_dias, aspect='auto',
                                       color_continuous_scale=_cs, text_auto=_fmt,
                                       template='cdt_a' if _CDT_THEME else 'plotly_white')
                    fig_hm.update_layout(height=330, xaxis_title='', yaxis_title='', coloraxis_showscale=False,
                                         margin=dict(l=10, r=10, t=10, b=10))
                    fig_hm.update_traces(textfont_size=9)
                    fig_hm.update_xaxes(side='top', tickfont_size=10)
                    st.plotly_chart(fig_hm, use_container_width=True)
                    _tv_fonte("API Talkerchat (alex_talkerchat_api) · created_at em BRT · soma dos períodos selecionados")

            # ---- motivos de fechamento + estoque ----
            st.markdown("---")
            m1, m2 = st.columns([1.6, 1])
            with m1:
                _mot = _tv_pivot7('s7_motivo')
                _tv_titulo("Motivos de fechamento (close_reason_id · título)", f"tickets fechados criados em {_tv_per_lbl} · top 12", "A")
                if _mot.empty:
                    st.caption("sem motivos no período.")
                else:
                    for _c in ['tickets', 'bot', 'humano']:
                        if _c not in _mot.columns:
                            _mot[_c] = 0.0
                    _mot = _mot.sort_values('tickets', ascending=False).head(12)
                    _ml = _mot.melt(id_vars=['dim', 'tickets'], value_vars=['bot', 'humano'], var_name='serie', value_name='valor')
                    _ml['serie'] = _ml['serie'].map({'bot': 'Só Lia (bot)', 'humano': 'Com atendente'})
                    _ml['rotulo'] = _ml['valor'].map(_tv_fmt_k)
                    fig_mt = px.bar(_ml, x='valor', y='dim', color='serie', orientation='h', text='rotulo', barmode='stack',
                                    category_orders={'dim': list(_mot['dim'][::-1])},
                                    color_discrete_sequence=[_TV_CORES_A[1], _TV_CORES_A[0]],
                                    template='cdt_a' if _CDT_THEME else 'plotly_white')
                    fig_mt.update_traces(textposition='inside', insidetextanchor='middle', textfont_size=10, textfont_color='#ffffff')
                    fig_mt.update_layout(height=max(320, 28 * len(_mot) + 80), xaxis_title='tickets', yaxis_title='', legend_title_text='',
                                         uniformtext_minsize=8, uniformtext_mode='hide')
                    st.plotly_chart(fig_mt, use_container_width=True)
                    _tv_fonte("API Talkerchat (alex_talkerchat_api) · status = 'closed' · id do motivo estável, título editável no Talkerchat")
            with m2:
                _tv_titulo("Estoque de tickets abertos — retrato de hoje",
                           f"status ≠ closed em toda a base" + (f" · {pd.Timestamp(_est_dt):%d/%m/%Y %H:%M}" if _est_dt is not None else ""), "A")
                if _est.empty:
                    st.caption("sem retrato do estoque (seção s7_estoque ausente).")
                else:
                    _et = _est.rename(columns={'dim': 'Status', 'abertos': 'Abertos', 'com_atendente': 'Com atendente',
                                               'de_dias_anteriores': 'De dias anteriores'})
                    _et = _et[[c for c in ['Status', 'Abertos', 'Com atendente', 'De dias anteriores'] if c in _et.columns]]
                    _et = _et.sort_values('Abertos', ascending=False)
                    _tot = {'Status': 'Total'}
                    for _c in _et.columns[1:]:
                        _tot[_c] = _et[_c].sum()
                    _et = pd.concat([_et, pd.DataFrame([_tot])], ignore_index=True)
                    st.dataframe(_et, use_container_width=True, hide_index=True)
                    _tv_note(
                        f"<b>{_tv_n(_est_tot)} tickets abertos agora</b>, {_tv_n(_est_ant)} deles criados antes de hoje "
                        f"({_tv_pct(_est_ant, _est_tot)}) — é a fila que envelhece; {_tv_n(_est_att)} já têm atendente "
                        f"(o resto está na Lia ou sem dono). Tickets do período ainda abertos: {_tv_n(tab_per)}. "
                        "O retrato é refeito a cada carga do agregado (recarga 11:00); o histórico por dia fica no MySQL "
                        "(status/closed_at por ticket).",
                        bg="#f8fafc", icon="📥")

    # =================================================================
    # 8 · POR TELEFONE DA EMPRESA (funil pelo lado-empresa: ramal · porta · WhatsApp)
    # -----------------------------------------------------------------
    # Réplica do estudo de 07/08: cada telefone-lead é atribuído ao ramal (ativo, REL003 ligacao.origem) ou à
    # porta (receptivo, REL002 ligacao.destino) da 1ª ligação do mês; conversa ≥10 s conta em qualquer ligação;
    # venda/conf vêm do ESCALLO_LEADS_MES por tel-8. WhatsApp: hubspot_leads_raw.whatsapp_de_origem.
    # Seções s8_ramal / s8_porta / s8_wpp (grão mensal; pipeline `gt7 run televendas_dash --arg only=s8`).
    # =================================================================
    with _tv_tabs[4]:
        _s8 = _tvd_m[_tvd_m['secao'].isin(['s8_ramal', 's8_porta', 's8_wpp', 's9_vendedor'])]   # R37: + s9_vendedor
        _s9_dim = _load_tv_ramal_dim()   # R37: tipo/agente/IDPV por (mês, ramal); vazio → heurística antiga
        if _s8.empty:
            st.warning("⚠️ As seções `s8_*` ainda não existem em `alex_tv_dash_mes`. Rode "
                       "`gt7 run televendas_dash --arg only=s8 --arg nv=skip` e recarregue os dados.")
        else:
            _s8_meses = [pd.Timestamp(m) for m in sorted(_s8['mes'].dropna().unique(), reverse=True)]
            _s8_alvo = pd.Timestamp(_tv_meses[-1]) if len(_tv_meses) else _s8_meses[0]
            _s8_idx = next((i for i, m in enumerate(_s8_meses) if m == _s8_alvo), 0)
            _s8_mes = st.selectbox("Mês:", _s8_meses, index=_s8_idx,
                                   format_func=lambda m: f"{pd.Timestamp(m):%m/%Y}", key='t6_s8_mes')
            st.caption("Cada telefone-lead é atribuído ao **ramal/porta da 1ª ligação que recebeu no mês**; a conversa "
                       "(≥10 s) conta em qualquer ligação do lead. Venda registrada = tabulação 'venda' no Escallo; conf = "
                       "confirmação por tel-8 no NOMINAL (teto de influência). Este funil é sempre mensal, mesmo com o "
                       "período em semana.")
            # R37: o que cada ramal é neste mês (para rótulo, hachura e a tabela explicativa)
            _rd = _s9_dim[_s9_dim['mes'] == pd.Timestamp(_s8_mes)] if not _s9_dim.empty else pd.DataFrame(columns=_TV_RAMAL_COLS)
            _s9_info = {}
            for _, _r in _rd.iterrows():
                _tp = str(_r['tipo'])
                if _tp == 'humano':
                    _sub = _tv_nome_curto(_r['nome_agente']) + (f" · {_r['cod_agente']}" if pd.notna(_r['cod_agente']) and _r['cod_agente'] else "")
                else:
                    _sub = _TV_TIPO_RAMAL.get(_tp, _tp)
                _s9_info[str(_r['ramal'])] = {'tipo': _tp, 'sub': _sub}
            _s9_hum = {k for k, v in _s9_info.items() if v['tipo'] == 'humano'}

            def _s8_piv(secao, mes):
                d = _s8[(_s8['secao'] == secao) & (_s8['mes'] == mes)]
                if d.empty:
                    return pd.DataFrame()
                return d.pivot_table(index='dim', columns='metrica', values='valor', aggfunc='sum').fillna(0)

            def _s8_lista(df, rotulo, col_map, titulo, subtitulo, fonte, flag_sistema=False, dim_info=None):
                """Lista estilo relatório: label | barra(vol) | nº | barra(%alô) | vendas (conf). col_map define as colunas."""
                _tv_titulo(titulo, subtitulo, "A")
                if df.empty:
                    st.caption("sem linhas para o mês.")
                    return
                df = df.sort_values(col_map['vol'], ascending=False)
                vmax = float(df[col_map['vol']].max()) or 1.0
                pcts = (df[col_map['alo']] / df[col_map['vol']].replace(0, pd.NA) * 100).fillna(0)
                pmax = float(pcts.max()) or 1.0
                _wl = 178 if dim_info else 92   # R37: coluna do rótulo mais larga quando há nome de agente
                linhas = [(
                    "<div style='display:flex;gap:10px;align-items:center;padding:3px 0;font-size:11px;color:#64748b;"
                    "font-weight:700;text-transform:uppercase;letter-spacing:.03em;'>"
                    f"<div style='flex:0 0 {_wl}px;'>{rotulo}</div><div style='flex:2.4;'>{col_map['vol_lbl']}</div>"
                    f"<div style='flex:0 0 90px;text-align:right;'>Ligações (tentativas)</div>"
                    f"<div style='flex:1.6;'>{col_map['alo_lbl']} <span style='font-weight:400;text-transform:none;letter-spacing:0;'>· % sobre {col_map['vol_lbl'].lower()}</span></div>"
                    f"<div style='flex:0 0 150px;text-align:right;'>{col_map['venda_lbl']}</div></div>")]
                for dim, r in df.iterrows():
                    vol = float(r[col_map['vol']]); alo = float(r[col_map['alo']])
                    pct = alo / vol * 100 if vol else 0
                    venda = float(r[col_map['venda']]); conf = float(r[col_map['conf']]) if col_map.get('conf') else None
                    _info = dim_info.get(str(dim)) if dim_info else None
                    # R37: com a dimensão do mês a hachura é o tipo real do ramal; sem ela, a heurística antiga
                    sistema = (_info['tipo'] != 'humano') if _info else (flag_sistema and venda == 0 and (conf or 0) <= 5 and vol >= 800)
                    _bg = ("repeating-linear-gradient(45deg,#c7cdf5 0 6px,#e4e7fb 6px 12px)" if sistema else "#7c86e8")
                    _fg = '#94a3b8' if sistema else '#0f172a'
                    lig = format_br(r['ligacoes']) if 'ligacoes' in r else ''
                    _vtx = (f"{format_br(venda)} <span style='color:#94a3b8'>· conf. CTN: {format_br(conf)}</span>" if conf is not None
                            else f"{format_br(venda)} · {_tv_pct(venda, vol)}")
                    linhas.append(
                        "<div style='display:flex;gap:10px;align-items:center;padding:3px 0;border-top:1px solid #f1f5f9;'>"
                        f"<div style='flex:0 0 {_wl}px;min-width:0;font-size:12.5px;font-weight:700;color:{_fg};'>{dim}"
                        + ((f"<div style='font-size:9.5px;font-weight:600;color:{'#94a3b8' if sistema else '#64748b'};white-space:nowrap;"
                            f"overflow:hidden;text-overflow:ellipsis;'>{_info['sub']}</div>") if _info else
                           ("<div style='font-size:9.5px;color:#94a3b8;'>linha de sistema?</div>" if sistema else "")) + "</div>"
                        f"<div style='flex:2.4;display:flex;align-items:center;gap:8px;'>"
                        f"<div style='height:14px;border-radius:4px;background:{_bg};width:{max(2, vol / vmax * 100):.1f}%;'></div>"
                        f"<span style='font-size:11.5px;color:#334155;'>{format_br(vol)}</span></div>"
                        f"<div style='flex:0 0 90px;text-align:right;font-size:11.5px;color:#64748b;'>{lig}</div>"
                        f"<div style='flex:1.6;display:flex;align-items:center;gap:8px;'>"
                        f"<div style='height:12px;border-radius:4px;background:#199e70;width:{max(2, pct / pmax * 88):.1f}%;'></div>"
                        f"<span style='font-size:11.5px;color:#334155;white-space:nowrap;'>{format_br(alo)} · {f'{pct:.1f}'.replace('.', ',')}%</span></div>"
                        f"<div style='flex:0 0 150px;text-align:right;font-size:12px;color:#0f172a;'>{_vtx}</div></div>")
                st.markdown("<div style='border:1px solid #e2e8f0;border-radius:12px;padding:12px 16px;background:#fff;'>"
                            + "".join(linhas) + "</div>", unsafe_allow_html=True)
                st.caption("**Como ler as colunas:** a % da conversa é sobre a **1ª coluna** (telefones/leads), não sobre "
                           "as ligações — ligações são tentativas, e um mesmo lead recebe várias no mês. **conf. CTN** = "
                           "telefones do grupo que apareceram com filiação no CTN dentro da janela (teto de influência "
                           "por tel-8): pode haver conf. com 0 vendas tabuladas quando o cliente filia por outro canal "
                           "(site, app, porta a porta) ou quando o operador não tabula a venda.")
                _tv_fonte(fonte)

            _pr = _s8_piv('s8_ramal', _s8_mes)
            _s8_lista(_pr, "Ramal", {'vol': 'leads', 'vol_lbl': 'Leads trabalhados', 'alo': 'alo10',
                                     'alo_lbl': 'Conversa ≥10 s', 'venda': 'venda', 'conf': 'conf',
                                     'venda_lbl': 'Venda registrada'},
                      "Escallo ativo — o funil de cada ramal",
                      ("cada telefone discado pertence ao ramal da 1ª ligação do mês; sob o ramal, o agente logado (nome · código) — "
                       "hachura = ramal sem agente (linha de sistema/URA), treinamento ou número externo" if _s9_info else
                       "cada telefone discado pertence ao ramal da 1ª ligação do mês; hachura = suspeita de linha de "
                       "sistema (muitos leads, zero venda) — rode o pipeline s9 para a classificação real"),
                      f"Televendas_REL003 (ligacao.origem + agente logado) × ESCALLO_LEADS_MES (ATIVO) · {pd.Timestamp(_s8_mes):%m/%Y}",
                      flag_sistema=True, dim_info=_s9_info)
            if not _pr.empty:
                _alos = (_pr['alo10'] / _pr['leads'].replace(0, pd.NA) * 100).dropna()
                _re = (_pr[pd.Series([str(i) in _s9_hum for i in _pr.index], index=_pr.index) & (_pr['leads'] >= 50)] if _s9_hum else _pr[(_pr['venda'] > 0) | (_pr['conf'] > 5)])  # R37c: humanos pela dimensão (Series), ≥ 50 leads
                if len(_re) >= 3:
                    _ral = (_re['alo10'] / _re['leads'].replace(0, pd.NA) * 100).dropna()
                    _f = lambda v: f"{v:.1f}".replace('.', ',')
                    st.caption(f"Taxa de conversa entre ramais reais: {_f(_ral.min())}% a {_f(_ral.max())}% "
                               f"(média {_f(_ral.mean())}%) — mesma lista, mesmo mês: a diferença é ritmo, horário e "
                               "insistência de cada posição.")

            # ---- R37: o que é cada ramal (agente, tipo, IDPVs, número que o cliente vê) ----
            if _rd.empty:
                st.caption("ℹ️ A dimensão de ramais (`alex_tv_ramal_dim`) ainda não tem este mês — rode "
                           "`gt7 run televendas_dash --arg only=s9 --arg nv=skip` e recarregue os dados.")
            else:
                _n_hum = int((_rd['tipo'] == 'humano').sum()); _n_sis = int((_rd['tipo'] == 'sistema').sum())
                _num_ext = _rd['numero_externo'].mode().iloc[0] if _rd['numero_externo'].notna().any() else "TIM 11 2250-8917"
                with st.expander(f"📖 O que é cada ramal — {_n_hum} operadores humanos, {_n_sis} linha(s) de sistema · o número que o cliente vê", expanded=False):
                    st.markdown(
                        f"**O ramal não é um número completo.** É a extensão interna de 4 dígitos da posição (9002…9077); toda ligação "
                        f"ativa sai pelo mesmo tronco externo — o cliente vê sempre **{_num_ext}**, qualquer que seja o ramal. "
                        "O que identifica a pessoa é o **agente logado** na ligação (REL003: `nomeAgenteOrigem` / `codigoAgenteOrigem`). "
                        "**Tipos:** *Operador humano* = agente logado na maioria das ligações do mês; *Linha de sistema* = ramal sem agente "
                        "com grande volume (discador/URA de validação, ex. 9902); *Treinamento / qualidade* = agente de treinamento; "
                        "*Sem agente logado* = ramal sem login e pouco volume; *Número externo* = telefone completo gravado no campo do ramal. "
                        "**IDPVs no CTN** = quantos IDPVs de `alex_idpvs` (fonte Televendas) casam com o nome do agente — é por eles que a venda "
                        "do vendedor aparece no NOMINAL (a variante '… ATENDIMENTO' é a mesma pessoa).")
                    _tab = _rd.copy()
                    _tab['_o'] = _tab['tipo'].map(_TV_TIPO_ORDEM).fillna(9)
                    _tab = _tab.sort_values(['_o', 'ligacoes'], ascending=[True, False])
                    _tab_show = pd.DataFrame({
                        'Ramal': _tab['ramal'].values,
                        'Tipo': _tab['tipo'].map(_TV_TIPO_RAMAL).fillna(_tab['tipo']).values,
                        'Agente logado': [(_tv_nome_curto(n) if t == 'humano' or pd.notna(n) else "—") for n, t in zip(_tab['nome_agente'], _tab['tipo'])],
                        'Código': [(str(c) if pd.notna(c) and c else "—") for c in _tab['cod_agente']],
                        'Ligações no mês': _tab['ligacoes'].astype(int).values,
                        '% com agente logado': (_tab['lig_com_agente'].astype(float) / _tab['ligacoes'].astype(float).where(_tab['ligacoes'] > 0) * 100).fillna(0).round(0).astype(int).values,   # R37b
                        'Alô ≥10 s (ligações)': _tab['alo10'].astype(int).values,
                        'Agentes distintos': _tab['n_agentes'].astype(int).values,
                        'IDPVs no CTN': _tab['n_idpv'].astype(int).values,
                        'Número que o cliente vê': _tab['numero_externo'].fillna(_num_ext).values,
                    })
                    st.dataframe(_tab_show, hide_index=True, use_container_width=True, height=min(560, 38 + 35 * len(_tab_show)),
                                 column_config={'% com agente logado': st.column_config.NumberColumn(format="%d%%"),
                                                'Ligações no mês': st.column_config.NumberColumn(format="%d"),
                                                'Alô ≥10 s (ligações)': st.column_config.NumberColumn(format="%d")})
                    _tv_fonte(f"alex_tv_ramal_dim (pipeline televendas_dash s9) · REL003 agente logado · REL100 canalEmpresa (saída) · "
                              f"alex_idpvs fonte Televendas · {pd.Timestamp(_s8_mes):%m/%Y}")

            # ---- R37: por vendedor — quem discou (ramal) × quem fechou no CTN (IDPV) ----
            _pv = _s8_piv('s9_vendedor', _s8_mes)
            if not _pv.empty:
                for _c in ('leads', 'ligacoes', 'alo10', 'venda', 'conf', 'ramais', 'vendas_idpv', 'vendas_idpv_tel', 'vendas_idpv_wpp',
                           'vendas_idpv_discado', 'vendas_idpv_proprio', 'vendas_idpv_outro', 'vendas_idpv_sistema', 'vendas_idpv_sem_discagem', 'n_idpv'):
                    if _c not in _pv.columns:
                        _pv[_c] = 0.0
                _hum_v = _pv[~_pv.index.astype(str).str.startswith('(')].copy()
                _esp_v = _pv[_pv.index.astype(str).str.startswith('(') & (_pv.index.astype(str) != '(total)')].copy()
                _tot_v = _pv.loc['(total)'] if '(total)' in _pv.index else None
                st.markdown("---")
                _tv_titulo("Por vendedor — quem discou (ramal) × quem fechou no CTN (IDPV)",
                           "duas atribuições da mesma venda: o operador que discou o telefone (Escallo) e o vendedor cujo IDPV consta na "
                           "filiação com tipo Televendas no NOMINAL (alex_idpvs) — nem sempre é a mesma pessoa", "A")
                if _tot_v is not None and float(_tot_v['vendas_idpv'] or 0) > 0:
                    _bots_v = float(_esp_v.loc[[i for i in _esp_v.index if 'bots' in str(i)], 'vendas_idpv'].sum()) if not _esp_v.empty else 0.0
                    _semag_v = float(_esp_v.loc[[i for i in _esp_v.index if 'sem agente' in str(i)], 'vendas_idpv'].sum()) if not _esp_v.empty else 0.0
                    _hv, _hp, _ho, _hs, _hn = (float(_hum_v[c].sum()) for c in ('vendas_idpv', 'vendas_idpv_proprio', 'vendas_idpv_outro', 'vendas_idpv_sistema', 'vendas_idpv_sem_discagem')) if not _hum_v.empty else (0.0,) * 5
                    _hw = float(_hum_v['vendas_idpv_wpp'].sum()) if not _hum_v.empty else 0.0
                    _tv_note(
                        f"<b>{_tv_n(_tot_v['vendas_idpv'])} vendas com tipo Televendas no CTN</b> em {pd.Timestamp(_s8_mes):%m/%Y}, por IDPV: "
                        f"<b>{_tv_n(_bots_v)} ({_tv_pct(_bots_v, _tot_v['vendas_idpv'])}) dos bots Talkerchat</b> (Lia/Cris/Nora — o IDPV deles também tem fonte Televendas), "
                        f"<b>{_tv_n(_hv)} ({_tv_pct(_hv, _tot_v['vendas_idpv'])}) dos operadores que discaram no mês</b>"
                        + (f" e {_tv_n(_semag_v)} de IDPVs Televendas de pessoas que não aparecem no Escallo ativo do mês" if _semag_v else "") + ". "
                        + ((f"Das vendas dos operadores, <b>{_tv_n(_hp)} ({_tv_pct(_hp, _hv)})</b> são de telefones que <i>o próprio vendedor</i> discou no mês; "
                            f"{_tv_n(_ho)} ({_tv_pct(_ho, _hv)}) de telefones discados só por colegas (ou linhas sem login); {_tv_n(_hs)} ({_tv_pct(_hs, _hv)}) de telefones que "
                            f"só a linha de sistema tocou; e <b>{_tv_n(_hn)} ({_tv_pct(_hn, _hv)})</b> sem discagem ativa no mês — receptivo, WhatsApp (cada operador tem um IDPV "
                            f"'… ATENDIMENTO WHATSAPP': {_tv_n(_hw)} vendas, {_tv_pct(_hw, _hv)}), indicação ou telefone divergente entre Escallo e CTN.")
                           if _hv > 0 else ""),
                        bg="#f8fafc", icon="🧾")
                if not _hum_v.empty:
                    _hum_v = _hum_v.sort_values('vendas_idpv', ascending=False)
                    _pct_col = lambda a, b: (a.astype(float) / b.astype(float).where(b.astype(float) > 0) * 100).fillna(0).round(1)   # R37b: sem pd.NA
                    _vend_show = pd.DataFrame({
                        'Vendedor': [_tv_nome_curto(str(i)) for i in _hum_v.index],
                        'Ramais': _hum_v['ramais'].astype(int).values,
                        'Leads discados': _hum_v['leads'].astype(int).values,
                        'Alô ≥10 s': _hum_v['alo10'].astype(int).values,
                        '% alô': _pct_col(_hum_v['alo10'], _hum_v['leads']).values,
                        'Venda tabulada': _hum_v['venda'].astype(int).values,
                        'Conf. CTN (janela)': _hum_v['conf'].astype(int).values,
                        'Vendas TV no CTN (IDPV)': _hum_v['vendas_idpv'].astype(int).values,
                        '└ IDPV telefone': _hum_v['vendas_idpv_tel'].astype(int).values,
                        '└ IDPV WhatsApp': _hum_v['vendas_idpv_wpp'].astype(int).values,
                        '└ leads que ele discou': _hum_v['vendas_idpv_proprio'].astype(int).values,
                        '└ discados por outro operador': _hum_v['vendas_idpv_outro'].astype(int).values,
                        '└ só linha de sistema': _hum_v['vendas_idpv_sistema'].astype(int).values,
                        '└ sem discagem ativa': _hum_v['vendas_idpv_sem_discagem'].astype(int).values,
                        '% carteira própria': _pct_col(_hum_v['vendas_idpv_proprio'], _hum_v['vendas_idpv']).values,
                        'IDPVs': _hum_v['n_idpv'].astype(int).values,
                    })
                    st.dataframe(_vend_show, hide_index=True, use_container_width=True, height=min(640, 38 + 35 * len(_vend_show)),
                                 column_config={'% alô': st.column_config.NumberColumn(format="%.1f%%"),
                                                '% carteira própria': st.column_config.NumberColumn(format="%.1f%%"),
                                                'Vendedor': st.column_config.TextColumn(width="medium")})
                    st.caption("**Como ler:** as colunas da esquerda (até *Conf. CTN*) são o **lado ramal** — leads cujo 1º contato do mês foi este operador, "
                               "alô em qualquer ligação, tabulação 'venda' e confirmação por tel-8 na janela do contato + 14 d. As colunas a partir de "
                               "**Vendas TV no CTN (IDPV)** são o **lado CTN** — filiações do mês-calendário com `tipo_venda = TELEVENDAS` cujo IDPV é "
                               "do vendedor (dedup CPF × data), somando o IDPV de telefone ('NOME') e o de WhatsApp ('NOME - ATENDIMENTO WHATSAPP'). "
                               "*Leads que ele discou* = o telefone da venda recebeu ligação deste operador no mês; "
                               "*discados por outro operador* = só colegas (ou linhas sem login) ligaram; *só linha de sistema* = só o discador/URA tocou; "
                               "*sem discagem ativa* = o telefone não aparece no REL003 do mês. Um operador que usou dois ramais aparece uma vez.")
                if not _esp_v.empty:
                    _esp_show = pd.DataFrame({
                        'Linha': [str(i).strip('()').capitalize() for i in _esp_v.index],
                        'Leads discados (1º contato)': _esp_v['leads'].astype(int).values,
                        'Alô ≥10 s': _esp_v['alo10'].astype(int).values,
                        'Venda tabulada': _esp_v['venda'].astype(int).values,
                        'Conf. CTN (janela)': _esp_v['conf'].astype(int).values,
                        'Vendas TV no CTN (IDPV)': _esp_v['vendas_idpv'].astype(int).values,
                        '└ IDPV telefone': _esp_v['vendas_idpv_tel'].astype(int).values,
                        '└ IDPV WhatsApp': _esp_v['vendas_idpv_wpp'].astype(int).values,
                        '└ discados no mês': _esp_v['vendas_idpv_discado'].astype(int).values,
                        '└ sem discagem ativa': _esp_v['vendas_idpv_sem_discagem'].astype(int).values,
                    })
                    st.caption("Linhas sem operador do Escallo ativo: a linha de sistema não fecha venda (o IDPV é sempre de uma pessoa ou bot); "
                               "'bots Talkerchat' = IDPVs Lia/Cris/Nora, que o CTN registra com tipo Televendas; 'IDPV Televendas sem agente no "
                               "Escallo' = vendedores do CTN que não discaram no mês:")
                    st.dataframe(_esp_show, hide_index=True, use_container_width=True, height=38 + 35 * len(_esp_show))
                _tv_fonte(f"alex_tv_dash_mes s9_vendedor (pipeline televendas_dash) · REL003 agente logado × ESCALLO_LEADS_MES × alex_nv_tel8 "
                          f"(NOMINAL tipo Televendas, mês-calendário) × alex_idpvs · {pd.Timestamp(_s8_mes):%m/%Y}")
            elif not _rd.empty:
                st.caption("ℹ️ Sem a seção `s9_vendedor` para este mês — rode `gt7 run televendas_dash --arg only=s9 --arg nv=skip`.")

            st.markdown("---")
            _pp = _s8_piv('s8_porta', _s8_mes)
            _s8_lista(_pp, "Porta", {'vol': 'leads', 'vol_lbl': 'Leads atendidos', 'alo': 'alo10',
                                     'alo_lbl': 'Conversa ≥10 s', 'venda': 'venda', 'conf': 'conf',
                                     'venda_lbl': 'Venda registrada'},
                      "Escallo receptivo — o funil de cada porta de entrada",
                      "no receptivo o telefone-empresa é a fila/URA que atendeu (ligacao.destino); a venda se concentra "
                      "nas primeiras portas — portas que falam pouco e vendem quase nada tendem a ser tráfego de outra "
                      "natureza (cobrança, retorno de URA)",
                      f"Televendas_REL002 (ligacao.destino) × ESCALLO_LEADS_MES (RECEPTIVO) · {pd.Timestamp(_s8_mes):%m/%Y}")

            st.markdown("---")
            _pw = _s8_piv('s8_wpp', _s8_mes)
            if not _pw.empty:
                _tv_titulo("HubSpot — o funil por número de WhatsApp de origem",
                           "Leads nascidos em WhatsApp: criados → com CPF → trabalhados no objeto Leads → filiaram; "
                           "os demais leads do mês nasceram fora de WhatsApp (site, mídia) e não têm telefone-empresa", "A")
                _pw = _pw.sort_values('criados', ascending=False)
                _vmax = float(_pw['criados'].max()) or 1.0
                linhas = [("<div style='display:flex;gap:10px;align-items:center;padding:3px 0;font-size:11px;color:#64748b;"
                           "font-weight:700;text-transform:uppercase;letter-spacing:.03em;'>"
                           "<div style='flex:0 0 130px;'>Número</div><div style='flex:2.2;'>Leads criados</div>"
                           "<div style='flex:0 0 120px;text-align:right;'>Com CPF</div>"
                           "<div style='flex:0 0 100px;text-align:right;'>Trabalhados</div>"
                           "<div style='flex:0 0 120px;text-align:right;'>Filiaram</div></div>")]
                for dim, r in _pw.iterrows():
                    cri = float(r['criados']); vazio = cri >= 300 and float(r['com_cpf']) == 0 and float(r['filiaram']) == 0
                    _bg = ("repeating-linear-gradient(45deg,#c7cdf5 0 6px,#e4e7fb 6px 12px)" if vazio else "#199e70")
                    linhas.append(
                        "<div style='display:flex;gap:10px;align-items:center;padding:3px 0;border-top:1px solid #f1f5f9;'>"
                        f"<div style='flex:0 0 130px;font-size:12.5px;font-weight:700;color:{'#94a3b8' if vazio else '#0f172a'};'>{dim}"
                        + ("<div style='font-size:9.5px;color:#94a3b8;'>lead vazio?</div>" if vazio else "") + "</div>"
                        f"<div style='flex:2.2;display:flex;align-items:center;gap:8px;'>"
                        f"<div style='height:14px;border-radius:4px;background:{_bg};width:{max(2, cri / _vmax * 100):.1f}%;'></div>"
                        f"<span style='font-size:11.5px;color:#334155;'>{format_br(cri)}</span></div>"
                        f"<div style='flex:0 0 120px;text-align:right;font-size:11.5px;'>{format_br(r['com_cpf'])} · {_tv_pct(r['com_cpf'], cri)}</div>"
                        f"<div style='flex:0 0 100px;text-align:right;font-size:11.5px;'>{format_br(r['trabalhados'])}</div>"
                        f"<div style='flex:0 0 120px;text-align:right;font-size:11.5px;'>{format_br(r['filiaram'])} · {_tv_pct(r['filiaram'], cri)}</div></div>")
                st.markdown("<div style='border:1px solid #e2e8f0;border-radius:12px;padding:12px 16px;background:#fff;'>"
                            + "".join(linhas) + "</div>", unsafe_allow_html=True)
                _tv_fonte(f"hubspot_leads_raw (whatsapp_de_origem, hs_createdate) · {pd.Timestamp(_s8_mes):%m/%Y} · "
                          "trabalhado = entrou em Attempting/Connected/Qualified/Unqualified; filiou = data_de_filiacao "
                          "preenchida (qualquer data). Hachura = número criando leads sem CPF, trabalho ou filiação "
                          "(auditar a integração)")
            else:
                st.caption("sem funil de WhatsApp para o mês (s8_wpp vazio).")


# =====================================================================
# TAB 7: APP — funil (download → cadastro → compra), uso de produtos, freemium
# ---------------------------------------------------------------------
# Lê SOMENTE a tabela agregada mensal `alex_app_dash_mes` (mes, secao, dim,
# metrica, valor), reconstruída pelo pipeline `gt7 run app_dash`
# (claude-toolkit/pipelines/app_dash.py), que lê o Athena (fl_data_login,
# fl_plano_usuario, fl_filiado, fl_utilizacao_filiado, fl_cashback).
# Reaproveita os helpers visuais da aba 📞 Televendas (_tv_kpi, _tv_note,
# _tv_funil, _tv_chart_mensal, _tv_titulo…) — por isso vem depois dela.
#
# Definições (glossário 30/07 · estudo de subprodutos 20/08):
#   download  = 1º login no app (fl_data_login.data_app)
#   cadastro  = fl_plano_usuario.dt_criacao
#   compra    = filiação de titular no mês (fl_filiado) — "com o app" = cadastro até o dia da venda
#   1ª filiação por CPF (histórico) separa "já era cliente" de "entrou como freemium"
#   freemium atual = plano Freemium e sem filiação; freemium → cliente = 1ª filiação ≥ 1 dia após o
#   cadastro e cliente ativo hoje (flag_qca=1, vam ≤ 34 — definição C)
# =====================================================================
_AP_COLS = ['mes', 'secao', 'dim', 'metrica', 'valor', 'atualizado_em']


@st.cache_data(ttl=43200)
def _load_app_dash_raw():
    d = cquery("SELECT mes, secao, dim, metrica, valor, atualizado_em FROM alex_app_dash_mes", ttl=0)
    d['mes'] = pd.to_datetime(d['mes'])
    d['valor'] = pd.to_numeric(d['valor'], errors='coerce')
    return d


def load_app_dash():
    try:
        return _load_app_dash_raw(), None
    except Exception as e:
        return pd.DataFrame(columns=_AP_COLS), f"{type(e).__name__}: {str(e)[:400]}"


_AP_POP_LBL = {'clientes_ativos': 'Clientes ativos (hoje)', 'clientes_nao_freemium': 'Clientes ativos que não vieram do freemium',
               'freemium_atual': 'Freemiums atuais', 'freemium_conv': 'Freemium → cliente ativo'}


def _ap_derivar_pop(d):
    """População derivada 'clientes_nao_freemium' = clientes_ativos − freemium_conv (o convertido é subconjunto do ativo e
    o uso dos dois vem da mesma fonte, fl_utilizacao_filiado): s2_pop.populacao, s2_uso (por produto|sub) e s2_uso_tot."""
    if d.empty:
        return d
    extra = []
    a = d[(d['secao'] == 's2_pop') & (d['dim'] == 'clientes_ativos')]
    c = d[(d['secao'] == 's2_pop') & (d['dim'] == 'freemium_conv')]
    if not a.empty:
        m = a.merge(c[['mes', 'metrica', 'valor']], on=['mes', 'metrica'], how='left', suffixes=('', '_c'))
        m['valor'] = (m['valor'] - m['valor_c'].fillna(0)).clip(lower=0)
        m['dim'] = 'clientes_nao_freemium'
        extra.append(m[_AP_COLS])
    a = d[(d['secao'] == 's2_uso_tot') & (d['dim'] == 'clientes_ativos')]
    c = d[(d['secao'] == 's2_uso_tot') & (d['dim'] == 'freemium_conv')]
    if not a.empty:
        m = a.merge(c[['mes', 'metrica', 'valor']], on=['mes', 'metrica'], how='left', suffixes=('', '_c'))
        m['valor'] = (m['valor'] - m['valor_c'].fillna(0)).clip(lower=0)
        m['dim'] = 'clientes_nao_freemium'
        extra.append(m[_AP_COLS])
    a = d[(d['secao'] == 's2_uso') & (d['dim'].str.startswith('clientes_ativos|'))].copy()
    c = d[(d['secao'] == 's2_uso') & (d['dim'].str.startswith('freemium_conv|'))].copy()
    if not a.empty:
        a['chave'] = a['dim'].str.split('|', n=1).str[1]
        c['chave'] = c['dim'].str.split('|', n=1).str[1]
        m = a.merge(c[['mes', 'metrica', 'chave', 'valor']], on=['mes', 'metrica', 'chave'], how='left', suffixes=('', '_c'))
        m['valor'] = (m['valor'] - m['valor_c'].fillna(0)).clip(lower=0)
        m['dim'] = 'clientes_nao_freemium|' + m['chave']
        extra.append(m[_AP_COLS])
    return pd.concat([d] + extra, ignore_index=True) if extra else d
_AP_BUCKET_LBL = {'a_0_30d': '0–30 dias', 'b_31_90d': '31–90 dias', 'c_91_180d': '91–180 dias',
                  'd_181_365d': '181–365 dias', 'e_mais_365d': 'mais de 1 ano'}
_AP_MESES_PT = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

with tab7:
    st.markdown("## App — funil, uso de produtos e freemium")
    _apd, _ap_err = load_app_dash()
    _apd = _ap_derivar_pop(_apd)
    _ap_meses = list(_tv_meses)          # meses tocados pelo período dos Controles Globais (mesma régua da aba 📞)
    _ap_meses_p = list(_tv_meses_p)
    _ap_m_fim = _tv_m_fim
    _ap_atual = _apd['atualizado_em'].max() if not _apd.empty else None
    _ap_hdr1, _ap_hdr2 = st.columns([3, 1.2])
    _ap_hdr1.caption(
        f"Período: **{_ap_meses[0]:%m/%Y}**" + (f" a **{_ap_meses[-1]:%m/%Y}**" if len(_ap_meses) > 1 else "")
        + " (meses tocados pelo período dos Controles Globais; grão mensal). "
        + (f"Comparação: {_ap_meses_p[0]:%m/%Y}–{_ap_meses_p[-1]:%m/%Y}. " if len(_ap_meses_p) > 1
           else (f"Comparação: {_ap_meses_p[0]:%m/%Y}. " if _ap_meses_p else ""))
        + "Fontes (Athena): fl_data_login · fl_plano_usuario · fl_filiado · fl_utilizacao_filiado · fl_cashback, "
          "agregadas em `alex_app_dash_mes` pelo pipeline `gt7 run app_dash`.")
    _ap_hdr2.markdown(
        "<div style='border:1px solid #e2e8f0;border-radius:10px;padding:7px 12px;background:#fff;'>"
        "<div style='font-size:10.5px;color:#64748b;font-weight:600;'>Agregado atualizado em</div>"
        f"<div style='font-size:13px;color:#0f172a;font-weight:700;'>🗓️ {pd.Timestamp(_ap_atual).strftime('%d/%m/%Y %H:%M') if _ap_atual is not None else '—'}</div>"
        "</div>", unsafe_allow_html=True)
    if _ap_err:
        st.error(f"⚠️ Falha ao ler `alex_app_dash_mes` — a query levantou: `{_ap_err}`.")
    elif _apd.empty:
        st.warning("⚠️ A tabela `alex_app_dash_mes` ainda não existe ou está vazia. Rode `gt7 run app_dash` (claude-toolkit) "
                   "e recarregue os dados.")

    def _ap_val(secao, metrica, dim='app', meses=None):
        meses = _ap_meses if meses is None else meses
        d = _apd[(_apd['secao'] == secao) & (_apd['metrica'] == metrica) & (_apd['dim'] == dim) & (_apd['mes'].isin(list(meses)))]
        return None if d.empty else float(d['valor'].sum(skipna=True))

    def _ap_serie(secao, metrica, dim='app', meses=None):
        meses = _ap_meses if meses is None else meses
        d = _apd[(_apd['secao'] == secao) & (_apd['metrica'] == metrica) & (_apd['dim'] == dim) & (_apd['mes'].isin(list(meses)))]
        return d.groupby('mes', as_index=False)['valor'].sum().sort_values('mes')

    def _ap_long(secao, metricas, labels=None, dim='app', meses=None):
        parts = []
        for m in metricas:
            s = _ap_serie(secao, m, dim=dim, meses=meses)
            s['serie'] = (labels or {}).get(m, m)
            parts.append(s)
        return pd.concat(parts) if parts else pd.DataFrame(columns=['mes', 'serie', 'valor'])

    def _ap_janela(key, opcoes=("3 meses", "12 meses"), padrao=0):
        """Janela das séries: últimos N meses até o fim do período (mês atual = só o último mês)."""
        esc = st.radio("Janela:", list(opcoes), index=padrao, horizontal=True, key=key)
        n = {"Mês atual": 1, "3 meses": 3, "12 meses": 12}[esc]
        return list(pd.period_range(_ap_m_fim - pd.DateOffset(months=n - 1), _ap_m_fim, freq='M').to_timestamp()), esc

    def _ap_mes_lbl(ts):
        ts = pd.Timestamp(ts)
        return f"{_AP_MESES_PT[ts.month - 1]}/{ts.strftime('%y')}"

    _ap_tabs = st.tabs(["📲 1 · Funil do app", "🧩 2 · Uso de produtos", "🌱 3 · Freemium", "💰 4 · LTV e entrada no app", "🎯 5 · Leads do app", "🔗 6 · Uso × conversão × LTV"])

    # =================================================================
    # 1 · FUNIL DO APP
    # =================================================================
    with _ap_tabs[0]:
        S = 's1_funil'
        dl = _ap_val(S, 'downloads'); dl_scpf = _ap_val(S, 'downloads_sem_cpf')
        cad = _ap_val(S, 'cadastros'); cad_fil = _ap_val(S, 'cadastros_ja_filiado'); cad_dia = _ap_val(S, 'cadastros_venda_no_dia')
        cad_free = _ap_val(S, 'cadastros_freemium'); cv30 = _ap_val(S, 'freemium_conv_30d'); cv90 = _ap_val(S, 'freemium_conv_90d')
        cvt = _ap_val(S, 'freemium_conv_total'); cad_cartao = _ap_val(S, 'cadastros_ativou_cartao')
        comp = _ap_val(S, 'compras'); comp_app = _ap_val(S, 'compras_com_app_ate_venda'); comp_idpv = _ap_val(S, 'compras_app_do_filiado')
        comp_antes = _ap_val(S, 'compras_app_antes'); comp_junto = _ap_val(S, 'compras_app_junto'); comp_dep = _ap_val(S, 'compras_app_depois')
        comp_cad = _ap_val(S, 'compras_com_cadastro_app')
        dl_p = _ap_val(S, 'downloads', meses=_ap_meses_p); cad_p = _ap_val(S, 'cadastros', meses=_ap_meses_p)
        comp_app_p = _ap_val(S, 'compras_com_app_ate_venda', meses=_ap_meses_p)
        comp_sem_app = (comp - comp_app) if (comp is not None and comp_app is not None) else None

        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "⬇️", "Downloads (1º login no app)", f"{_tv_n(dl)} {_tv_delta(dl, dl_p)}",
                f"{_tv_pct(dl_scpf, dl)} sem CPF (ficam fora dos cruzamentos)")
        _tv_kpi(k2, "📝", "Cadastros no app", f"{_tv_n(cad)} {_tv_delta(cad, cad_p)}",
                f"já cliente {_tv_pct(cad_fil, cad)} · venda no dia {_tv_pct(cad_dia, cad)} · entraram como freemium {_tv_pct(cad_free, cad)}",
                color="#2e8a4f")
        _tv_kpi(k3, "🛒", "Compras com o app = filiações de quem já tinha cadastro no app", f"{_tv_n(comp_app)} {_tv_delta(comp_app, comp_app_p)}",
                f"{_tv_pct(comp_app, comp)} das {_tv_n(comp)} filiações de titulares do período; cadastro no app até 1 dia após a venda", color="#0f172a")
        _tv_kpi(k4, "🌱", "Freemium que converteu (coorte do período)", f"{_tv_pct(cvt, cad_free)}",
                f"{_tv_n(cvt)} de {_tv_n(cad_free)} · em 30 d {_tv_pct(cv30, cad_free)} · em 90 d {_tv_pct(cv90, cad_free)}", color="#b45309")

        c1, c2 = st.columns([1.9, 1])
        with c1:
            _tv_funil("Funil do app · download → cadastro → compra", [
                ("⬇️", "Downloads (1º login)", dl, "fl_data_login.data_app no mês — 1 linha por usuário"),
                ("📝", "Cadastros", cad, "fl_plano_usuario.dt_criacao no mês"),
                ("🛒", "Compras com o app", comp_app, "filiações de titulares no mês de CPFs com cadastro no app até 1 dia após a venda"),
                ("📱", "…das quais IDPV do app (APP DO FILIADO)", comp_idpv, "tipo_prospeccao = APP DO FILIADO"),
            ], subtitle=(f"{_ap_meses[0]:%m/%Y}–{_ap_meses[-1]:%m/%Y}" if len(_ap_meses) > 1 else f"{_ap_meses[0]:%m/%Y}"))
            st.caption("As três etapas são contagens do mesmo mês, não uma coorte: quem baixou num mês pode cadastrar e comprar em outro "
                       "(por isso 'compras' pode passar de 100% de 'cadastros' em meses de venda forte). A leitura por coorte — dos "
                       "cadastros freemium do mês, quantos converteram — está no 4º card, nas linhas '……' da tabela e no gráfico de conversão.")
            _rows_f = [
                {'Etapa': 'Downloads (1º login)', 'Valor': _tv_n(dl), '% da etapa anterior': '—', '_level': 0, '_is_eff': False},
                {'Etapa': '… sem CPF no login', 'Valor': _tv_n(dl_scpf), '% da etapa anterior': _tv_pct(dl_scpf, dl), '_level': 1, '_is_eff': False},
                {'Etapa': 'Cadastros', 'Valor': _tv_n(cad), '% da etapa anterior': _tv_pct(cad, dl), '_level': 0, '_is_eff': False},
                {'Etapa': '… já era cliente ao cadastrar', 'Valor': _tv_n(cad_fil), '% da etapa anterior': _tv_pct(cad_fil, cad), '_level': 1, '_is_eff': False},
                {'Etapa': '… comprou no dia do cadastro (venda no ato)', 'Valor': _tv_n(cad_dia), '% da etapa anterior': _tv_pct(cad_dia, cad), '_level': 1, '_is_eff': False},
                {'Etapa': '… entrou como freemium', 'Valor': _tv_n(cad_free), '% da etapa anterior': _tv_pct(cad_free, cad), '_level': 1, '_is_eff': False},
                {'Etapa': '…… converteu em até 30 dias', 'Valor': _tv_n(cv30), '% da etapa anterior': _tv_pct(cv30, cad_free), '_level': 2, '_is_eff': False},
                {'Etapa': '…… converteu em até 90 dias', 'Valor': _tv_n(cv90), '% da etapa anterior': _tv_pct(cv90, cad_free), '_level': 2, '_is_eff': False},
                {'Etapa': '…… converteu até hoje', 'Valor': _tv_n(cvt), '% da etapa anterior': _tv_pct(cvt, cad_free), '_level': 2, '_is_eff': False},
                {'Etapa': '… ativou o cartão virtual', 'Valor': _tv_n(cad_cartao), '% da etapa anterior': _tv_pct(cad_cartao, cad), '_level': 1, '_is_eff': False},
                {'Etapa': 'Compras (filiações de titulares no mês, todos os canais)', 'Valor': _tv_n(comp), '% da etapa anterior': '—', '_level': 0, '_is_eff': False},
                {'Etapa': '… com o app: cadastro no app até 1 dia após a venda', 'Valor': _tv_n(comp_app), '% da etapa anterior': _tv_pct(comp_app, comp), '_level': 1, '_is_eff': False},
                {'Etapa': '…… cadastro antes da venda (freemium / ex-cliente com app)', 'Valor': _tv_n(comp_antes), '% da etapa anterior': _tv_pct(comp_antes, comp_app), '_level': 2, '_is_eff': False},
                {'Etapa': '…… cadastro junto com a venda (±1 dia)', 'Valor': _tv_n(comp_junto), '% da etapa anterior': _tv_pct(comp_junto, comp_app), '_level': 2, '_is_eff': False},
                {'Etapa': '… IDPV do app (APP DO FILIADO)', 'Valor': _tv_n(comp_idpv), '% da etapa anterior': _tv_pct(comp_idpv, comp), '_level': 1, '_is_eff': False},
                {'Etapa': '… cadastrou depois da venda', 'Valor': _tv_n(comp_dep), '% da etapa anterior': _tv_pct(comp_dep, comp), '_level': 1, '_is_eff': False},
                {'Etapa': '… sem app até a venda', 'Valor': _tv_n(comp_sem_app), '% da etapa anterior': _tv_pct(comp_sem_app, comp), '_level': 1, '_is_eff': False},
            ]
            st.markdown(render_metric_table(_rows_f, ['Etapa', 'Valor', '% da etapa anterior']), unsafe_allow_html=True)
            with st.expander("📖 Definição exata de cada etapa da tabela"):
                st.markdown(
                    "Tudo é contado por **CPF** e por **mês** (meses tocados pelo período dos Controles Globais). "
                    "A **1ª filiação** de um CPF é o `MIN(dt_filiacao)` no histórico completo de contratos do `fl_filiado` "
                    "(titular ou dependente) — é ela que decide se a pessoa já era cliente quando cadastrou o app.\n\n"
                    "| Etapa | Definição (tabela · regra) | Como ler o % |\n|---|---|---|\n"
                    "| **Downloads (1º login)** | `fl_data_login.data_app` no mês. É o *primeiro login* de cada usuário (1 linha por usuário), a régua que a área usa como download. | — |\n"
                    "| … sem CPF no login | linhas de `fl_data_login` com `document` vazio. Ficam fora de todos os cruzamentos por CPF (pico de 25% em jun/26). | ÷ downloads |\n"
                    "| **Cadastros** | `fl_plano_usuario.dt_criacao` no mês — a pessoa criou a conta no app (o campo `tem_registro` deixou de ser preenchido em out/2025 e não é usado). | ÷ downloads (não é conversão: login e cadastro podem cair em meses diferentes) |\n"
                    "| … já era cliente ao cadastrar | cadastros cuja 1ª filiação é **anterior** ao dia do cadastro — cliente (ou ex-cliente) instalando o app. | ÷ cadastros |\n"
                    "| … comprou no dia do cadastro (venda no ato) | 1ª filiação **no mesmo dia** do cadastro — venda pelo app ou cadastro feito junto com a venda (balcão/vendedor). | ÷ cadastros |\n"
                    "| … entrou como freemium | 1ª filiação **nula** ou **posterior** ao dia do cadastro — a pessoa usou o app sem ser cliente. É a única fatia em que faz sentido medir conversão. | ÷ cadastros |\n"
                    "| …… converteu em até 30 / 90 dias | dos que entraram como freemium naquele mês, quantos tiveram a 1ª filiação entre 1 e 30 (ou 90) dias depois do cadastro. | ÷ entraram como freemium |\n"
                    "| …… converteu até hoje | idem, com a 1ª filiação em qualquer data até a última carga (≥ 1 dia após o cadastro). | ÷ entraram como freemium |\n"
                    "| … ativou o cartão virtual | cadastros do mês com `dt_ativacao_pl` preenchido (em qualquer data). Sinal fraco: não prediz conversão (estudo 20/08). | ÷ cadastros |\n"
                    "| **Compras** | filiações de **titulares** no mês: `fl_filiado` com `registro_atual = 1`, `flag_titular = 1` e `dt_filiacao` no mês — todos os canais de venda. | — |\n"
                    "| … com o app: cadastro até 1 dia após a venda | dessas filiações, as de CPFs que têm cadastro em `fl_plano_usuario` com `dt_criacao` ≤ `dt_filiacao` + 1 dia. **Não** é 'todo mundo que tem o app': é quem já tinha a conta no app *até o dia seguinte à venda* (a folga de 1 dia captura o cadastro feito junto com a venda). Quem instalou o app depois disso está em 'cadastrou depois da venda'; quem só baixou e nunca cadastrou não conta (download sem cadastro não tem CPF confiável). | ÷ compras |\n"
                    "| …… cadastro antes da venda | `dt_criacao` < `dt_filiacao` − 1 dia: freemium que converteu ou ex-cliente que mantinha o app. | ÷ compras com o app |\n"
                    "| …… cadastro junto com a venda (±1 dia) | `dt_criacao` entre `dt_filiacao` − 1 e + 1 dia: conta criada no ato da venda. | ÷ compras com o app |\n"
                    "| … IDPV do app (APP DO FILIADO) | filiações do mês com `tipo_prospeccao = 'APP DO FILIADO'` — o canal de venda oficial do app (venda concluída dentro do app). Subconjunto de 'compras', não de 'compras com o app' (algumas vendas do app têm cadastro só depois). | ÷ compras |\n"
                    "| … cadastrou depois da venda | `dt_criacao` > `dt_filiacao` + 1 dia: cliente que instalou o app depois de comprar. | ÷ compras |\n"
                    "| … sem app até a venda | compras − compras com o app: filiações sem cadastro no app até o dia seguinte à venda (inclui quem cadastrou depois e quem nunca cadastrou). | ÷ compras |")
        with c2:
            _tv_note(
                "<b>Como ler.</b> <b>Download</b> é o 1º login (fl_data_login), não o evento de loja; "
                f"{_tv_pct(dl_scpf, dl)} vêm sem CPF e não cruzam com nada. <b>Cadastro</b> é o dt_criacao no fl_plano_usuario "
                "(o campo tem_registro parou de ser preenchido em out/2025). Dos cadastros, uma parte <b>já era cliente</b> "
                "(instalou o app depois de filiar), outra <b>comprou no ato</b> (venda pelo app / no balcão) e o resto "
                "<b>entrou como freemium</b> — é sobre esse grupo que a conversão faz sentido.<br><br>"
                "<b>Compra</b> = filiação de titular no mês; conta 'com o app' quando o cadastro existia até o dia da venda. "
                f"No período, {_tv_pct(comp_app, comp)} das filiações passaram pelo app, mas só {_tv_pct(comp_idpv, comp)} têm IDPV "
                "do app (APP DO FILIADO): o app é presença no caminho, não o canal de fechamento — metade da conversão do "
                "freemium fecha no porta a porta (estudo de 20/08).<br><br>"
                "<b>Sinal de qualidade:</b> cashback de farmácia no 1º mês prediz 3,5× a conversão do freemium; "
                "ativar o cartão virtual sozinho não prediz nada (ver sub-aba 2).")
        _mg1, _ = _ap_janela('t7_s1_jan')
        _tv_chart_mensal(_ap_long(S, ['downloads', 'cadastros', 'cadastros_freemium', 'compras_com_app_ate_venda'], meses=_mg1,
                                  labels={'downloads': 'Downloads', 'cadastros': 'Cadastros', 'cadastros_freemium': 'Entraram como freemium',
                                          'compras_com_app_ate_venda': 'Compras com o app'}),
                         "Série mensal — funil do app", stacked=False, rotulos=True,
                         fonte="Athena: fl_data_login · fl_plano_usuario · fl_filiado")
        _s1 = _ap_serie(S, 'cadastros_freemium', meses=_mg1).rename(columns={'valor': 'free'})
        for m_ in ['freemium_conv_30d', 'freemium_conv_90d', 'freemium_conv_total']:
            _s1 = _s1.merge(_ap_serie(S, m_, meses=_mg1).rename(columns={'valor': m_}), on='mes', how='left')
        _pl = []
        for m_, lbl_ in [('freemium_conv_30d', '% conv. em 30 d'), ('freemium_conv_90d', '% conv. em 90 d'), ('freemium_conv_total', '% conv. até hoje')]:
            _t = _s1[['mes']].copy(); _t['serie'] = lbl_; _t['valor'] = (_s1[m_] / _s1['free'] * 100).round(2)
            _pl.append(_t)
        _tv_linhas_mensal(pd.concat(_pl) if _pl else pd.DataFrame(columns=['mes', 'serie', 'valor']),
                          "Conversão da coorte de freemiums por mês de cadastro (%)", pct=True, rotulos=True,
                          subtitle="coorte = quem cadastrou o app naquele mês SEM ser cliente; % = quantos filiaram em até 30 d, 90 d ou até hoje")
        st.caption("**Como ler:** cada ponto é uma coorte de cadastro (o mês no eixo X), não o mês da venda. Denominador = cadastros do mês "
                   "que entraram como freemium; numerador = os que tiveram a 1ª filiação de 1 a 30 dias depois do cadastro (30 d), de 1 a 90 "
                   "dias (90 d) ou em qualquer data até a última carga (até hoje). Por construção até hoje ≥ 90 d ≥ 30 d. Meses recentes "
                   "ainda não tiveram tempo: uma coorte com menos de 30 dias mostra as três curvas iguais, e só a partir de 90 dias de idade "
                   "a curva '90 d' está fechada. Compare coortes com a mesma idade (ex.: '30 d' de meses já maduros) para ver se a "
                   "conversão está melhorando ou piorando.")

    # =================================================================
    # 2 · USO DE PRODUTOS
    # =================================================================
    with _ap_tabs[1]:
        cc1, cc2 = st.columns([1.6, 1])
        _pop = cc1.radio("População:", list(_AP_POP_LBL.keys()), format_func=lambda k: _AP_POP_LBL[k], horizontal=True, key='t7_s2_pop')
        with cc2:
            _mg2, _ = _ap_janela('t7_s2_jan')
        _mes_pop = _apd[_apd['secao'] == 's2_pop']['mes'].max() if not _apd.empty else None
        _pop_n = _ap_val('s2_pop', 'populacao', dim=_pop, meses=[_mes_pop] if _mes_pop is not None else [])
        _ex_free = _ap_val('s2_pop', 'populacao', dim='exfiliados_plano_freemium', meses=[_mes_pop] if _mes_pop is not None else [])
        _uso = _apd[(_apd['secao'] == 's2_uso') & (_apd['mes'].isin(_mg2)) & (_apd['dim'].str.startswith(_pop + '|'))].copy()
        _tot = _apd[(_apd['secao'] == 's2_uso_tot') & (_apd['mes'].isin(_mg2)) & (_apd['dim'] == _pop)]
        _ult = _mg2[-1]
        _u_ult = float(_tot[_tot['mes'] == _ult]['valor'].sum()) if not _tot.empty else None
        _u_med = float(_tot['valor'].mean()) if not _tot.empty else None

        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "👥", f"{_AP_POP_LBL[_pop]} — população (hoje)", _tv_n(_pop_n),
                {"clientes_ativos": "flag_qca = 1 e vam ≤ 34 (def. C), titulares e dependentes",
                 "clientes_nao_freemium": "clientes ativos (def. C) menos os que entraram como freemium e converteram",
                 "freemium_atual": f"plano Freemium sem filiação (freemium puro) · + {_tv_n(_ex_free)} ex-filiados no plano Freemium",
                 "freemium_conv": "entraram como freemium, filiaram ≥ 1 dia depois e são clientes ativos hoje"}[_pop])
        _tv_kpi(k2, "📈", f"Usaram algum produto em {_ap_mes_lbl(_ult)}", f"{_tv_n(_u_ult)}",
                f"{_tv_pct(_u_ult, _pop_n)} da população · média da janela {_tv_n(_u_med)}/mês", color="#2e8a4f")
        if not _uso.empty:
            _uso[['pop', 'produto', 'sub']] = _uso['dim'].str.split('|', n=2, expand=True)
            _top = _uso[(_uso['mes'] == _ult) & (_uso['metrica'] == 'usuarios')].groupby('produto')['valor'].sum().sort_values(ascending=False)
            _top1 = _top.index[0] if len(_top) else '—'
            _tv_kpi(k3, "🏆", f"Produto mais usado em {_ap_mes_lbl(_ult)}", _top1,
                    f"{_tv_n(_top.iloc[0]) if len(_top) else '—'} usuários · {_tv_pct(_top.iloc[0] if len(_top) else None, _pop_n)} da população", color="#0f172a")
            _usos_ult = float(_uso[(_uso['mes'] == _ult) & (_uso['metrica'] == 'usos')]['valor'].sum())
            _tv_kpi(k4, "🔁", f"Usos por usuário em {_ap_mes_lbl(_ult)}",
                    (f"{_usos_ult / _u_ult:.2f}".replace('.', ',') if _u_ult else "—"),
                    f"{_tv_n(_usos_ult)} usos registrados no mês", color="#b45309")
        else:
            _tv_kpi(k3, "🏆", "Produto mais usado", "—", "sem linhas de uso na janela", color="#0f172a")
            _tv_kpi(k4, "🔁", "Usos por usuário", "—", "", color="#b45309")

        if _uso.empty:
            st.info("Sem dados de uso para esta população na janela. Rode `gt7 run app_dash --arg only=s2`.")
        else:
            c1, c2 = st.columns([1.9, 1])
            with c1:
                _lp = _uso[_uso['metrica'] == 'usuarios'].groupby(['mes', 'produto'], as_index=False)['valor'].sum().rename(columns={'produto': 'serie'})
                _tv_chart_mensal(_lp, f"Usuários por produto e mês — {_AP_POP_LBL[_pop]}", stacked=False, rotulos=True,
                                 subtitle="usuários únicos (CPF) com pelo menos um uso do produto no mês",
                                 fonte="Athena: fl_utilizacao_filiado (filiados) · fl_cashback + fl_plano_usuario (freemium)")
                _pv = _uso[_uso['metrica'] == 'usuarios'].pivot_table(index=['produto', 'sub'], columns='mes', values='valor', aggfunc='sum').fillna(0)
                _pv = _pv.reindex(columns=sorted(_pv.columns))
                _pv_show = _pv.copy()
                _pv_show.columns = [_ap_mes_lbl(c) for c in _pv_show.columns]
                _pv_show = _pv_show.sort_values(_pv_show.columns[-1], ascending=False)
                _rows2 = []
                for (prod, sub), r in _pv_show.iterrows():
                    row = {'Produto · subproduto': f"{prod} · {sub}", '_level': 0, '_is_eff': False}
                    for c in _pv_show.columns:
                        row[c] = format_br(r[c])
                    row['% pop. (último mês)'] = _tv_pct(r[_pv_show.columns[-1]], _pop_n)
                    _rows2.append(row)
                st.markdown(render_metric_table(_rows2, ['Produto · subproduto'] + list(_pv_show.columns) + ['% pop. (último mês)']),
                            unsafe_allow_html=True)
            with c2:
                _tv_note({
                    "clientes_ativos": "<b>Clientes ativos.</b> Uso vem do fl_utilizacao_filiado: Cashback (Nacionais = Raia/Drogasil, "
                                       "Locais, Grupo, Campanhas, Online), Amor Saúde (consulta, exames, sessão, procedimento), Web Dental, "
                                       "Refuturiza e Visão de Todos. <code>valor</code> é o que o filiado consumiu, não receita. A população "
                                       "é a de <i>hoje</i> (def. C) — meses antigos medem o uso passado de quem está ativo agora.",
                    "clientes_nao_freemium": "<b>Clientes ativos que não vieram do freemium.</b> É a população de clientes ativos "
                                             "(def. C) <i>menos</i> os freemiums convertidos — ou seja, quem virou cliente sem passar pelo "
                                             "app como não-cliente (porta a porta, link do vendedor, PJ…). Uso do fl_utilizacao_filiado, "
                                             "calculado por diferença (o convertido é subconjunto do ativo). Compare com "
                                             "'Freemium → cliente ativo' no gráfico de penetração abaixo: o que o cliente de sempre usa "
                                             "× o que o freemium convertido usa.",
                    "freemium_atual": "<b>Freemiums atuais.</b> Não existe fl_utilizacao para não filiado: o sinal de uso é o "
                                      "<b>cashback</b> (fl_cashback, cashin; excluído o cashback de adesão), separado em farmácia "
                                      "(Raia/Drogasil) e outros parceiros, mais a <b>ativação do cartão virtual</b> e os <b>cadastros do mês</b>. "
                                      "A população é a de hoje (freemium puro) — quem converteu depois não está aqui, está em "
                                      "'Freemium → cliente ativo'.",
                    "freemium_conv": "<b>Freemium → cliente ativo.</b> Entraram como freemium (nenhuma filiação anterior), filiaram ≥ 1 dia "
                                     "depois do cadastro e hoje são clientes ativos. O uso aqui é o de <i>cliente</i> (fl_utilizacao). "
                                     "Abaixo, o mesmo grupo aberto por <b>tempo que ficou como freemium</b>: o que usava antes de "
                                     "converter e o que usa hoje.",
                }[_pop], bg="#f8fafc", icon="ℹ️")
                _tv_note("<b>Régua do estudo de 20/08.</b> Cashback de farmácia no 1º mês → conversão 13,3% vs 3,8% sem uso (3,5×); "
                         "quem usou farmácia antes de converter paga +7,5% de meses em 12 m e deve menos (21,6% vs 26,9% no mês 6). "
                         "Cashback de 'outros parceiros' sinaliza o contrário (3,1% de conversão; 37,3% de inadimplência). "
                         "Cartão ativado: 3,8%, igual a nada.", bg="#ecfdf5", icon="💡")


            st.markdown("---")
            _su = _uso[(_uso['mes'] == _ult) & (_uso['metrica'] == 'usuarios')].copy()
            _su_usos = _uso[(_uso['mes'] == _ult) & (_uso['metrica'] == 'usos')].copy()
            if not _su.empty:
                _tv_titulo("Composição por subproduto",
                           f"como cada produto se divide em {_ap_mes_lbl(_ult)} — % sobre a soma dos usuários por subproduto", "A")
                _prods = _su.groupby('produto')['valor'].sum().sort_values(ascending=False)
                _prod_sel = st.selectbox("Produto:", list(_prods.index), key=f't7_s2_sub_{_pop}')
                _sb1, _sb2 = st.columns([1, 1.4])
                with _sb1:
                    _ss = _su[_su['produto'] == _prod_sel].groupby('sub')['valor'].sum().sort_values(ascending=False)
                    _ssu = _su_usos[_su_usos['produto'] == _prod_sel].groupby('sub')['valor'].sum()
                    _den = float(_ss.sum())
                    _rows_sb = []
                    for _sb_, _v in _ss.items():
                        _rows_sb.append({'Subproduto': _sb_, '_level': 0, '_is_eff': False,
                                         'Usuários': format_br(_v), '% do produto': _tv_pct(_v, _den),
                                         'Usos': format_br(_ssu.get(_sb_, 0)),
                                         'Usos/usuário': (f"{(_ssu.get(_sb_, 0) / _v):.2f}".replace('.', ',') if _v else '—')})
                    st.markdown(render_metric_table(_rows_sb, ['Subproduto', 'Usuários', '% do produto', 'Usos', 'Usos/usuário']),
                                unsafe_allow_html=True)
                    st.caption("Um CPF pode usar mais de um subproduto no mês: as fatias fecham 100% sobre a **soma** das linhas, "
                               "que pode passar dos usuários únicos do produto.")
                with _sb2:
                    _ev = _uso[(_uso['produto'] == _prod_sel) & (_uso['metrica'] == 'usuarios')] \
                        .groupby(['mes', 'sub'], as_index=False)['valor'].sum().rename(columns={'sub': 'serie'})
                    _tv_chart_mensal(_ev, f"{_prod_sel} — usuários por subproduto e mês", stacked=True, rotulos=False,
                                     subtitle=f"população {_AP_POP_LBL[_pop]} · janela selecionada",
                                     fonte="Athena: fl_utilizacao_filiado (produto × sub_produto), agregado em alex_app_dash_mes (s2_uso)")

                if _prod_sel == 'CASHBACK' and _pop == 'clientes_ativos':
                    _pc = _apd[(_apd['secao'] == 's2_parc') & (_apd['mes'].isin(_mg2))
                               & (_apd['dim'].str.startswith('clientes_ativos|'))].copy()
                    if _pc.empty:
                        st.caption("ℹ️ Abertura por parceiro ainda não materializada: rode `gt7 run app_dash --arg only=s2p`.")
                    else:
                        _pc['parceiro'] = _pc['dim'].str.split('|', n=1).str[1]
                        _npar = _ap_val('s2_parc_tot', 'parceiros', dim='clientes_ativos', meses=[_ult])
                        _tv_titulo("Cashback por parceiro",
                                   f"onde os clientes ativos usaram cashback em {_ap_mes_lbl(_ult)} — top 20 do mês "
                                   f"(de {_tv_n(_npar)} parceiros distintos); o resto vira 'OUTROS PARCEIROS'", "A")
                        _pu = _pc[(_pc['mes'] == _ult) & (_pc['metrica'] == 'usuarios')].groupby('parceiro')['valor'].sum().sort_values(ascending=False)
                        _po = _pc[(_pc['mes'] == _ult) & (_pc['metrica'] == 'usos')].groupby('parceiro')['valor'].sum()
                        _denp = float(_pu.sum())
                        _pb1, _pb2 = st.columns([1, 1.4])
                        with _pb1:
                            _rows_pc = []
                            for _pp_, _v in _pu.items():
                                _rows_pc.append({'Parceiro': _pp_, '_level': 0, '_is_eff': _pp_ == 'OUTROS PARCEIROS',
                                                 'Usuários': format_br(_v), '% do cashback': _tv_pct(_v, _denp),
                                                 'Usos': format_br(_po.get(_pp_, 0))})
                            st.markdown(render_metric_table(_rows_pc, ['Parceiro', 'Usuários', '% do cashback', 'Usos']),
                                        unsafe_allow_html=True)
                        with _pb2:
                            _tops = [p for p in _pu.index if p != 'OUTROS PARCEIROS'][:6]
                            _evp = _pc[(_pc['metrica'] == 'usuarios') & (_pc['parceiro'].isin(_tops))] \
                                .groupby(['mes', 'parceiro'], as_index=False)['valor'].sum().rename(columns={'parceiro': 'serie'})
                            _tv_chart_mensal(_evp, "Top parceiros — usuários por mês", stacked=False, rotulos=False,
                                             subtitle="6 maiores do último mês (sem o agregado OUTROS)",
                                             fonte="Athena: fl_utilizacao_filiado.cash_nome_parceiro (s2_parc)")
                            _tv_note("<b>Leitura.</b> O subproduto NACIONAIS concentra Raia/Drogasil — aqui esse bloco abre por bandeira. "
                                     "O top 20 é recalculado a cada mês, então a lista de parceiros pode mudar de um mês para outro; "
                                     "a fatia OUTROS PARCEIROS agrega todos os demais.", bg="#f8fafc", icon="ℹ️")

            if _pop in ('clientes_nao_freemium', 'freemium_conv'):
                st.markdown("---")
                _tv_titulo("Penetração por produto — clientes de sempre × freemium convertido",
                           f"% da população que usou o produto em {_ap_mes_lbl(_ult)} (usuários únicos ÷ população de hoje); "
                           "populações de tamanhos muito diferentes, por isso a comparação é em %", "A")
                _cmp_rows = []
                for _pp, _lbl in [('clientes_nao_freemium', 'Clientes que não vieram do freemium'), ('freemium_conv', 'Freemium → cliente ativo')]:
                    _pn_ = _ap_val('s2_pop', 'populacao', dim=_pp, meses=[_mes_pop] if _mes_pop is not None else [])
                    _u_ = _apd[(_apd['secao'] == 's2_uso') & (_apd['mes'] == _ult) & (_apd['metrica'] == 'usuarios')
                               & (_apd['dim'].str.startswith(_pp + '|'))].copy()
                    if _u_.empty or not _pn_:
                        continue
                    _u_['produto'] = _u_['dim'].str.split('|', n=2).str[1]
                    for _prod, _v in _u_.groupby('produto')['valor'].sum().items():
                        _cmp_rows.append({'serie': _lbl, 'produto': _prod, 'pct': _v / _pn_ * 100, 'usuarios': _v})
                _dcmp = pd.DataFrame(_cmp_rows)
                if _dcmp.empty:
                    st.caption("sem uso no último mês para uma das populações.")
                else:
                    _ordp = _dcmp.groupby('produto')['pct'].max().sort_values(ascending=False).index.tolist()
                    _dcmp['rotulo'] = _dcmp['pct'].map(lambda v: f"{v:.1f}%".replace('.', ','))
                    fig = px.bar(_dcmp, x='produto', y='pct', color='serie', barmode='group', text='rotulo',
                                 category_orders={'produto': _ordp, 'serie': ['Clientes que não vieram do freemium', 'Freemium → cliente ativo']},
                                 color_discrete_sequence=['#166534', '#b45309'], template='cdt_a' if _CDT_THEME else 'plotly_white',
                                 custom_data=['usuarios'])
                    fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False,
                                      hovertemplate='%{x} · %{fullData.name}<br>%{y:.2f}% da população · %{customdata:,.0f} usuários<extra></extra>')
                    fig.update_layout(height=340, xaxis_title='', yaxis_title='', legend_title_text='', bargap=0.3)
                    fig.update_yaxes(ticksuffix='%')
                    st.plotly_chart(fig, use_container_width=True)
                    _tv_fonte("Athena: fl_utilizacao_filiado × populações de hoje (def. C) · 'não vieram do freemium' = ativos − convertidos")
                    st.caption("Leitura: a barra laranja acima da verde num produto diz que esse produto pesa mais para quem chegou pelo "
                               "app como freemium do que para o cliente de sempre — é o produto que 'puxa' a conversão; o inverso mostra o "
                               "que segura o cliente existente.")

            if _pop == 'freemium_conv':
                st.markdown("---")
                _tv_titulo("Freemium → cliente: uso por tempo que ficou como freemium",
                           "distribuição % do uso entre os produtos, dentro de cada faixa de tempo entre o cadastro e a 1ª filiação", "A")
                _pre = _apd[(_apd['secao'] == 's2_conv_pre')]
                _popb = _apd[(_apd['secao'] == 's2_pop') & (_apd['dim'].str.startswith('freemium_conv|'))]
                _cv = _apd[(_apd['secao'] == 's2_conv') & (_apd['mes'].isin(_mg2)) & (_apd['metrica'] == 'usuarios')].copy()
                cb1, cb2 = st.columns([1.2, 1])
                with cb1:
                    if not _cv.empty:
                        _cv[['bucket', 'produto', 'sub']] = _cv['dim'].str.split('|', n=2, expand=True)
                        _g = _cv.groupby(['bucket', 'produto'], as_index=False)['valor'].sum()
                        _g['pct'] = _g['valor'] / _g.groupby('bucket')['valor'].transform('sum') * 100
                        _g['bucket_lbl'] = _g['bucket'].map(_AP_BUCKET_LBL)
                        _g = _g.sort_values('bucket')
                        fig = px.bar(_g, x='bucket_lbl', y='pct', color='produto', barmode='stack',
                                     text=_g['pct'].map(lambda v: f"{v:.0f}%" if v >= 6 else ""),
                                     color_discrete_sequence=_TV_CORES_A, template='cdt_a' if _CDT_THEME else 'plotly_white',
                                     category_orders={'bucket_lbl': [_AP_BUCKET_LBL[k] for k in sorted(_AP_BUCKET_LBL)]})
                        fig.update_traces(textposition='inside', insidetextanchor='middle', textfont_size=10.5, textfont_color='#ffffff')
                        fig.update_layout(height=360, xaxis_title='', yaxis_title='', legend_title_text='', yaxis_ticksuffix='%',
                                          uniformtext_minsize=9, uniformtext_mode='hide')
                        st.plotly_chart(fig, use_container_width=True)
                        st.caption(f"Uso de hoje (como cliente) na janela {_ap_mes_lbl(_mg2[0])}–{_ap_mes_lbl(_mg2[-1])}: "
                                   "% = usuários do produto ÷ soma de usuários de todos os produtos na faixa (um CPF conta em cada produto que usou).")
                    else:
                        st.info("Sem linhas de uso por faixa na janela.")
                with cb2:
                    if not _pre.empty:
                        _pre2 = _pre[_pre['mes'] == _pre['mes'].max()].pivot_table(index='dim', columns='metrica', values='valor', aggfunc='sum').fillna(0)
                        _pre2 = _pre2.reindex(sorted(_pre2.index))
                        _rows3 = []
                        for b_, r in _pre2.iterrows():
                            n_ = float(r.get('n', 0))
                            _rows3.append({'Tempo como freemium': _AP_BUCKET_LBL.get(b_, b_), 'Convertidos': format_br(n_),
                                           'Farmácia antes': _tv_pct(r.get('com_farmacia'), n_), 'Outros parceiros': _tv_pct(r.get('com_outros'), n_),
                                           'Cartão ativado': _tv_pct(r.get('com_cartao'), n_), 'Nenhum uso': _tv_pct(r.get('nenhum'), n_),
                                           '_level': 0, '_is_eff': False})
                        _n_tot = float(_pre2['n'].sum()) if 'n' in _pre2.columns else 0
                        _rows3.append({'Tempo como freemium': 'Total', 'Convertidos': format_br(_n_tot),
                                       'Farmácia antes': _tv_pct(_pre2['com_farmacia'].sum(), _n_tot), 'Outros parceiros': _tv_pct(_pre2['com_outros'].sum(), _n_tot),
                                       'Cartão ativado': _tv_pct(_pre2['com_cartao'].sum(), _n_tot), 'Nenhum uso': _tv_pct(_pre2['nenhum'].sum(), _n_tot),
                                       '_level': 0, '_is_eff': False})
                        st.markdown("**O que usaram ANTES de converter** (entre o cadastro e a 1ª filiação)")
                        st.markdown(render_metric_table(_rows3, ['Tempo como freemium', 'Convertidos', 'Farmácia antes', 'Outros parceiros', 'Cartão ativado', 'Nenhum uso']),
                                    unsafe_allow_html=True)
                        st.caption("Sinal disponível para não filiado = cashback (farmácia × outros) e ativação do cartão; "
                                   "'Nenhum uso' = nem cashback nem cartão antes de filiar. População de hoje (convertidos ativos).")

    # =================================================================
    # 3 · FREEMIUM — estoque × gerados
    # =================================================================
    with _ap_tabs[2]:
        S = 's3_freemium'
        _mg3, _esc3 = _ap_janela('t7_s3_jan', opcoes=("Mês atual", "3 meses", "12 meses"), padrao=1)
        _ult3 = _mg3[-1]
        est = _ap_val(S, 'estoque_fim_mes', dim='freemium', meses=[_ult3])
        est_ini = _ap_val(S, 'estoque_fim_mes', dim='freemium', meses=[_mg3[0] - pd.DateOffset(months=1)])
        ger = _ap_val(S, 'gerados', dim='freemium', meses=_mg3); ger_ult = _ap_val(S, 'gerados', dim='freemium', meses=[_ult3])
        cvm = _ap_val(S, 'convertidos', dim='freemium', meses=_mg3); cvm_ult = _ap_val(S, 'convertidos', dim='freemium', meses=[_ult3])
        gcm = _ap_val(S, 'gerados_convertidos_no_mes', dim='freemium', meses=[_ult3])
        ger_prev = _ap_val(S, 'gerados', dim='freemium', meses=[_ult3 - pd.DateOffset(months=1)])
        cvm_prev = _ap_val(S, 'convertidos', dim='freemium', meses=[_ult3 - pd.DateOffset(months=1)])
        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "🌱", f"Estoque de freemiums no fim de {_ap_mes_lbl(_ult3)}", _tv_n(est),
                (f"{_tv_delta(est, est_ini)} vs fim de {_ap_mes_lbl(_mg3[0] - pd.DateOffset(months=1))}" if est_ini else "cadastrados sem nenhuma filiação até o fim do mês"))
        _tv_kpi(k2, "➕", f"Freemiums gerados em {_ap_mes_lbl(_ult3)}", f"{_tv_n(ger_ult)} {_tv_delta(ger_ult, ger_prev)}",
                f"cadastros do mês sem filiação anterior nem venda no dia · {_tv_n(gcm)} já converteram no próprio mês", color="#2e8a4f")
        _tv_kpi(k3, "🛒", f"Freemiums convertidos em {_ap_mes_lbl(_ult3)}", f"{_tv_n(cvm_ult)} {_tv_delta(cvm_ult, cvm_prev)}",
                f"1ª filiação no mês, de qualquer coorte · {_tv_pct(cvm_ult, est_ini if est_ini else est)} do estoque inicial", color="#0f172a")
        _tv_kpi(k4, "📊", f"Janela: {_esc3}", f"+{_tv_n(ger)} · −{_tv_n(cvm)}",
                "gerados · convertidos na janela (o estoque também perde cadastros excluídos e ganha regularizações)", color="#b45309")

        c1, c2 = st.columns([1.9, 1])
        with c1:
            _s3 = _ap_serie(S, 'estoque_fim_mes', dim='freemium', meses=_mg3).rename(columns={'valor': 'estoque'})
            _s3 = _s3.merge(_ap_serie(S, 'gerados', dim='freemium', meses=_mg3).rename(columns={'valor': 'gerados'}), on='mes', how='left')
            _s3 = _s3.merge(_ap_serie(S, 'convertidos', dim='freemium', meses=_mg3).rename(columns={'valor': 'convertidos'}), on='mes', how='left')
            _tv_titulo("Estoque de freemiums no fim do mês — o que ficou, o que entrou, o que saiu",
                       "barra = estoque no fim do mês: base clara = o que sobrou do estoque anterior, topo escuro = gerados no mês; "
                       "laranja abaixo do zero = convertidos no mês (saíram do estoque)", "A")
            if not _s3.empty:
                import plotly.graph_objects as _go
                _x = [_ap_mes_lbl(m) for m in _s3['mes']]
                _ger = _s3['gerados'].fillna(0); _cvm = _s3['convertidos'].fillna(0); _est = _s3['estoque'].fillna(0)
                _base = (_est - _ger).clip(lower=0)
                fig = _go.Figure()
                fig.add_bar(name='Ficou do estoque anterior', x=_x, y=_base, marker_color='#8cc79e',
                            hovertemplate='%{x}<br>ficou do estoque anterior: %{y:,.0f}<extra></extra>')
                fig.add_bar(name='Gerados no mês (entraram)', x=_x, y=_ger, marker_color='#166534',
                            hovertemplate='%{x}<br>gerados no mês: %{y:,.0f}<extra></extra>')
                fig.add_bar(name='Convertidos no mês (saíram)', x=_x, y=-_cvm, marker_color='#b45309',
                            text=[f"−{_tv_fmt_k(v)}" for v in _cvm], textposition='outside', cliponaxis=False,
                            textfont=dict(color='#b45309', size=11),
                            hovertemplate='%{x}<br>convertidos no mês: %{customdata:,.0f}<extra></extra>', customdata=_cvm)
                for xx, e, g in zip(_x, _est, _ger):
                    fig.add_annotation(x=xx, y=e, text=f"<b>{_tv_fmt_k(e)}</b><span style='color:#166534'>  +{_tv_fmt_k(g)}</span>",
                                       showarrow=False, yshift=12, font=dict(size=11))
                fig.update_layout(template='cdt_a' if _CDT_THEME else 'plotly_white', barmode='relative', height=400,
                                  xaxis_title='', yaxis_title='', legend_title_text='', margin=dict(l=45, r=60, t=40, b=30))
                fig.update_yaxes(zeroline=True, zerolinecolor='#0f172a', zerolinewidth=1.2)
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("Athena: fl_plano_usuario × 1ª filiação por CPF (fl_filiado) · estoque(m) = ficou do anterior + gerados; "
                          "ficou do anterior = estoque(m−1) − convertidos − cadastros removidos/regularizados")
            else:
                st.info("Sem série de freemium na janela.")
        with c2:
            _tv_note(
                "<b>Como ler.</b> Cada barra é o <b>estoque de freemiums no fim do mês</b>: usuários cadastrados no app até "
                "ali que ainda não tinham nenhuma filiação (a 1ª filiação por CPF vem do histórico do fl_filiado — quem já "
                "era cliente ou ex-cliente ao cadastrar não é freemium). A parte <b>clara</b> é o que sobrou do estoque do mês "
                "anterior; a parte <b>escura</b> são os <b>gerados</b> no mês (cadastros que entraram como freemium). A barra "
                "<b>laranja</b>, abaixo do zero, são os <b>convertidos</b> no mês — freemiums de qualquer coorte cuja 1ª "
                "filiação caiu ali — e por isso saem do estoque. Estoque(m) = estoque(m−1) + gerados − convertidos − "
                "cadastros removidos/regularizados.<br><br>"
                "<b>Ressalvas.</b> Freemium só existe desde 2024 (antes, 0,08% dos cadastros); o mês corrente é parcial; "
                "ex-filiados que usam o app no plano Freemium não entram no estoque (aparecem à parte na sub-aba 2). "
                "Cadastros sem CPF no login (até 25% em jun/26) não cruzam.")

        # ---- convertidos no mês por tipo de venda da 1ª filiação ----
        _ct = _apd[(_apd['secao'] == S) & (_apd['metrica'] == 'convertidos') & (_apd['dim'].str.startswith('tipo:'))
                   & (_apd['mes'].isin(_mg3))].copy() if not _apd.empty else pd.DataFrame(columns=_AP_COLS)
        _tv_titulo(f"Convertidos por tipo de venda da 1ª filiação — {_ap_mes_lbl(_mg3[0])}" + (f" a {_ap_mes_lbl(_mg3[-1])}" if len(_mg3) > 1 else ""),
                   "com que canal o freemium fechou a compra (tipo_prospeccao da filiação); % do total de convertidos na janela, do maior para o menor", "A")
        if _ct.empty:
            st.caption("sem abertura por tipo de venda: rode `gt7 run app_dash --arg only=s3` para gravar `s3_freemium · tipo:*`.")
        else:
            _ct['tipo'] = _ct['dim'].str[5:]
            _tt = _ct.groupby('tipo')['valor'].sum().sort_values(ascending=False)
            _tot_ct = float(_tt.sum())
            _sh = (_tt / _tot_ct * 100) if _tot_ct else _tt * 0
            _peq = _sh[_sh < 0.5]
            _rk = _sh[_sh >= 0.5].to_frame('pct')
            _rk['n'] = _tt[_rk.index]
            if len(_peq):
                _rk.loc[f"Outros ({len(_peq)} tipos)"] = [float(_peq.sum()), float(_tt[_peq.index].sum())]
            _rk = _rk.reset_index().rename(columns={'index': 'tipo'})
            _rk['rotulo'] = _rk.apply(lambda r: f"{r['pct']:.1f}%".replace('.', ',') + f"  ({_tv_fmt_k(r['n'])})", axis=1)
            _rk['cor'] = _rk['tipo'].map(lambda t: '#94a3b8' if t.startswith('Outros') else '#166534')
            _rk = _rk.sort_values('pct', ascending=True)
            fig = px.bar(_rk, x='pct', y='tipo', orientation='h', text='rotulo', template='cdt_a' if _CDT_THEME else 'plotly_white')
            fig.update_traces(textposition='outside', cliponaxis=False, marker_color=_rk['cor'].tolist(), textfont_size=11,
                              hovertemplate='%{y}<br>%{x:.1f}% · %{text}<extra></extra>')
            fig.update_layout(height=max(300, 30 * len(_rk) + 70), margin=dict(l=150, r=110, t=10, b=30), xaxis_title='', yaxis_title='',
                              showlegend=False, yaxis=dict(autorange=True, side='left', showgrid=False, tickfont=dict(size=12, color='#0f172a')))
            fig.update_xaxes(ticksuffix='%', range=[0, float(_rk['pct'].max()) * 1.25])
            st.plotly_chart(fig, use_container_width=True)
            _tv_fonte(f"Athena: fl_plano_usuario × fl_filiado (tipo_prospeccao da linha com dt_filiacao = 1ª filiação) · "
                      f"{format_br(_tot_ct)} convertidos na janela · tipos com menos de 0,5% agrupados em Outros")
            _pv = _ct.pivot_table(index='tipo', columns='mes', values='valor', aggfunc='sum').fillna(0)
            _pv = _pv.loc[_pv.sum(axis=1).sort_values(ascending=False).index]
            _pv.columns = [_ap_mes_lbl(c) for c in _pv.columns]
            _pv['Total'] = _pv.sum(axis=1)
            _pv['% do total'] = (_pv['Total'] / _pv['Total'].sum() * 100).round(1).map(lambda v: f"{v:.1f}%".replace('.', ','))
            for _c in [c for c in _pv.columns if c != '% do total']:
                _pv[_c] = _pv[_c].map(format_br)
            with st.expander("Tabela — convertidos por tipo de venda, mês a mês (absolutos)"):
                st.dataframe(_pv.reset_index().rename(columns={'tipo': 'Tipo de venda'}), use_container_width=True, hide_index=True)
                st.caption("Leitura do estudo de 20/08: o app é presença no caminho, não o canal de fechamento — parte grande da "
                           "conversão do freemium fecha no porta a porta; APP DO FILIADO é a venda concluída dentro do app.")

    # =================================================================
    # 4 · LTV E ENTRADA NO APP (evolução das coortes no app, 05/08)
    # -----------------------------------------------------------------
    # Lê secao 's4_ltv' (pipeline app_dash s4): por MÊS DA VENDA (coorte de titulares) e por dim
    # ('total', 'entrada:*', 'tipo:*'), n = tamanho da coorte e pag_k{0..11}_{A|C|B} = quantos pagavam
    # no mês k depois da venda. LTV em N meses = 33,40 × (1 + Σ_{k<N} pag_k / n) — receita bruta,
    # antes de desconto, 1 = adesão. Uma coorte só entra numa janela de N meses quando o painel já
    # tem o mês k = N−1 dela (ref_max_idx).
    # =================================================================
    with _ap_tabs[3]:
        S = 's4_ltv'
        _L4 = _apd[_apd['secao'] == S] if not _apd.empty else pd.DataFrame(columns=_AP_COLS)
        _LTV_MENS = 33.40
        _ENT_LBL = {'antes': 'Baixou antes da venda', 'no_mes': 'Baixou no mês da venda',
                    'depois': 'Baixou depois da venda', 'nunca': 'Nunca baixou'}
        _ENT_ORD = ['antes', 'no_mes', 'depois', 'nunca']
        _ENT_COR = {'Baixou antes da venda': '#166534', 'Baixou no mês da venda': '#57a86f',
                    'Baixou depois da venda': '#8cc79e', 'Nunca baixou': '#b45309'}
        _DEF_LBL = {'A': 'A · contrato ativo', 'C': 'C · até 1 mês de atraso', 'B': 'B · sem nenhum atraso'}
        _JAN = [3, 6, 12]
        _JAN_COR = {3: '#8cc79e', 6: '#57a86f', 12: '#166534'}
        _NCO = 6                                    # coortes agregadas por janela nos gráficos por grupo
        _rm = _L4[(_L4['dim'] == 'painel') & (_L4['metrica'] == 'ref_max_idx')]['valor']
        _ref_max = int(_rm.max()) if not _rm.empty and pd.notna(_rm.max()) else None
        _ref_max_lbl = (f"{(_ref_max - 1) % 12 + 1:02d}/{(_ref_max - 1) // 12}" if _ref_max else "—")
        _todas4 = [pd.Timestamp(m) for m in sorted(_L4[_L4['dim'] == 'total']['mes'].dropna().unique())]

        def _s4_idx(ts):
            ts = pd.Timestamp(ts)
            return ts.year * 12 + ts.month

        def _s4_sum(dim, metrica, meses):
            d = _L4[(_L4['dim'] == dim) & (_L4['metrica'] == metrica) & (_L4['mes'].isin(list(meses)))]
            return float(d['valor'].sum()) if not d.empty else 0.0

        def _s4_eleg(meses, N):
            """Coortes (meses de venda) que já têm o mês k = N−1 no painel."""
            if _ref_max is None:
                return []
            return [m for m in meses if _s4_idx(m) + N - 1 <= _ref_max]

        def _s4_ltv(dim, N, defn, meses):
            """(ltv, n, ret_{N-1}, coortes usadas) sob a definição defn, agregando as coortes elegíveis (peso = n)."""
            el = _s4_eleg(meses, N)
            n = _s4_sum(dim, 'n', el) if el else 0.0
            if n <= 0:
                return None, 0.0, None, el
            s = sum(_s4_sum(dim, f'pag_k{k}_{defn}', el) for k in range(N))
            r = _s4_sum(dim, f'pag_k{N - 1}_{defn}', el) / n
            return _LTV_MENS * (1 + s / n), n, r, el

        def _s4_brl(v, nd=2):
            return "—" if v is None or pd.isna(v) else f"R$ {v:,.{nd}f}".replace(',', 'X').replace('.', ',').replace('X', '.')

        def _s4_ult_coortes(N, quantas=_NCO):
            """As últimas `quantas` coortes com a janela de N meses completa (entre todas as gravadas)."""
            el = _s4_eleg(_todas4, N)
            return el[-quantas:] if el else []

        def _s4_rng(meses):
            return (f"{_ap_mes_lbl(meses[0])}–{_ap_mes_lbl(meses[-1])}" if len(meses) > 1
                    else (_ap_mes_lbl(meses[0]) if meses else "—"))

        _tv_note(
            "<b>Esta sub-aba não segue o Período de análise dos Controles Globais.</b> Aqui o eixo do tempo é o "
            "<b>mês da venda</b> (coorte), e cada coorte precisa envelhecer no painel para ter LTV: uma venda de junho só tem "
            "3 meses de vida em agosto. Por isso os controles são outros — quantas coortes mostrar e qual definição de "
            f"pagante usar — e as janelas de 6 e 12 meses só existem para coortes mais antigas. Painel até <b>{_ref_max_lbl}</b> "
            "(o mês corrente é provisório: a inadimplência dele ainda está acumulando).", bg="#f8fafc", icon="🧭")
        with st.expander("📖 Como ler esta sub-aba (coortes, janelas fixas e definições)"):
            st.markdown(
                "**Coorte de venda** = todos os titulares que compraram num mês (`fl_filiado`, registro_atual = 1, "
                "flag_titular = 1). Ela é acompanhada mês a mês no painel `fl_nominal_qca_qcd`: no mês da venda (k = 0), no "
                "mês seguinte (k = 1) e assim por diante.\n\n"
                "**LTV em N meses (janela fixa)** = R$ 33,40 × (1 + meses pagos em k = 0…N−1). O 1 é a adesão; R$ 33,40 é a "
                "mensalidade típica (receita bruta, antes de desconto — premissa, não faturamento medido). Comparar coortes só "
                "faz sentido com a mesma janela: uma coorte de janeiro já viveu 8 meses, uma de junho viveu 3 — sem janela fixa, "
                "a média mede exposição, não qualidade.\n\n"
                "**Por que as linhas param.** A linha de 12 meses só existe para coortes que já têm o 12º mês no painel "
                f"(hoje: vendas até {_ap_mes_lbl(_s4_eleg(_todas4, 12)[-1]) if _s4_eleg(_todas4, 12) else '—'}); a de 6 meses, "
                f"até {_ap_mes_lbl(_s4_eleg(_todas4, 6)[-1]) if _s4_eleg(_todas4, 6) else '—'}; a de 3 meses, até "
                f"{_ap_mes_lbl(_s4_eleg(_todas4, 3)[-1]) if _s4_eleg(_todas4, 3) else '—'}. Coortes mais novas ainda não têm "
                "o número — não é falta de dado, é falta de tempo.\n\n"
                "**Definições de pagante** (o mês k conta como pago se…): **A** contrato ativo (`qca = 1`) — conta quem está "
                "devendo há meses; **C** até 1 mês de atraso (`vam_inadimplente ≤ 34`) — tolera a defasagem normal de "
                "cobrança; **B** sem nenhum atraso (`vam = 0`). A distância A → B é a inadimplência; é ela que separa canais "
                "cedo, quando a retenção ainda não separa.\n\n"
                f"**Gráficos por grupo (entrada no app, tipo de venda).** Cada janela usa as **últimas {_NCO} coortes que já a "
                "completaram** — o rótulo diz quais. Dentro de uma janela os grupos são comparáveis entre si (mesmas coortes); "
                "entre janelas, não (coortes diferentes, épocas diferentes).\n\n"
                "**Ressalvas.** Só titulares (o contrato é a unidade que paga). Sem desconto/voucher (fl_contagem_filiados_v2 não "
                "alcança 2026). A referência 2026/04 do painel veio com vam = 0 em todas as linhas — para ela, C e B valem a "
                "média do estado do mesmo CPF em 2026/03 e 2026/05. Leitura precoce engana: nas coortes de 2025 a retenção no "
                "mês 3 explicou só 3% da retenção no mês 12 (TUTTI era 4º no mês 3 e último no mês 12) — use as janelas curtas "
                "para inadimplência e espere a de 12 meses para ranquear canal por LTV.")
        if _L4.empty or _ref_max is None:
            st.warning("⚠️ A seção `s4_ltv` ainda não existe em `alex_app_dash_mes`. Rode `gt7 run app_dash --arg only=s4` "
                       "(claude-toolkit) e recarregue os dados.")
        else:
            _c4a, _c4b = st.columns([1, 1.4])
            with _c4a:
                _nco_show = int(st.radio("Coortes mostradas (meses de venda):", ["12 coortes", "24 coortes"], index=0, horizontal=True,
                                         key='t7_s4_jan').split()[0])
            with _c4b:
                _def4 = st.radio("Definição de pagante:", ['A', 'C', 'B'], index=1, horizontal=True, key='t7_s4_def',
                                 format_func=lambda k: _DEF_LBL[k])
            _co4 = _todas4[-_nco_show:]
            _xs = [_ap_mes_lbl(m) for m in _co4]
            _denso = len(_co4) > 12

            # ---------- (a) entrada no app por coorte de venda ----------
            _rows_a = []
            for m in _co4:
                for g in _ENT_ORD:
                    _rows_a.append({'mes': m, 'serie': _ENT_LBL[g], 'valor': _s4_sum(f'entrada:{g}', 'n', [m])})
            _da = pd.DataFrame(_rows_a)
            _tv_titulo("Entrada no app por coorte de venda",
                       "como cada mês de venda se divide entre quem já tinha o app, baixou no mês da venda, baixou depois ou nunca baixou", "A")
            if _da.empty:
                st.caption("sem coortes gravadas.")
            else:
                _da['x'] = _da['mes'].map(_ap_mes_lbl)
                _da['rotulo'] = "" if _denso else _da['valor'].map(_tv_fmt_k)
                fig = px.bar(_da, x='x', y='valor', color='serie', barmode='stack', text='rotulo',
                             category_orders={'serie': [_ENT_LBL[g] for g in _ENT_ORD], 'x': _xs},
                             color_discrete_map=_ENT_COR, template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='inside', insidetextanchor='middle', textfont_size=10.5, textfont_color='#ffffff')
                _tot_a = _da.groupby('x', sort=False)['valor'].sum()
                _nun_a = _da[_da['serie'] == 'Nunca baixou'].set_index('x')['valor']
                for xx in _xs:
                    t = float(_tot_a.get(xx, 0)); nn = float(_nun_a.get(xx, 0))
                    _pn = f"{(nn / t * 100 if t else 0):.1f}%".replace('.', ',')
                    fig.add_annotation(x=xx, y=t, text=(f"<span style='color:#b45309'>{_pn}</span>" if _denso
                                                        else f"<b>{_tv_fmt_k(t)}</b><br><span style='color:#b45309'>{_pn}</span>"),
                                       showarrow=False, yshift=(12 if _denso else 22), font=dict(size=(9.5 if _denso else 10.5)), align='center')
                fig.update_layout(height=380, xaxis_title='', yaxis_title='titulares vendidos', legend_title_text='',
                                  uniformtext_minsize=9, uniformtext_mode='hide', margin=dict(t=56))
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("Athena: fl_filiado (titulares) × fl_data_login (1º login) · sobre cada coluna: total e, em laranja, a fatia que nunca baixou o app")
                _ta = []
                for m in _co4:
                    tot = _s4_sum('total', 'n', [m])
                    row = {'Mês da venda': _ap_mes_lbl(m), 'Titulares': format_br(tot)}
                    for g in _ENT_ORD:
                        row[_ENT_LBL[g]] = _tv_pct(_s4_sum(f'entrada:{g}', 'n', [m]), tot)
                    _ta.append(row)
                with st.expander("Tabela da composição (%)"):
                    st.dataframe(pd.DataFrame(_ta), use_container_width=True, hide_index=True)
                    st.caption("Entrada = mês do 1º login no app (fl_data_login, 1 linha por usuário; logins sem CPF não cruzam) "
                               "comparado com o mês da venda. 'Depois' encolhe nos meses recentes por exposição: quem comprou "
                               "há um mês teve um mês para baixar.")

            st.markdown("---")
            # ---------- (b) LTV por coorte de venda — janelas fixas de 3, 6 e 12 meses ----------
            _cmp4 = st.toggle("Ver A × C × B em vez das três janelas (janela fixa de 3 meses)", value=False, key='t7_s4_cmp')
            _rows_b = []
            if _cmp4:
                for m in _co4:
                    for dk in ['A', 'C', 'B']:
                        v, n, r, el = _s4_ltv('total', 3, dk, [m])
                        _rows_b.append({'mes': m, 'serie': _DEF_LBL[dk], 'valor': v})
                _cores_b = ['#166534', '#57a86f', '#b45309']
                _tit_b = "LTV em 3 meses por coorte de venda — A × C × B"
                _sub_b = "mesma janela (k = 0, 1, 2) sob as três definições de pagante; a distância A → B é a inadimplência"
            else:
                for m in _co4:
                    for N in _JAN:
                        v, n, r, el = _s4_ltv('total', N, _def4, [m])
                        _rows_b.append({'mes': m, 'serie': f"{N} meses", 'valor': v})
                _cores_b = [_JAN_COR[N] for N in _JAN]
                _tit_b = f"LTV por coorte de venda em janelas fixas de 3, 6 e 12 meses — {_DEF_LBL[_def4]}"
                _sub_b = "R$ 33,40 × (1 + meses pagos na janela); cada linha para onde as coortes ainda não completaram a janela"
            _db = pd.DataFrame(_rows_b)
            _tv_titulo(_tit_b, _sub_b, "B")
            if _db.empty or _db['valor'].dropna().empty:
                st.caption(f"nenhuma coorte mostrada tem janela completa no painel (última referência {_ref_max_lbl}).")
            else:
                _db['x'] = _db['mes'].map(_ap_mes_lbl)
                _db = _db.dropna(subset=['valor']).copy()
                _db['rotulo'] = "" if _denso else _db['valor'].map(lambda v: _s4_brl(v, 0))
                _ylo, _yhi = float(_db['valor'].min()), float(_db['valor'].max())
                _pad = max(6.0, (_yhi - _ylo) * 0.18)
                fig = px.line(_db, x='x', y='valor', color='serie', markers=True, text='rotulo',
                              category_orders={'x': _xs, 'serie': ([_DEF_LBL[k] for k in ['A', 'C', 'B']] if _cmp4 else [f"{N} meses" for N in _JAN])},
                              color_discrete_sequence=_cores_b, template='cdt_b' if _CDT_THEME else 'plotly_white')
                fig.update_traces(line_width=2.5, marker_size=7, textposition='top center', textfont_size=10, mode='lines+markers+text',
                                  connectgaps=False, hovertemplate='%{x} · %{fullData.name}: R$ %{y:,.2f}<extra></extra>')
                fig.update_layout(height=360, xaxis_title='', yaxis_title='', legend_title_text='', margin=dict(l=45, r=110))
                fig.update_yaxes(tickprefix='R$ ', range=[_ylo - _pad, _yhi + _pad], rangemode='normal')
                fig.update_xaxes(categoryorder='array', categoryarray=_xs)
                if _CDT_THEME:
                    cdt_theme.rotular_pontas(fig)
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("Athena: fl_filiado (coorte) × fl_nominal_qca_qcd (painel mensal, qca/vam_inadimplente)")
                _tb = []
                for m in _co4:
                    row = {'Coorte': _ap_mes_lbl(m), 'Titulares': format_br(_s4_sum('total', 'n', [m]))}
                    for N in _JAN:
                        v, n, r, el = _s4_ltv('total', N, _def4, [m])
                        row[f'LTV {N}m'] = _s4_brl(v)
                        row[f'ret. m{N - 1}'] = ("—" if r is None else f"{r * 100:.1f}%".replace('.', ','))
                    for dk in ['A', 'B']:
                        if dk != _def4:
                            v, n, r, el = _s4_ltv('total', 3, dk, [m])
                            row[f'LTV 3m · {dk}'] = _s4_brl(v)
                    _tb.append(row)
                with st.expander(f"Tabela por coorte — janelas de 3, 6 e 12 meses sob {_def4}, e o 3 meses sob as outras definições"):
                    st.dataframe(pd.DataFrame(_tb), use_container_width=True, hide_index=True)
                    st.caption("ret. m(N−1) = fração da coorte pagando no último mês da janela, sob a definição escolhida. "
                               "Coortes sem a janela completa ficam com '—'.")

            st.markdown("---")
            # ---------- (c) LTV por entrada no app · 3 / 6 / 12 meses ----------
            _rows_c, _tab_c = [], []
            for N in _JAN:
                el = _s4_ult_coortes(N)
                for g in _ENT_ORD:
                    v, n, r, _ = _s4_ltv(f'entrada:{g}', N, _def4, el)
                    _rows_c.append({'janela': f"{N} meses", 'serie': _ENT_LBL[g], 'valor': v, 'n': n, 'ret': r, 'coortes': _s4_rng(el)})
            _dc = pd.DataFrame(_rows_c)
            _tv_titulo(f"LTV por entrada no app — {_DEF_LBL[_def4]}",
                       f"janelas fixas de 3, 6 e 12 meses; cada janela agrega as últimas {_NCO} coortes que já a completaram (o rótulo diz quais)", "A")
            if _dc.empty or _dc['valor'].dropna().empty:
                st.caption("sem coortes com janela completa.")
            else:
                _dcp = _dc.dropna(subset=['valor']).copy()
                _dcp['x'] = _dcp.apply(lambda r: f"{r['janela']}<br><span style='font-size:10px'>coortes {r['coortes']}</span>", axis=1)
                _dcp['rotulo'] = _dcp['valor'].map(lambda v: _s4_brl(v).replace('R$ ', ''))
                fig = px.bar(_dcp, x='x', y='valor', color='serie', barmode='group', text='rotulo',
                             category_orders={'serie': [_ENT_LBL[g] for g in _ENT_ORD]}, color_discrete_map=_ENT_COR,
                             template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
                fig.update_layout(height=380, xaxis_title='', yaxis_title='', legend_title_text='', bargap=0.25, margin=dict(b=62))
                fig.update_yaxes(tickprefix='R$ ')
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("Athena: fl_filiado × fl_data_login × fl_nominal_qca_qcd")
                for N in _JAN:
                    d = _dc[_dc['janela'] == f"{N} meses"].dropna(subset=['valor'])
                    if d.empty:
                        _tab_c.append({'Janela': f"{N} meses", 'Coortes': '— (nenhuma coorte completou a janela)'})
                        continue
                    row = {'Janela': f"{N} meses", 'Coortes': d['coortes'].iloc[0]}
                    for _, r in d.iterrows():
                        _rp = ("" if r['ret'] is None else " · ret. " + f"{r['ret'] * 100:.1f}%".replace('.', ','))
                        row[r['serie']] = f"{_s4_brl(r['valor'])} · n {_tv_fmt_k(r['n'])}{_rp}"
                    _tab_c.append(row)
                with st.expander("Tabela por janela (LTV · tamanho · retenção no último mês da janela)"):
                    st.dataframe(pd.DataFrame(_tab_c), use_container_width=True, hide_index=True)
                    st.caption("Cuidado com 'baixou depois': para baixar depois é preciso sobreviver até baixar — quem cancelou antes "
                               "cai em 'nunca baixou'. Parte da vantagem desse grupo é artefato (evolução do app, seção 3).")

            st.markdown("---")
            # ---------- (d) LTV por tipo de venda · 3 / 6 / 12 meses (um painel por janela) ----------
            _tipos = sorted({d[5:] for d in _L4['dim'].unique() if str(d).startswith('tipo:')})
            _rows_d = []
            for t in _tipos:
                row = {'Tipo de venda': t}
                for N in _JAN:
                    v, n, r, _ = _s4_ltv(f'tipo:{t}', N, _def4, _s4_ult_coortes(N))
                    row[f'ltv{N}'] = v; row[f'n{N}'] = n; row[f'ret{N}'] = r
                _rows_d.append(row)
            _dd = pd.DataFrame(_rows_d)
            _tv_titulo(f"LTV por tipo de venda — {_DEF_LBL[_def4]}",
                       f"um painel por janela, cada um ordenado pelo próprio LTV e agregando as últimas {_NCO} coortes que completaram a janela; "
                       "eixos cortados para abrir a diferença entre canais; tipos com menos de 200 vendas ficam só na tabela", "A")
            if _dd.empty:
                st.caption("sem tipos de venda gravados.")
            else:
                _cols_d = st.columns(3)
                for _cd, N in zip(_cols_d, _JAN):
                    with _cd:
                        el = _s4_ult_coortes(N)
                        _ddp = _dd.dropna(subset=[f'ltv{N}']).copy()
                        _ddp = _ddp[_ddp[f'n{N}'] >= 200].sort_values(f'ltv{N}', ascending=True)
                        st.markdown(f"<div style='font-size:13px;font-weight:700;color:#0f172a;margin:2px 0 0;'>{N} meses</div>"
                                    f"<div style='font-size:11px;color:#64748b;'>coortes {_s4_rng(el)} · "
                                    f"{_tv_fmt_k(float(_ddp[f'n{N}'].sum())) if not _ddp.empty else '—'} titulares</div>", unsafe_allow_html=True)
                        if _ddp.empty:
                            st.caption("nenhuma coorte completou esta janela.")
                            continue
                        _ddp['rotulo'] = _ddp[f'ltv{N}'].map(lambda v: _s4_brl(v, 0).replace('R$ ', ''))
                        fig = px.bar(_ddp, x=f'ltv{N}', y='Tipo de venda', orientation='h', text='rotulo',
                                     color_discrete_sequence=[_JAN_COR[N]], template='cdt_a' if _CDT_THEME else 'plotly_white',
                                     custom_data=[f'n{N}', f'ret{N}'])
                        fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False,
                                          hovertemplate='%{y}<br>LTV R$ %{x:,.2f} · n %{customdata[0]:,.0f} · ret. %{customdata[1]:.1%}<extra></extra>')
                        _xmin = float(_ddp[f'ltv{N}'].min()); _xmax = float(_ddp[f'ltv{N}'].max()); _sp = max(_xmax - _xmin, 1.0)
                        fig.update_layout(height=max(280, 30 * len(_ddp) + 60), xaxis_title='', yaxis_title='',
                                          margin=dict(l=8, r=48, t=6, b=28), showlegend=False,
                                          yaxis=dict(side='left', showgrid=False, automargin=True,
                                                     tickfont=dict(size=10, color='#0f172a')))
                        fig.update_xaxes(tickprefix='R$ ', range=[max(0, _xmin - _sp * 1.2 - 3), _xmax + _sp * 0.45 + 3], nticks=4)
                        st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("Athena: fl_filiado (tipo_prospeccao) × fl_nominal_qca_qcd")
                _td = []
                for _, r in _dd.sort_values('ltv3', ascending=False, na_position='last').iterrows():
                    row = {'Tipo de venda': r['Tipo de venda']}
                    for N in _JAN:
                        row[f'LTV {N}m'] = _s4_brl(r[f'ltv{N}'])
                        row[f'n {N}m'] = _tv_fmt_k(r[f'n{N}']) if r[f'n{N}'] else "—"
                        row[f'ret. m{N - 1}'] = ("—" if r[f'ret{N}'] is None else f"{r[f'ret{N}'] * 100:.1f}%".replace('.', ','))
                    _td.append(row)
                with st.expander("Tabela por tipo de venda (3 · 6 · 12 meses, todos os tipos)"):
                    st.dataframe(pd.DataFrame(_td), use_container_width=True, hide_index=True)
                    st.caption("Leitura precoce engana: nas coortes de 2025 a retenção no mês 3 explicou só 3% da retenção no mês 12 "
                               "(TUTTI era 4º no mês 3 e último no mês 12). Use as janelas curtas para inadimplência (que já separa "
                               "canais) e espere a de 12 meses para ranquear canal por LTV.")

    # =================================================================
    # 5 · LEADS DO APP (não-filiados) — mapa "App leads in Athena" (30/07)
    # -----------------------------------------------------------------
    # Retrato de hoje da fl_usuario_nao_filiado_atual (secao 's5_leads', carimbo no último mês do pipeline):
    # leads puros (nunca filiaram) por recência de login × cartão digital; mornos (≤90 d) × cashback; quadrante de
    # score comportamental; desfiliados por recência + motivo. E a conversão pós-cadastro por coorte (s1_funil).
    # =================================================================
    with _ap_tabs[4]:
        S = 's5_leads'
        _L5 = _apd[_apd['secao'] == S] if not _apd.empty else pd.DataFrame(columns=_AP_COLS)
        _REC_LBL = {'a_ate7d': '≤ 7 d', 'b_8_30d': '8–30 d', 'c_31_90d': '31–90 d', 'd_91_180d': '91–180 d',
                    'e_181_365d': '181–365 d', 'f_mais365d': '> 365 d', 'g_nunca': 'nunca logou'}
        _REC_ORD = ['a_ate7d', 'b_8_30d', 'c_31_90d', 'd_91_180d', 'e_181_365d', 'f_mais365d', 'g_nunca']
        if _L5.empty:
            st.warning("⚠️ A seção `s5_leads` ainda não existe em `alex_app_dash_mes`. Rode `gt7 run app_dash --arg only=s5` "
                       "e recarregue os dados.")
        else:
            _st5 = _L5['mes'].max()

            def _v5(dim, met='n'):
                d = _L5[(_L5['mes'] == _st5) & (_L5['dim'] == dim) & (_L5['metrica'] == met)]
                return float(d['valor'].sum()) if not d.empty else 0.0

            _nf = _L5[(_L5['mes'] == _st5) & (_L5['dim'].str.startswith('nf:')) & (_L5['metrica'] == 'n')].copy()
            _nf[['rec', 'cartao']] = _nf['dim'].str[3:].str.split('|', n=1, expand=True)
            _tot_nf = float(_nf['valor'].sum())
            _login90 = float(_nf[_nf['rec'].isin(['a_ate7d', 'b_8_30d', 'c_31_90d'])]['valor'].sum())
            _wm = {seg: {m: _v5(f'warm:{seg}', m) for m in ('n', 'transacoes', 'cashback')}
                   for seg in ('cartao_sim|cash_sim', 'cartao_sim|cash_nao', 'cartao_nao|cash_sim', 'cartao_nao|cash_nao')}
            _cash_n = _wm['cartao_sim|cash_sim']['n'] + _wm['cartao_nao|cash_sim']['n']
            _cash_v = _wm['cartao_sim|cash_sim']['cashback'] + _wm['cartao_nao|cash_sim']['cashback']
            _df5 = _L5[(_L5['mes'] == _st5) & (_L5['dim'].str.startswith('desf:')) & (_L5['metrica'] == 'n')].copy()
            _df5['rec'] = _df5['dim'].str[5:]
            _tot_desf = float(_df5['valor'].sum())
            _desf90 = float(_df5[_df5['rec'].isin(['a_ate7d', 'b_8_30d', 'c_31_90d'])]['valor'].sum())

            st.caption(f"Retrato de **{pd.Timestamp(_st5):%m/%Y}** (última carga do pipeline) da base do app fora do "
                       "quadro de filiados (`fl_usuario_nao_filiado_atual`). **Lead puro** = cadastrou o app e nunca "
                       "foi cliente; **desfiliado** = já foi cliente (dt_filiacao preenchida). O HubSpot diz de onde o "
                       "lead veio; esta base diz o que ele FEZ depois — login, cartão digital, cashback.")
            k1, k2, k3, k4 = st.columns(4)
            _tv_kpi(k1, "🌡️", "Leads puros (nunca filiaram)", _tv_n(_tot_nf),
                    f"{_tv_pct(_login90, _tot_nf)} abriram o app nos últimos 90 d")
            _tv_kpi(k2, "🔥", "Mornos: login ≤ 90 d", _tv_n(_login90),
                    f"alcançáveis agora · {_tv_n(_v5('warm:cartao_sim|cash_sim') + _v5('warm:cartao_sim|cash_nao'))} com cartão ativado", color="#2e8a4f")
            _tv_kpi(k3, "💳", "Mornos já transacionando cashback", _tv_n(_cash_n),
                    f"R$ {format_br(_cash_v)} em cashback — usam o benefício sem pagar: a lista de upsell mais limpa", color="#b45309")
            _tv_kpi(k4, "🚪", "Desfiliados na base do app", _tv_n(_tot_desf),
                    f"{_tv_n(_desf90)} ainda abriram o app em 90 d — win-back com o app instalado", color="#0f172a")

            st.markdown("---")
            # ---- (a) recência × cartão ----
            _tv_titulo("Onde os leads do app estão — por recência do último login",
                       "leads puros; a recência é o termômetro: quem nunca logou é falha de onboarding, quem esfriou é nutrição", "A")
            _da5 = _nf.copy()
            _da5['x'] = _da5['rec'].map(_REC_LBL)
            _da5['serie'] = _da5['cartao'].map({'cartao_sim': 'Ativou o cartão digital', 'cartao_nao': 'Nunca ativou'})
            _da5['rotulo'] = _da5['valor'].map(_tv_fmt_k)
            fig = px.bar(_da5, x='x', y='valor', color='serie', barmode='group', text='rotulo',
                         category_orders={'x': [_REC_LBL[r] for r in _REC_ORD],
                                          'serie': ['Ativou o cartão digital', 'Nunca ativou']},
                         color_discrete_map={'Ativou o cartão digital': '#166534', 'Nunca ativou': '#b45309'},
                         template='cdt_a' if _CDT_THEME else 'plotly_white')
            fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
            fig.update_layout(height=360, xaxis_title='', yaxis_title='leads', legend_title_text='', bargap=0.25)
            st.plotly_chart(fig, use_container_width=True)
            _tv_fonte("Athena: fl_usuario_nao_filiado_atual (dt_ultimo_login_app · dt_ativacao_pl · dt_filiacao IS NULL)")
            _nunca_card = _v5('nf:g_nunca|cartao_sim')
            st.caption(f"Quem **nunca logou** ({_tv_n(float(_nf[_nf['rec'] == 'g_nunca']['valor'].sum()))}) é um problema "
                       f"diferente de quem esfriou: só {_tv_n(_nunca_card)} deles ativaram o cartão — baixaram, cadastraram "
                       "e pararam. Isso é falha de onboarding (medir contra a campanha que os trouxe), não oportunidade de nutrição.")

            st.markdown("---")
            # ---- quadrante ----
            _tv_titulo("Quadrante de score comportamental — cartão digital × login em 90 dias",
                       "o gt7_score do HubSpot não enxerga nada depois da captura; estes dois sinais separam os leads que convertem", "A")
            _q = {('sim', 'sim'): float(_nf[(_nf['cartao'] == 'cartao_sim') & (_nf['rec'].isin(['a_ate7d', 'b_8_30d', 'c_31_90d']))]['valor'].sum()),
                  ('sim', 'nao'): float(_nf[(_nf['cartao'] == 'cartao_sim') & (~_nf['rec'].isin(['a_ate7d', 'b_8_30d', 'c_31_90d']))]['valor'].sum()),
                  ('nao', 'sim'): float(_nf[(_nf['cartao'] == 'cartao_nao') & (_nf['rec'].isin(['a_ate7d', 'b_8_30d', 'c_31_90d']))]['valor'].sum()),
                  ('nao', 'nao'): float(_nf[(_nf['cartao'] == 'cartao_nao') & (~_nf['rec'].isin(['a_ate7d', 'b_8_30d', 'c_31_90d']))]['valor'].sum())}
            _qc1, _qc2 = st.columns(2)
            for _col, _cart, _t in [(_qc1, 'sim', '💳 Cartão ativado'), (_qc2, 'nao', 'Sem cartão')]:
                with _col:
                    for _lg, _lt in [('sim', 'login ≤ 90 d'), ('nao', 'sem login em 90 d')]:
                        _n = _q[(_cart, _lg)]
                        _top = _cart == 'sim' and _lg == 'sim'
                        st.markdown(
                            f"<div style='border:2px solid {'#166534' if _top else '#e2e8f0'};border-radius:12px;"
                            f"padding:12px 16px;margin-bottom:8px;background:{'#ecfdf5' if _top else '#fff'};'>"
                            f"<div style='font-size:12px;color:#64748b;font-weight:600;'>{_t} · {_lt}</div>"
                            f"<div style='font-size:22px;font-weight:800;color:#0f172a;'>{_tv_n(_n)}"
                            f" <span style='font-size:12px;color:#64748b;font-weight:600;'>{_tv_pct(_n, _tot_nf)} dos leads puros</span></div>"
                            + ("<div style='font-size:11px;color:#166534;font-weight:700;'>quadrante de maior conversão — "
                               "priorizar no score e nas réguas</div>" if _top else "") + "</div>", unsafe_allow_html=True)
            st.caption("Quatro sinais comportamentais duros que o CRM não tem: onboarding concluído (flg_onboarding — morto "
                       "desde out/25, não usar), cartão digital ativado, recência de login e cashback transacionado. Leads com "
                       "cartão + login em 90 d convertem a taxas visivelmente diferentes dos sem nada.")

            st.markdown("---")
            _cw1, _cw2 = st.columns(2)
            with _cw1:
                # ---- mornos × cashback ----
                _tv_titulo("Os mornos (login ≤ 90 d) — cartão × cashback",
                           "quem já transaciona cashback usa o benefício sem pagar a mensalidade", "A")
                _rows_w = []
                for seg, lbl in [('cartao_sim|cash_sim', 'Cartão + cashback'), ('cartao_sim|cash_nao', 'Cartão, sem cashback'),
                                 ('cartao_nao|cash_sim', 'Cashback, sem cartão'), ('cartao_nao|cash_nao', 'Nenhum dos dois')]:
                    _rows_w.append({'seg': lbl, 'n': _wm[seg]['n'], 'cash': _wm[seg]['cashback']})
                _dw = pd.DataFrame(_rows_w).sort_values('n', ascending=True)
                _dw['rotulo'] = _dw.apply(lambda r: f"{_tv_fmt_k(r['n'])}" + (f"  (R$ {_tv_fmt_k(r['cash'])})" if r['cash'] else ""), axis=1)
                fig = px.bar(_dw, x='n', y='seg', orientation='h', text='rotulo',
                             color_discrete_sequence=['#166534'], template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
                fig.update_layout(height=300, xaxis_title='', yaxis_title='', showlegend=False,
                                  margin=dict(l=10, r=90, t=8, b=28), yaxis=dict(automargin=True, side='left', showgrid=False))
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("fl_usuario_nao_filiado_atual × fl_cashback (flg_cashback = 1) · entre parênteses, cashback acumulado")
            with _cw2:
                # ---- desfiliados ----
                _tv_titulo("Desfiliados com o app instalado — por recência de login",
                           "ex-clientes na mesma base; win-back com o app na mão é outra campanha", "A")
                _dd5 = _df5.copy()
                _dd5['x'] = _dd5['rec'].map(_REC_LBL)
                _dd5['rotulo'] = _dd5['valor'].map(_tv_fmt_k)
                fig = px.bar(_dd5, x='x', y='valor', text='rotulo',
                             category_orders={'x': [_REC_LBL[r] for r in _REC_ORD]},
                             color_discrete_sequence=['#0f172a'], template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
                fig.update_layout(height=300, xaxis_title='', yaxis_title='', showlegend=False, margin=dict(t=8, b=28))
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("fl_usuario_nao_filiado_atual (dt_filiacao NOT NULL) · histórico completo: franquia, forma de "
                          "pagamento e motivo via fl_filiado")
            _mot = _L5[(_L5['mes'] == _st5) & (_L5['dim'].str.startswith('desf_motivo:')) & (_L5['metrica'] == 'n')].copy()
            if not _mot.empty:
                _mot['motivo'] = _mot['dim'].str[12:]
                _mot = _mot.sort_values('valor', ascending=False)
                _tm = float(_mot['valor'].sum())
                with st.expander(f"Motivo de desfiliação dos {_tv_n(_desf90)} desfiliados ativos em 90 d (top {len(_mot)})"):
                    st.dataframe(pd.DataFrame({'Motivo': _mot['motivo'], 'Ex-clientes': _mot['valor'].map(format_br),
                                               '%': (_mot['valor'] / _tm * 100).map(lambda v: f"{v:.1f}%".replace('.', ','))}),
                                 use_container_width=True, hide_index=True)

            st.markdown("---")
            # ---- conversão pós-cadastro por coorte (dados do s1_funil) ----
            _tv_titulo("Conversão pós-cadastro em 90 dias — coortes mensais",
                       "dos que cadastraram o app SEM comprar no dia, % que filiou em até 90 dias; isola a contribuição própria "
                       "do app da venda de balcão", "B")
            _cf = _apd[(_apd['secao'] == 's1_funil') & (_apd['dim'] == 'app')
                       & (_apd['metrica'].isin(['cadastros_freemium', 'freemium_conv_90d']))]
            if _cf.empty:
                st.caption("sem dados do funil (s1).")
            else:
                _cp = _cf.pivot_table(index='mes', columns='metrica', values='valor', aggfunc='sum').reset_index()
                _cp = _cp[_cp['cadastros_freemium'] > 0].sort_values('mes')
                _cp['pct'] = _cp['freemium_conv_90d'] / _cp['cadastros_freemium'] * 100
                _hoje5 = pd.Timestamp(reference_date)
                _cp['madura'] = _cp['mes'] <= _hoje5 - pd.DateOffset(days=90)
                _cpm = _cp[_cp['madura']]
                if not _cpm.empty:
                    fig = px.line(_cpm.assign(x=_cpm['mes'].map(_ap_mes_lbl)), x='x', y='pct', markers=True,
                                  text=_cpm['pct'].map(lambda v: f"{v:.1f}%".replace('.', ',')),
                                  color_discrete_sequence=['#166534'], template='cdt_b' if _CDT_THEME else 'plotly_white')
                    fig.update_traces(line_width=2.5, marker_size=7, textposition='top center', textfont_size=10,
                                      mode='lines+markers+text')
                    _ylo5, _yhi5 = float(_cpm['pct'].min()), float(_cpm['pct'].max())
                    fig.update_layout(height=320, xaxis_title='', yaxis_title='', showlegend=False, margin=dict(l=45, r=40))
                    fig.update_yaxes(ticksuffix='%', range=[max(0, _ylo5 - 4), _yhi5 + 4])
                    st.plotly_chart(fig, use_container_width=True)
                    _tv_fonte("s1_funil: freemium_conv_90d ÷ cadastros_freemium por mês de cadastro · coortes com menos de "
                              "90 dias ficam fora (imaturas)")
                    st.caption("A oscilação é real e grande (o estudo mediu 11,5% em fev/26 contra 25,4% em abr/26 — mais de "
                               "2×): é esta a métrica para pôr contra o gasto de campanha, porque tira da conta a venda no ato. "
                               "Meses de pico de volume tendem a puxar a taxa para baixo (volume × qualidade).")
                else:
                    st.caption("nenhuma coorte com 90 dias completos ainda.")

    # =================================================================
    # 6 · USO × CONVERSÃO × LTV — correlações (s6_free_uso, s6_cli_uso) e cruzamentos do LTV (s4_ltv)
    # -----------------------------------------------------------------
    # (a) freemium: conversão por uso ANTES de converter, nos 30 primeiros dias (a régua 3,5× do estudo de 20/08,
    #     agora com o denominador certo: toda a coorte, convertida ou não);
    # (b) clientes: retenção/adimplência no mês 3 e 5 por produto usado nos 60 primeiros dias;
    # (c) LTV cruzado: tipo de venda × entrada no app, e por promoção (voucher) onde a base alcança.
    # =================================================================
    with _ap_tabs[5]:
        _F6 = _apd[_apd['secao'] == 's6_free_uso'] if not _apd.empty else pd.DataFrame(columns=_AP_COLS)
        _C6 = _apd[_apd['secao'] == 's6_cli_uso'] if not _apd.empty else pd.DataFrame(columns=_AP_COLS)
        _USO_LBL = {'a_farmacia': 'Cashback de farmácia', 'b_outros': 'Cashback de outros parceiros',
                    'c_farmacia_e_outros': 'Farmácia + outros', 'd_so_cartao': 'Só ativou o cartão',
                    'e_nenhum': 'Nenhum uso'}
        _USO_ORD = ['a_farmacia', 'c_farmacia_e_outros', 'b_outros', 'd_so_cartao', 'e_nenhum']
        if _F6.empty and _C6.empty:
            st.warning("⚠️ As seções `s6_*` ainda não existem em `alex_app_dash_mes`. Rode `gt7 run app_dash --arg only=s6` "
                       "e recarregue os dados.")
        else:
            st.caption("Duas perguntas de causa e efeito, com as coortes certas: **o que o freemium precisa fazer para "
                       "virar cliente** e **o que o cliente precisa usar para continuar pagando**. O uso é sempre medido "
                       "ANTES do desfecho (para o freemium, só o que ele fez antes de filiar) — senão o número mede "
                       "consequência, não causa.")
            # ---------- (a) freemium ----------
            _j6 = st.radio("Coortes de cadastro:", ["3 meses", "12 meses"], index=1, horizontal=True, key='t7_s6_jan')
            _n6 = 3 if _j6.startswith("3") else 12
            _hoje6 = pd.Timestamp(reference_date)
            _mF = [m for m in sorted(_F6['mes'].dropna().unique()) if pd.Timestamp(m) <= _hoje6 - pd.DateOffset(days=90)]
            _mF = _mF[-_n6:]
            _sub6 = (f"coortes de cadastro {_ap_mes_lbl(_mF[0])}–{_ap_mes_lbl(_mF[-1])} (só as que já completaram 90 dias)"
                     if _mF else "sem coortes maduras")
            _tv_titulo("Freemium → cliente: conversão por uso nos 30 primeiros dias", _sub6, "A")
            if not _mF:
                st.caption("nenhuma coorte com 90 dias completos.")
            else:
                _fd = _F6[_F6['mes'].isin(_mF)].copy()
                _fd['uso'] = _fd['dim'].str[4:]
                _pv6 = _fd.pivot_table(index='uso', columns='metrica', values='valor', aggfunc='sum').fillna(0)
                _pv6 = _pv6.reindex([u for u in _USO_ORD if u in _pv6.index])
                _base90 = (float(_pv6.loc['e_nenhum', 'conv_90d']) / float(_pv6.loc['e_nenhum', 'n'])
                           if 'e_nenhum' in _pv6.index and float(_pv6.loc['e_nenhum', 'n']) else None)
                _rows6 = []
                for u, r in _pv6.iterrows():
                    n = float(r['n'])
                    if n <= 0:
                        continue
                    for met, lbl in [('conv_30d', 'em 30 dias'), ('conv_90d', 'em 90 dias')]:
                        _rows6.append({'grupo': _USO_LBL.get(u, u), 'serie': lbl, 'pct': float(r[met]) / n * 100, 'n': n})
                _d6c = pd.DataFrame(_rows6)
                _d6c['rotulo'] = _d6c['pct'].map(lambda v: f"{v:.1f}%".replace('.', ','))
                fig = px.bar(_d6c, x='grupo', y='pct', color='serie', barmode='group', text='rotulo',
                             category_orders={'grupo': [_USO_LBL[u] for u in _USO_ORD if u in _pv6.index],
                                              'serie': ['em 30 dias', 'em 90 dias']},
                             color_discrete_map={'em 30 dias': '#8cc79e', 'em 90 dias': '#166534'},
                             template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
                fig.update_layout(height=380, xaxis_title='', yaxis_title='da coorte que converteu', legend_title_text='',
                                  bargap=0.28)
                fig.update_yaxes(ticksuffix='%')
                if _base90:
                    fig.add_hline(y=_base90 * 100, line_dash='dot', line_color='#b45309',
                                  annotation_text=f"linha de base (nenhum uso, 90 d): {_base90 * 100:.1f}%".replace('.', ','),
                                  annotation_position='top right', annotation_font_size=10.5)
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("Athena: fl_plano_usuario (coorte de freemium) × fl_cashback (cashin, exceto cashback de adesão) × "
                          "1ª filiação por CPF · uso contado só ANTES da filiação")
                _t6 = []
                for u, r in _pv6.iterrows():
                    n = float(r['n'])
                    _lift = (float(r['conv_90d']) / n / _base90) if (_base90 and n) else None
                    _t6.append({'Uso nos 30 primeiros dias': _USO_LBL.get(u, u), 'Freemiums': format_br(n),
                                '% da coorte': _tv_pct(n, float(_pv6['n'].sum())),
                                'Converteu em 30 d': _tv_pct(r['conv_30d'], n), 'Em 90 d': _tv_pct(r['conv_90d'], n),
                                'Até hoje': _tv_pct(r['conv_total'], n),
                                'vs quem não usou nada (90 d)': ("—" if not _lift else f"{_lift:.1f}×".replace('.', ','))})
                with st.expander("Tabela — conversão por uso prévio"):
                    st.dataframe(pd.DataFrame(_t6), use_container_width=True, hide_index=True)
                    st.caption("'Até hoje' tem horizonte aberto (coortes antigas tiveram mais tempo) — compare pelas colunas "
                               "de 30 e 90 dias. O cartão virtual sozinho não separa nada: fica na linha de base. Cashback de "
                               "farmácia é o único sinal forte, e é acionável no primeiro mês.")

            st.markdown("---")
            # ---------- (b) clientes ----------
            _tv_titulo("Cliente: retenção por produto usado nos 60 primeiros dias",
                       "% da coorte de venda ainda pagando (definição C: até 1 mês de atraso) no mês 3 e no mês 5", "A")
            _mC = [m for m in sorted(_C6['mes'].dropna().unique()) if pd.Timestamp(m) <= _hoje6 - pd.DateOffset(months=6)]
            _mC = _mC[-_n6:]
            if not _mC:
                st.caption("nenhuma coorte de venda com 6 meses completos.")
            else:
                _cd = _C6[_C6['mes'].isin(_mC)].copy()
                _cd['prod'] = _cd['dim'].str[5:]
                _pc6 = _cd.pivot_table(index='prod', columns='metrica', values='valor', aggfunc='sum').fillna(0)
                _pc6 = _pc6[_pc6['n'] >= 500].sort_values('n', ascending=False)
                _rows7 = []
                for prod, r in _pc6.iterrows():
                    n = float(r['n'])
                    for met, lbl in [('ret_m3_C', 'mês 3'), ('ret_m5_C', 'mês 5')]:
                        _rows7.append({'grupo': prod.title() if prod not in ('NENHUM USO', 'QUALQUER PRODUTO') else prod.capitalize(),
                                       'serie': lbl, 'pct': float(r[met]) / n * 100, 'n': n})
                _d7c = pd.DataFrame(_rows7)
                _ordp7 = list(dict.fromkeys(_d7c[_d7c['serie'] == 'mês 5'].sort_values('pct', ascending=False)['grupo']))
                _d7c['rotulo'] = _d7c['pct'].map(lambda v: f"{v:.1f}%".replace('.', ','))
                fig = px.bar(_d7c, x='grupo', y='pct', color='serie', barmode='group', text='rotulo',
                             category_orders={'grupo': _ordp7, 'serie': ['mês 3', 'mês 5']},
                             color_discrete_map={'mês 3': '#8cc79e', 'mês 5': '#166534'},
                             template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='outside', textfont_size=10, cliponaxis=False)
                fig.update_layout(height=380, xaxis_title='', yaxis_title='ainda pagando', legend_title_text='', bargap=0.28)
                fig.update_yaxes(ticksuffix='%', range=[0, 100])
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte(f"Athena: fl_filiado (coortes de venda {_ap_mes_lbl(_mC[0])}–{_ap_mes_lbl(_mC[-1])}, titulares) × "
                          "fl_utilizacao_filiado (60 primeiros dias) × fl_nominal_qca_qcd")
                _nen = _pc6.loc['NENHUM USO'] if 'NENHUM USO' in _pc6.index else None
                _qq = _pc6.loc['QUALQUER PRODUTO'] if 'QUALQUER PRODUTO' in _pc6.index else None
                if _nen is not None and _qq is not None:
                    _d3 = (float(_qq['ret_m3_C']) / float(_qq['n']) - float(_nen['ret_m3_C']) / float(_nen['n'])) * 100
                    _d5 = (float(_qq['ret_m5_C']) / float(_qq['n']) - float(_nen['ret_m5_C']) / float(_nen['n'])) * 100
                    st.caption(f"Usar **qualquer** produto nos 2 primeiros meses vale **+{_d3:.1f} p.p.** de retenção no mês 3 "
                               f"e **+{_d5:.1f} p.p.** no mês 5 — e a diferença abre com o tempo. Um CPF entra em todos os "
                               "produtos que usou, então as barras não somam 100%.".replace('.', ','))
                with st.expander("Tabela — retenção e adimplência por produto"):
                    _t7 = []
                    for prod, r in _pc6.iterrows():
                        n = float(r['n'])
                        _t7.append({'Produto usado (60 d)': prod, 'Clientes': format_br(n),
                                    'Mês 3 · A (contrato ativo)': _tv_pct(r.get('ret_m3_A'), n),
                                    'Mês 3 · C (até 1 mês atraso)': _tv_pct(r.get('ret_m3_C'), n),
                                    'Mês 3 · B (sem atraso)': _tv_pct(r.get('ret_m3_B'), n),
                                    'Mês 5 · C': _tv_pct(r.get('ret_m5_C'), n)})
                    st.dataframe(pd.DataFrame(_t7), use_container_width=True, hide_index=True)
                    st.caption("A distância entre A e B é a inadimplência do grupo: produto usado também prediz pagar em dia, "
                               "não só continuar no contrato.")

            st.markdown("---")
            # ---------- (c) LTV cruzado: tipo × entrada, e promoção ----------
            _tv_titulo("LTV cruzado — tipo de venda × entrada no app",
                       "LTV na janela de 3 meses, pelas últimas coortes completas; cada célula é um cruzamento", "A")
            if _L4.empty or _ref_max is None:
                st.caption("sem s4_ltv — rode `gt7 run app_dash --arg only=s4`.")
            else:
                _el3 = _s4_ult_coortes(3)
                _tipos6 = sorted({d[9:].split('|')[0] for d in _L4['dim'].unique() if str(d).startswith('tipo_ent:')})
                _cells = []
                for t in _tipos6:
                    for g in _ENT_ORD:
                        v, n, r, _ = _s4_ltv(f'tipo_ent:{t}|{g}', 3, _def4, _el3)
                        if v is not None and n >= 200:
                            _cells.append({'tipo': t, 'entrada': _ENT_LBL[g], 'ltv': v, 'n': n})
                _dm = pd.DataFrame(_cells)
                if _dm.empty:
                    st.caption("sem cruzamentos com volume suficiente (n ≥ 200) na janela.")
                else:
                    _piv = _dm.pivot(index='tipo', columns='entrada', values='ltv')
                    _piv = _piv.reindex(columns=[_ENT_LBL[g] for g in _ENT_ORD if _ENT_LBL[g] in _piv.columns])
                    _piv = _piv.loc[_dm.groupby('tipo')['n'].sum().sort_values(ascending=False).index]
                    _pn = _dm.pivot(index='tipo', columns='entrada', values='n').reindex(index=_piv.index, columns=_piv.columns)
                    fig = px.imshow(_piv, text_auto=False, aspect='auto', color_continuous_scale=['#fee2e2', '#fef9c3', '#166534'],
                                    template='cdt_a' if _CDT_THEME else 'plotly_white')
                    fig.update_traces(text=_piv.map(lambda v: "" if pd.isna(v) else _s4_brl(v, 0).replace('R$ ', '')),
                                      texttemplate='%{text}', textfont_size=10.5,
                                      customdata=_pn.values,
                                      hovertemplate='%{y} · %{x}<br>LTV R$ %{z:,.2f} · n %{customdata:,.0f}<extra></extra>')
                    fig.update_layout(height=max(320, 38 * len(_piv) + 120), xaxis_title='', yaxis_title='',
                                      coloraxis_colorbar=dict(title=dict(text='LTV 3m', side='right'), tickprefix='R$ ',
                                                              thickness=12, len=0.85, x=1.02),
                                      margin=dict(l=8, r=150, t=58, b=10))
                    fig.update_xaxes(side='top', automargin=True, tickangle=0, showgrid=False)
                    fig.update_yaxes(side='left', automargin=True, showgrid=False, tickfont=dict(size=11, color='#0f172a'))
                    st.plotly_chart(fig, use_container_width=True)
                    _tv_fonte(f"coortes {_s4_rng(_el3)} · {_DEF_LBL[_def4]} (o seletor da sub-aba 4 vale aqui) · células com "
                              "menos de 200 clientes ficam vazias")
                    st.caption("Leitura: dentro de uma mesma linha (tipo de venda), a variação entre colunas é o efeito do app; "
                               "entre linhas, o efeito do canal. Onde as duas coisas se somam é onde vale investir.")

                _promos = sorted({d[6:] for d in _L4['dim'].unique() if str(d).startswith('promo:')})
                _vrm = _L4[(_L4['dim'] == 'painel') & (_L4['metrica'] == 'voucher_ref_max_idx')]['valor']
                if _promos:
                    _vr = int(_vrm.max()) if not _vrm.empty and pd.notna(_vrm.max()) else None
                    _vr_lbl = (f"{(_vr - 1) % 12 + 1:02d}/{(_vr - 1) // 12}" if _vr else "—")
                    st.markdown("---")
                    _tv_titulo("LTV e inadimplência por promoção (voucher da mensalidade)",
                               f"base de voucher (fl_contagem_filiados_v2) vai até {_vr_lbl}; o último mês costuma vir parcial", "A")
                    _rp = []
                    _elp = [m for m in _s4_eleg(_todas4, 3) if not _vr or _s4_idx(m) <= _vr]
                    _elp = _elp[-_NCO:]
                    for pr in _promos:
                        row = {'promo': pr}
                        for dk in ['A', 'C', 'B']:
                            v, n, r, _ = _s4_ltv(f'promo:{pr}', 3, dk, _elp)
                            row[f'ltv_{dk}'] = v
                            row['n'] = n
                        _rp.append(row)
                    _dp6 = pd.DataFrame(_rp).dropna(subset=['ltv_A'])
                    _dp6 = _dp6[_dp6['n'] >= 200].sort_values('ltv_B', ascending=True)
                    if _dp6.empty:
                        st.caption("sem coortes com voucher e janela de 3 meses completa.")
                    else:
                        _dl = _dp6.melt(id_vars=['promo', 'n'], value_vars=['ltv_A', 'ltv_C', 'ltv_B'],
                                        var_name='defn', value_name='ltv')
                        _dl['defn'] = _dl['defn'].str[4:].map(_DEF_LBL)
                        _dl['rotulo'] = _dl['ltv'].map(lambda v: _s4_brl(v, 0).replace('R$ ', ''))
                        fig = px.bar(_dl, x='ltv', y='promo', color='defn', orientation='h', barmode='group', text='rotulo',
                                     category_orders={'defn': [_DEF_LBL[k] for k in ['A', 'C', 'B']]},
                                     color_discrete_map={_DEF_LBL['A']: '#166534', _DEF_LBL['C']: '#57a86f', _DEF_LBL['B']: '#b45309'},
                                     template='cdt_a' if _CDT_THEME else 'plotly_white')
                        fig.update_traces(textposition='outside', textfont_size=10, cliponaxis=False)
                        fig.update_layout(height=max(320, 60 * len(_dp6) + 90), xaxis_title='', yaxis_title='',
                                          legend_title_text='', margin=dict(l=8, r=70),
                                          yaxis=dict(automargin=True, side='left', showgrid=False))
                        fig.update_xaxes(tickprefix='R$ ')
                        st.plotly_chart(fig, use_container_width=True)
                        _tv_fonte(f"coortes {_s4_rng(_elp)} · LTV de 3 meses · A→B mede a inadimplência de cada promoção")
                        _t8p = []
                        for _, r in _dp6.sort_values('n', ascending=False).iterrows():
                            _perda = ((r['ltv_A'] - r['ltv_B']) / r['ltv_A'] * 100) if r['ltv_A'] else None
                            _t8p.append({'Promoção (voucher da mensalidade)': r['promo'], 'Clientes': _tv_fmt_k(r['n']),
                                         'LTV 3m · A': _s4_brl(r['ltv_A']), 'LTV 3m · C': _s4_brl(r['ltv_C']),
                                         'LTV 3m · B': _s4_brl(r['ltv_B']),
                                         'Perdido A → B': ("—" if _perda is None else f"{_perda:.1f}%".replace('.', ','))})
                        with st.expander("Tabela — LTV por promoção e perda para inadimplência"):
                            st.dataframe(pd.DataFrame(_t8p), use_container_width=True, hide_index=True)
                            st.caption("'(fora da base de voucher)' = venda que não casou com a fl_contagem_filiados_v2 no mês "
                                       "(a tabela está incompleta desde 2026/04) — não é 'sem desconto'. O LTV aqui é bruto, "
                                       "antes do desconto concedido: uma promoção com LTV parecido custou mais para chegar lá.")

# =====================================================================
# TAB 8: CRM — WhatsApp/SMS da Instância Aquisição: gasto por disparo × vendas GA4 × CPA
# ---------------------------------------------------------------------
# Réplica viva do estudo "CRM WhatsApp — Agosto vs Julho 2026 · dias 1–15" (18/08), generalizada:
# mês atual × mês anterior, alinhados pelo dia do mês, em buckets semanais (1–7 · 8–14 · 15–21 · 22–fim).
# Fontes: alex_zenvia_template_status (custo por disparo; recarregada da planilha Ad Sources & Events pela
# pipeline `gt7 run zenvia_sheet_load`) e alex_crm_wpp_sms_vendas / _leads (GA4, campanhas CRM wpp/sms).
# Disparo da Aquisição = template com 'GT7' no nome (GT7 - AQUI…, AQUI - GT7…, GT7 - Contato sem sucesso) —
# regra validada contra o estudo: ago 1–15 = R$ 12.783,04 exato; jul 1–15 = R$ 17.238,40 (estudo: 17.351,36).
# Reaproveita helpers das abas 6/7 (_tv_kpi, _tv_titulo, _tv_fonte, format_br, cquery) — vem depois delas.
# =====================================================================


with tab8:
    st.markdown("## CRM — WhatsApp/SMS da Instância Aquisição")
    _c8, _c8_err = load_crm_cpa()
    if _c8_err:
        st.error(f"⚠️ Falha ao ler as tabelas do CRM: `{_c8_err}`")
    elif _c8.empty:
        st.warning("⚠️ Sem dados: rode `gt7 run zenvia_sheet_load` (recarrega alex_zenvia_template_status da planilha) "
                   "e confira alex_crm_wpp_sms_vendas/leads.")
    else:
        _CRIT_BD = "Critério da planilha BD_CRM (padrão)"
        _CRIT_OLD = "Recorte antigo do dashboard"
        _crit8 = st.radio("Critério dos números:", [_CRIT_BD, _CRIT_OLD], index=0, horizontal=True, key='t8_crit',
                          help="Padrão: disparos Enviada/Entregue/Lida × R$ 0,32 (exclui 'Não Entregue') e vendas GA4 com "
                               "sessionSourceMedium contendo mkt_direto — 100% fonte própria, mesma régua da Mesa. "
                               "Recorte antigo: custo cobrado pela Zenvia (inclui 'Não Entregue') e vendas GA4 só das "
                               "campanhas com 'crm' no nome.")
        if _crit8 == _CRIT_BD:
            _c8['gasto'] = _c8['gasto_bd']
            _c8['vendas'] = _c8['vendas_ga']
            st.caption("**100% fonte própria, régua da Mesa**: investimento = disparos Enviada/Entregue/Lida × R$ 0,32 "
                       "(API Zenvia, exclui 'Não Entregue'); vendas = GA4 com `sessionSourceMedium` contendo "
                       "**mkt_direto** (`alex_crm_wpp_sms_vendas`). Validado contra a BD_CRM_V2: ago/26 = 1.152 vendas "
                       "e custo diário idêntico (o dia 31/08 está zerado só LÁ). Sem dependência de preenchimento manual. "
                       "**Não confundir** com o bloco 'CRM & Mensageria' da aba 💰 Investimento: lá é a mensageria da empresa inteira "
                       "(todos os remetentes, ~R$ 300 mil/mês, 90% relacionamento/engajamento com a base, cobrado pela Zenvia); aqui é "
                       "só a Instância de Aquisição (templates GT7) na régua da BD_CRM — a ponte entre os dois está naquele bloco.")
        else:
            _c8['gasto'] = _c8['gasto_zenvia']
            _c8['vendas'] = _c8['vendas_crm']
            st.caption("Recorte antigo: custo cobrado pela Zenvia (inclui 'Não Entregue', que é cobrada) e vendas GA4 "
                       "só das campanhas com 'crm' no nome — por definição, gasto maior e vendas menores que o padrão.")
        _c8m = sorted({pd.Timestamp(d).to_period('M').to_timestamp() for d in _c8[_c8['gasto'] > 0]['dia']}, reverse=True)
        _c8_ult = _c8[_c8['gasto'] > 0]['dia'].max()
        if pd.notna(_c8_ult) and (pd.Timestamp(reference_date) - pd.Timestamp(_c8_ult)).days > 7:
            st.warning(f"⚠️ O custo (Zenvia) está carregado só até **{pd.Timestamp(_c8_ult):%d/%m/%Y}** — o import "
                       "automático da planilha *Ad Sources & Events* quebrou em ago/26 e a recarga é manual. O seletor "
                       "de mês só lista meses **com custo dos templates GT7** (a convenção de nome 'GT7' começou em "
                       "jul/2025 — por isso não há meses anteriores). Para atualizar: preencher a planilha e rodar "
                       "`gt7 run zenvia_sheet_load`.")
        _cc1, _cc2, _cc3 = st.columns([1, 1, 1.6])
        with _cc1:
            _m_atu = st.selectbox("Mês:", _c8m, index=0, format_func=_ap_mes_lbl, key='t8_mes')
        with _cc2:
            _m_ant_def = _m_atu - pd.DateOffset(months=1)
            _outros = [m for m in _c8m if m != _m_atu]
            _m_ant = st.selectbox("Comparar com:", _outros,
                                  index=next((i for i, m in enumerate(_outros) if m == _m_ant_def), 0),
                                  format_func=_ap_mes_lbl, key='t8_mes_ant')
        _da = _c8[(_c8['dia'] >= _m_atu) & (_c8['dia'] < _m_atu + pd.DateOffset(months=1))].copy()
        _dp = _c8[(_c8['dia'] >= _m_ant) & (_c8['dia'] < _m_ant + pd.DateOffset(months=1))].copy()
        _dlim = int(_da[_da['gasto'] > 0]['dia'].dt.day.max()) if (_da['gasto'] > 0).any() else int(_da['dia'].dt.day.max() or 0)
        with _cc3:
            st.markdown(f"<div style='padding-top:30px;font-size:12.5px;color:#64748b;'>Recorte comparável: "
                        f"<b>dias 1–{_dlim}</b> nos dois meses (último dia com disparo em {_ap_mes_lbl(_m_atu)}).</div>",
                        unsafe_allow_html=True)
        _da, _dp = _da[_da['dia'].dt.day <= _dlim], _dp[_dp['dia'].dt.day <= _dlim]

        def _kpis(d):
            g, v, l = float(d['gasto'].sum()), float(d['vendas'].sum()), float(d['leads'].sum())
            return g, v, l, (g / v if v else None), (g / l if l else None)

        _ga, _va, _la, _cpa_a, _cpl_a = _kpis(_da)
        _gp, _vp, _lp, _cpa_p, _cpl_p = _kpis(_dp)
        _lbl_a, _lbl_p = _ap_mes_lbl(_m_atu), _ap_mes_lbl(_m_ant)
        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "💸", f"Valor gasto — {_lbl_a} 1–{_dlim}", f"{format_money(_ga)} {_tv_delta(_ga, _gp)}",
                f"{_lbl_p} 1–{_dlim}: {format_money(_gp)} · disparos GT7 (Aquisição)")
        _tv_kpi(k2, "🛒", f"Vendas — {_lbl_a} 1–{_dlim}", f"{format_br(_va)} {_tv_delta(_va, _vp)}",
                f"{_lbl_p} 1–{_dlim}: {format_br(_vp)} · GA4, campanhas CRM wpp/sms", color="#2e8a4f")
        _chip_cpa = ""
        if _cpa_a and _cpa_p:
            _dd = (_cpa_a - _cpa_p) / _cpa_p * 100
            _bgc, _fgc = ("#dcfce7", "#15803d") if _dd < 0 else ("#fee2e2", "#b91c1c")
            _chip_cpa = (f"<span style='background:{_bgc};color:{_fgc};font-weight:700;font-size:11.5px;"
                         f"padding:2px 8px;border-radius:10px;white-space:nowrap;'>{'+' if _dd > 0 else ''}{_dd:.0f}%</span>")
        _tv_kpi(k3, "🎯", f"CPA — {_lbl_a} 1–{_dlim}", (f"{format_money(_cpa_a)} " if _cpa_a else "— ") + _chip_cpa,
                f"{_lbl_p} 1–{_dlim}: {format_money(_cpa_p) if _cpa_p else '—'} · gasto ÷ vendas (verde = CPA caiu)",
                color="#0f172a")
        _tv_kpi(k4, "🧲", f"Leads e CPL — {_lbl_a} 1–{_dlim}", f"{format_br(_la)} · {format_money(_cpl_a) if _cpl_a else '—'}",
                f"{_lbl_p} 1–{_dlim}: {format_br(_lp)} · {format_money(_cpl_p) if _cpl_p else '—'} · leads GA4 CRM",
                color="#b45309")

        _BUCKETS = [("Sem 1", 1, 7), ("Sem 2", 8, 14), ("Sem 3", 15, 21), ("Sem 4", 22, 31)]

        def _bucket_df(metrica):
            rows = []
            for nome, d0, d1 in _BUCKETS:
                if d0 > _dlim:
                    continue
                d1e = min(d1, _dlim)
                lbl = f"{nome}<br><span style='font-size:10px'>{d0}–{d1e}" + (" (parcial)" if d1e < d1 else "") + "</span>"
                for serie, dd in [(f"Mês atual ({_lbl_a})", _da), (f"Mês anterior ({_lbl_p})", _dp)]:
                    f = dd[(dd['dia'].dt.day >= d0) & (dd['dia'].dt.day <= d1e)]
                    g, v = float(f['gasto'].sum()), float(f['vendas'].sum())
                    val = {'gasto': g, 'vendas': v, 'cpa': (g / v if v else None)}[metrica]
                    rows.append({'x': lbl, 'serie': serie, 'valor': val})
            return pd.DataFrame(rows)

        _CORES8 = {f"Mês atual ({_lbl_a})": '#166534', f"Mês anterior ({_lbl_p})": '#94a3b8'}
        for _met, _tit, _fmt, _pref in [('gasto', 'Valor gasto (R$)', lambda v: _tv_fmt_k(v), 'R$ '),
                                        ('vendas', 'Vendas', lambda v: format_br(v), ''),
                                        ('cpa', 'CPA — custo por aquisição (R$)', lambda v: f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'), 'R$ ')]:
            _db8 = _bucket_df(_met).dropna(subset=['valor'])
            _tv_titulo(_tit, f"buckets pelo dia do mês, dias 1–{_dlim} nos dois meses", "A")
            if _db8.empty:
                st.caption("sem dados na janela.")
                continue
            _db8['rotulo'] = _db8['valor'].map(_fmt)
            fig = px.bar(_db8, x='x', y='valor', color='serie', barmode='group', text='rotulo',
                         color_discrete_map=_CORES8, template='cdt_a' if _CDT_THEME else 'plotly_white')
            fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
            fig.update_layout(height=330, xaxis_title='', yaxis_title='', legend_title_text='', bargap=0.3,
                              margin=dict(b=52))
            if _pref:
                fig.update_yaxes(tickprefix=_pref)
            st.plotly_chart(fig, use_container_width=True)
        _tv_fonte("alex_zenvia_template_status (custo por disparo; templates com 'GT7' no nome = Instância Aquisição; "
                  "recarga: gt7 run zenvia_sheet_load) × alex_crm_wpp_sms_vendas/leads (GA4)")

        with st.expander("Ver dados em tabela (dia a dia)"):
            _t8 = []
            for _, r in _da.iterrows():
                dd = int(r['dia'].day)
                rp = _dp[_dp['dia'].dt.day == dd]
                _t8.append({'Dia': dd,
                            f'Gasto {_lbl_a}': format_money(r['gasto']), f'Vendas {_lbl_a}': format_br(r['vendas']),
                            f'Gasto {_lbl_p}': format_money(float(rp['gasto'].sum())), f'Vendas {_lbl_p}': format_br(float(rp['vendas'].sum()))})
            st.dataframe(pd.DataFrame(_t8), use_container_width=True, hide_index=True)
        _tv_note(
            "<b>Definições e ressalvas.</b> <b>Gasto</b> = custo por disparo (status × template × dia) dos templates da "
            "Instância Aquisição — regra: nome contém <code>GT7</code> (GT7 - AQUI…, AQUI - GT7…, GT7 - Contato sem "
            "sucesso). Validação contra o estudo de 18/08: ago 1–15 = R$ 12.783,04 exato; jul 1–15 = R$ 17.238,40 "
            "(estudo: R$ 17.351,36 — diferença de R$ 113, um template renomeado). <b>Vendas/Leads</b> = eventos GA4 "
            "atribuídos às campanhas CRM wpp/sms (podem sofrer pequenas revisões retroativas). Picos isolados de CPA "
            "geralmente são testes — ex.: 15/07, teste 'engajamento base lia' (R$ 4.742 num dia, 23 vendas). A tabela "
            "de custo é recarregada da planilha Ad Sources & Events pela pipeline <code>gt7 run zenvia_sheet_load</code> "
            "(o import automático quebrou em ago/26 — rodar após atualizar a planilha).", bg="#fff7ed", icon="⚠️")

        # ---- R28 (15/09): funil de entrega — enviadas → entregues → lidas, por canal (WhatsApp/SMS) e escopo ----
        st.markdown("---")
        _tv_titulo("Funil de entrega dos disparos — enviadas → entregues → lidas",
                   f"mesmo mês, comparação e recorte de dias 1–{_dlim} escolhidos acima · canal pelo nome do template "
                   "('SMS' no nome = SMS; o resto = WhatsApp)", "A")
        _f8, _f8_err = load_crm_funil()
        if _f8_err:
            st.error(f"⚠️ Falha ao ler o funil de disparos: `{_f8_err}`")
        elif _f8.empty:
            st.warning("⚠️ Sem dados em alex_zenvia_template_status para o funil.")
        else:
            _ESC_GT7 = "Instância Aquisição (templates GT7)"
            _ESC_ALL = "Todos os templates (empresa inteira)"
            _fc1, _fc2 = st.columns([1, 1.5])
            with _fc1:
                _can8 = st.radio("Canal:", ["WhatsApp", "SMS", "Total"], index=0, horizontal=True, key='t8_fun_canal',
                                 help="WhatsApp e SMS são separados pelo nome do template. O SMS não tem confirmação de "
                                      "leitura, então o funil dele termina em 'entregues'; em 'Total' a taxa de leitura "
                                      "é calculada só sobre as entregues do WhatsApp.")
            with _fc2:
                _esc8 = st.radio("Escopo:", [_ESC_GT7, _ESC_ALL], index=0, horizontal=True, key='t8_fun_esc',
                                 help="GT7 = templates com 'GT7' no nome (Instância Aquisição, mesmo recorte do custo/CPA "
                                      "acima). Todos = mensageria da empresa inteira (relacionamento, engajamento, outras "
                                      "unidades). No recorte GT7 só houve SMS em jan–abr/2026.")
            _fb = _f8 if _esc8 == _ESC_ALL else _f8[_f8['gt7'] == 1]
            if _can8 != "Total":
                _fb = _fb[_fb['canal'] == _can8]
            _FMET = ['enviadas', 'entregues', 'lidas', 'nao_disparadas', 'custo']

            def _fjan(m):
                return _fb[(_fb['dia'] >= m) & (_fb['dia'] < m + pd.DateOffset(months=1)) & (_fb['dia'].dt.day <= _dlim)]

            def _fsum(f):
                s = {c: float(f[c].sum()) for c in _FMET}
                s['ent_wpp'] = float(f[f['canal'] == 'WhatsApp']['entregues'].sum())   # base da leitura
                return s

            _sa, _sp = _fsum(_fjan(_m_atu)), _fsum(_fjan(_m_ant))
            _sem_leitura = (_can8 == "SMS")
            k1, k2, k3, k4 = st.columns(4)
            _tv_kpi(k1, "📤", f"Enviadas — {_lbl_a} 1–{_dlim}", f"{format_br(_sa['enviadas'])} {_tv_delta(_sa['enviadas'], _sp['enviadas'])}",
                    f"{_lbl_p} 1–{_dlim}: {format_br(_sp['enviadas'])} · + {format_br(_sa['nao_disparadas'])} não disparadas "
                    "(erro / descadastro / pendente)")
            _tv_kpi(k2, "📬", f"Taxa de entrega — {_lbl_a}", f"{_tv_pct(_sa['entregues'], _sa['enviadas'])}",
                    f"{_lbl_p}: {_tv_pct(_sp['entregues'], _sp['enviadas'])} · {format_br(_sa['entregues'])} entregues "
                    "(Entregue + Lida)", color="#2e8a4f")
            if _sem_leitura:
                _tv_kpi(k3, "👀", f"Taxa de leitura — {_lbl_a}", "—", "SMS não tem confirmação de leitura", color="#94a3b8")
            else:
                _tv_kpi(k3, "👀", f"Taxa de leitura — {_lbl_a}", f"{_tv_pct(_sa['lidas'], _sa['ent_wpp'])}",
                        f"{_lbl_p}: {_tv_pct(_sp['lidas'], _sp['ent_wpp'])} · {format_br(_sa['lidas'])} lidas ÷ entregues"
                        + (" do WhatsApp" if _can8 == "Total" else ""), color="#0f172a")
            _tv_kpi(k4, "💸", f"Custo Zenvia — {_lbl_a} 1–{_dlim}", f"{format_money(_sa['custo'])} {_tv_delta(_sa['custo'], _sp['custo'])}",
                    f"{_lbl_p}: {format_money(_sp['custo'])} · "
                    + (f"{format_money(_sa['custo'] / _sa['entregues'])} por entregue" if _sa['entregues'] else "—")
                    + " · custo cobrado (total_cost), não a régua BD_CRM", color="#b45309")

            def _fstages(s):
                return [("📤", "Enviadas", s['enviadas'] or None, "Enviada + Entregue + Lida + Não Entregue (saíram da plataforma)"),
                        ("📬", "Entregues", s['entregues'] or None, "Entregue + Lida (Lida implica entrega)"),
                        ("👀", "Lidas", None if _sem_leitura else (s['lidas'] or None),
                         "SMS não tem confirmação de leitura" if _sem_leitura else
                         ("Lida · seq. sobre TODAS as entregues (inclui SMS); a taxa correta está no KPI" if _can8 == "Total" else "Lida"))]

            _fa1, _fa2 = st.columns(2)
            with _fa1:
                _tv_funil(f"{_can8} · {_lbl_a} 1–{_dlim}", _fstages(_sa), subtitle=_esc8)
            with _fa2:
                _tv_funil(f"{_can8} · {_lbl_p} 1–{_dlim}", _fstages(_sp), subtitle="mês de comparação")

            # ---- série mensal (meses completos): taxas e volume por canal ----
            _fm0 = (_m_atu - pd.DateOffset(months=11)).to_period('M').to_timestamp()
            _fmm = _fb[(_fb['dia'] >= _fm0) & (_fb['dia'] < _m_atu + pd.DateOffset(months=1))].copy()
            _fmm['mes'] = _fmm['dia'].dt.to_period('M').dt.to_timestamp()
            if not _fmm.empty:
                _fg = _fmm.groupby('mes')[['enviadas', 'entregues', 'lidas']].sum()
                _fgw = _fmm[_fmm['canal'] == 'WhatsApp'].groupby('mes')['entregues'].sum().reindex(_fg.index).fillna(0)
                _rows_f = []
                for m, r in _fg.iterrows():
                    _rows_f.append({'mes': m, 'serie': 'Taxa de entrega (% das enviadas)',
                                    'valor': (r['entregues'] / r['enviadas'] * 100) if r['enviadas'] else None})
                    if not _sem_leitura:
                        _rows_f.append({'mes': m, 'serie': 'Taxa de leitura (% das entregues WhatsApp)',
                                        'valor': (r['lidas'] / _fgw[m] * 100) if _fgw[m] else None})
                _dfr = pd.DataFrame(_rows_f).dropna(subset=['valor'])
                _fl1, _fl2 = st.columns(2)
                with _fl1:
                    _tv_linhas_mensal(_dfr, "Taxas mês a mês", pct=True, rotulos=True,
                                      subtitle=f"meses completos, {_can8} · {_esc8}")
                with _fl2:
                    _dfv = _fmm.groupby(['mes', 'canal'], as_index=False)['enviadas'].sum().rename(columns={'canal': 'serie', 'enviadas': 'valor'})
                    _tv_chart_mensal(_dfv, "Enviadas mês a mês", stacked=True, rotulos=True,
                                     subtitle="volume que saiu da plataforma, por canal" if _can8 == "Total" else f"volume que saiu da plataforma · {_can8}")
            _tv_fonte("alex_zenvia_template_status (status final × template × dia; recarga: gt7 run zenvia_sheet_load) · "
                      "canal pelo nome do template · escopo GT7 = nome contém 'GT7'")
            _tv_note(
                "<b>Como ler.</b> Cada mensagem entra uma vez, no seu <b>status final</b> — por isso o funil é cumulativo: "
                "<b>enviadas</b> = Enviada + Entregue + Lida + Não Entregue (tudo que saiu da plataforma); <b>entregues</b> = "
                "Entregue + Lida; <b>lidas</b> = Lida. Erro, Descadastrados e Pendente não saíram (custo zero) e ficam fora "
                "do funil — aparecem como 'não disparadas' no 1º cartão. <b>SMS</b> não tem confirmação de leitura: o funil "
                "dele termina em entregues e, na visão Total, a taxa de leitura usa só as entregues do WhatsApp. "
                "<b>Canal</b> é identificado pelo nome do template (todo template SMS tem zero Lida, o que valida a regra); "
                "no <code>sender_name</code> o SMS só aparece em rótulos compostos ('SMS | CDT Relacionamento - 9713'), "
                "porque divide o sender_id com números de WhatsApp. <b>Custo</b> aqui é o cobrado pela Zenvia "
                "(<code>total_cost</code>: ~R$ 0,32 por WhatsApp, ~R$ 0,06 por SMS) — diferente da régua BD_CRM do topo da "
                "aba, que precifica tudo a R$ 0,32. No recorte GT7 só houve SMS em jan–abr/2026; o SMS corrente "
                "(QualificadoCEP_*_SMS) não tem 'GT7' no nome e só aparece em 'Todos os templates'.", bg="#f8fafc", icon="ℹ️")

# =====================================================================
# TAB 9: SITE — comparação entre períodos (investimento · leads · vendas · CPA · CPL) e mídia × mkt direto
# ---------------------------------------------------------------------
# Lê a agregada mensal `alex_aq_dash_mes` (pipeline `gt7 run aquisicao_dash`): s5_invest (RESUMO_INVESTIMENTO_DIARIO
# por canal|plataforma), s4_ga (funil do checkout no GA4), s6_crm (leads/vendas GA4 das campanhas CRM wpp/sms),
# s1_rma (Leads Únicos do HubSpot) e s3_nominal (vendas por tipo_venda no CTN).
# Três definições de CPL, porque cada área usa uma régua: HubSpot (Leads Únicos), GA (generate_lead) e CTN
# (vol_leads do RESUMO). Reaproveita helpers das abas 6/7.
# =====================================================================
with tab5:
    st.markdown("---")
    st.markdown("## Site — investimento, leads, vendas e custo por resultado")
    _aq, _aq_err = load_aq()
    if _aq_err:
        st.error(f"⚠️ Falha ao ler `alex_aq_dash_mes`: `{_aq_err}`")
    elif _aq.empty:
        st.warning("⚠️ A tabela `alex_aq_dash_mes` ainda não existe ou está vazia. Rode `gt7 run aquisicao_dash` "
                   "(claude-toolkit) e recarregue os dados.")
    else:
        _aq_m = sorted(_aq['mes'].dropna().unique())

        def _aqv(secao, metrica, meses, dim=None, dim_pref=None):
            d = _aq[(_aq['secao'] == secao) & (_aq['metrica'] == metrica) & (_aq['mes'].isin(list(meses)))]
            if dim is not None:
                d = d[d['dim'] == dim]
            if dim_pref is not None:
                d = d[d['dim'].str.startswith(dim_pref)]
            return float(d['valor'].sum()) if not d.empty else 0.0

        def _aqs(secao, metrica, meses, dim=None, dim_pref=None):
            d = _aq[(_aq['secao'] == secao) & (_aq['metrica'] == metrica) & (_aq['mes'].isin(list(meses)))]
            if dim is not None:
                d = d[d['dim'] == dim]
            if dim_pref is not None:
                d = d[d['dim'].str.startswith(dim_pref)]
            return d.groupby('mes', as_index=False)['valor'].sum().sort_values('mes')

        _c9a, _c9b, _c9c = st.columns([1.1, 1.1, 1.2])
        with _c9a:
            _p9 = st.selectbox("Período:", ["Últimos 3 meses", "Últimos 6 meses", "Últimos 12 meses", "Ano atual"],
                               index=1, key='t9_per')
        _fim9 = pd.Timestamp(_aq_m[-1])
        _n9 = {"Últimos 3 meses": 3, "Últimos 6 meses": 6, "Últimos 12 meses": 12}.get(_p9)
        if _n9:
            _mA = [m for m in _aq_m if pd.Timestamp(m) > _fim9 - pd.DateOffset(months=_n9)]
        else:
            _mA = [m for m in _aq_m if pd.Timestamp(m).year == _fim9.year]
        _dur = len(_mA)
        with _c9b:
            _cmp9 = st.selectbox("Comparar com:", [f"{_dur} meses anteriores", "Mesmo período do ano passado"],
                                 index=0, key='t9_cmp')
        if _cmp9.startswith("Mesmo"):
            _mB = [pd.Timestamp(m) - pd.DateOffset(years=1) for m in _mA]
        else:
            _ini = pd.Timestamp(_mA[0])
            _mB = [m for m in _aq_m if _ini - pd.DateOffset(months=_dur) <= pd.Timestamp(m) < _ini]
        _mB = [m for m in _mB if m in list(_aq_m)]
        with _c9c:
            _cl9 = st.radio("Definição de lead (para o CPL):", ["HubSpot", "HubSpot pagos", "GA", "CTN"], index=0, horizontal=True,
                            key='t9_cpl', help="HubSpot = Leads Únicos da instância de Aquisição · HubSpot pagos = Contatos do núcleo "
                                               "criados por canais de mídia paga nacional (Facebook, formulários de LP, Great Pages, WhatsApp "
                                               "Nacional Mídias — a régua da coluna Leads_Pagos_HubSpot da planilha Aquisição | Resumo; o CPL "
                                               "usa só o investimento em campanhas de leads) · GA = evento generate_lead do checkout · "
                                               "CTN = vol_leads do RESUMO_INVESTIMENTO_DIARIO")
            st.caption("ℹ️ **Por que o lead CTN é ~1/3 menor que GA e HubSpot** (jul/26: CTN 59,9 mil · GA 96,7 mil · HubSpot 107,1 mil): "
                       "o `vol_leads` do RESUMO conta só os leads **atribuídos a campanhas de mídia paga** (as sessões com campanha do GA, recortadas para o tráfego pago e abertas por plataforma); o **GA** conta *todos* os eventos `generate_lead` do checkout — pago, orgânico, direto e CRM; e o **HubSpot** conta Contatos criados por *todas* as portas (formulários, WhatsApp, parcerias). "
                       "Não é erro de coleta: são três réguas, do recorte mais estreito ao mais largo — compare cada uma só com ela mesma no tempo.")
        _lbl9A = (f"{_ap_mes_lbl(_mA[0])}–{_ap_mes_lbl(_mA[-1])}" if len(_mA) > 1 else _ap_mes_lbl(_mA[0])) if _mA else "—"
        _lbl9B = (f"{_ap_mes_lbl(_mB[0])}–{_ap_mes_lbl(_mB[-1])}" if len(_mB) > 1 else (_ap_mes_lbl(_mB[0]) if _mB else "—"))

        def _leads(meses):
            if _cl9 == "HubSpot":
                return _aqv('s1_rma', 'leads_unicos', meses, dim='rma')
            if _cl9 == "HubSpot pagos":
                return _aqv('s9_pagos', 'leads_pagos', meses, dim='hs')
            if _cl9 == "GA":
                return _aqv('s4_ga', 'generate_lead', meses, dim='ga')
            return _aqv('s5_invest', 'vol_leads', meses, dim_pref='Website|')

        def _leads_serie(meses):
            if _cl9 == "HubSpot":
                return _aqs('s1_rma', 'leads_unicos', meses, dim='rma')
            if _cl9 == "HubSpot pagos":
                return _aqs('s9_pagos', 'leads_pagos', meses, dim='hs')
            if _cl9 == "GA":
                return _aqs('s4_ga', 'generate_lead', meses, dim='ga')
            return _aqs('s5_invest', 'vol_leads', meses, dim_pref='Website|')

        # CPL: investimento total do Website para as réguas largas; só as campanhas de LEADS para a régua "pagos"
        _inv_cpl = (lambda ms: _aqv('s5_invest', 'leads_custo', ms, dim_pref='Website|')) if _cl9 == "HubSpot pagos" \
                   else (lambda ms: _aqv('s5_invest', 'total', ms, dim_pref='Website|'))
        if _cl9 == "HubSpot pagos" and not _aq[(_aq['secao'] == 's9_pagos')].shape[0]:
            st.info("A seção `s9_pagos` ainda não está em `alex_aq_dash_mes` — rode `gt7 run aquisicao_dash --arg only=s9`.")
        _inv = lambda ms: _aqv('s5_invest', 'total', ms, dim_pref='Website|')
        _inv_s = lambda ms: _aqs('s5_invest', 'total', ms, dim_pref='Website|')
        _vga = lambda ms: _aqv('s4_ga', 'purchase', ms, dim='ga')
        _vga_s = lambda ms: _aqs('s4_ga', 'purchase', ms, dim='ga')
        _vsite = lambda ms: _aqv('s3_nominal', 'vendas', ms, dim='WEBSITE')
        _vsite_s = lambda ms: _aqs('s3_nominal', 'vendas', ms, dim='WEBSITE')

        _iA, _iB = _inv(_mA), _inv(_mB)
        _lA, _lB = _leads(_mA), _leads(_mB)
        _sA, _sB = _vsite(_mA), _vsite(_mB)
        _gA, _gB = _vga(_mA), _vga(_mB)
        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "💸", f"Investimento · {_lbl9A}", f"{format_money(_iA)} {_tv_delta(_iA, _iB)}",
                f"{_lbl9B}: {format_money(_iB)} · mídia paga do canal Website")
        _icA = _inv_cpl(_mA)
        _tv_kpi(k2, "🧲", f"Leads ({_cl9}) · {_lbl9A}", f"{_tv_n(_lA)} {_tv_delta(_lA, _lB)}",
                f"{_lbl9B}: {_tv_n(_lB)} · CPL {format_money(_icA / _lA) if _lA else '—'}"
                + (" (investimento em campanhas de leads)" if _cl9 == "HubSpot pagos" else ""), color="#2e8a4f")
        _tv_kpi(k3, "🛒", f"Vendas WEBSITE (CTN) · {_lbl9A}", f"{_tv_n(_sA)} {_tv_delta(_sA, _sB)}",
                f"{_lbl9B}: {_tv_n(_sB)} · GA purchase: {_tv_n(_gA)}", color="#0f172a")
        _cpaA = _iA / _sA if _sA else None
        _cpaB = _iB / _sB if _sB else None
        _chip9 = ""
        if _cpaA and _cpaB:
            _d9 = (_cpaA - _cpaB) / _cpaB * 100
            _bg9, _fg9 = ("#dcfce7", "#15803d") if _d9 < 0 else ("#fee2e2", "#b91c1c")
            _chip9 = (f"<span style='background:{_bg9};color:{_fg9};font-weight:700;font-size:11.5px;"
                      f"padding:2px 8px;border-radius:10px;'>{'+' if _d9 > 0 else ''}{_d9:.0f}%</span>")
        _tv_kpi(k4, "🎯", f"CPA (invest ÷ vendas CTN) · {_lbl9A}",
                (f"{format_money(_cpaA)} " if _cpaA else "— ") + _chip9,
                f"{_lbl9B}: {format_money(_cpaB) if _cpaB else '—'} · verde = CPA caiu", color="#b45309")

        # ---------- gráfico 1: série mensal da métrica escolhida, dois períodos sobrepostos ----------
        _met9 = st.radio("Métrica dos gráficos:", ["Investimento", "Leads", "Vendas", "CPA", "CPL"], index=0,
                         horizontal=True, key='t9_met')

        def _serie(meses):
            inv = _inv_s(meses).rename(columns={'valor': 'inv'})
            lea = _leads_serie(meses).rename(columns={'valor': 'lead'})
            ven = _vsite_s(meses).rename(columns={'valor': 'venda'})
            d = inv.merge(lea, on='mes', how='outer').merge(ven, on='mes', how='outer').fillna(0).sort_values('mes')
            d['CPA'] = d.apply(lambda r: (r['inv'] / r['venda']) if r['venda'] else None, axis=1)
            d['CPL'] = d.apply(lambda r: (r['inv'] / r['lead']) if r['lead'] else None, axis=1)
            return d.rename(columns={'inv': 'Investimento', 'lead': 'Leads', 'venda': 'Vendas'})

        _dA, _dB = _serie(_mA), _serie(_mB)
        _rows9 = []
        for _d, _per in [(_dA, f"Período atual ({_lbl9A})"), (_dB, f"Comparação ({_lbl9B})")]:
            for i, (_, r) in enumerate(_d.iterrows()):
                _rows9.append({'i': i + 1, 'mes': r['mes'], 'serie': _per, 'valor': r[_met9]})
        _d9c = pd.DataFrame(_rows9).dropna(subset=['valor'])
        _dinheiro = _met9 in ("Investimento", "CPA", "CPL")
        _tv_titulo(f"{_met9} — período atual × comparação",
                   "os dois períodos alinhados pela posição do mês (1º mês do período, 2º…); o rótulo do eixo mostra o "
                   "mês do período atual", "A" if _met9 in ("Investimento", "Leads", "Vendas") else "B")
        if _d9c.empty:
            st.caption("sem dados nos períodos escolhidos.")
        else:
            _xmap = {i + 1: _ap_mes_lbl(m) for i, m in enumerate(_dA['mes'])} if not _dA.empty else {}
            _d9c['x'] = _d9c['i'].map(lambda i: _xmap.get(i, f"mês {i}"))
            _d9c['rotulo'] = _d9c['valor'].map(lambda v: (format_money(v) if _met9 in ("CPA", "CPL") else
                                                         (_tv_fmt_k(v) if _met9 != "Investimento" else "R$ " + _tv_fmt_k(v))))
            _cores9 = {f"Período atual ({_lbl9A})": '#166534', f"Comparação ({_lbl9B})": '#94a3b8'}
            if _met9 in ("Investimento", "Leads", "Vendas"):
                fig = px.bar(_d9c, x='x', y='valor', color='serie', barmode='group', text='rotulo',
                             color_discrete_map=_cores9, template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
            else:
                fig = px.line(_d9c, x='x', y='valor', color='serie', markers=True, text='rotulo',
                              color_discrete_map=_cores9, template='cdt_b' if _CDT_THEME else 'plotly_white')
                fig.update_traces(line_width=2.5, marker_size=7, textposition='top center', textfont_size=10,
                                  mode='lines+markers+text')
            fig.update_layout(height=350, xaxis_title='', yaxis_title='', legend_title_text='', bargap=0.28,
                              margin=dict(r=90))
            if _dinheiro:
                fig.update_yaxes(tickprefix='R$ ')
            st.plotly_chart(fig, use_container_width=True)
            _tv_fonte("RESUMO_INVESTIMENTO_DIARIO (canal Website) · " +
                      {"HubSpot": "HS - Leads Únicos mês", "HubSpot pagos": "hubspot_contacts_raw (núcleo × canais pagos, s9_pagos)",
                       "GA": "alex_ga_checkout_funnel (generate_lead)", "CTN": "vol_leads do RESUMO"}[_cl9] + " · NOMINAL_VENDAS (tipo_venda WEBSITE)")

        # ---------- gráfico 2: plataformas ----------
        _tv_titulo("Por plataforma — período atual × comparação",
                   f"{_met9} por plataforma de mídia do canal Website", "A")
        _plats = sorted({d.split('|')[1] for d in _aq[_aq['secao'] == 's5_invest']['dim'].unique() if d.startswith('Website|')})
        _rows10 = []
        for pl in _plats:
            for meses, per in [(_mA, f"Período atual ({_lbl9A})"), (_mB, f"Comparação ({_lbl9B})")]:
                inv = _aqv('s5_invest', 'total', meses, dim=f'Website|{pl}')
                lea = _aqv('s5_invest', 'vol_leads', meses, dim=f'Website|{pl}')
                ven = _aqv('s5_invest', 'vol_vendas', meses, dim=f'Website|{pl}')
                val = {'Investimento': inv, 'Leads': lea, 'Vendas': ven,
                       'CPA': (inv / ven if ven else None), 'CPL': (inv / lea if lea else None)}[_met9]
                _rows10.append({'plataforma': pl, 'serie': per, 'valor': val})
        _d10 = pd.DataFrame(_rows10).dropna(subset=['valor'])
        if _d10.empty:
            st.caption("sem investimento por plataforma nos períodos.")
        else:
            _ordp = list(_d10[_d10['serie'].str.startswith('Período')].sort_values('valor', ascending=False)['plataforma'])
            _d10['rotulo'] = _d10['valor'].map(lambda v: (format_money(v) if _met9 in ("CPA", "CPL") else _tv_fmt_k(v)))
            fig = px.bar(_d10, x='plataforma', y='valor', color='serie', barmode='group', text='rotulo',
                         category_orders={'plataforma': _ordp}, color_discrete_map=_cores9,
                         template='cdt_a' if _CDT_THEME else 'plotly_white')
            fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
            fig.update_layout(height=340, xaxis_title='', yaxis_title='', legend_title_text='', bargap=0.28)
            if _dinheiro:
                fig.update_yaxes(tickprefix='R$ ')
            st.plotly_chart(fig, use_container_width=True)
            _tv_fonte("RESUMO_INVESTIMENTO_DIARIO · leads/vendas por plataforma são os volumes do próprio RESUMO (CTN), "
                      "não o GA nem o HubSpot")
        with st.expander("Como cada CPL é calculado (e por que eles não batem entre si)"):
            _t9 = []
            for defn, lbl, fonte in [("HubSpot", "Leads Únicos (instância de Aquisição)", "HS - Leads Únicos mês · createdate no mês, canal de origem conhecido"),
                                     ("GA", "generate_lead do checkout", "alex_ga_checkout_funnel (GA4)"),
                                     ("CTN", "vol_leads do RESUMO", "RESUMO_INVESTIMENTO_DIARIO, canal Website")]:
                if defn == "HubSpot":
                    lv = _aqv('s1_rma', 'leads_unicos', _mA, dim='rma')
                elif defn == "GA":
                    lv = _aqv('s4_ga', 'generate_lead', _mA, dim='ga')
                else:
                    lv = _aqv('s5_invest', 'vol_leads', _mA, dim_pref='Website|')
                _t9.append({'Definição': defn, 'O que conta': lbl, 'Leads no período': format_br(lv),
                            'CPL': format_money(_iA / lv) if lv else '—', 'Fonte': fonte})
            st.dataframe(pd.DataFrame(_t9), use_container_width=True, hide_index=True)
            st.caption("O HubSpot conta a pessoa (1 lead por contato criado, todos os canais da instância); o GA conta o "
                       "evento no site (mesma pessoa pode gerar vários); o CTN conta o que a mídia reportou. Escolha uma "
                       "régua e compare sempre com ela — misturar as três é o que faz o CPL 'mudar' sem nada ter mudado.")

        st.markdown("---")
        # ---------- tabela mídia × marketing direto ----------
        _tv_titulo("Vendas de mídia × marketing direto",
                   "mídia = vendas do GA atribuídas às campanhas pagas do checkout · marketing direto = vendas do GA nas "
                   "campanhas de CRM (WhatsApp/SMS) · base = vendas WEBSITE no CTN", "A")
        _rows11 = []
        for meses, per in [(_mA, f"Período atual ({_lbl9A})"), (_mB, f"Comparação ({_lbl9B})")]:
            if not meses:
                continue
            ga_tot = _aqv('s4_ga', 'purchase', meses, dim='ga')
            crm_v = _aqv('s6_crm', 'vendas', meses, dim='crm')
            ctn = _aqv('s3_nominal', 'vendas', meses, dim='WEBSITE')
            midia = max(ga_tot - crm_v, 0)
            _rows11.append({'Período': per, 'Vendas WEBSITE (CTN)': format_br(ctn),
                            'Vendas GA (checkout)': format_br(ga_tot),
                            'Mídia (GA − CRM)': f"{format_br(midia)} · {_tv_pct(midia, ctn)}",
                            'Marketing direto (CRM)': f"{format_br(crm_v)} · {_tv_pct(crm_v, ctn)}",
                            'Mídia + mkt direto': f"{format_br(ga_tot)} · {_tv_pct(ga_tot, ctn)}"})
        st.dataframe(pd.DataFrame(_rows11), use_container_width=True, hide_index=True)
        _tv_fonte("alex_ga_checkout_funnel (purchase) · alex_crm_wpp_sms_vendas (GA4, campanhas CRM) · NOMINAL_VENDAS "
                  "(tipo_venda WEBSITE)")
        _tv_note(
            "<b>Como ler os percentuais.</b> O denominador é a venda do CTN (a que existe no faturamento). "
            "<b>Mídia</b> = tudo que o GA registrou como compra no checkout menos o que ele atribuiu às campanhas de CRM; "
            "<b>marketing direto</b> = o pedaço do CRM (WhatsApp/SMS). A soma das duas raramente dá 100%: o GA perde "
            "sessões (bloqueio de cookie, app, compra que termina no televendas) e o CTN registra vendas que nunca "
            "passaram pelo checkout. Trate a diferença como 'venda sem rastro digital', não como erro.<br><br>"
            "<b>Investimento</b> nesta aba é só o canal <i>Website</i> do RESUMO_INVESTIMENTO_DIARIO (mídia paga; o "
            "App do Filiado tem verba própria e fica fora). O custo do CRM está na aba 📨 CRM.", bg="#f8fafc", icon="ℹ️")

# =====================================================================
# TAB 10: AQUISICAO — funis de leads por superfície e as três views do RMA (Apropriação de Leads)
# ---------------------------------------------------------------------
# Lê `alex_aq_dash_mes` (pipeline `gt7 run aquisicao_dash`): s1_rma (Leads Únicos → Engajamento → Franquias →
# vendas nas franquias, coluna Site do RMA), s1_canal (o mesmo por primeiro_canal_de_origem), s2_super (Escallo
# ativo/receptivo), s4_ga (checkout), s3_nominal (vendas por tipo_venda). O funil do app vem de
# `alex_app_dash_mes` (aba 📱 App) — aqui ele entra lado a lado, sem deduplicar por CPF (ver a nota).
# Definições: claude/definicoes_24-08_apropriacao_leads_rma.md.
# =====================================================================

# --- Leads Únicos por bucket (compartilhado: 🧲 Aquisição e 🧭 Funil Ponta a Ponta; regra em gt7/rules.py) ---
_LU_LBL = {
    'core': 'Núcleo (site, checkout, WhatsApp, mídia)', 'tim': 'Parceria B2B2C - TIM (fora das definições)',
    'franquia_promotor': 'Franquia — ID Promotor', 'franquia_facebook': 'Franquia — Facebook (captação)',
    'franquia_cms': 'Franquia — formulário CMS', 'regional': 'Formulários regionais',
    'ruptura': 'Projeto Ruptura', 'importacao': 'Importação de base',
    'desfiliados': 'Desfiliados em massa', 'engajamento': 'Instância de Engajamento',
    'sem_canal': 'Sem canal registrado',
}
_LU_DEFS = {
    'Abrangente (tudo menos Engajamento e TIM)': ['core', 'importacao', 'desfiliados', 'franquia_cms',
                                            'franquia_promotor', 'franquia_facebook', 'ruptura', 'regional', 'sem_canal'],
    'HubSpot — relatório "Leads Únicos" (347496241)': ['core', 'franquia_cms', 'franquia_promotor',
                                                       'franquia_facebook', 'ruptura', 'regional', 'sem_canal'],
    'RMA antiga (só núcleo)': ['core'],
    'Personalizada': None,
}


def _tv_foto_filme_exemplo(key):
    """R29: exemplo didático fotografia (🧲, régua do relatório mensal) × filme (🧭, coorte seguida até hoje).
    Números inventados e pequenos de propósito — o ponto é a mecânica, não a escala. `key` só diferencia o
    expander entre as abas."""
    with st.expander("📖 Fotografia × filme — um exemplo com 18 leads", expanded=False):
        st.markdown(
            "Imagine **10 pessoas que viraram Lead em agosto**. Ainda em agosto, 6 delas foram enviadas a uma franquia e 2 "
            "compraram. Em **setembro**, mais 3 das 10 foram enviadas e mais 2 compraram. Em setembro também entraram "
            "**8 Leads novos**: 5 foram enviados e 1 comprou dentro do mês.\n\n"
            "A mesma história contada pelas duas réguas:")
        _th = "padding:6px 10px;text-align:right;color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.04em;"
        _td = "padding:6px 10px;text-align:right;"
        _tl = "padding:6px 10px;text-align:left;font-weight:600;color:#0f172a;"
        st.markdown(
            "<div style='border:1px solid #e2e8f0;border-radius:12px;background:#fff;overflow-x:auto;'>"
            "<table style='border-collapse:collapse;width:100%;font-size:12.5px;'>"
            f"<thead><tr><th style='{_th}text-align:left;'>Régua</th><th style='{_th}'>Leads</th>"
            f"<th style='{_th}'>Enviados à franquia</th><th style='{_th}'>Taxa</th><th style='{_th}'>Vendas</th><th style='{_th}'>Taxa</th></tr></thead>"
            "<tbody>"
            f"<tr style='border-top:1px solid #f1f5f9;'><td style='{_tl}'>📷 Fotografia de <b>agosto</b> (🧲)"
            "<div style='font-size:10.5px;color:#94a3b8;font-weight:400;'>o que aconteceu em agosto, de quem quer que seja</div></td>"
            f"<td style='{_td}'>10</td><td style='{_td}'>6</td><td style='{_td}color:#166534;font-weight:700;'>60%</td>"
            f"<td style='{_td}'>2</td><td style='{_td}color:#166534;font-weight:700;'>20%</td></tr>"
            f"<tr style='border-top:1px solid #f1f5f9;'><td style='{_tl}'>📷 Fotografia de <b>setembro</b> (🧲)"
            "<div style='font-size:10.5px;color:#94a3b8;font-weight:400;'>enviados = 3 da coorte de agosto + 5 da de setembro; venda = só leads de setembro que compraram em setembro</div></td>"
            f"<td style='{_td}'>8</td><td style='{_td}'>8</td><td style='{_td}color:#b45309;font-weight:700;'>100%</td>"
            f"<td style='{_td}'>1</td><td style='{_td}color:#166534;font-weight:700;'>12,5%</td></tr>"
            f"<tr style='border-top:1px solid #f1f5f9;'><td style='{_tl}'>🎬 Filme da coorte de <b>agosto</b> (🧭), visto em setembro"
            "<div style='font-size:10.5px;color:#94a3b8;font-weight:400;'>as 10 pessoas de agosto seguidas até hoje, em qualquer data</div></td>"
            f"<td style='{_td}'>10</td><td style='{_td}'>9</td><td style='{_td}color:#166534;font-weight:700;'>90%</td>"
            f"<td style='{_td}'>4</td><td style='{_td}color:#166534;font-weight:700;'>40%</td></tr>"
            f"<tr style='border-top:1px solid #f1f5f9;'><td style='{_tl}'>🎬 Filme da coorte de <b>setembro</b> (🧭), visto em setembro"
            "<div style='font-size:10.5px;color:#94a3b8;font-weight:400;'>ainda maturando — vai crescer nos próximos meses</div></td>"
            f"<td style='{_td}'>8</td><td style='{_td}'>5</td><td style='{_td}color:#166534;font-weight:700;'>62,5%</td>"
            f"<td style='{_td}'>1</td><td style='{_td}color:#166534;font-weight:700;'>12,5%</td></tr>"
            "</tbody></table></div>", unsafe_allow_html=True)
        st.markdown(
            "**O que o exemplo mostra.** (1) Na **fotografia**, o numerador mistura coortes: os 8 enviados de setembro incluem 3 "
            "pessoas que viraram Lead em agosto — por isso a taxa de transbordo pode passar de 100% (e, no dashboard real, de 50%: "
            "os Negócios contados vêm de qualquer origem, inclusive dos promotores, que a regra de Leads Únicos exclui). "
            "(2) No **filme**, a coorte de agosto \"cresce\" com o tempo: 6 → 9 enviados e 2 → 4 vendas conforme os meses passam; "
            "coortes recentes sempre parecem piores porque ainda não maturaram. (3) A fotografia de agosto **não muda** depois de "
            "fechado o mês (é a régua do Relatório Mensal); o filme de agosto muda a cada recarga. (4) As 2 vendas de setembro de "
            "leads de agosto **não aparecem em nenhuma fotografia** com a régua 'venda no mês do lead' — só no filme (ou na linha "
            "*Vendas nas franquias* da Apropriação, que aceita qualquer data ≥ lead).\n\n"
            "**Regra de bolso.** Fotografia (🧲) responde *quanto a operação fez no mês* e bate com o Relatório Mensal; filme (🧭) "
            "responde *o que aconteceu com quem entrou no mês* — taxas de conversão, perdas por etapa e tempos. Os dois estão "
            "certos e nunca vão bater.")


@st.cache_data(ttl=43200)
def load_lu_buckets():
    d = cquery("SELECT mes, bucket, COUNT(*) criados FROM alex_funil_journey GROUP BY 1,2")
    d['mes'] = pd.to_datetime(d['mes'])
    d['criados'] = pd.to_numeric(d['criados'])
    return d


with tab10:
    st.markdown("## Aquisição — funis de leads e apropriação (RMA)")
    st.caption("📌 **O que esta aba responde:** a FOTO operacional do período — quanto entrou e quanto virou venda "
               "em cada superfície (site, app, televendas ativo/receptivo), cada uma medida na própria fonte "
               "(GA4, CTN, Escallo, HubSpot). Para seguir o CAMINHO de cada Lead — esteira de televendas, "
               "transbordo para engajamento, rota de franquias — use a aba 🧭 Funil Ponta a Ponta: lá o grão é a "
               "coorte do mês de criação do Lead, por isso os números não batem 1:1 com os daqui.")
    _tv_chips_legenda(['contato', 'negocio', 'ctn', 'tel', 'tel_ctn', 'ga', 'app', 'foto', 'foto_lead'])
    _aq10, _aq10_err = load_aq()
    if _aq10_err:
        st.error(f"⚠️ Falha ao ler `alex_aq_dash_mes`: `{_aq10_err}`")
    elif _aq10.empty:
        st.warning("⚠️ A tabela `alex_aq_dash_mes` ainda não existe ou está vazia. Rode `gt7 run aquisicao_dash`.")
    else:
        _m10 = sorted(_aq10['mes'].dropna().unique())
        # ---- período: por padrão os MESES TOCADOS pelo período dos Controles Globais (mesma régua das abas 📞 e 📱);
        #      o grão aqui é sempre o mês (lead criado / venda filiada / telefone discado no mês). O toggle desligado
        #      volta à janela fixa (últimos N meses até o último mês carregado). As coortes da aba 🧭 não mudam. ----
        _c10a, _c10b = st.columns([1, 2])
        with _c10a:
            _t10_glob = st.toggle("Seguir o período dos Controles Globais", value=True, key='t10_global',
                                  help="Ligado: meses tocados pelo 'Período de Análise' da barra lateral (grão mensal). "
                                       "Desligado: janela fixa de N meses até o último mês carregado.")
            if not _t10_glob:
                _j10 = st.selectbox("Janela:", ["Mês atual", "Últimos 3 meses", "Últimos 6 meses", "Últimos 12 meses"],
                                    index=1, key='t10_jan')
        if _t10_glob:
            _sel10 = [m for m in _m10 if pd.Timestamp(m) in set(_tv_meses)]
            _t10_fora = not _sel10
            if _t10_fora:
                _sel10 = [_m10[-1]]
            _n10 = len(_sel10)
        else:
            _t10_fora = False
            _n10 = {"Mês atual": 1, "Últimos 3 meses": 3, "Últimos 6 meses": 6, "Últimos 12 meses": 12}[_j10]
            _sel10 = [m for m in _m10 if pd.Timestamp(m) > pd.Timestamp(_m10[-1]) - pd.DateOffset(months=_n10)]
        _prev10 = [m for m in _m10 if pd.Timestamp(_sel10[0]) - pd.DateOffset(months=_n10) <= pd.Timestamp(m) < pd.Timestamp(_sel10[0])]
        _lbl10 = (f"{_ap_mes_lbl(_sel10[0])}–{_ap_mes_lbl(_sel10[-1])}" if len(_sel10) > 1 else _ap_mes_lbl(_sel10[0]))
        _lbl10_p = (_ap_mes_lbl(_prev10[0]) + '–' + _ap_mes_lbl(_prev10[-1])) if len(_prev10) > 1 else (_ap_mes_lbl(_prev10[0]) if _prev10 else '—')
        with _c10b:
            if _t10_glob:
                st.caption(f"Período: **{_lbl10}** — meses tocados pelo período dos Controles Globais (grão mensal) · "
                           f"comparação: **{_lbl10_p}** (os {_n10} meses anteriores). "
                           "Mês corrente = parcial até a última carga. Semanas e dias não se aplicam aqui: o lead é contado "
                           "no mês em que foi criado, a venda no mês da filiação.")
                if _t10_fora:
                    st.info(f"O período dos Controles Globais não toca os meses carregados em `alex_aq_dash_mes` "
                            f"({_ap_mes_lbl(_m10[0])}–{_ap_mes_lbl(_m10[-1])}); mostrando {_lbl10}.")
            else:
                st.caption(f"Janela fixa: **{_lbl10}** · comparação: {_lbl10_p}. "
                           "Ligue o toggle para seguir o período dos Controles Globais.")

        # ---- frescor: cada seção do agregado tem a própria data de cálculo; o mês corrente é parcial até a última carga ----
        _fr10 = _aq10[_aq10['mes'].isin(list(_sel10))].groupby('secao')['atualizado_em'].max()
        _fr_lbl = {'s1_rma': 'Leads/RMA (s1)', 's1_canal': 'Leads por canal (s1)', 's2_super': 'Escallo (s2)', 's3_nominal': 'CTN (s3)',
                   's4_ga': 'GA checkout (s4)', 's5_invest': 'Investimento (s5)', 's6_crm': 'CRM (s6)', 's7_canal': 'Qualidade por canal (s7)',
                   's7_midia': 'Mídia × retenção (s7)', 's8_mesa': 'Funis do relatório (s8)', 's9_pagos': 'Leads pagos (s9)'}
        # Seções MENSAIS: ficam fora da recarga diária (recarga_agregados.ps1 roda only=s1..s6,s8) por custo — s7 consulta o painel
        # do Athena (~5 min) e s9 faz COUNT DISTINCT em 3,6 M Contatos (~4 min). São recalculadas no fechamento do mês
        # (`gt7 run aquisicao_dash --arg only=s7,s9`); por isso não entram no aviso ⏳ de frescor diário, e sim no aviso mensal abaixo.
        _fr_mensal = ('s7_canal', 's7_midia', 's9_pagos')
        if not _fr10.empty:
            _fr_txt = " · ".join(f"{_fr_lbl.get(k, k)} {pd.Timestamp(v):%d/%m %H:%M}" for k, v in _fr10.sort_index().items())
            _fr_old = [(_fr_lbl.get(k, k)) for k, v in _fr10.items() if pd.Timestamp(v).date() < reference_date and k not in _fr_mensal]
            _fr_mes_ini = pd.Timestamp(reference_date).to_period('M').to_timestamp()
            _fr_m_old = sorted({_fr_lbl.get(k, k) for k, v in _fr10.items() if k in _fr_mensal and pd.Timestamp(v) < _fr_mes_ini})
            st.caption(f"🗓️ Agregado `alex_aq_dash_mes` calculado em — {_fr_txt}.")
            if _fr_old and pd.Timestamp(_sel10[-1]) >= pd.Timestamp(reference_date).to_period('M').to_timestamp() - pd.DateOffset(months=1):
                st.warning("⏳ Seções calculadas antes do último dia completo da base (" + ", ".join(_fr_old) + "): o mês corrente — e o "
                           "anterior, se a carga foi antes do fechamento — estão **parciais** nelas. Rode `gt7 run aquisicao_dash` "
                           "(ou `--arg only=s1,s2,s3,s4,s5,s6,s8`) e ♻️ Recarregar dados.")
            if _fr_m_old:
                st.caption("ℹ️ Seções mensais calculadas antes do início do mês corrente (" + ", ".join(_fr_m_old) + "): o mês corrente "
                           "ainda não existe nelas e o anterior pode ter sido calculado antes do fechamento. Recalcular no fechamento do mês: "
                           "`gt7 run aquisicao_dash --arg only=s7,s9` e ♻️ Recarregar dados.")

        with st.expander("📖 Qual visão usar? — os funis desta aba × abas 📞 Televendas, 🧭 Funil Ponta a Ponta e 🌐 Site"):
            st.markdown(
                "Os números **não batem entre abas por desenho**: cada uma responde uma pergunta diferente sobre a mesma base. "
                "Resumo (ago/26 como exemplo):\n\n"
                "| Pergunta | Onde | O que conta | Ago/26 |\n|---|---|---|---|\n"
                "| *Quanto o televendas ativo entregou de filiação?* (relatório mensal) | **🧲 · Funis do relatório** e **Funis por superfície** | leads ATIVO discados no mês (Escallo) que aparecem no NOMINAL **no mesmo mês**, por qualquer porta; abertura do tipo TELEVENDAS | 29.746 → 6.035 → 9.844 (1.137 TV) |\n"
                "| *Como está a operação do discador?* | **📞 Televendas · 1 · Escallo Ativo** | o que o operador registrou: fase de negociação, tabulação 'venda' e a confirmação **dessa tabulação** no CTN na janela do contato + 14 d | 29.746 → 6.035 → 338+342 → 342 → 249 |\n"
                "| *O que aconteceu com os Contatos criados no mês?* (filme da coorte) | **🧭 Funil Ponta a Ponta** | Contatos criados no mês (espelho vivo, buckets) seguidos até hoje: esteira TV, Distribuição, Validador, venda na franquia em qualquer data | coorte: 259k criados · 83k Distribuição · 63k Validador · 32,7k vendas |\n"
                "| *Quanto transbordou e vendeu nas franquias no mês?* (relatório mensal) | **🧲 · Funil Franquias** | Leads Únicos da lista `HS - Leads Únicos mês` (regra do deck) → Negócios com 1ª entrada em Distribuição/Validador **no mês** (qualquer coorte) → CPF do lead × NOMINAL campo **no mês** | 178.494 → 100.583 → 29.717 |\n"
                "| *As três linhas do RMA (coluna Site)* | **🧲 · Apropriação de Leads** | regra RMA (exclui TIM, franquias, regional, ruptura) + seletor de buckets; vendas em qualquer data ≥ lead | 114.862 (regra RMA) |\n"
                "| *Como está o checkout do site, dia a dia?* | **🌐 Site · Funil do checkout** | GA4 por dia no período exato dos Controles Globais; usuários (padrão) ou eventos | 384.609 → 79.132 → 70.915 → 31.883 → 23.161 |\n"
                "| *Checkout no grão mensal, ao lado dos outros canais* | **🧲 · Funis por superfície · Site** | as mesmas colunas de usuários do GA4, somadas por mês | idem quando o período é o mês inteiro |\n\n"
                "**Regras de bolso.** (1) Para o Relatório Mensal de Aquisição e para comparar canais, use a 🧲 — é a régua da Mesa. "
                "(2) Para gerir o televendas (fila, aproveitamento, tabulação), use a 📞: ela conta registros da operação, por isso as "
                "'vendas' lá são menores. (3) Para entender **rota e tempo** de um lead (e perdas por etapa), use a 🧭: ela segue a coorte "
                "até hoje, então os números crescem com a maturação e nunca vão bater com o 'no mês'. (4) Três coisas fazem o mesmo nome "
                "mudar de valor: **população** (lista `HS - Leads Únicos mês` × Contatos vivos por bucket × telefones discados), "
                "**janela** (no mês-calendário × janela do contato + 14 d × qualquer data até hoje) e **frescor** (cada agregado tem a "
                "própria data de cálculo — veja a linha 🗓️ acima e o quadro da aba 📞).")
        _tv_foto_filme_exemplo('t10')

        # --- definição de Leads Únicos = seleção de buckets (mesmo seletor da aba 🧭) ---
        _lu_tab_b = None
        _sel_bk10 = None
        try:
            _lub = load_lu_buckets()
        except Exception:
            _lub = pd.DataFrame()
        _lu_bucket_ok = (not _lub.empty) and all(pd.Timestamp(m) in set(_lub['mes']) for m in _sel10)
        if _lu_bucket_ok:
            _cd1, _cd2 = st.columns([1.2, 2])
            _def10 = _cd1.radio("Definição de **Leads Únicos** (seleção de buckets):",
                                list(_LU_DEFS.keys()), index=0, key='t10_def')
            if _LU_DEFS[_def10] is None:
                _sel_bk10 = _cd2.multiselect("Buckets que contam:", sorted(_lub['bucket'].unique()),
                                             default=[b for b in sorted(_lub['bucket'].unique()) if b not in ('engajamento', 'tim')],
                                             format_func=lambda b: _LU_LBL.get(b, b), key='t10_bk')
            else:
                _sel_bk10 = [b for b in _LU_DEFS[_def10] if b in set(_lub['bucket'])]
                _cd2.caption("Conta: " + " · ".join(_LU_LBL.get(b, b) for b in _sel_bk10) +
                             ". Fonte: canal **na criação** do Contato, espelho vivo (`alex_funil_journey`). "
                             "A composição completa por bucket está na aba 🧭 Funil Ponta a Ponta.")
        else:
            st.caption("ℹ️ O seletor de definição de Leads Únicos cobre coortes de mai/2026 em diante "
                       "(`alex_funil_journey`); nesta janela vale a regra RMA antiga (s1_rma).")

        def _v10(secao, metrica, meses, dim=None):
            d = _aq10[(_aq10['secao'] == secao) & (_aq10['metrica'] == metrica) & (_aq10['mes'].isin(list(meses)))]
            if dim is not None:
                d = d[d['dim'] == dim]
            return float(d['valor'].sum()) if not d.empty else 0.0

        def _s10(secao, metrica, meses, dim=None):
            d = _aq10[(_aq10['secao'] == secao) & (_aq10['metrica'] == metrica) & (_aq10['mes'].isin(list(meses)))]
            if dim is not None:
                d = d[d['dim'] == dim]
            return d.groupby('mes', as_index=False)['valor'].sum().sort_values('mes')

        # ---------- 1 · as três linhas do RMA ----------
        _lu = _v10('s1_rma', 'leads_unicos', _sel10, 'rma')
        _lu_rma = _lu  # regra RMA (s1) — base do % com CPF, mesmo quando _lu vem dos buckets
        _cpf = _v10('s1_rma', 'com_cpf', _sel10, 'rma')
        _eng_cpf = _v10('s1_rma', 'enviados_com_cpf', _sel10, 'rma')
        _eng = _v10('s1_rma', 'enviados_engajamento', _sel10, 'rma')
        _fra = _v10('s1_rma', 'transbordados_franquias', _sel10, 'rma')
        _vf = _v10('s1_rma', 'vendas', _sel10, 'venda_franquia')
        _lu_p = _v10('s1_rma', 'leads_unicos', _prev10, 'rma')
        if _lu_bucket_ok and _sel_bk10:
            _mm10 = [pd.Timestamp(m) for m in _sel10]
            _lu = float(_lub[_lub['mes'].isin(_mm10) & _lub['bucket'].isin(_sel_bk10)]['criados'].sum())
            _lu_tab_b = float(_lub[_lub['mes'].isin(_mm10)]['criados'].sum())
            _pp10 = [pd.Timestamp(m) for m in _prev10]
            if _prev10 and all(m in set(_lub['mes']) for m in _pp10):
                _lu_p = float(_lub[_lub['mes'].isin(_pp10) & _lub['bucket'].isin(_sel_bk10)]['criados'].sum())
            else:
                _lu_p = None
        _eng_p = _v10('s1_rma', 'enviados_engajamento', _prev10, 'rma')
        _fra_p = _v10('s1_rma', 'transbordados_franquias', _prev10, 'rma')
        _vf_p = _v10('s1_rma', 'vendas', _prev10, 'venda_franquia')
        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "🧲", "Leads Únicos", f"{_tv_n(_lu)} {_tv_delta(_lu, _lu_p)}",
                "instância de Aquisição (site, checkout, mídia, WhatsApp)")
        _tv_kpi(k2, "📨", "Encaminhados para engajamento", f"{_tv_n(_eng)} {_tv_delta(_eng, _eng_p)}",
                f"{_tv_pct(_eng, _lu)} dos leads únicos", color="#2e8a4f")
        _tv_kpi(k3, "🏪", "Transbordados para franquias", f"{_tv_n(_fra)} {_tv_delta(_fra, _fra_p)}",
                f"{_tv_pct(_fra, _lu)} dos leads únicos", color="#0f172a")
        _tv_kpi(k4, "🛒", "Vendas nas franquias", f"{_tv_n(_vf)} {_tv_delta(_vf, _vf_p)}",
                f"{_tv_pct(_vf, _lu)} dos leads únicos (conversão do RMA)", color="#b45309")

        _pg = _v10('s9_pagos', 'leads_pagos', _sel10, 'hs'); _pg_p = _v10('s9_pagos', 'leads_pagos', _prev10, 'hs') if _prev10 else 0.0
        _core9 = _v10('s9_pagos', 'leads_core', _sel10, 'hs')
        _inv_leads10 = sum(float(v) for v in _aq10[(_aq10['secao'] == 's5_invest') & (_aq10['metrica'] == 'leads_custo') & (_aq10['dim'].str.startswith('Website|')) & (_aq10['mes'].isin(list(_sel10)))]['valor'])
        if _pg:
            st.caption(f"💳 **Leads pagos (mídia nacional):** {_tv_n(_pg)} {_tv_delta(_pg, _pg_p or None)} — {_tv_pct(_pg, _core9)} dos Contatos do núcleo "
                       f"({_tv_n(_core9)}, `hubspot_contacts_raw`); CPL da mídia de leads = {format_money(_inv_leads10)} ÷ {_tv_n(_pg)} = "
                       f"**{format_money(_inv_leads10 / _pg)}**. Mesma régua da coluna Leads_Pagos_HubSpot da planilha Aquisição | Resumo "
                       "(canais Facebook, formulários de LP, Great Pages, WhatsApp Nacional Mídias — `rules.LEADS_PAGOS_CANAIS`).",
                       unsafe_allow_html=True)
        _lu_tab = _v10('s1_rma', 'leads_tabela', _sel10, 'rma')
        # R29: "Com CPF" saiu da sequência — qualificava a ÚLTIMA etapa (venda = CPF × NOMINAL), não os encaminhados,
        #      que vêm dos Negócios do pipeline Distribuição sem filtro de CPF (a % sequencial passava de 100%).
        # R31: visualização alternativa — diagrama em raias com os mesmos números (toggle desligado = funil com chips)
        _t10_raias = st.toggle("🗺️ Ver como diagrama de raias — onde cada número nasce", value=False, key='t10_raias',
                               help="Alternativa ao funil: as mesmas quatro linhas do RMA desenhadas nas raias Contato / Negócio / CTN, "
                                    "com a lente da fotografia (o mês) em destaque e a do filme (coorte, aba 🧭) esmaecida.")
        if _t10_raias:
            _tv_raias('foto', {'lu': _lu, 'eng': _eng, 'fra': _fra, 'vf': _vf},
                      "Apropriação de Leads — coluna Site do RMA", f"janela {_lbl10}")
        else:
            _tv_funil("Apropriação de Leads — coluna Site do RMA", [
                ("🧲", "Leads Únicos", _lu, "Contatos criados no mês na instância de Aquisição"),
                ("📨", "Encaminhados para engajamento", _eng, "Negócios criados no pipeline CDT - Distribuição (com ou sem CPF)"),
                ("🏪", "Transbordados para franquias", _fra, "entraram em Distribuição de Leads / Validador"),
                ("🛒", "Vendas nas franquias", _vf, "CPF do lead × NOMINAL: porta a porta / link / app do vendedor — só leads com CPF cruzam"),
            ], subtitle=f"janela {_lbl10}",
                chips=[['contato', 'foto'], ['negocio', 'foto'], ['negocio', 'foto'], ['ctn', 'foto_lead']])
        if _lu_rma and _cpf:
            st.caption(f"🆔 **CPF:** {_tv_pct(_cpf, _lu_rma)} dos Leads Únicos (regra RMA, {_tv_n(_cpf)} de {_tv_n(_lu_rma)}) têm `cpf_chave` — "
                       "só esses podem aparecer em *Vendas nas franquias*, porque a venda é casada por CPF com o NOMINAL. "
                       "*Encaminhados* e *Transbordados* contam Negócios e não dependem do CPF"
                       + (f" ({_tv_pct(_eng - _eng_cpf, _eng)} dos encaminhados estão sem CPF e nunca cruzam com venda)" if _eng and _eng_cpf else "")
                       + ".")
        _bruto_cap = _lu_tab_b if _lu_tab_b else _lu_tab
        if _bruto_cap and _lu:
            st.caption(f"Contatos criados na janela: {format_br(_bruto_cap)} — a definição selecionada mantém "
                       f"{_tv_pct(_lu, _bruto_cap)} (o que fica de fora — TIM, importação etc. — está aberto por bucket na "
                       "aba 🧭). **Engajamento e franquias vêm dos Negócios** do pipeline CDT - Distribuição — o espelho "
                       "`hubspot_deals_raw` só cobre bem desde 13/05/2026, então meses anteriores são piso.")
        _mg10 = _sel10 if len(_sel10) > 1 else _m10[-6:]
        _long10 = []
        for met, lbl in [('leads_unicos', 'Leads Únicos'), ('enviados_engajamento', 'Engajamento'),
                         ('transbordados_franquias', 'Franquias')]:
            s = _s10('s1_rma', met, _mg10, 'rma')
            s['serie'] = lbl
            _long10.append(s)
        _sv = _s10('s1_rma', 'vendas', _mg10, 'venda_franquia')
        _sv['serie'] = 'Vendas nas franquias'
        _long10.append(_sv)
        _tv_chart_mensal(pd.concat(_long10), "Série mensal — apropriação de leads", stacked=False, rotulos=True,
                         subtitle="cada linha da tabela do RMA, mês a mês",
                         fonte="HS - Leads Únicos mês (createdate, data de envio ao engajamento, entrada em Distribuição) × NOMINAL_VENDAS")

        with st.expander("📖 Definições exatas (RMA · coluna Site)"):
            st.markdown(
                "| Linha | Objeto | Regra |\n|---|---|---|\n"
                "| **Leads Únicos** | Contatos | `createdate` no mês, canal de origem conhecido e fora de Importação / Base de "
                "Desfiliados / Instância de Engajamento. A contagem oficial é **abrangente + seleção de buckets** (seletor no topo da aba) sobre o canal **na criação**, lida do espelho vivo via `alex_funil_journey`; `HS - Leads Únicos mês` virou legado (congelava o canal). |\n"
                "| **Encaminhados para engajamento** | Contatos ↔ Negócios | tem `data_do_primeiro_envio_para_instancia_de_engajamento` "
                "(espelho no contato do Negócio criado no pipeline CDT - Distribuição). |\n"
                "| **Transbordados para franquias** | Negócios | entrou em `Distribuição de Leads` (1020141703) ou `Validador de "
                "Distribuição` (1020141709). |\n"
                "| **Vendas nas franquias** | fora do HubSpot | CPF do lead × `NOMINAL_VENDAS` com `tipo_venda` ∈ porta a porta / "
                "link do vendedor / app do vendedor, filiação a partir da data do lead; dedupe `COUNT(DISTINCT CPF, DT_FILIACAO)`. |\n\n"
                "**Site aqui é a instância inteira** (site CDT, checkout, formulários de mídia nacional e regional, WhatsApp "
                "Zenvia, parcerias) — não é o filtro `canal_de_origem_detalhada = 'Site CDT - Checkout Adesão'`, que é outra "
                "métrica (Leads Únicos no Checkout). A coluna App do RMA é zero por construção: os leads do app vivem no "
                "Singular/Mais TODOS, fora do CRM — no dashboard eles estão na aba 📱 App.")

        st.markdown("---")
        # ---------- 1b · os dois funis do Relatório Mensal de Aquisição (Mesa) ----------
        _tv_titulo("Funis do Relatório Mensal de Aquisição — Televendas e Franquias",
                   "as mesmas definições dos slides 'Funil Televendas (ligações ativas)' e 'Funil Franquias' do "
                   "relatório da Mesa (fechadas em 10/09/2026); seção s8_mesa do `aquisicao_dash`", "A")
        _mesa = _aq10[_aq10['secao'] == 's8_mesa']
        if _mesa.empty:
            st.warning("⚠️ A seção `s8_mesa` ainda não está em `alex_aq_dash_mes`. Rode `gt7 run aquisicao_dash --arg only=s8` "
                       "e recarregue os dados.")
        else:
            def _m8(metrica, dim, meses=None):
                meses = _sel10 if meses is None else meses
                d = _mesa[(_mesa['dim'] == dim) & (_mesa['metrica'] == metrica) & (_mesa['mes'].isin(list(meses)))]
                return float(d['valor'].sum()) if not d.empty else None

            def _m8_ok(dim, meses):
                """True se TODOS os meses pedidos têm a seção (senão a comparação sai truncada)."""
                d = _mesa[(_mesa['dim'] == dim) & (_mesa['mes'].isin(list(meses)))]
                return bool(meses) and d['mes'].nunique() == len(list(meses))

            # --- televendas (ligações ativas) ---
            _d8 = _m8('discados', 'televendas');      _d8p = _m8('discados', 'televendas', _prev10) if _m8_ok('televendas', _prev10) else None
            _a8 = _m8('alo10', 'televendas');         _a8p = _m8('alo10', 'televendas', _prev10) if _d8p is not None else None
            _n8 = _m8('negociacao_hs', 'televendas'); _n8p = _m8('negociacao_hs', 'televendas', _prev10) if _d8p is not None else None
            _v8 = _m8('vendas_mes', 'televendas');    _v8p = _m8('vendas_mes', 'televendas', _prev10) if _d8p is not None else None
            _t8 = _m8('vendas_mes_tv', 'televendas'); _t8p = _m8('vendas_mes_tv', 'televendas', _prev10) if _d8p is not None else None
            _ap8 = _m8('vendas_apos', 'televendas')
            _g8 = _m8('ganho_hs', 'televendas')
            # R33: fatia dos alôs, visão por Negócio (por lead e por Negócio) — seção s8_mesa (pipeline R33)
            _va8x = _m8('vendas_alo', 'televendas');     _vt8x = _m8('vendas_alo_tv', 'televendas')
            _n8_tv = _m8('negociacao_hs_pipe_tv', 'televendas')
            _r33 = {k: _m8(k, 'televendas') for k in ('com_contato', 'com_negocio', 'com_negocio_tv', 'negociacao_leads', 'ganho_leads',
                                                      'negociacao_leads_venda', 'ganho_leads_venda', 'venda_sem_negocio', 'venda_sem_contato',
                                                      'negociacao_deals', 'ganho_de_negociacao', 'ganho_de_negociacao_mes',
                                                      'negociacao_com_venda', 'negociacao_com_venda_tv', 'ganho_com_venda', 'venda_sem_ganho')}
            _r33_ok = _r33['com_contato'] is not None
            # --- franquias ---
            _lu8 = _m8('leads_unicos_deck', 'franquias'); _lu8p = _m8('leads_unicos_deck', 'franquias', _prev10) if _m8_ok('franquias', _prev10) else None
            _tr8 = _m8('transbordados', 'franquias');     _tr8p = _m8('transbordados', 'franquias', _prev10) if _lu8p is not None else None
            _va8 = _m8('validador', 'franquias')
            _vf8 = _m8('vendas_mes', 'franquias');        _vf8p = _m8('vendas_mes', 'franquias', _prev10) if _lu8p is not None else None
            # R39: numerador restrito aos Contatos da MESMA definição do denominador (regra do relatório, sem promotor/TIM/
            #      Importação/Desfiliados/Engajamento) — métricas *_def do s8 (18/09) + decomposição do que fica de fora.
            _tr8d = _m8('transbordados_def', 'franquias'); _tr8dp = _m8('transbordados_def', 'franquias', _prev10) if _lu8p is not None else None
            _va8d = _m8('validador_def', 'franquias')
            _vf8d = _m8('vendas_mes_def', 'franquias');    _vf8dp = _m8('vendas_mes_def', 'franquias', _prev10) if _lu8p is not None else None
            _ex8 = {k: _m8('transbordados_' + k, 'franquias') for k in ('promotor', 'tim', 'outros_fora', 'sem_lista')}
            _coer_ok = _tr8d is not None
            # o toggle `t10_coer` é desenhado ao lado do funil (mais abaixo), mas os KPIs desta linha precisam do estado agora:
            # session_state guarda o valor do widget da última execução (False na 1ª vez = régua do relatório).
            _t10_coer = bool(st.session_state.get('t10_coer', False)) and _coer_ok
            _trX, _trXp, _vaX, _vfX, _vfXp = (_tr8d, _tr8dp, _va8d, _vf8d, _vf8dp) if _t10_coer else (_tr8, _tr8p, _va8, _vf8, _vf8p)
            _coer_tag = ' · mesma definição' if _t10_coer else ''
            _fr_tot = sum(_v10('s3_nominal', 'vendas', _sel10, t) for t in ('PORTA A PORTA', 'LINK DO VENDEDOR', 'APP DO VENDEDOR'))
            _fr_tot_p = sum(_v10('s3_nominal', 'vendas', _prev10, t) for t in ('PORTA A PORTA', 'LINK DO VENDEDOR', 'APP DO VENDEDOR')) if _prev10 else None
            _tv_ctn = _v10('s3_nominal', 'vendas', _sel10, 'TELEVENDAS')

            _k8 = st.columns(6)
            _tv_kpi(_k8[0], "📵", "Leads ativos discados", f"{_tv_n(_d8)} {_tv_delta(_d8, _d8p)}", "Escallo, tipo ATIVO, 1º contato no mês")
            _tv_kpi(_k8[1], "🛒", "Discados que filiaram no mês", f"{_tv_n(_v8)} {_tv_delta(_v8, _v8p)}",
                    f"{_tv_pct(_v8, _d8)} dos discados · qualquer tipo de venda", color="#2e8a4f")
            _tv_kpi(_k8[2], "📞", "└ com tipo Televendas", f"{_tv_n(_t8)} {_tv_delta(_t8, _t8p)}",
                    f"{_tv_pct(_t8, _v8)} das filiações dos discados · {_tv_pct(_t8, _tv_ctn)} das vendas TELEVENDAS do CTN", color="#b45309")
            _tv_kpi(_k8[3], "🧲", "Leads Únicos (regra do relatório)", f"{_tv_n(_lu8)} {_tv_delta(_lu8, _lu8p)}",
                    "canal conhecido, fora de Importação / Desfiliados / Engajamento / TIM / promotor", color="#0f172a")
            _tv_kpi(_k8[4], "🏪", "Transbordados para franquias", f"{_tv_n(_trX)} {_tv_delta(_trX, _trXp)}",
                    f"{_tv_pct(_trX, _lu8)} dos leads únicos (tx. de transbordo){_coer_tag}", color="#0f172a")
            _tv_kpi(_k8[5], "✅", "Vendas nas franquias (mês do lead)", f"{_tv_n(_vfX)} {_tv_delta(_vfX, _vfXp)}",
                    f"{_tv_pct(_vfX, _trX)} dos transbordados · {_tv_pct(_vfX, _fr_tot)} das vendas das franquias{_coer_tag}", color="#b45309")

            _f8a, _f8b = st.columns(2)
            with _f8a:
                # R33: duas visões da MESMA população (leads ATIVO discados no mês): por telefone (régua do relatório, com a
                #      fatia dos alôs) ou por Negócio (Contato → Negócio → EM NEGOCIAÇÃO → GANHO, vendas do CTN ao lado).
                _t10_neg = st.toggle("🤝 Ver pelo Negócio — Contato → Negócio → negociação → GANHO", value=False, key='t10_neg',
                                     disabled=not _r33_ok,
                                     help="Mesmos leads discados, vistos pelo CRM: quantos têm Contato (telefone), Negócio, entraram em EM "
                                          "NEGOCIAÇÃO e em GANHO no mês; as vendas do CTN ficam como referência ao lado de cada etapa.")
                # R34: escada de atribuição do último degrau (teto → após 1º contato → conversou → piso tipo TELEVENDAS)
                _t10_esc = st.toggle("🪜 Abrir o último degrau — escada de atribuição (teto → piso)", value=False, key='t10_esc',
                                     disabled=(_va8x is None),
                                     help="Abre 'Vendas — discados no NOMINAL' em quatro leituras da mesma população: teto (qualquer "
                                          "filiação do discado, tel-8 × NOMINAL, sem depender do HubSpot), após o 1º contato do mês, "
                                          "conversou (alô ≥ 10 s) e filiou, e piso (tipo_venda = TELEVENDAS, com/sem alô). "
                                          "Teto e piso não se aninham com os alôs: são cortes diferentes da mesma população.")
                if _t10_neg and _r33_ok:
                    _tv_funil("🤝 Funil Televendas — visto pelo Negócio", [
                        ("📵", "Leads ativos discados", _d8, "ESCALLO_LEADS_MES, tipo ATIVO"),
                        ("🧑", "Com Contato no HubSpot", _r33['com_contato'], "tel-8 do lead = telefone/WhatsApp do Contato"),
                        ("🤝", "Com Negócio associado", _r33['com_negocio'], f"Contatos sem Negócio: {_tv_n((_r33['com_contato'] or 0) - (_r33['com_negocio'] or 0))}"),
                        ("📞", "└ Negócio que passou pela esteira (LEAD)", _r33['com_negocio_tv'], "hs_v2_date_entered LEAD preenchida", 2),
                        ("🗣️", "Entraram em EM NEGOCIAÇÃO no mês", _r33['negociacao_leads'], f"com venda no CTN no mês: {_tv_n(_r33['negociacao_leads_venda'])} ({_tv_pct(_r33['negociacao_leads_venda'], _r33['negociacao_leads'])})"),
                        ("🏆", "Entraram em GANHO no mês", _r33['ganho_leads'], f"seq. = % dos leads com Negócio (GANHO não passa necessariamente por negociação) · com venda no CTN: {_tv_n(_r33['ganho_leads_venda'])} ({_tv_pct(_r33['ganho_leads_venda'], _r33['ganho_leads'])})", 2),
                    ], subtitle=_lbl10, chips=[['tel', 'foto'], ['contato', 'foto'], ['negocio', 'foto'], ['negocio', 'foto'], ['negocio', 'foto'], ['negocio', 'foto']])
                    st.caption(f"🪪 **Vendas no CTN da mesma população:** {_tv_n(_v8)} discados filiaram no mês — {_tv_n(_r33['venda_sem_negocio'])} sem "
                               f"Negócio e {_tv_n(_r33['venda_sem_contato'])} sem Contato. **Pelo lado dos Negócios:** {_tv_n(_r33['negociacao_deals'])} entradas em "
                               f"EM NEGOCIAÇÃO no mês (qualquer pipeline atual; {_tv_n(_n8_tv)} ainda no pipeline TV) → {_tv_n(_r33['ganho_de_negociacao'])} foram a GANHO "
                               f"({_tv_n(_r33['ganho_de_negociacao_mes'])} no mês) · {_tv_n(_r33['negociacao_com_venda'])} com venda no CTN no mês "
                               f"({_tv_pct(_r33['negociacao_com_venda'], _r33['negociacao_deals'])}; tipo TELEVENDAS: {_tv_n(_r33['negociacao_com_venda_tv'])}) · "
                               f"GANHO com venda {_tv_n(_r33['ganho_com_venda'])} · **venda sem GANHO {_tv_n(_r33['venda_sem_ganho'])}** — o write-back da "
                               "esteira captura só uma fração das vendas de quem passou por negociação.", unsafe_allow_html=True)
                elif _t10_esc and _va8x is not None:
                    _sem_alo_tv = ((_t8 or 0) - (_vt8x or 0)) if (_t8 is not None and _vt8x is not None) else None
                    _antes8 = ((_v8 or 0) - (_ap8 or 0)) if (_v8 is not None and _ap8 is not None) else None
                    _tv_funil("🪜 Funil Televendas — último degrau aberto (escada de atribuição)", [
                        ("📵", "Leads ativos discados", _d8, "ESCALLO_LEADS_MES, tipo ATIVO"),
                        ("🗣️", "Ligações qualificadas (≥ 10 s)", _a8, "alô humano em alguma ligação do mês"),
                        ("🛒", "Teto — discados que filiaram no mês (qualquer canal)", _v8, "tel-8 × NOMINAL, mesmo mês-calendário; não depende do HubSpot · seq. = % dos discados", 0),
                        ("⏱️", "└ após o 1º contato do mês", _ap8, f"{_tv_n(_antes8)} compraram antes de serem discados · seq. = % do teto", 2),
                        ("🗣️", "└ conversaram (alô ≥ 10 s) e filiaram", _va8x, f"{_tv_pct(_va8x, _a8)} dos alôs · seq. = % do teto", 2),
                        ("📞", "└ Piso — tipo_venda = TELEVENDAS", _t8, f"{_tv_n(_vt8x)} com alô · {_tv_n(_sem_alo_tv)} sem alô ≥ 10 s no mês · seq. = % do teto", 2),
                    ], subtitle=_lbl10, chips=[['tel', 'foto'], ['tel', 'foto'], ['tel_ctn', 'foto'], ['tel_ctn', 'foto'], ['tel_ctn', 'foto'], ['tel_ctn', 'foto']])
                    st.caption(f"🪜 **Escada de atribuição** da mesma população ({_tv_n(_d8)} discados): o **teto** ({_tv_n(_v8)}) é tudo o que o mailing tocou e "
                               f"filiou; **após o 1º contato** ({_tv_n(_ap8)}) tira quem já tinha comprado; **conversou e filiou** ({_tv_n(_va8x)}) é a leitura "
                               f"defensável para CPA; o **piso** ({_tv_n(_t8)}) é o que o vendedor registrou — e {_tv_n(_sem_alo_tv)} dessas não têm alô ≥ 10 s no mês. "
                               "Piso e alôs não se aninham: são dois cortes diferentes do teto.", unsafe_allow_html=True)
                else:
                    _tv_funil("📵 Funil Televendas — pipeline de ligações ativas", [
                        ("📵", "Leads ativos discados", _d8, "ESCALLO_LEADS_MES, tipo ATIVO"),
                        ("🗣️", "Ligações qualificadas (≥ 10 s)", _a8, "alô humano em alguma ligação do mês"),
                        ("🛒", "└ dos alôs: filiaram no mês", _va8x, "fatia dos alôs · tel-8 × NOMINAL, mesmo mês", 1),
                        ("📞", "└ dos alôs: com tipo TELEVENDAS", _vt8x, "seq. = % das filiações dos alôs", 2),
                        ("🛒", "Vendas — discados que aparecem no NOMINAL no mês", _v8, "todos os discados · inner join por tel-8, 1 lead = 1, mesmo mês-calendário · seq. = % dos discados", 0),
                        ("📞", "└ com tipo_venda = TELEVENDAS", _t8, "seq. = % das filiações dos discados", 4),
                    ], subtitle=_lbl10, chips=[['tel', 'foto'], ['tel', 'foto'], ['tel_ctn', 'foto'], ['tel_ctn', 'foto'], ['tel_ctn', 'foto'], ['tel_ctn', 'foto']])
                    _sem_alo = ((_v8 or 0) - (_va8x or 0)) if _va8x is not None else None
                    _sem_alo_b = ((_d8 or 0) - (_a8 or 0)) if _va8x is not None else None
                    st.caption((f"🗣️ **Filiação com alô × sem alô:** {_tv_pct(_va8x, _a8)} dos alôs filiaram no mês contra {_tv_pct(_sem_alo, _sem_alo_b)} "
                                f"de quem não teve alô ≥ 10 s — a régua sobre alôs mede a esteira, a sobre discados mede o mailing. "
                                f"Das {_tv_n(_t8)} filiações com tipo TELEVENDAS, {_tv_n(_vt8x)} são de leads com alô. " if _va8x is not None else "")
                               + f"Indicadores laterais (HubSpot): **{_tv_n(_n8)}** Negócios entraram em EM NEGOCIAÇÃO {_tv_delta(_n8, _n8p)}"
                               + (f" (qualquer pipeline atual; {_tv_n(_n8_tv)} ainda no pipeline TV)" if _n8_tv is not None else "")
                               + f" · **{_tv_n(_g8)}** entraram em GANHO. Filiações após o 1º contato do mês: **{_tv_n(_ap8)}** de {_tv_n(_v8)}. "
                               "A maioria das filiações dos discados fecha fora da esteira do CRM (site, MGM, campo).", unsafe_allow_html=True)
            with _f8b:
                # R39: numerador e denominador com a MESMA definição (toggle). Desligado = régua do Relatório Mensal (transbordados
                #      de qualquer origem sobre Leads Únicos sem promotor/TIM). O caption registra, nos dois estados, quem está
                #      dentro/fora do numerador. O estado (_t10_coer) foi lido de session_state antes dos KPIs.
                st.toggle("⚖️ Mesma definição no numerador — só Negócios de Contatos da regra do relatório", value=False, key='t10_coer',
                          disabled=not _coer_ok,
                          help="Desligado: régua do Relatório Mensal — 'transbordados' conta Negócios do pipeline Distribuição de qualquer origem "
                               "(promotores, TIM, Importação/Desfiliados/Engajamento, Negócios sem Contato na lista), enquanto 'Leads Únicos' "
                               "os exclui. Ligado: transbordados, Validador e vendas restritos aos Contatos que passam na mesma regra dos "
                               "Leads Únicos (KPIs e série mensal acompanham). Precisa do s8 recarregado em/após 18/09.")
                if _t10_coer:
                    _tv_funil("🏪 Funil Franquias — transbordo de leads (mesma definição)", [
                        ("🧲", "Leads Únicos (regra do relatório)", _lu8, "`HS - Leads Únicos mês`, createdate no mês"),
                        ("🏪", "Leads transbordados — Contatos da regra", _tr8d, "Negócios com 1ª entrada em Distribuição / Validador no mês, só de Contatos que passam na regra do relatório"),
                        ("✅", "Vendas nas franquias — Contatos da regra", _vf8d, "CPF do lead (regra do relatório, sem promotor) × NOMINAL campo, filiação no mês do lead"),
                    ], subtitle=_lbl10, chips=[['contato', 'foto'], ['negocio', 'foto'], ['ctn', 'foto']])
                else:
                    _tv_funil("🏪 Funil Franquias — transbordo de leads", [
                        ("🧲", "Leads Únicos (regra do relatório)", _lu8, "`HS - Leads Únicos mês`, createdate no mês"),
                        ("🏪", "Leads transbordados", _tr8, "Negócios com 1ª entrada em Distribuição / Validador no mês (qualquer origem)"),
                        ("✅", "Vendas nas franquias", _vf8, "CPF do lead (regra de abril, com promotores) × NOMINAL campo, filiação no mês do lead"),
                    ], subtitle=_lbl10, chips=[['contato', 'foto'], ['negocio', 'foto'], ['ctn', 'foto']])
                _fora8 = (f"promotores **{_tv_n(_ex8['promotor'])}** · TIM **{_tv_n(_ex8['tim'])}** · outras exclusões da regra (Importação / "
                          f"Desfiliados / Engajamento / sem canal) **{_tv_n(_ex8['outros_fora'])}** · sem Contato na `HS - Leads Únicos mês` "
                          f"**{_tv_n(_ex8['sem_lista'])}**") if _coer_ok else ""
                if _t10_coer:
                    st.caption(f"⚖️ **Numerador restrito à mesma definição:** dos **{_tv_n(_tr8)}** transbordados da régua do relatório, "
                               f"**{_tv_n(_tr8d)}** ({_tv_pct(_tr8d, _tr8)}) são de Contatos que passam na regra dos Leads Únicos. **Ficam de fora:** "
                               f"{_fora8}. Vendas nas franquias pela régua do relatório (com promotores): {_tv_n(_vf8)}; sem eles: **{_tv_n(_vf8d)}**. "
                               f"Entradas no **Validador** (mesma restrição): **{_tv_n(_va8d)}** (todas: {_tv_n(_va8)}). "
                               f"Vendas das franquias no CTN no período: **{_tv_n(_fr_tot)}** — os leads nacionais respondem por "
                               f"**{_tv_pct(_vf8d, _fr_tot)}**" + (f" (período anterior: {_tv_pct(_vf8dp, _fr_tot_p)})" if _vf8dp and _fr_tot_p else "") + ".",
                               unsafe_allow_html=True)
                else:
                    st.caption((f"⚖️ **Régua do Relatório Mensal:** os **{_tv_n(_tr8)}** transbordados incluem Negócios que os Leads Únicos excluem — "
                                f"{_fora8} — por isso a taxa de transbordo sai inflada ({_tv_pct(_tr8d, _lu8)} com a mesma definição, toggle acima). "
                                if _coer_ok else "")
                               + f"Entradas no **Validador** (entrega confirmada à franquia): **{_tv_n(_va8)}**. "
                               f"Vendas das franquias no CTN no período: **{_tv_n(_fr_tot)}** — os leads nacionais respondem por "
                               f"**{_tv_pct(_vf8, _fr_tot)}**" + (f" (período anterior: {_tv_pct(_vf8p, _fr_tot_p)})" if _vf8p and _fr_tot_p else "") + ".",
                               unsafe_allow_html=True)

            # --- abertura por tipo de venda dos discados com venda ---
            _tt8 = _mesa[(_mesa['dim'].str.startswith('tv_tipo|')) & (_mesa['metrica'] == 'vendas_mes') & (_mesa['mes'].isin(list(_sel10)))]
            _c8a, _c8b = st.columns([1.1, 2])
            with _c8a:
                _tv_titulo("Discados com venda — por tipo de venda", f"{_lbl10} · um lead pode ter mais de um tipo", "A")
                if _tt8.empty:
                    st.caption("sem abertura por tipo.")
                else:
                    _gt8 = _tt8.assign(tipo=_tt8['dim'].str.split('|').str[1]).groupby('tipo', as_index=False)['valor'].sum()
                    _gt8 = _gt8.sort_values('valor', ascending=True)
                    _gt8['rotulo'] = _gt8['valor'].map(lambda v: f"{_tv_fmt_k(v)}  ({(v / _v8 * 100 if _v8 else 0):.1f}%)".replace('.', ','))
                    _gt8['cor'] = _gt8['tipo'].map(lambda t: '#b45309' if t == 'TELEVENDAS' else '#166534')
                    fig = px.bar(_gt8, x='valor', y='tipo', orientation='h', text='rotulo',
                                 template='cdt_a' if _CDT_THEME else 'plotly_white')
                    fig.update_traces(marker_color=list(_gt8['cor']), textposition='outside', textfont_size=10.5, cliponaxis=False)
                    fig.update_layout(height=max(240, 26 * len(_gt8) + 60), xaxis_title='', yaxis_title='', showlegend=False,
                                      margin=dict(l=8, r=110, t=8, b=28),
                                      yaxis=dict(automargin=True, showgrid=False, tickfont=dict(size=11)))
                    st.plotly_chart(fig, use_container_width=True)
                    _tv_fonte("ESCALLO_LEADS_MES (ATIVO) × NOMINAL_VENDAS por tel-8, mesmo mês; % sobre os discados com venda")
            with _c8b:
                _mg8 = _m10[-12:]
                _l8 = []
                for met, lbl, dim in [('discados', 'Discados', 'televendas'), ('vendas_mes', 'Discados que filiaram', 'televendas'),
                                      ('vendas_mes_tv', '└ tipo Televendas', 'televendas')]:
                    d = _mesa[(_mesa['dim'] == dim) & (_mesa['metrica'] == met) & (_mesa['mes'].isin(list(_mg8)))]
                    d = d.groupby('mes', as_index=False)['valor'].sum().sort_values('mes'); d['serie'] = lbl
                    _l8.append(d)
                _tv_chart_mensal(pd.concat(_l8), "Série mensal — funil Televendas (ligações ativas)", stacked=False, rotulos=True,
                                 subtitle="últimos 12 meses carregados", fonte="ESCALLO_LEADS_MES × NOMINAL_VENDAS (tel-8, mesmo mês)")
                _l8 = []
                _ser8 = ([('leads_unicos_deck', 'Leads Únicos'), ('transbordados_def', 'Transbordados (mesma definição)'), ('vendas_mes_def', 'Vendas nas franquias (mesma definição)')]
                         if _t10_coer else [('leads_unicos_deck', 'Leads Únicos'), ('transbordados', 'Transbordados'), ('vendas_mes', 'Vendas nas franquias')])  # R39
                for met, lbl in _ser8:
                    d = _mesa[(_mesa['dim'] == 'franquias') & (_mesa['metrica'] == met) & (_mesa['mes'].isin(list(_mg8)))]
                    d = d.groupby('mes', as_index=False)['valor'].sum().sort_values('mes'); d['serie'] = lbl
                    _l8.append(d)
                _tv_chart_mensal(pd.concat(_l8), "Série mensal — funil Franquias" + (" (mesma definição)" if _t10_coer else ""), stacked=False, rotulos=True,
                                 subtitle="últimos 12 meses carregados",
                                 fonte="HS - Leads Únicos mês · hubspot_deals_raw (pipeline CDT - Distribuição) · NOMINAL_VENDAS")

            with st.expander("📖 Definições exatas (slides 'Funil Televendas' e 'Funil Franquias' do relatório da Mesa)"):
                st.markdown(
                    "| Etapa | Objeto | Regra |\n|---|---|---|\n"
                    "| **Leads ativos discados** | telefone | `ESCALLO_LEADS_MES`, `tipo_lead = 'ATIVO'`, mês do 1º contato. |\n"
                    "| **Ligações qualificadas** | telefone | `alo_humano = 1` — falou ≥ 10 s em alguma ligação do mês. |\n"
                    "| **Vendas (discados que filiaram)** | telefone × CPF | *inner join* dos discados do mês com `NOMINAL_VENDAS` do **mesmo mês-calendário**, "
                    "chave tel-8 (`RIGHT(CELULAR, 8) = RIGHT(tel_lead, 8)`; o Escallo não tem CPF), 1 lead contado uma vez. Difere do "
                    "`venda_confirmada` da própria tabela (janela 1º contato → último + 14 d) e do GANHO do HubSpot (write-back da esteira). |\n"
                    "| **└ tipo Televendas** | idem | o subconjunto cuja filiação tem `tipo_venda = 'TELEVENDAS'`; a % sequencial é sobre as filiações dos discados. |\n"
                    "| **└ dos alôs: filiaram no mês** | telefone × CPF | a mesma venda restrita aos leads com `alo_humano = 1` — mede a esteira; a linha de todos os discados mede o mailing (R33). |\n"
                    "| **Negociação (lateral)** | Negócios | entradas em `EM NEGOCIAÇÃO` (961121695) no mês, **sem filtrar o pipeline atual** (R33): 81% dos Negócios que passam "
                    "pela esteira já foram movidos ao pipeline Distribuição e o filtro antigo deixava o número 5× menor; o valor 'ainda no pipeline TV' é a régua antiga. |\n"
                    "| **Visão pelo Negócio (toggle)** | telefone → Contato → Negócio | tel-8 do lead × telefone/WhatsApp do Contato (`alex_tv_contato_tel`) → Negócios associados (`hubspot_assoc_contact_deal`); "
                    "'passou pela esteira' = `hs_v2_date_entered` LEAD preenchida; negociação/GANHO = entrada no mês; venda = o mesmo cruzamento tel-8/CPF × NOMINAL do mês. "
                    "Pelo lado dos Negócios, a venda casa pelo CPF do Negócio ou pelo telefone do Contato. Ressalva: `hs_v2_date_entered_*` guarda a ÚLTIMA entrada. |\n"
                    "| **Leads Únicos (relatório)** | Contatos | `HS - Leads Únicos mês`, `createdate` no mês, canal conhecido e fora de Importação / "
                    "Base de Desfiliados / Instância de Engajamento / `B2B2C - TIM` (fora desde 18/09) / `Franquia - ID Promotor Lead` (regra que reproduzia o deck: jul/26 = 184,3k antes de tirar a TIM). |\n"
                    "| **Leads transbordados** | Negócios | pipeline CDT - Distribuição (697831824), 1ª entrada em `Distribuição de Leads` (1020141703) ou "
                    "`Validador de Distribuição` (1020141709) no mês — `hs_v2_date_entered_*` guarda a ÚLTIMA entrada, então redistribuições reescrevem meses passados. |\n"
                    "| **Vendas nas franquias** | CPF | leads criados no mês (regra de abril, **com** os promotores — são eles que mais viram venda de franquia) × "
                    "`NOMINAL_VENDAS` porta a porta / link / app do vendedor, filiação no mesmo mês; dedupe `COUNT(DISTINCT CPF, DT_FILIACAO)`. |\n"
                    "| **Mesma definição (toggle ⚖️, R39)** | Negócios × Contatos | `transbordados_def` / `validador_def` = os mesmos Negócios, restritos aos que têm "
                    "algum Contato associado que passa na regra dos Leads Únicos (canal conhecido, fora de Importação / Desfiliados / Engajamento / TIM / promotor); "
                    "`vendas_mes_def` = a venda de franquia com a mesma regra (sem promotores). O resto do numerador é decomposto em promotor · TIM · "
                    "outras exclusões · sem Contato na lista (soma = transbordados). Desligado = régua do Relatório Mensal. |\n\n"
                    "**Ressalva do funil de franquias:** na régua do relatório, 'transbordados' conta Negócios de qualquer origem (promotores, TIM, "
                    "Importação/Desfiliados/Engajamento, Negócios sem Contato na lista), enquanto 'Leads Únicos' os exclui — depois de tirar a TIM "
                    "(18/09) a taxa de transbordo passou de 80% em ago/26. O toggle ⚖️ restringe o numerador à mesma definição e o caption registra "
                    "quem entra e quem sai nos dois estados. A leitura por coorte só com os leads "
                    "da regra do relatório está na aba 🧭 Funil Ponta a Ponta (buckets ≠ promotor). Fonte de tudo: seção `s8_mesa` do "
                    "`aquisicao_dash` (`gt7 run aquisicao_dash --arg only=s8`).")

        st.markdown("---")
        # ---------- 2 · funis por superfície ----------
        _tv_titulo("Funis de aquisição por superfície",
                   "cada superfície tem a sua própria definição de 'lead' — os números NÃO são deduplicados entre elas "
                   "(a mesma pessoa pode ser lead no site, no app e no televendas)", "A")
        # R29: um funil por linha — o _tv_funil (rótulo 250 px + barra ≥ 120 px + 2 × 58 px) não cabe em 1/4 da largura
        #      e os quatro se sobrepunham; containers criados em sequência renderizam na ordem Site → Ativo → Receptivo → App.
        _cs1, _cs2, _cs3, _cs4 = st.container(), st.container(), st.container(), st.container()
        # helper: métrica do s8_mesa (régua do relatório) para a janela — None se a seção não cobre a janela
        def _v8s(metrica, dim, meses=None):
            meses = _sel10 if meses is None else meses
            d = _aq10[(_aq10['secao'] == 's8_mesa') & (_aq10['dim'] == dim) & (_aq10['metrica'] == metrica) & (_aq10['mes'].isin(list(meses)))]
            return float(d['valor'].sum()) if not d.empty else None
        _ga_users_ok = not _aq10[(_aq10['secao'] == 's4_ga') & (_aq10['metrica'] == 'purchase_users') & (_aq10['mes'].isin(list(_sel10)))].empty
        with _cs1:
            if _ga_users_ok:
                _tv_funil("🌐 Site — checkout (usuários, régua da aba 🌐)", [
                    ("👥", "Etapa 0 · Usuários ativos (GA)", _v10('s4_ga', 'active_users', _sel10, 'ga'), "activeUsers por dia, somados no mês"),
                    ("📝", "Etapa 1 · Início de checkout", _v10('s4_ga', 'generate_lead_users', _sel10, 'ga'), "generate_lead (usuários)"),
                    ("🚚", "Etapa 2 · Dados de envio", _v10('s4_ga', 'add_shipping_info_users', _sel10, 'ga'), "add_shipping_info (usuários)"),
                    ("💳", "Etapa 3 · Dados de pagamento", _v10('s4_ga', 'add_payment_info_users', _sel10, 'ga'), "add_payment_info (usuários)"),
                    ("🛒", "Etapa 4 · Compra (purchase)", _v10('s4_ga', 'purchase_users', _sel10, 'ga'), "purchase (usuários)"),
                    ("✅", "Vendas WEBSITE (CTN)", _v10('s3_nominal', 'vendas', _sel10, 'WEBSITE'), "tipo_venda WEBSITE no NOMINAL"),
                ], subtitle=_lbl10, chips=[['ga', 'foto'], ['ga', 'foto'], ['ga', 'foto'], ['ga', 'foto'], ['ga', 'foto'], ['ctn', 'foto']])
            else:
                _tv_funil("🌐 Site — checkout (eventos)", [
                    ("👣", "Usuários ativos (GA)", _v10('s4_ga', 'active_users', _sel10, 'ga'), "usuários ativos no checkout"),
                    ("📝", "Início de checkout (eventos)", _v10('s4_ga', 'generate_lead', _sel10, 'ga'), "generate_lead"),
                    ("💳", "Pagamento iniciado (eventos)", _v10('s4_ga', 'add_payment_info', _sel10, 'ga'), "add_payment_info"),
                    ("🛒", "Compras (eventos)", _v10('s4_ga', 'purchase', _sel10, 'ga'), "purchase no checkout"),
                    ("✅", "Vendas WEBSITE (CTN)", _v10('s3_nominal', 'vendas', _sel10, 'WEBSITE'), "tipo_venda WEBSITE no NOMINAL"),
                ], subtitle=_lbl10, chips=[['ga', 'foto'], ['ga', 'foto'], ['ga', 'foto'], ['ga', 'foto'], ['ctn', 'foto']])
                st.caption("ℹ️ Colunas de usuários ainda não carregadas — rode `gt7 run aquisicao_dash --arg only=s4` para ver a mesma régua da aba 🌐.")
            st.caption(f"🧲 Leads Únicos (HubSpot) na janela: **{_tv_n(_lu)}** — ficam fora do funil porque contam Contatos criados por "
                       "todas as portas (formulários, WhatsApp, parcerias), não só o checkout; a comparação certa é com a Etapa 1.")
        with _cs2:
            if _v8s('discados', 'televendas') is not None:
                # R34: com o toggle t10_esc (bloco 1b) ligado, o último degrau abre na escada teto → após 1º contato → alô → piso
                _esc_s = bool(st.session_state.get('t10_esc', False)) and _v8s('vendas_alo', 'televendas') is not None
                _tv_funil("📵 Televendas — Ativo (discador)" + (" · último degrau aberto" if _esc_s else ""), [
                    ("📵", "Leads discados", _v8s('discados', 'televendas'), "ESCALLO_LEADS_MES, tipo ATIVO"),
                    ("🗣️", "Falaram ≥ 10 s", _v8s('alo10', 'televendas'), "alô humano"),
                    ("🛒", "Filiaram no mês (NOMINAL)" + (" — teto" if _esc_s else ""), _v8s('vendas_mes', 'televendas'), "tel-8 × NOMINAL no mesmo mês — régua do relatório", 0),
                ] + ([
                    ("⏱️", "└ após o 1º contato do mês", _v8s('vendas_apos', 'televendas'), "seq. = % do teto", 2),
                    ("🗣️", "└ conversaram (alô ≥ 10 s) e filiaram", _v8s('vendas_alo', 'televendas'), "seq. = % do teto", 2),
                ] if _esc_s else []) + [
                    ("📞", "└ com tipo_venda TELEVENDAS" + (" — piso" if _esc_s else ""), _v8s('vendas_mes_tv', 'televendas'),
                     (f"{_tv_n(_v8s('vendas_alo_tv', 'televendas'))} com alô · seq. = % do teto" if _esc_s else "seq. = % das filiações dos discados"), 2),
                ], subtitle=_lbl10, chips=[['tel', 'foto'], ['tel', 'foto']] + [['tel_ctn', 'foto']] * (4 if _esc_s else 2))
            else:
                _tv_funil("📵 Televendas — Ativo (discador)", [
                    ("📵", "Leads discados", _v10('s2_super', 'leads', _sel10, 'ativo'), "ESCALLO_LEADS_MES, tipo ATIVO"),
                    ("🗣️", "Falaram ≥ 10 s", _v10('s2_super', 'alo10', _sel10, 'ativo'), "alô humano"),
                    ("✅", "Vendas confirmadas no CTN", _v10('s2_super', 'venda_confirmada', _sel10, 'ativo'), "tel-8 × NOMINAL na janela do contato"),
                ], subtitle=_lbl10, chips=[['tel', 'foto'], ['tel', 'foto'], ['tel_ctn', 'foto']])
        with _cs3:
            if _v8s('discados', 'receptivo') is not None:
                _tv_funil("📲 Televendas — Receptivo", [
                    ("📲", "Ligações recebidas", _v8s('discados', 'receptivo'), "ESCALLO_LEADS_MES, tipo RECEPTIVO"),
                    ("🗣️", "Falaram ≥ 10 s", _v8s('alo10', 'receptivo'), "alô humano"),
                    ("🛒", "Filiaram no mês (NOMINAL)", _v8s('vendas_mes', 'receptivo'), "tel-8 × NOMINAL no mesmo mês — régua do relatório"),
                    ("📞", "└ com tipo_venda TELEVENDAS", _v8s('vendas_mes_tv', 'receptivo'), "seq. = % das filiações"),
                ], subtitle=_lbl10, chips=[['tel', 'foto'], ['tel', 'foto'], ['tel_ctn', 'foto'], ['tel_ctn', 'foto']])
            else:
                _tv_funil("📲 Televendas — Receptivo", [
                    ("📲", "Ligações recebidas", _v10('s2_super', 'leads', _sel10, 'receptivo'), "ESCALLO_LEADS_MES, tipo RECEPTIVO"),
                    ("🗣️", "Falaram ≥ 10 s", _v10('s2_super', 'alo10', _sel10, 'receptivo'), "alô humano"),
                    ("✅", "Vendas confirmadas no CTN", _v10('s2_super', 'venda_confirmada', _sel10, 'receptivo'), "tel-8 × NOMINAL na janela do contato"),
                ], subtitle=_lbl10, chips=[['tel', 'foto'], ['tel', 'foto'], ['tel_ctn', 'foto']])
        with _cs4:
            _ap_dl = _ap_dr = _ap_cad = _ap_com = None
            if not _apd.empty:
                _ms_app = [m for m in _sel10 if m in list(_apd['mes'].unique())]
                _ap_dl = _ap_val('s1_funil', 'downloads', meses=_ms_app)
                _ap_cad = _ap_val('s1_funil', 'cadastros', meses=_ms_app)
                _ap_fre = _ap_val('s1_funil', 'cadastros_freemium', meses=_ms_app)
                _ap_com = _ap_val('s1_funil', 'compras_com_app_ate_venda', meses=_ms_app)
                _ap_idpv = _ap_val('s1_funil', 'compras_app_do_filiado', meses=_ms_app)
            _tv_funil("📱 App", [
                ("⬇️", "Downloads (1º login)", _ap_dl, "fl_data_login"),
                ("📝", "Cadastros", _ap_cad, "fl_plano_usuario.dt_criacao"),
                ("🌱", "└ dos cadastros: entraram como freemium", _ap_fre if _ap_dl is not None else None, "fatia de Cadastros: sem filiação anterior · seq. = % dos cadastros", 1),
                ("🛒", "└ dos cadastros: compra junto à venda", _ap_com, "fatia de Cadastros: cadastro até 1 dia após a venda · seq. = % dos cadastros", 1),
                ("✅", "Vendas APP DO FILIADO (CTN)", _v10('s3_nominal', 'vendas', _sel10, 'APP DO FILIADO'), "tipo_venda · seq. = % dos cadastros"),
            ], subtitle=_lbl10, chips=[['app', 'foto'], ['app', 'foto'], ['app', 'foto'], ['app', 'foto'], ['ctn', 'foto']])
        st.caption(f"📞 As vendas **TELEVENDAS (CTN)** da janela — {format_br(_v10('s3_nominal', 'vendas', _sel10, 'TELEVENDAS'))} — "
                   "fecham as duas esteiras juntas: o `tipo_venda` do CTN não separa ligação ativa de receptiva. Os dois funis de "
                   "televendas usam a **mesma régua do relatório** (bloco acima e aba 📞 → nota 🧲): filiou no mês, por qualquer porta; "
                   "a *venda tabulada* e a *confirmada na janela do contato* ficam na aba 📞 (visão da operação). 📱 No app, **freemium** e "
                   "**compra junto à venda** são dois **subconjuntos de Cadastros** — fatias irmãs, não etapas em sequência: a % seq. "
                   "delas (e a de Vendas APP DO FILIADO) é calculada **sobre Cadastros**. ⏳ **Downloads no mês corrente ficam abaixo dos "
                   "Cadastros até a base alcançar:** o 1º login (`fl_data_login`) chega ao lake com dias de atraso, enquanto o cadastro "
                   "(`fl_plano_usuario`) é quase imediato — e ~3/4 dos cadastros nascem no ato da venda, antes do primeiro login. Nos "
                   "meses fechados Downloads > Cadastros.")
        _tv_note(
            "<b>Por que não somamos as três superfícies.</b> Cada uma conta uma coisa: o site conta <i>contato criado</i>, "
            "o televendas conta <i>telefone trabalhado no mês</i> e o app conta <i>cadastro</i>. A mesma pessoa aparece em "
            "duas ou três — somar os topos infla a base. O único denominador comum é a <b>venda no CTN</b>, e é por isso "
            "que os três funis terminam na mesma régua (NOMINAL_VENDAS por tipo_venda). Para o total do período, use o "
            "quadro abaixo.", bg="#f8fafc", icon="ℹ️")

        _tv_titulo("Vendas por tipo (CTN) — o denominador comum", f"janela {_lbl10}", "A")
        _nom10 = _aq10[(_aq10['secao'] == 's3_nominal') & (_aq10['metrica'] == 'vendas') & (_aq10['mes'].isin(_sel10))]
        if not _nom10.empty:
            _g10 = _nom10.groupby('dim', as_index=False)['valor'].sum().sort_values('valor', ascending=True)
            _tot10 = float(_g10['valor'].sum())
            _g10 = _g10[_g10['valor'] / _tot10 >= 0.002]
            _g10['rotulo'] = _g10['valor'].map(lambda v: f"{_tv_fmt_k(v)}  ({v / _tot10 * 100:.1f}%)".replace('.', ','))
            fig = px.bar(_g10, x='valor', y='dim', orientation='h', text='rotulo',
                         color_discrete_sequence=['#166534'], template='cdt_a' if _CDT_THEME else 'plotly_white')
            fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
            fig.update_layout(height=max(300, 28 * len(_g10) + 70), xaxis_title='', yaxis_title='', showlegend=False,
                              margin=dict(l=8, r=110, t=8, b=28),
                              yaxis=dict(automargin=True, side='left', showgrid=False, tickfont=dict(size=11)))
            st.plotly_chart(fig, use_container_width=True)
            _tv_fonte(f"NOMINAL_VENDAS · dedupe COUNT(DISTINCT CPF, DT_FILIACAO) · total {format_br(_tot10)} vendas na janela")

        st.markdown("---")
        # ---------- 3 · canais de origem ----------
        _tv_titulo("Leads Únicos por canal de origem — e o que aconteceu com eles",
                   "primeiro_canal_de_origem do contato; % sobre os leads do próprio canal", "A")
        _can = _aq10[(_aq10['secao'] == 's1_canal') & (_aq10['mes'].isin(_sel10))]
        if _can.empty:
            st.caption("sem abertura por canal (rode `gt7 run aquisicao_dash --arg only=s1`).")
        else:
            _pc = _can.pivot_table(index='dim', columns='metrica', values='valor', aggfunc='sum').fillna(0)
            _pc = _pc.sort_values('leads_unicos', ascending=False)
            _pc = _pc[_pc['leads_unicos'] >= 200]
            _t10 = []
            for canal, r in _pc.iterrows():
                lu = float(r['leads_unicos'])
                _t10.append({'Canal de origem': canal, 'Leads Únicos': format_br(lu),
                             '% do total': _tv_pct(lu, float(_pc['leads_unicos'].sum())),
                             'Com CPF': _tv_pct(r.get('com_cpf'), lu),
                             'Engajamento': _tv_pct(r.get('enviados_engajamento'), lu),
                             'Franquias': _tv_pct(r.get('transbordados_franquias'), lu)})
            st.dataframe(pd.DataFrame(_t10), use_container_width=True, hide_index=True)
            _tv_fonte("HS - Leads Únicos mês · canais com menos de 200 leads na janela ficam fora da tabela")
            st.caption("Leitura: canais com **% Engajamento** alto e **% Franquias** baixo estão parando na régua do "
                       "engajamento; o inverso (Franquias alto, Engajamento ~0) é o Grupo B da Jornada, que vai direto "
                       "para a distribuição. A aba 📞 Televendas → 🔀 Grupos A–D detalha esse roteamento.")

        st.markdown("---")
        # ---------- 4 · qualidade do canal: o membro fica? ----------
        _tv_titulo("Qualidade do canal — o membro fica?",
                   "cada venda atribuída ao canal é seguida no painel do CTN 3 e 6 meses depois da filiação", "A")
        # A retenção só existe para coortes que já completaram 3 meses de painel. Se a janela escolhida for recente
        # demais, a seção alarga sozinha para os últimos 12 meses e avisa — em vez de mostrar um quadro vazio.
        _sel7, _amp7 = _sel10, False
        _b3t = _aq10[(_aq10['secao'] == 's7_canal') & (_aq10['metrica'] == 'base_m3') & (_aq10['dim'] != 'painel')]
        if float(_b3t[_b3t['mes'].isin(_sel7)]['valor'].sum()) < 500:
            _sel7 = [m for m in _m10 if pd.Timestamp(m) > pd.Timestamp(_m10[-1]) - pd.DateOffset(months=12)]
            _amp7 = True
        _q7 = _aq10[(_aq10['secao'] == 's7_canal') & (_aq10['mes'].isin(_sel7)) & (_aq10['dim'] != 'painel')]
        _lbl7 = (f"{_ap_mes_lbl(_sel7[0])}–{_ap_mes_lbl(_sel7[-1])}" if len(_sel7) > 1 else _ap_mes_lbl(_sel7[0]))
        if _amp7 and not _q7.empty:
            st.caption(f"↔️ A janela **{_lbl10}** ainda não tem coortes com 3 meses de painel, então esta seção usa "
                       f"**{_lbl7}**. O relógio da retenção começa na filiação: uma venda de junho só entra no m3 "
                       "quando a referência de setembro fechar.")
        if _q7.empty:
            st.caption("sem dados de retenção por canal na janela (rode `gt7 run aquisicao_dash --arg only=s7`).")
        else:
            _p7 = _q7.pivot_table(index='dim', columns='metrica', values='valor', aggfunc='sum').fillna(0.0)
            for _c in ('vendas', 'base_m3', 'ret_m3_A', 'ret_m3_C', 'base_m6', 'ret_m6_A', 'ret_m6_C'):
                if _c not in _p7.columns:
                    _p7[_c] = 0.0
            _lu7 = (_aq10[(_aq10['secao'] == 's1_canal') & (_aq10['metrica'] == 'leads_unicos_rma')
                          & (_aq10['mes'].isin(_sel7))].groupby('dim')['valor'].sum())
            _p7['leads'] = _p7.index.map(lambda d: float(_lu7.get(d, 0.0)))
            _p7 = _p7.sort_values('vendas', ascending=False)

            _tv7 = float(_p7['vendas'].sum())
            _b3, _r3c, _r3a = float(_p7['base_m3'].sum()), float(_p7['ret_m3_C'].sum()), float(_p7['ret_m3_A'].sum())
            _b6, _r6c = float(_p7['base_m6'].sum()), float(_p7['ret_m6_C'].sum())
            _inv7 = _v10('s7_midia', 'investimento', _sel7, 'midia')
            _cac = (_inv7 / _r3c) if _r3c > 0 else None

            k1, k2, k3, k4 = st.columns(4)
            _tv_kpi(k1, "🤝", "Vendas atribuídas a canais", f"{_tv_n(_tv7)}",
                    f"{_tv_pct(_tv7, float(_p7['leads'].sum()))} dos leads únicos do período viraram venda de franquia")
            _tv_kpi(k2, "📌", "Ainda pagando aos 3 meses", f"{_tv_pct(_r3c, _b3)}",
                    f"{_tv_n(_r3c)} de {_tv_n(_b3)} mensuráveis · def. C (até 1 mês de atraso)", color="#2e8a4f")
            _tv_kpi(k3, "🗓️", "Ainda pagando aos 6 meses", f"{_tv_pct(_r6c, _b6)}" if _b6 > 0 else "—",
                    (f"{_tv_n(_r6c)} de {_tv_n(_b6)} mensuráveis" if _b6 > 0 else "nenhuma coorte completou 6 meses"),
                    color="#0f172a")
            _tv_kpi(k4, "💸", "Custo por membro retido (m3)", (f"R$ {format_br(round(_cac))}" if _cac else "—"),
                    f"= R$ {format_br(round(_inv7))} de mídia (site) ÷ {_tv_n(_r3c)} ainda pagando no 3º mês", color="#b45309")

            st.caption("💸 **Custo por membro retido (m3)** — fórmula: `investimento de mídia do site no período ÷ membros ainda pagando 3 meses após a filiação` (definição C do painel `fl_nominal_qca_qcd`: contrato ativo com até 1 mês de atraso, `vam_inadimplente ≤ 34`). É quanto a mídia paga por **cliente que fica**, não por venda — e é do agregado de mídia do site, porque o investimento não tem rateio por canal do HubSpot (detalhes no expansor no fim da seção).")
            _g7 = _p7[_p7['base_m3'] >= 100].copy()
            if not _g7.empty:
                _g7['ret3'] = _g7['ret_m3_C'] / _g7['base_m3'] * 100
                _g7['ret3a'] = _g7['ret_m3_A'] / _g7['base_m3'] * 100
                _g7 = _g7.sort_values('ret3', ascending=True)
                _g7['rot'] = _g7.apply(lambda r: f"{r['ret3']:.1f}%  (n={_tv_fmt_k(r['base_m3'])})".replace('.', ','), axis=1)
                _med3 = (_r3c / _b3 * 100) if _b3 > 0 else 0
                fig = px.bar(_g7.reset_index(), x='ret3', y='dim', orientation='h', text='rot',
                             color_discrete_sequence=['#166534'], template='cdt_a' if _CDT_THEME else 'plotly_white')
                fig.update_traces(textposition='outside', textfont_size=10.5, cliponaxis=False)
                fig.add_vline(x=_med3, line_dash='dot', line_color='#b45309',
                              annotation_text=f"média {_med3:.1f}%".replace('.', ','),
                              annotation_position='top', annotation_font_size=10)
                fig.update_layout(height=max(300, 28 * len(_g7) + 80), xaxis_title='', yaxis_title='', showlegend=False,
                                  margin=dict(l=8, r=130, t=30, b=28),
                                  xaxis=dict(range=[0, max(100.0, float(_g7['ret3'].max()) * 1.18)], ticksuffix='%'),
                                  yaxis=dict(automargin=True, side='left', showgrid=False, tickfont=dict(size=11)))
                st.plotly_chart(fig, use_container_width=True)
                _tv_fonte("painel fl_nominal_qca_qcd (Athena) · definição C: contrato ativo e até 1 mês de atraso · "
                          "canais com menos de 100 vendas mensuráveis ficam fora")

                _tv_titulo("Escala × qualidade", "cada bolha é um canal; o tamanho é o volume de leads únicos", "A")
                _q = _g7.reset_index().copy()
                _q['conv'] = _q.apply(lambda r: (r['vendas'] / r['leads'] * 1000) if r['leads'] > 0 else 0, axis=1)
                _q = _q[_q['conv'] > 0]
                if not _q.empty:
                    _mx, _my = float(_q['conv'].median()), float(_q['ret3'].median())
                    fig = px.scatter(_q, x='conv', y='ret3', size='leads', text='dim', size_max=46,
                                     color_discrete_sequence=['#166534'],
                                     template='cdt_a' if _CDT_THEME else 'plotly_white')
                    fig.update_traces(textposition='top center', textfont_size=9.5,
                                      hovertemplate='%{text}<br>%{x:.1f} vendas/1.000 leads<br>%{y:.1f}% retidos<extra></extra>')
                    fig.add_vline(x=_mx, line_dash='dot', line_color='#94a3b8')
                    fig.add_hline(y=_my, line_dash='dot', line_color='#94a3b8')
                    fig.update_layout(height=430, showlegend=False, margin=dict(l=8, r=20, t=30, b=40),
                                      xaxis_title='vendas por 1.000 leads únicos', yaxis_title='% ainda pagando aos 3 meses',
                                      yaxis=dict(ticksuffix='%'))
                    st.plotly_chart(fig, use_container_width=True)
                    _tv_fonte("quadrante superior direito = converte e retém (escalar); inferior direito = converte e "
                              "não retém (rever oferta/qualificação); superior esquerdo = retém pouco volume (testar verba)")

                _tb7 = []
                for canal, r in _p7[_p7['vendas'] >= 20].iterrows():
                    _tb7.append({
                        'Canal de origem': canal,
                        'Leads Únicos': format_br(r['leads']),
                        'Vendas': format_br(r['vendas']),
                        'Conv.': _tv_pct(r['vendas'], r['leads']),
                        'Mensuráveis m3': format_br(r['base_m3']),
                        'Ativos m3 (A)': _tv_pct(r['ret_m3_A'], r['base_m3']),
                        'Pagando m3 (C)': _tv_pct(r['ret_m3_C'], r['base_m3']),
                        'Pagando m6 (C)': _tv_pct(r['ret_m6_C'], r['base_m6']) if r['base_m6'] > 0 else '—',
                        'Retidos / 1.000 leads': (f"{r['ret_m3_C'] / r['leads'] * 1000:.1f}".replace('.', ',')
                                                  if r['leads'] > 0 else '—')})
                st.dataframe(pd.DataFrame(_tb7), use_container_width=True, hide_index=True)
                _tv_fonte(f"janela {_lbl7} · canais com menos de 20 vendas no período ficam fora da tabela")
            else:
                st.caption("Nenhum canal tem 100 vendas com 3 meses de painel nesta janela — sem base para ranquear. "
                           "Abra a janela para 12 meses ou espere o painel do CTN fechar o mês seguinte.")

            with st.expander("Como isso é calculado — e o que o custo por membro retido pode e não pode dizer"):
                st.markdown(
                    "**Fórmula.** `custo por membro retido (m3) = investimento de mídia do site (RESUMO_INVESTIMENTO_DIARIO) ÷ retidos m3 (def. C)`. Exemplo: R$ 1,5 mi ÷ 5.000 retidos = R$ 300 por membro que continua pagando no 3º mês.\n\n"
                    "**A venda é do canal do primeiro lead.** Um CPF que aparece como lead em dois canais conta uma vez "
                    "só, no lead mais antigo. A atribuição é a mesma do RMA: CPF do lead único × `NOMINAL_VENDAS`, "
                    "`tipo_venda` de franquia (porta a porta, link do vendedor, app do vendedor), filiação em qualquer "
                    "data a partir do lead.\n\n"
                    "**Retido = ainda pagando N meses depois da filiação**, lido no painel mensal do CTN "
                    "(`fl_nominal_qca_qcd`) — as mesmas definições do LTV da aba 📱 App: **A** = contrato ativo "
                    "(`qca = 1`); **C** = ativo e com até um mês de atraso (`vam_inadimplente ≤ 34`). O relógio começa "
                    "na **filiação**, não no lead.\n\n"
                    "**Mensuráveis.** Uma venda de junho só entra no m3 quando a referência de setembro existir no "
                    "painel. Por isso a coluna *Mensuráveis m3* é menor que *Vendas* nos meses recentes — o "
                    "denominador é sempre a base mensurável, nunca o total.\n\n"
                    "**O custo é de mídia, não do canal.** `RESUMO_INVESTIMENTO_DIARIO` só abre o investimento em "
                    "canal (Website, App do Filiado) × plataforma (Google, Meta, Kwai, TikTok, Actionpay); não há "
                    "rateio para os canais do HubSpot. Então o **custo por membro retido é do agregado de mídia do "
                    "site** — serve para acompanhar a tendência do conjunto, não para comparar canais entre si. "
                    "Para comparar canais, use **retidos por 1.000 leads**, que é a mesma pergunta sem depender do "
                    "rateio de verba.\n\n"
                    "**Ressalva de abril/2026:** o `vam_inadimplente` veio quebrado na origem nesse mês; nele "
                    "a definição C é a média do estado do mesmo CPF em março e maio (mesmo tratamento do LTV).")

# =====================================================================================
# --- 11. 🧭 FUNIL PONTA A PONTA (R17, 08/09/2026) -----------------------------------
# Lê alex_funil_journey (pipelines/funil_journey.py no claude-toolkit): 1 linha por
# Contato criado no mês, com as datas de cada marco da jornada. Definições da reunião
# com o especialista de HubSpot (31/08–04/09) — doc: claude/plano_03-09 no projeto
# Televendas Funnel. Objetos do HubSpot sempre com maiúscula: Contato, Lead, Negócio.
# =====================================================================================
with tab11:
    st.markdown("## Funil Ponta a Ponta — do lead criado à venda")
    st.caption("Cada mês é uma **coorte**: todo mundo que virou lead naquele mês, acompanhado pelos marcos "
               "seguintes (mesmo que aconteçam meses depois). É reconstrução da jornada, não foto do estágio atual.")
    st.caption("📌 **Diferença para a aba Aquisição:** lá é a foto do PERÍODO por superfície (cada fonte mede a sua "
               "régua); aqui é o FILME da coorte numa fonte única (`alex_funil_journey`), com todos os encaminhamentos "
               "do Lead — esteira de televendas, transbordo para engajamento, rota de franquias — e os tempos entre "
               "etapas. Taxas de conversão e transbordos: use esta aba. Acompanhar o mês corrente canal a canal: "
               "use a Aquisição.")
    _tv_chips_legenda(['contato', 'negocio', 'ctn', 'filme'])

    _FJ_LBL = {
        'core': 'Núcleo (site, checkout, WhatsApp, mídia)', 'tim': 'Parceria B2B2C - TIM (fora das definições)',
        'franquia_promotor': 'Franquia — ID Promotor', 'franquia_facebook': 'Franquia — Facebook (captação)',
        'franquia_cms': 'Franquia — formulário CMS', 'regional': 'Formulários regionais',
        'ruptura': 'Projeto Ruptura', 'importacao': 'Importação de base',
        'desfiliados': 'Desfiliados em massa', 'engajamento': 'Instância de Engajamento',
        'sem_canal': 'Sem canal registrado',
    }
    _FJ_DEFS = {
        'Abrangente (tudo menos Engajamento e TIM)': ['core', 'importacao', 'desfiliados', 'franquia_cms',
                                                'franquia_promotor', 'franquia_facebook', 'ruptura', 'regional', 'sem_canal'],
        'HubSpot — relatório "Leads Únicos" (347496241)': ['core', 'franquia_cms', 'franquia_promotor',
                                                           'franquia_facebook', 'ruptura', 'regional', 'sem_canal'],
        'RMA antiga (só núcleo)': ['core'],
        'Personalizada': None,
    }

    @st.cache_data(ttl=43200)
    def load_fj_buckets():
        return cquery(
            "SELECT mes, bucket, COUNT(*) criados, SUM(n_negocios>0) com_negocio, "
            "SUM(dt_lead_tv IS NOT NULL) tv_lead, "
            "SUM(dt_lead_tv IS NOT NULL AND COALESCE(dt_negociacao,dt_css,dt_perdido,dt_ganho) IS NOT NULL) tv_trab, "
            "SUM(dt_negociacao IS NOT NULL) negociacao, SUM(dt_ganho IS NOT NULL) ganho, "
            "SUM(dt_perdido IS NOT NULL) perdido, "
            "SUM(COALESCE(dt_distrib,dt_semcep,dt_validador) IS NOT NULL) pipe_distrib, "
            "SUM(dt_validador IS NOT NULL) enviado_franquia, SUM(dt_distrib IS NOT NULL) encaminhado_conf, "
            "SUM(dt_venda_franquia IS NOT NULL) venda_franquia, SUM(dt_venda_app IS NOT NULL) venda_app "
            "FROM alex_funil_journey GROUP BY 1,2")

    @st.cache_data(ttl=43200)
    def load_fj_tempos(meses_key):
        """Medianas exatas, calculadas no banco (window functions). meses_key: tupla de 'YYYY-MM-DD'."""
        _in = ",".join(f"'{m}'" for m in meses_key)
        out = {}
        specs = {
            'h_criado_tv': ("TIMESTAMPDIFF(MINUTE, createdate, dt_lead_tv)/60.0", "dt_lead_tv IS NOT NULL"),
            'h_tv_trab': ("TIMESTAMPDIFF(MINUTE, dt_lead_tv, COALESCE(dt_negociacao,dt_css,dt_perdido,dt_ganho))/60.0",
                          "dt_lead_tv IS NOT NULL AND COALESCE(dt_negociacao,dt_css,dt_perdido,dt_ganho) IS NOT NULL"),
            'h_criado_valid': ("TIMESTAMPDIFF(MINUTE, createdate, dt_validador)/60.0", "dt_validador IS NOT NULL"),
            'd_criado_venda': ("TIMESTAMPDIFF(HOUR, createdate, dt_venda_franquia)/24.0", "dt_venda_franquia IS NOT NULL"),
        }
        for k, (expr, cond) in specs.items():
            df = cquery(
                f"SELECT AVG(v) med FROM (SELECT v, ROW_NUMBER() OVER (ORDER BY v) rn, COUNT(*) OVER () c "
                f"FROM (SELECT {expr} v FROM alex_funil_journey WHERE mes IN ({_in}) AND {cond}) t) t2 "
                f"WHERE rn IN (FLOOR((c+1)/2), CEIL((c+1)/2))")
            out[k] = None if df.empty or pd.isna(df['med'].iloc[0]) else float(df['med'].iloc[0])
        return out

    _fjb = load_fj_buckets()
    if _fjb.empty:
        st.warning("`alex_funil_journey` vazia — rode `gt7 run funil_journey` no claude-toolkit.")
        st.stop()
    _fjb['mes'] = pd.to_datetime(_fjb['mes'])
    _num = ['criados', 'com_negocio', 'tv_lead', 'tv_trab', 'negociacao', 'ganho', 'perdido',
            'pipe_distrib', 'enviado_franquia', 'encaminhado_conf', 'venda_franquia', 'venda_app']
    for _c in _num:
        _fjb[_c] = pd.to_numeric(_fjb[_c])
    _fj_disp = [pd.Timestamp(x) for x in sorted(_fjb['mes'].unique())]

    # período (R29): toggle igual ao da aba 🧲 — ligado = coortes tocadas pelo Período de Análise dos Controles Globais
    #   (interseção com as coortes disponíveis); desligado = as últimas N coortes carregadas em alex_funil_journey.
    _c11a, _c11b = st.columns([1, 2])
    with _c11a:
        _t11_glob = st.toggle("Seguir o período dos Controles Globais", value=True, key='t11_global',
                              help="Ligado: coortes (mês de criação do Contato) tocadas pelo 'Período de Análise' da barra lateral. "
                                   "Desligado: janela fixa de N coortes até a mais recente carregada.")
        if not _t11_glob:
            _j11 = st.selectbox("Janela:", ["Coorte mais recente", "Últimas 3 coortes", "Últimas 6 coortes", "Últimas 12 coortes"],
                                index=1, key='t11_jan')
    if _t11_glob:
        _fj_meses = [m for m in _tv_meses if m in set(_fj_disp)]
        _t11_fora = not _fj_meses
        if _t11_fora:
            _fj_meses = [_fj_disp[-1]]
    else:
        _t11_fora = False
        _n11 = {"Coorte mais recente": 1, "Últimas 3 coortes": 3, "Últimas 6 coortes": 6, "Últimas 12 coortes": 12}[_j11]
        _fj_meses = list(_fj_disp[-_n11:])
    with _c11b:
        _lbl11 = (f"{_fj_meses[0]:%m/%Y}" if len(_fj_meses) == 1 else f"{_fj_meses[0]:%m/%Y}–{_fj_meses[-1]:%m/%Y}")
        if _t11_glob:
            st.caption(f"Coortes: **{_lbl11}** — meses de criação do Contato tocados pelo período dos Controles Globais. "
                       "Semanas e dias não se aplicam: o eixo é sempre a coorte do mês; cada coorte é seguida até a última carga. "
                       f"Coortes disponíveis: {_fj_disp[0]:%m/%Y}–{_fj_disp[-1]:%m/%Y}.")
            if _t11_fora:
                st.info(f"O período dos Controles Globais não toca as coortes disponíveis "
                        f"({_fj_disp[0]:%m/%Y}–{_fj_disp[-1]:%m/%Y}); mostrando {_fj_meses[0]:%m/%Y}.")
        else:
            st.caption(f"Janela fixa: coortes **{_lbl11}** (as {len(_fj_meses)} mais recentes carregadas). "
                       "Ligue o toggle para seguir o período dos Controles Globais.")
    _fj_lbl_per = (f"coorte de {_fj_meses[0]:%m/%Y}" if len(_fj_meses) == 1
                   else f"coortes de {_fj_meses[0]:%m/%Y} a {_fj_meses[-1]:%m/%Y}")

    # ---- a decisão de negócio fica visível: qual definição de "lead elegível"? ----
    _c_def, _c_bk = st.columns([1.1, 2])
    _fj_def_nome = _c_def.radio("Definição de **lead elegível** (D3 — seleção de buckets):",
                                list(_FJ_DEFS.keys()), index=0, key="fj_def")
    _todos_bk = [b for b in _FJ_LBL if b in set(_fjb['bucket'])]
    if _FJ_DEFS[_fj_def_nome] is None:
        _fj_sel = _c_bk.multiselect("Buckets que contam como elegíveis:", _todos_bk,
                                    default=[b for b in _todos_bk if b not in ('engajamento', 'tim')],
                                    format_func=lambda b: _FJ_LBL.get(b, b), key="fj_sel")
    else:
        _fj_sel = [b for b in _FJ_DEFS[_fj_def_nome] if b in _todos_bk]
        _c_bk.caption("Buckets desta definição: " + " · ".join(_FJ_LBL.get(b, b) for b in _fj_sel)
                      + ". Regional e Ruptura ainda **sem definição oficial** — por isso tudo aqui é seleção, não filtro fixo. TIM fica fora de todas as definições (18/09): não segue os fluxos de televendas/franquias; marque o bucket em Personalizada se quiser vê-la.")

    _cur = _fjb[_fjb['mes'].isin(_fj_meses)]
    _sel = _cur[_cur['bucket'].isin(_fj_sel)]
    _tot, _els = _cur[_num].sum(), _sel[_num].sum()

    # período anterior de mesmo tamanho (para os deltas dos KPIs)
    _prev_meses = [m - pd.DateOffset(months=len(_fj_meses)) for m in _fj_meses]
    _prv = _fjb[_fjb['mes'].isin(_prev_meses) & _fjb['bucket'].isin(_fj_sel)][_num].sum() \
        if set(_prev_meses) & set(_fj_disp) else None

    def _fj_d(campo):
        return _tv_delta(int(_els[campo]), int(_prv[campo])) if _prv is not None else ""

    st.markdown(f"#### Visão macro — {_fj_lbl_per}")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    _tv_kpi(k1, "🌱", "Leads criados (tudo)", f"{_tv_n(int(_tot['criados']))}",
            "Contatos novos na instância de Aquisição")
    _tv_kpi(k2, "✅", "Elegíveis (definição acima)", f"{_tv_n(int(_els['criados']))} {_fj_d('criados')}",
            f"{_els['criados'] / _tot['criados'] * 100:.0f}% do total" if _tot['criados'] else "—")
    _tv_kpi(k3, "🤝", "Viraram Negócio", f"{_tv_n(int(_els['com_negocio']))} {_fj_d('com_negocio')}",
            "elegíveis com ao menos 1 Negócio no CRM")
    _tv_kpi(k4, "📞", "Chegaram ao Televendas", f"{_tv_n(int(_els['tv_lead']))} {_fj_d('tv_lead')}",
            "entraram na etapa LEAD da esteira")
    _tv_kpi(k5, "🏪", "Enviados a franquias", f"{_tv_n(int(_els['enviado_franquia']))} {_fj_d('enviado_franquia')}",
            "passaram pelo Validador de Distribuição")
    _tv_kpi(k6, "💰", "Vendas nas franquias", f"{_tv_n(int(_els['venda_franquia']))} {_fj_d('venda_franquia')}",
            f"porta a porta + link + app do vendedor · {format_br(int(_els['venda_app']))} via app")

    st.markdown("")

    # ---- as duas rotas, lado a lado — ou o diagrama em raias (R31, toggle) ----
    _t11_raias = st.toggle("🗺️ Ver como diagrama de raias — onde cada número nasce", value=False, key='t11_raias',
                           help="Alternativa aos dois funis: as etapas das rotas desenhadas nas raias Contato / Negócio / CTN, "
                                "com a lente do filme (coorte seguida até hoje) em destaque e a da fotografia (aba 🧲) esmaecida.")
    if _t11_raias:
        _tv_raias('filme', {'criados': int(_tot['criados']), 'eleg': int(_els['criados']), 'tv': int(_els['tv_lead']),
                            'pipe': int(_els['pipe_distrib']), 'valid': int(_els['enviado_franquia']),
                            'venda': int(_els['venda_franquia'])},
                  "Rotas Televendas e Franquias — a coorte nas raias", _fj_lbl_per)
    else:
        _cA, _cB = st.columns(2)
        with _cA:
            _tv_funil("📞 Rota Televendas", [
                ("🌱", "Leads criados", int(_tot['criados']), "todos os Contatos novos do período"),
                ("✅", "Elegíveis", int(_els['criados']), "definição selecionada acima"),
                ("📞", "Entraram na esteira", int(_els['tv_lead']), "etapa LEAD (CDT - Lead Televendas)"),
                ("🛠️", "Trabalhados", int(_els['tv_trab']), "saíram de LEAD para qualquer etapa"),
                ("🤝", "Em negociação", int(_els['negociacao']), "etapa EM NEGOCIAÇÃO"),
                ("🏆", "GANHO", int(_els['ganho']), f"PERDIDO: {format_br(int(_els['perdido']))}"),
            ], subtitle=_fj_lbl_per,
                chips=[['contato', 'filme'], ['contato', 'filme'], ['negocio', 'filme'], ['negocio', 'filme'],
                       ['negocio', 'filme'], ['negocio', 'filme']])
        with _cB:
            _tv_funil("🏪 Rota Franquias", [
                ("🌱", "Leads criados", int(_tot['criados']), "todos os Contatos novos do período"),
                ("✅", "Elegíveis", int(_els['criados']), "definição selecionada acima"),
                ("🔀", "No pipeline Distribuição", int(_els['pipe_distrib']), "CDT - Distribuição de Leads"),
                ("📮", "Enviados à franquia", int(_els['enviado_franquia']), "Validador = válido e enviado (definição do especialista)"),
                ("💰", "Venda na franquia", int(_els['venda_franquia']), "CPF × NOMINAL: porta a porta + link + app do vendedor"),
            ], subtitle=_fj_lbl_per,
                chips=[['contato', 'filme'], ['contato', 'filme'], ['negocio', 'filme'], ['negocio', 'filme'], ['ctn', 'filme']])
    _tv_note(
        "<b>Por que a Rota Franquias não bate com o 'Funil Franquias' da aba 🧲.</b> Aqui é o <b>filme da coorte</b>: os Contatos "
        "criados no período (espelho vivo, canal <i>na criação</i>, buckets à sua escolha) seguidos até hoje — Distribuição, Validador "
        "e venda na franquia em <b>qualquer data</b> posterior. Na 🧲 é a <b>foto do mês</b>, do jeito que o Relatório Mensal conta: "
        "Leads Únicos da lista <code>HS - Leads Únicos mês</code> (regra do deck, sem os promotores), Negócios com 1ª entrada em "
        "Distribuição/Validador <b>no mês</b> (de qualquer coorte, inclusive leads dos promotores) e vendas <b>no mês do lead</b>. "
        "Três diferenças de uma vez — população, evento contado e janela — e por isso ago/26 dá 259k → 83k → 63k → 32,7k aqui "
        "(todos os buckets) contra 178k → 101k → 29,7k lá. <b>Quando usar:</b> 🧭 para rota, perdas por etapa, tempos e a decisão de "
        "elegibilidade; 🧲 para bater com o relatório e comparar meses fechados. Esta aba não segue o Período de Análise no grão de "
        "dias/semanas: o eixo é sempre a coorte do mês de criação do Contato.",
        bg="#f8fafc", icon="🧲")
    _tv_foto_filme_exemplo('t11')

    # ---- etapa a etapa: entrada, avançou, taxa, perda, tempo ----
    _tmp = load_fj_tempos(tuple(m.strftime('%Y-%m-%d') for m in _fj_meses))

    def _fj_t(v, unidade):
        if v is None:
            return "—"
        if unidade == 'h':
            return f"{v:.0f} h" if v >= 2 else f"{v * 60:.0f} min"
        return f"{v:.0f} dias" if v >= 2 else f"{v * 24:.0f} h"

    _etapas = [
        ("Criados → Elegíveis", int(_tot['criados']), int(_els['criados']), "—",
         "buckets excluídos pela definição (detalhe abaixo)"),
        ("Elegíveis → viraram Negócio", int(_els['criados']), int(_els['com_negocio']), "—",
         "sem Negócio: parte por desenho (TIM, franquias operam fora do CRM), parte perda real"),
        ("Elegíveis → esteira Televendas", int(_els['criados']), int(_els['tv_lead']), _fj_t(_tmp['h_criado_tv'], 'h'),
         "roteamento: grupos A–D (ver aba 📞 → Grupos)"),
        ("Esteira → trabalhado", int(_els['tv_lead']), int(_els['tv_trab']), _fj_t(_tmp['h_tv_trab'], 'h'),
         "parados em LEAD = fila não tocada"),
        ("Trabalhado → em negociação", int(_els['tv_trab']), int(_els['negociacao']), "—", ""),
        ("Em negociação → GANHO", int(_els['negociacao']), int(_els['ganho']), "—",
         f"PERDIDO no caminho: {format_br(int(_els['perdido']))}"),
        ("Elegíveis → enviado à franquia", int(_els['criados']), int(_els['enviado_franquia']),
         _fj_t(_tmp['h_criado_valid'], 'h'), "marcador: entrada no Validador de Distribuição"),
        ("Enviado → venda na franquia", int(_els['enviado_franquia']), int(_els['venda_franquia']),
         _fj_t(_tmp['d_criado_venda'], 'd'), "tempo mostrado = criação do lead → filiação"),
    ]
    _rows_html = []
    for nome, ent, av, tempo, nota in _etapas:
        taxa = f"{av / ent * 100:.1f}%" if ent else "—"
        perda = format_br(ent - av) if ent >= av else "—"
        _rows_html.append(
            "<tr>"
            f"<td style='padding:7px 10px;font-weight:600;color:#0f172a;'>{nome}"
            f"<div style='font-size:10.5px;color:#94a3b8;font-weight:400;'>{nota}</div></td>"
            f"<td style='padding:7px 10px;text-align:right;'>{format_br(ent)}</td>"
            f"<td style='padding:7px 10px;text-align:right;font-weight:700;'>{format_br(av)}</td>"
            f"<td style='padding:7px 10px;text-align:right;color:#166534;font-weight:700;'>{taxa}</td>"
            f"<td style='padding:7px 10px;text-align:right;color:#b91c1c;'>{perda}</td>"
            f"<td style='padding:7px 10px;text-align:right;color:#475569;'>{tempo}</td>"
            "</tr>")
    st.markdown(
        "<div style='border:1px solid #e2e8f0;border-radius:12px;background:#fff;overflow-x:auto;margin-top:14px;'>"
        "<table style='border-collapse:collapse;width:100%;font-size:12.5px;'>"
        "<thead><tr style='color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:.04em;'>"
        "<th style='padding:8px 10px;text-align:left;'>Etapa</th><th style='padding:8px 10px;text-align:right;'>Entrada</th>"
        "<th style='padding:8px 10px;text-align:right;'>Avançou</th><th style='padding:8px 10px;text-align:right;'>Taxa</th>"
        "<th style='padding:8px 10px;text-align:right;'>Ficou/perdeu</th><th style='padding:8px 10px;text-align:right;'>Tempo mediano</th>"
        "</tr></thead><tbody>" + "".join(_rows_html) + "</tbody></table></div>", unsafe_allow_html=True)
    st.caption("Tempo mediano = metade avança mais rápido, metade mais devagar (mediana exata, calculada no banco). "
               "\"Ficou/perdeu\" mistura quem parou e quem ainda vai avançar — em coortes recentes, parte é só tempo.")

    # ---- onde os leads entram: buckets do período ----
    st.markdown("#### Onde os leads entram — e o que a definição exclui")
    _bk = _cur.groupby('bucket', as_index=False)[_num].sum().sort_values('criados', ascending=True)
    _bk['rotulo'] = _bk['bucket'].map(lambda b: _FJ_LBL.get(b, b))
    _bk['status'] = _bk['bucket'].map(lambda b: 'Conta como elegível' if b in _fj_sel else 'Fora da definição')
    _bk['pct'] = _bk['criados'] / max(int(_tot['criados']), 1) * 100
    _figb = px.bar(_bk, x='criados', y='rotulo', orientation='h', color='status',
                   color_discrete_map={'Conta como elegível': '#166534', 'Fora da definição': '#cbd5e1'},
                   text=_bk.apply(lambda r: f"{_tv_fmt_k(r['criados'])} · {r['pct']:.0f}%", axis=1))
    _figb.update_traces(textposition='outside', cliponaxis=False)
    _figb.update_layout(height=max(300, 34 * len(_bk)), margin=dict(l=0, r=10, t=10, b=0),
                        plot_bgcolor='white', paper_bgcolor='rgba(0,0,0,0)',
                        xaxis=dict(title=None, showgrid=True, gridcolor='#f1f5f9'),
                        yaxis=dict(title=None), legend=dict(title=None, orientation='h', y=1.08),
                        font=dict(size=12))
    st.plotly_chart(_figb, use_container_width=True)

    # ---- evolução por coorte ----
    st.markdown("#### Evolução por coorte")
    _ev = _fjb[_fjb['bucket'].isin(_fj_sel)].groupby('mes', as_index=False)[_num].sum()
    _ev['Vendas (franquia + GANHO TV)'] = _ev['venda_franquia'] + _ev['ganho']
    _ev_m = _ev.melt(id_vars='mes',
                     value_vars=['criados', 'tv_lead', 'enviado_franquia', 'Vendas (franquia + GANHO TV)'],
                     var_name='serie', value_name='valor')
    _ev_m['serie'] = _ev_m['serie'].map({'criados': 'Elegíveis criados', 'tv_lead': 'Chegaram ao Televendas',
                                         'enviado_franquia': 'Enviados a franquias'}).fillna(_ev_m['serie'])
    _fige = px.line(_ev_m, x='mes', y='valor', color='serie', markers=True,
                    color_discrete_sequence=['#14532d', '#2e8a4f', '#8cc79e', '#b45309'])
    _fige.update_layout(height=320, margin=dict(l=0, r=10, t=10, b=0), plot_bgcolor='white',
                        paper_bgcolor='rgba(0,0,0,0)', xaxis=dict(title=None, tickformat='%m/%Y'),
                        yaxis=dict(title=None, showgrid=True, gridcolor='#f1f5f9'),
                        legend=dict(title=None, orientation='h', y=1.12), font=dict(size=12))
    st.plotly_chart(_fige, use_container_width=True)

    # ---- notas de leitura (para quem não vive dentro do HubSpot) ----
    _tv_note(
        "<b>Como ler esta aba.</b> <b>Contato</b> é a pessoa no CRM; <b>Negócio</b> é a oportunidade que o sistema "
        "abre para ela. Cada pessoa entra na <b>coorte</b> do mês em que virou lead e carrega as datas do que "
        "aconteceu depois: entrar na esteira do Televendas, ser enviada a uma franquia (o <b>Validador</b> é a "
        "confirmação de que ela foi validada e enviada — definição do especialista de HubSpot), e a <b>venda real</b> "
        "(filiação no NOMINAL, casada por CPF; 'porta a porta', 'link do vendedor' e 'app do vendedor' contam como venda "
        "de franquia — a mesma régua do Funil Franquias da 🧲 e do Relatório Mensal; o app do vendedor aparece também "
        "como fatia no KPI). O canal usado nas quebras é o <b>canal da criação</b> — o que "
        "trouxe a pessoa — e não o último canal que a tocou.")
    _tv_note(
        "<b>Ressalvas que mudam número.</b> (1) Coortes até <b>abr/2026</b> têm as etapas de Negócio como "
        "<b>piso</b> (o espelho de Negócios cobre bem desde 13/05); em <b>maio</b> a etapa 'trabalhado' está em "
        "validação. (2) O pipeline novo <b>924101912</b> (carga em massa de 06/08, sem Contatos associados) fica "
        "fora desta jornada por construção. (3) ~20% dos cadastros de um mês são <b>mesclados</b> depois — a "
        "jornada resolve a pessoa por CPF (tabela alex_contato_resolucao). (4) 'Regional' e 'Ruptura' ainda não "
        "têm definição oficial de elegibilidade — por isso a definição aqui é uma <b>seleção explícita</b>, e a "
        "barra cinza mostra sempre o que ficou de fora.", bg="#fefce8", icon="⚠️")
