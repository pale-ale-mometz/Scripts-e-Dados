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
    query = f"SELECT data_venda, uf, tipo_venda, Vendas FROM RESUMO_VENDAS_DIARIAS WHERE data_venda >= '{start_history}'"
    df = conn.query(query)
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

# Call the cached data loaders
df_cal = load_calendar()
df_raw = load_data()
df_invest_raw = load_invest_data()
df_goals = load_goals_data()

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

if now_sp.time() >= datetime.time(11, 30):
    reference_date = now_sp.date() - datetime.timedelta(days=1)
    hora_atualizacao = "Hoje às 11:30"
else:
    reference_date = now_sp.date() - datetime.timedelta(days=2)
    hora_atualizacao = "Ontem às 11:30"

st.sidebar.caption(f"🔄 **Base atualizada:** {hora_atualizacao}\n(Dados até {reference_date.strftime('%d/%m/%Y')})")
st.sidebar.divider()

view_option = st.sidebar.radio("Período de Análise:", [
    "Semana Atual", "Mês Atual", "Ano Atual", "Últimos 30 Dias", "Últimos 90 Dias", "Último 1 Ano"
])

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

df_fcst = generate_prophet_forecast(ref_datetime.strftime('%Y-%m-%d'))

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
else: 
    c_s, c_e = ref_datetime - pd.DateOffset(years=1) + pd.DateOffset(days=1), ref_datetime
    p_s, p_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
    l_s, l_e = c_s - pd.DateOffset(years=2), c_e - pd.DateOffset(years=2)

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

