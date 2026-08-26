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
        query = "SELECT data AS data_ref, eh_dia_util AS is_dia_util FROM dim_calendario"
        cal = conn.query(query)
        cal['data_ref'] = pd.to_datetime(cal['data_ref'])
        return cal
    except Exception:
        dr = pd.date_range(start='2020-01-01', end='2030-12-31')
        return pd.DataFrame({'data_ref': dr, 'is_dia_util': (dr.weekday < 5).astype(int)})

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
        df = conn.query(query)
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
        df_inv = conn.query(query)
        df_inv['data_investimento'] = pd.to_datetime(df_inv['data_investimento'])
        df_inv['canal'] = df_inv['canal'].fillna("Não Informado").astype(str).str.strip().str.title()
        return df_inv
    except Exception:
        return pd.DataFrame(columns=['data_investimento', 'canal', 'plataforma', 'branding', 'leads', 'venda', 'vol_leads', 'vol_vendas'])

@st.cache_data(ttl=43200)
def load_goals_data():
    try:
        query = "SELECT * FROM alex_metas"
        df_goals = conn.query(query)
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
        df_raw = conn.query(f"SELECT ds, channel_group, y, spend_total, spend_total2 FROM vw_prophet_input WHERE y IS NOT NULL AND ds <= '{ref_date_str}' ORDER BY ds")
    except Exception:
        try:
            df_raw = conn.query(f"SELECT ds, channel_group, y, spend_total FROM vw_prophet_input WHERE y IS NOT NULL AND ds <= '{ref_date_str}' ORDER BY ds")
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
        d = conn.query("""
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
            part = conn.query(f"SELECT `date`, `campaign_name`, `cost` FROM {tbl} WHERE `date` >= '{start_history}'")
            part['plataforma'] = plat
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
        out = conn.query("SELECT `date`, `session_campaign_name`, `session_source_medium`, `conversions` "
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
        out = conn.query("SELECT `date`, `session_campaign_name`, `session_source_medium`, `conversions` "
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
        d = conn.query("SELECT `date`, `campaign_name`, COALESCE(`on_facebook_leads`, 0) AS leads "
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
            f = conn.query(
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
        d = conn.query(q)
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
            d = conn.query(f"SELECT `date`, `session_campaign_name`, `session_source_medium`, "
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
        d = conn.query("SELECT report_date, sender_name, total_messages, total_price "
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
            p = conn.query(f"SELECT `date`, `campaign_name`, `cost`, `impressions`, "
                           f"`{clicks_col}` AS clicks FROM {tbl} WHERE `date` >= '{start_history}'")
            p['plataforma'] = plat
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
    d = conn.query("SELECT * FROM alex_ga_checkout_funnel", ttl=0)
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
    "Semana Atual", "Mês Atual", "Ano Atual", "Últimos 30 Dias", "Últimos 90 Dias", "Último 1 Ano",
    "Personalizado"
])

# Custom date range: two pickers that override the preset above.
custom_start = custom_end = None
if view_option == "Personalizado":
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
elif view_option == "Últimos 30 Dias": proj_days = 30
elif view_option == "Últimos 90 Dias": proj_days = 90
elif view_option == "Personalizado": proj_days = (custom_end - custom_start).days + 1
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
elif view_option == "Últimos 30 Dias":
    c_s, c_e = ref_datetime - pd.DateOffset(days=29), ref_datetime
    p_s, p_e = c_s - pd.DateOffset(days=30), c_e - pd.DateOffset(days=30)
    l_s, l_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
elif view_option == "Últimos 90 Dias":
    c_s, c_e = ref_datetime - pd.DateOffset(days=89), ref_datetime
    p_s, p_e = c_s - pd.DateOffset(days=90), c_e - pd.DateOffset(days=90)
    l_s, l_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
elif view_option == "Personalizado":
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

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📈 Desempenho de Vendas", "🗺️ Mapa Regional (UF)", "💰 Investimento", "📣 Campanhas", "🧪 Funil (Piloto)", "📞 Televendas"])

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
            "da janela principal."
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
    
    todas_plataformas = ["Google", "Meta", "TikTok", "Kwai", "Adsplay", "Actionpay", "CRM"]
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
# TAB 5: FUNIL (PILOTO) — Website Checkout
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
               "Funil restrito ao checkout do site (hosts adesao/solicite).")

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
    d = conn.query("SELECT mes, secao, dim, metrica, valor, atualizado_em FROM alex_tv_dash_mes", ttl=0)
    d['mes'] = pd.to_datetime(d['mes'])
    d['valor'] = pd.to_numeric(d['valor'], errors='coerce')
    return d


@st.cache_data(ttl=43200)
def _load_tv_dash_sem_raw():
    # Grão semanal (alex_tv_dash_sem, semana = segunda-feira); coluna renomeada para `mes` para reaproveitar os helpers.
    d = conn.query("SELECT semana AS mes, secao, dim, metrica, valor, atualizado_em FROM alex_tv_dash_sem", ttl=0)
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

    def _tv_funil(title, stages, subtitle=""):
        """stages: lista de (icone, rotulo, valor, nota). Barra proporcional ao topo,
        conversão sequencial (vs etapa anterior) e acumulada (vs topo)."""
        vals = [v for _i, _l, v, _n in stages if v is not None]
        top = vals[0] if vals else 0
        rows = [(f"<div style='display:flex;gap:14px;align-items:baseline;margin-bottom:8px;'>"
                 f"<div style='font-size:15px;font-weight:800;color:#0f172a;'>{title}</div>"
                 f"<div style='font-size:11px;color:#64748b;'>{subtitle}</div>"
                 f"<div style='margin-left:auto;font-size:10.5px;font-weight:700;color:#166534;'>seq. | do topo</div></div>")]
        prev = None
        for i, (ic, lbl, v, note) in enumerate(stages):
            label = (f"<div style='flex:0 0 250px;display:flex;align-items:center;gap:8px;'>"
                     f"<div style='width:30px;height:30px;border-radius:8px;background:#14532d;display:flex;"
                     f"align-items:center;justify-content:center;font-size:14px;flex:0 0 30px;'>{ic}</div>"
                     f"<div><div style='font-size:12.5px;font-weight:700;color:#0f172a;'>{lbl}</div>"
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
                        f"{_tv_pct(v, prev) if prev else '—'}</div>"
                        f"<div style='flex:0 0 58px;text-align:right;font-size:12.5px;color:#64748b;'>"
                        f"{_tv_pct(v, top) if i > 0 else '100%'}</div>")
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

    _tv_tabs = st.tabs(["📵 1 · Escallo Ativo", "📲 2 · Escallo Receptivo", "🚪 3 · Ganhos por porta",
                        "📏 4 · Três réguas", "🧭 5 · Pipeline CRM", "🔀 6 · Grupos A–D", "💬 7 · Talkerchat"])

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
    # 3 · GANHOS POR PORTA
    # =================================================================
    with _tv_tabs[2]:
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
    # 4 · TRÊS RÉGUAS DA VENDA
    # =================================================================
    with _tv_tabs[3]:
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
    with _tv_tabs[4]:
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
            _tv_funil("Pipeline CDT - Lead Televendas · entradas por estágio no período", [
                ("🚪", "Contatos no fluxo do televendas", fluxo, "Contato: data_de_entrada_no_fluxo_do_televendas"),
                ("🧩", "LEAD", _ent['LEAD'], "Negócio: hs_v2_date_entered_961121694"),
                ("🤝", "EM NEGOCIAÇÃO", _ent['EM NEGOCIAÇÃO'], "…961121695 (7 d)"),
                ("📵", "CONTATO SEM SUCESSO", _ent['CONTATO SEM SUCESSO'], "…961121696 (1 d 12 h)"),
                ("🏁", "GANHO", _ent['GANHO'], "…961121698 — porta 1 (tabulação) ou porta 2 (checkout)"),
            ], subtitle="cada linha conta ENTRADAS no estágio (um Negócio pode entrar em vários); PERDIDO fora do funil")
            _mg5 = _tv_meses_grafico('t6_s5_ano')
            _tv_chart_mensal(pd.concat([_tv_serie(S, 'entradas', dim=s_, meses=_mg5).assign(serie=s_) for s_ in _stages]),
                             "Entradas por estágio, por mês", stacked=False, rotulos=True,
                             subtitle="hs_v2_date_entered_* do pipeline CDT - Lead Televendas", fonte="hubspot_deals_raw")
            _est = _tvd_m[(_tvd_m['secao'] == 's5_estoque') & (_tvd_m['metrica'] == 'estoque')]
            if not _est.empty:
                _est = _est[_est['mes'] == _est['mes'].max()].groupby('dim', as_index=False)['valor'].sum()
                _est = _est[_est['dim'].isin(_stages)].set_index('dim').reindex(_stages).fillna(0).reset_index()
                _rows5 = [{'Estágio (estoque atual)': r['dim'], 'Negócios': format_br(r['valor']), '_level': 0, '_is_eff': False}
                          for _, r in _est.iterrows()]
                st.markdown(render_metric_table(_rows5, ['Estágio (estoque atual)', 'Negócios']), unsafe_allow_html=True)
                st.caption("Estoque = Negócios cujo estágio ATUAL é o indicado (pipeline CDT - Lead Televendas), na data do último pipeline.")
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
    # 6 · GRUPOS A–D
    # =================================================================
    with _tv_tabs[5]:
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
                _d6 = _w6.sort_values('contatos', ascending=False)[['grupo', 'canal_regra', 'dim'] + _cols6]
                _d6 = _d6.rename(columns={'dim': 'primeiro_canal_de_origem'})
                st.dataframe(_d6, use_container_width=True, hide_index=True)

    # =================================================================
    # 7 · TALKERCHAT
    # =================================================================
    with _tv_tabs[6]:
        S = 's7_talkerchat'
        tk = _tv_val(S, 'tickets'); tl = _tv_val(S, 'leads'); tcpf = _tv_val(S, 'com_cpf')
        th = _tv_val(S, 'leads_humano'); tcomp = _tv_val(S, 'compras'); tlia = _tv_val(S, 'compras_lia'); thum = _tv_val(S, 'compras_humano')
        tlc = _tv_val(S, 'leads_compra'); tpar = _tv_val(S, 'pares_compra_cpf'); tconf = _tv_val(S, 'compras_confirmadas')
        tcrm_l = _tv_val(S, 'leads_cpf'); tcrm_c = _tv_val(S, 'com_contato_hs'); tcrm_d = _tv_val(S, 'com_deal_criado_no_mes'); tcrm_dq = _tv_val(S, 'com_deal_qualquer_epoca')
        tl_p = _tv_val(S, 'leads', meses=_tv_per_p); tcomp_p = _tv_val(S, 'compras', meses=_tv_per_p)
        tbot = (tl - th) if (tl is not None and th is not None) else None

        k1, k2, k3, k4 = st.columns(4)
        _tv_kpi(k1, "💬", "Usuários únicos (tel-8) no período", f"{_tv_n(tl)} {_tv_delta(tl, tl_p)}",
                (f"{_tv_n(tk)} tickets · " + f"{tk / tl:.2f}".replace('.', ',') + " por usuário") if tk and tl else "")
        _tv_kpi(k2, "🪪", "Qualificados (com CPF)", f"{_tv_pct(tcpf, tl)}", f"{_tv_n(tcpf)} usuários com CPF capturado")
        _tv_kpi(k3, "🤖", "Só bot (Lia) × humano", f"{_tv_pct(tbot, tl)} · {_tv_pct(th, tl)}",
                f"{_tv_n(tbot)} sem atendente humano · {_tv_n(th)} com atendente", color="#2e8a4f")
        _tv_kpi(k4, "🛒", "Compras reportadas → confirmadas", f"{_tv_n(tcomp)} {_tv_delta(tcomp, tcomp_p)}",
                f"Lia {_tv_pct(tlia, tcomp)} · humano {_tv_pct(thum, tcomp)} · {_tv_pct(tconf, tpar)} confirmadas no NOMINAL (CPF ±3 d)")

        c1, c2 = st.columns([1.9, 1])
        with c1:
            _tv_funil("Funil Talkerchat (WhatsApp)", [
                ("💬", "Tickets", tk, "conversas abertas no período (criado_dt)"),
                ("👤", "Usuários únicos", tl, "telefone_key (tel-8)"),
                ("🪪", "Qualificados (CPF)", tcpf, "cpf_norm capturado na conversa"),
                ("🛒", "Compra reportada (usuários)", tlc, f"motivo = 'compra reportada' · {_tv_n(tcomp)} tickets"),
                ("✅", "Confirmadas no NOMINAL", tconf, "pares CPF × âncora ±3 d"),
            ], subtitle=_tv_per_lbl)
            _mg7 = _tv_meses_grafico('t6_s7_ano')
            _tv_chart_mensal(_tv_long(S, ['leads', 'com_cpf', 'leads_humano', 'compras', 'compras_lia'], meses=_mg7,
                                      labels={'leads': 'Usuários únicos', 'com_cpf': 'Com CPF', 'leads_humano': 'Com atendente humano',
                                              'compras': 'Compras reportadas', 'compras_lia': 'Compras Lia'}),
                             "Série mensal — Talkerchat", stacked=False, rotulos=True, fonte="export Talkerchat (v_alex_talkerchat)")
        with c2:
            _tv_note(
                f"<b>Bot × humano.</b> {_tv_pct(tbot, tl)} dos usuários só falaram com a Lia (nenhum atendente no mês); "
                f"{_tv_pct(th, tl)} chegaram a um vendedor humano — a transferência é sempre bot → humano. "
                f"Nas compras, a Lia responde por {_tv_pct(tlia, tcomp)} (etiqueta 'vendalia' marca a venda, não o atendimento).<br><br>"
                f"<b>A falha: nenhum Negócio é criado.</b> Dos {_tv_n(tcrm_l)} usuários com CPF, {_tv_pct(tcrm_c, tcrm_l)} existem como "
                f"Contato no HubSpot, mas só <b>{_tv_pct(tcrm_d, tcrm_l)}</b> tiveram um Negócio criado no mês da conversa "
                f"({_tv_pct(tcrm_dq, tcrm_l)} têm algum Negócio em qualquer época). O Talkerchat não está integrado ao CRM "
                f"(L2): a conversa e a venda vivem só no export; os IDPVs de bot não criam Negócio.",
                bg="#fff7ed", icon="⚠️")
            _tv_note(
                "Fonte: export do Talkerchat (alex_talkerchat via v_alex_talkerchat); compras confirmadas por CPF ±3 dias no NOMINAL. "
                "Cobertura do export: reimportar o CSV no fechamento do mês (última data carregada aparece no último mês com dados).",
                bg="#f8fafc", icon="ℹ️")