tab1, tab2, tab3, tab4 = st.tabs(["📈 Desempenho de Vendas", "🗺️ Mapa Regional (UF)", "💰 Investimento", "📣 Campanhas"])

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
    
    col_t1, col_t2 = st.columns(2)
    mostrar_detalhes = col_t1.checkbox("Mostrar detalhamento por canal (Expandir Grupos)")
    
    if not df_fcst.empty:
        mostrar_previsao = col_t2.checkbox("Incluir Previsão da Inteligência Artificial (Tabela)")
        if mostrar_previsao:
            horizonte_previsao_tabela = col_t2.radio("Horizonte da Previsão (Tabela):", ["Fim do Período Atual", f"Próximos {proj_days} Dias"], horizontal=True, key="horiz_tabela")
    else:
        mostrar_previsao = False

    if mostrar_previsao and not df_fcst.empty:
        if horizonte_previsao_tabela == "Fim do Período Atual":
            fcst_end_date = c_e
        else:
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
        
        if mostrar_detalhes:
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
        
        col_gt1, col_gt2 = st.columns(2)
        tipo_visao_tend = col_gt1.radio("Nível de Visualização:", ["Grupos de Canais", "Canais Específicos"], horizontal=True, key='tend_rad')
        tipo_graf_tend = col_gt2.radio("Soma do Gráfico:", ["Diário", "Acumulado"], horizontal=True)
        
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
                
                if horizonte_grafico == "Fim do Período Atual":
                    fcst_end_d = c_e
                else:
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

        df_main = get_trend_data(c_s, c_e, "", max_actual_date=ref_datetime)
        plot_dfs = [df_main] if not df_main.empty else []
        
        if show_prev:
            df_prev_plot = get_trend_data(p_s, p_e, " (Anterior)")
            if not df_prev_plot.empty: plot_dfs.append(df_prev_plot)
            
        if show_last_yr and view_option != "Ano Atual":
            df_last_plot = get_trend_data(l_s, l_e, " (Ano Passado)")
            if not df_last_plot.empty: plot_dfs.append(df_last_plot)
            
        if show_forecast_chart:
            df_fcst_plot = get_trend_data(c_s, c_e, " (Previsão)", max_actual_date=ref_datetime, is_forecast_src=True)
            if not df_fcst_plot.empty:
                if not df_main.empty:
                    last_points = []
                    for g in df_fcst_plot['Grupo'].unique():
                        g_main = df_main[df_main['Grupo'] == g]
                        if not g_main.empty:
                            last_row = g_main.iloc[-1].copy()
                            last_row['Traço'] = last_row['Grupo'] + " (Previsão)"
                            last_points.append(pd.DataFrame([last_row]))
                    if last_points:
                        df_fcst_plot = pd.concat(last_points + [df_fcst_plot], ignore_index=True).sort_values(['Grupo', 'Dia']).reset_index(drop=True)
                plot_dfs.append(df_fcst_plot)

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
                            first_fcst_val_map[g] = df_plot_trend.loc[mask, 'Vendas'].iloc[0]
                
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
                meta_dfs = [build_goal_trend(g, c_s, c_e, cumulative_mode) for g in canais_grafico]
                meta_dfs = [m for m in meta_dfs if not m.empty]
                if meta_dfs:
                    df_plot_trend = pd.concat([df_plot_trend] + meta_dfs, ignore_index=True)

            df_plot_trend['Formatado'] = df_plot_trend['Vendas'].apply(format_br)
            df_plot_trend['Data_Str'] = df_plot_trend['Data_Real'].dt.strftime('%d/%m/%Y')
            
            fig_trend = px.line(df_plot_trend, x='Dia', y='Vendas', color='Traço', markers=True)
            
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
                    
            fig_trend.update_traces(hovertemplate="<b>Data Original: %{customdata[1]}</b><br>Vendas: %{customdata[0]}<extra></extra>",
                                    customdata=df_plot_trend[['Formatado', 'Data_Str']])
            fig_trend.update_layout(margin=dict(t=10, b=0, l=0, r=0), xaxis_title="Dias Decorridos", yaxis_title=f"Vendas ({tipo_graf_tend})")

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
                    x_now = (ref_datetime - c_s).days + 1
                    x_end = (c_e - c_s).days + 1
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
        else:
            st.info("Sem dados para o gráfico de tendência.")


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
            
            tipo_filtro_mapa = st.radio(f"Nível de Filtro:", ["Grupos de Canais", "Canais Específicos"], horizontal=True, key=f"t2_rad_{map_id}")
            
            if tipo_filtro_mapa == "Grupos de Canais":
                grupos_sel_mapa = st.multiselect(f"Selecione os Grupos:", ['Digital', 'Franquias', 'Outros', 'Nacional', 'CDT'], default=[default_group], key=f"t2_grp_sel_{map_id}")
                canais_mapa_alvo = []
                for g in grupos_sel_mapa:
                    canais_mapa_alvo.extend(group_map[g])
                canais_mapa_alvo = list(set(canais_mapa_alvo))
            else:
                opcoes_canais_brutos = sorted([str(c) for c in df_raw['tipo_venda'].dropna().unique()])
                canais_mapa_raw = st.multiselect(f"Selecione os Canais:", options=opcoes_canais_brutos, default=opcoes_canais_brutos[:2] if opcoes_canais_brutos else [], key=f"t2_can_sel_{map_id}")
                canais_mapa_alvo = [c.lower() for c in canais_mapa_raw]
            
            mask_map = (df['data_venda'] >= c_s) & (df['data_venda'] <= ref_datetime) & (df['tipo_venda'].str.lower().isin(canais_mapa_alvo))
            df_map = df.loc[mask_map].copy()
            
            if not df_map.empty:
                df_map['uf'] = df_map['uf'].str.upper()
                uf_sales = df_map.groupby('uf')['Vendas'].sum().reset_index()
                total_map_sales = uf_sales['Vendas'].sum()
                
                if brazil_geo:
                    fig_map = px.choropleth(
                        uf_sales, geojson=brazil_geo, locations='uf', featureidkey='properties.sigla',
                        color='Vendas', color_continuous_scale="Blues"
                    )
                    fig_map.update_geos(fitbounds="locations", visible=False)
                    fig_map.update_traces(customdata=[format_br(v) for v in uf_sales['Vendas']], hovertemplate="<b>%{location}</b><br>Vendas: %{customdata}<extra></extra>")
                    fig_map.update_layout(margin={"r":0,"t":20,"l":0,"b":0})
                    st.plotly_chart(fig_map, use_container_width=True, key=f"plotly_map_{map_id}")
                else:
                    st.warning("Mapa do Brasil não carregado. Exibindo apenas barras.")
                
                df_sorted = uf_sales.sort_values(by='Vendas', ascending=True).copy()
                df_sorted["Perc"] = (df_sorted["Vendas"] / total_map_sales * 100).round(1).astype(str) + "%"
                df_sorted["Vendas_Formatadas"] = df_sorted["Vendas"].apply(format_br) + " (" + df_sorted["Perc"] + ")"
                
                fig_bar_uf = px.bar(df_sorted, x='Vendas', y='uf', orientation='h', title="Ranking por UF", text="Vendas_Formatadas")
                fig_bar_uf.update_traces(textposition='outside', cliponaxis=False, hovertemplate="<b>%{y}</b><br>Vendas: %{text}<extra></extra>")
                fig_bar_uf.update_layout(margin={"r":80,"t":40,"l":0,"b":0}, yaxis_title="")
                st.plotly_chart(fig_bar_uf, use_container_width=True, key=f"plotly_bar_{map_id}")
            else:
                st.info("Nenhuma venda encontrada para os filtros selecionados.")

    render_map_column(col_map_left, "1", "Digital")
    render_map_column(col_map_right, "2", "Franquias")


# =====================================================================
# TAB 3: ANÁLISE DE INVESTIMENTO
# =====================================================================
with tab3:
    st.header("Análise de Investimento")
    st.info(f"**Status do Período ({view_option}):** Decorridos **{e_days_c} de {t_days_c} dias** no calendário. | **Dias Úteis Decorridos:** Atual: {w_ela_c} | Anterior: {w_ela_p} | Ano Passado: {w_ela_l}")
    
    col_filt1, col_filt2, col_filt3 = st.columns(3)
    
    opcoes_canais_inv = sorted([str(c) for c in df_invest_raw['canal'].dropna().unique()])
    canais_invest = col_filt1.multiselect("Canal:", options=opcoes_canais_inv, default=opcoes_canais_inv, key='t3_can_inv')
    categorias_invest = col_filt2.multiselect("Categoria:", ["Branding", "Leads", "Venda"], default=["Branding", "Leads", "Venda"], key='t3_cat_inv')
    
    todas_plataformas = ["Google", "Meta", "TikTok", "Adsplay", "Actionpay", "CRM"]
    plataformas_invest = col_filt3.multiselect("Plataforma:", todas_plataformas, default=todas_plataformas, key='t3_plat_inv')
    
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
    df_invest_global = df_invest.copy()
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
        
        # Display the true Global Pacing percentage for the top-level parent rows
        if not is_sub and goal_col and df_global is not None:
            m_c_global = get_inv_metrics(df_global, None)[metric_idx]
            meta_p = get_prorated_goal(df_goals, c_s, ref_datetime, goal_col)
            meta_t = get_prorated_goal(df_goals, c_s, c_e, goal_col)
            
            if meta_p > 0:
                val_str_p = format_money(meta_p) if is_money else format_br(meta_p)
                pct_p = f"{val_str_p} ({(m_c_global / meta_p * 100):.1f}% Global)"
            if meta_t > 0:
                val_str_t = format_money(meta_t) if is_money else format_br(meta_t)
                pct_t = f"{val_str_t} ({(m_c_global / meta_t * 100):.1f}% Global)"
        
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

    # ---- controls row 1: Plataforma | Conjunto | Métrica ----
    col_cf1, col_cf2, col_cf3 = st.columns(3)
    plataforma_camp = col_cf1.selectbox("Plataforma:", ["Google", "Meta", "TikTok", "CRM"], key='t4_plat')
    sel_opts = ["Campanhas individuais", "Todas", "Top 5", "Bottom 5"] + GROUP_NAMES
    sel_tipo = col_cf2.selectbox("Conjunto:", sel_opts, key='t4_seltype')

    crm_is_selected = (plataforma_camp == "CRM")
    group_mode = sel_tipo in GROUP_NAMES

    if group_mode or not crm_is_selected:
        metric_opts = ["Custo", "CPA", "Eventos de Compra"]
    else:
        metric_opts = ["Eventos de Compra"]
    metrica_camp = col_cf3.radio("Métrica:", metric_opts, horizontal=True, key='t4_metric')
    metric_col = {"Custo": "cost", "CPA": "cpa", "Eventos de Compra": "purchases"}[metrica_camp]

    # ---- build the period-bounded campaign universe ----
    #   group_mode   -> cross-platform (group rules span platforms; e.g. affiliate cpc).
    #   CRM          -> GA rows matching CRM source patterns; no cost.
    #   paid (G/M/T) -> that platform's cost-table campaigns, plus their GA purchases.
    # Restricting to the selected period (and platform) is what hides campaigns with no
    # data in the window and campaigns from other platforms.
    ga_p = ga_vendas[(ga_vendas['date'] >= cmp_start) & (ga_vendas['date'] <= cmp_end)].copy()
    cost_p = camp_cost[(camp_cost['date'] >= cmp_start) & (camp_cost['date'] <= cmp_end)].copy()

    if group_mode:
        cost_scope, ga_scope = cost_p, ga_p
    elif crm_is_selected:
        ga_scope = ga_p[_crm_mask_t4(ga_p)] if not ga_p.empty else ga_p
        cost_scope = cost_p.iloc[0:0]
    else:
        cost_scope = cost_p[cost_p['plataforma'] == plataforma_camp]
        _plat_names = set(cost_scope['campaign_name'].dropna().unique())
        ga_scope = ga_p[ga_p['session_campaign_name'].isin(_plat_names)] if not ga_p.empty else ga_p

    _cost_by = cost_scope.groupby('campaign_name')['cost'].sum() if not cost_scope.empty else pd.Series(dtype=float)
    _purch_by = ga_scope.groupby('session_campaign_name')['conversions'].sum() if not ga_scope.empty else pd.Series(dtype=float)
    _src_by = (ga_scope.groupby('session_campaign_name')['session_source_medium']
               .apply(lambda s: set(x.lower() for x in s.dropna()))
               if not ga_scope.empty else pd.Series(dtype=object))

    _uni_names = sorted(set(_cost_by.index) | set(_purch_by.index))
    uni = pd.DataFrame({'campaign_name': _uni_names})
    uni['cost'] = uni['campaign_name'].map(_cost_by).fillna(0.0)
    uni['purchases'] = uni['campaign_name'].map(_purch_by).fillna(0.0)
    uni['cpa'] = uni['cost'] / uni['purchases'].replace(0, np.nan)
    uni['srcs'] = uni['campaign_name'].map(lambda c: _src_by.get(c, set()))

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
            st.caption("ℹ️ CRM ainda não tem custo no banco — apenas eventos de compra (filtrados por "
                       "session_source_medium).")

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

            # purchases from the GA scope (already platform/CRM-filtered above)
            purch_f = ga_scope[ga_scope['session_campaign_name'].isin(campanhas_sel)].copy()
            purch_f = purch_f.rename(columns={'session_campaign_name': 'campaign_name', 'conversions': 'purchases'})

            def _bucketize(dframe, col):
                if dframe.empty:
                    return pd.DataFrame(columns=keys + ['bucket', col])
                g = dframe.groupby(keys + [pd.Grouper(key='date', freq=freq)])[col].sum().reset_index()
                return g.rename(columns={'date': 'bucket'})

            cost_b = _bucketize(cost_f, 'cost')
            purch_b = _bucketize(purch_f, 'purchases')
            merge_on = keys + ['bucket']
            data = pd.merge(cost_b, purch_b, on=merge_on, how='outer')
            for _c in ['cost', 'purchases']:
                if _c not in data.columns:
                    data[_c] = 0.0
            data[['cost', 'purchases']] = data[['cost', 'purchases']].fillna(0.0)
            data = data.sort_values(merge_on)

            if is_acum and not data.empty:
                if per_campaign:
                    data['cost'] = data.groupby('campaign_name')['cost'].cumsum()
                    data['purchases'] = data.groupby('campaign_name')['purchases'].cumsum()
                else:
                    data['cost'] = data['cost'].cumsum()
                    data['purchases'] = data['purchases'].cumsum()

            data['cpa'] = data['cost'] / data['purchases'].replace(0, np.nan)
            metric_label = {"Custo": "Custo (R$)", "CPA": "CPA (R$)",
                            "Eventos de Compra": "Eventos de Compra"}[metrica_camp]

            # ---- summary metrics, ABOVE the chart, separated and colour-coded ----
            tot_cost = float(cost_f['cost'].sum()) if not cost_f.empty else 0.0
            tot_purch = float(purch_f['purchases'].sum()) if not purch_f.empty else 0.0
            cpa_avg = (tot_cost / tot_purch) if tot_purch > 0 else None
            has_cost = not (crm_is_selected and not group_mode)

            def _metric_card(col, label, value, color):
                col.markdown(
                    f"<div style='border-left:5px solid {color};padding:4px 14px;margin-bottom:6px;'>"
                    f"<div style='font-size:0.78rem;color:#6b7280;text-transform:uppercase;letter-spacing:.03em'>{label}</div>"
                    f"<div style='font-size:1.5rem;font-weight:700;color:{color};line-height:1.25'>{value}</div></div>",
                    unsafe_allow_html=True)

            if has_cost:
                mc1, mc2, mc3 = st.columns(3)
                _metric_card(mc1, "Custo total", format_money(tot_cost), "#2563eb")
                _metric_card(mc2, "Eventos de compra", format_br(tot_purch), "#16a34a")
                _metric_card(mc3, "CPA médio",
                             (format_money(cpa_avg) if cpa_avg is not None else "N/A (0 compras)"), "#d97706")
            else:
                mc1, _mc2 = st.columns([1, 2])
                _metric_card(mc1, "Eventos de compra", format_br(tot_purch), "#16a34a")
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