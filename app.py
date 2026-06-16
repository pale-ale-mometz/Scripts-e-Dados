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
st.set_page_config(page_title="MySQL Dashboard", page_icon="📊", layout="wide")

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
    except:
        pass
    return ''

def parse_br_float(val):
    """Bulletproof string-to-float converter for messy database varchars and doubles"""
    if pd.isna(val): return 0.0
    if isinstance(val, (int, float)): return float(val)
    
    s = str(val).upper().replace('R$', '').replace('R', '').replace('$', '').strip()
    if s in ['NAN', 'NONE', '']: return 0.0
    
    # Handle Brazilian (1.500,50) vs US (1,500.50) formats safely
    if '.' in s and ',' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
        
    try:
        return float(s)
    except ValueError:
        return 0.0

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
    start_of_last_year = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    query = f"SELECT data_venda, uf, tipo_venda, Vendas FROM RESUMO_VENDAS_DIARIAS WHERE data_venda >= '{start_of_last_year}'"
    df = conn.query(query)
    df['data_venda'] = pd.to_datetime(df['data_venda'])
    df['tipo_venda'] = df['tipo_venda'].fillna("Não Informado").astype(str).str.strip().str.title()
    return df

@st.cache_data(ttl=43200) 
def load_invest_data():
    start_of_last_year = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    query = f"SELECT data_investimento, canal, plataforma, branding, leads, venda, vol_leads, vol_vendas FROM RESUMO_INVESTIMENTO_DIARIO WHERE data_investimento >= '{start_of_last_year}'"
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
        
        # Crucial Fix: format='mixed' and dayfirst=True guarantees dates like "15/05/2026" don't turn into NaT and get dropped
        df_goals['Data_Corrigida'] = pd.to_datetime(df_goals['Data_Corrigida'].astype(str).str.strip(), format='mixed', dayfirst=True, errors='coerce')
        df_goals = df_goals.dropna(subset=['Data_Corrigida'])
        df_goals['mes_ano'] = df_goals['Data_Corrigida'].dt.to_period('M').dt.to_timestamp()
        
        # Aggressively force ALL metric columns to be clean floats to prevent TypeErrors
        for col in df_goals.columns:
            if col not in ['Data_Corrigida', 'mes_ano']:
                df_goals[col] = df_goals[col].apply(parse_br_float)
                
        # SMART FIX: Brazilian decimal bug auto-corrector for 'double' sales columns
        if 'CDT (Total)' in df_goals.columns and df_goals['CDT (Total)'].max() > 0 and df_goals['CDT (Total)'].max() < 1000:
            for col in df_goals.columns:
                if col not in ['Data_Corrigida', 'mes_ano', 'Investimento Total'] and pd.api.types.is_numeric_dtype(df_goals[col]):
                    df_goals[col] = df_goals[col] * 1000
                    
        return df_goals
    except Exception as e:
        st.error(f"Erro no módulo de metas: {e}")
        return pd.DataFrame()

# =============================================================================
# 4. IN-APP PROPHET FORECASTING ENGINE
# =============================================================================
SPEND_ALLOCATION = {"website": 0.425, "app do filiado": 0.425, "televendas": 0.15}
TRAINING_START = {
    "franquias": "2025-01-01", "website": "2025-09-01", "app do filiado": "2025-09-01",
    "televendas": "2025-09-01", "mgm": "2026-02-01", "outros": "2025-01-01"
}
MEGA_CAMPAIGNS = ["2026-04-22"]
channel_configs = {
    "franquias":      {'use_spend': False, 'working_days': 5, 'floor': 10, 'weekly_fourier': 5, 'cps': 0.05, 'hps': 5.0,  'seasonality_mode': 'additive',       'use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'force_nonnegative_spend': False, 'is_saturday_prior_scale': 100.0},
    "website":        {'use_spend': True,  'working_days': 7, 'floor': 50, 'weekly_fourier': 3, 'cps': 0.3,  'hps': 1.0,  'seasonality_mode': 'multiplicative','use_peak_season': True,  'spend_lag': 0, 'spend_prior_scale': 0.5, 'force_nonnegative_spend': True,  'is_saturday_prior_scale': 10.0,  'spend_lookback_weeks': 4},
    "app do filiado": {'use_spend': True,  'working_days': 7, 'floor': 20, 'weekly_fourier': 3, 'cps': 0.5,  'hps': 10.0, 'seasonality_mode': 'multiplicative','use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'force_nonnegative_spend': True,  'is_saturday_prior_scale': 10.0},
    "televendas":     {'use_spend': True,  'working_days': 5, 'floor': 10, 'weekly_fourier': 3, 'cps': 0.5,  'hps': 10.0, 'seasonality_mode': 'multiplicative','use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'force_nonnegative_spend': True,  'is_saturday_prior_scale': 10.0},
    "mgm":            {'use_spend': False, 'working_days': 7, 'floor': 5,  'weekly_fourier': 5, 'cps': 0.05, 'hps': 1.0,  'seasonality_mode': 'additive',       'use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'force_nonnegative_spend': False, 'is_saturday_prior_scale': 100.0},
    "outros":         {'use_spend': False, 'working_days': 7, 'floor': 5,  'weekly_fourier': 5, 'cps': 0.3,  'hps': 1.0,  'seasonality_mode': 'additive',       'use_peak_season': False, 'spend_lag': 0, 'spend_prior_scale': 0.5, 'force_nonnegative_spend': False, 'is_saturday_prior_scale': 100.0},
}
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
    m = Prophet(
        yearly_seasonality=False, daily_seasonality=False, weekly_seasonality=False,
        holidays=holidays_df, holidays_prior_scale=config["hps"],
        changepoint_prior_scale=config["cps"], seasonality_mode=config.get("seasonality_mode", "additive"),
        interval_width=0.90, mcmc_samples=0
    )
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

@st.cache_data(ttl=43200, show_spinner="🤖 Treinando modelos de Inteligência Artificial para gerar previsões de vendas (Prophet)...")
def generate_prophet_forecast(ref_date_str):
    if not PROPHET_AVAILABLE: return pd.DataFrame()
    
    try:
        df_raw = conn.query("SELECT ds, channel_group, y, spend_total FROM vw_prophet_input WHERE y IS NOT NULL ORDER BY ds")
    except Exception:
        return pd.DataFrame()
        
    if df_raw.empty: return pd.DataFrame()

    df_raw["ds"] = pd.to_datetime(df_raw["ds"])
    df_raw["y"] = pd.to_numeric(df_raw["y"], errors="coerce").fillna(0)
    df_raw["spend_total"] = pd.to_numeric(df_raw["spend_total"], errors="coerce").fillna(0)

    df_raw["spend_channel"] = 0.0
    for ch, weight in SPEND_ALLOCATION.items():
        mask = df_raw["channel_group"] == ch
        df_raw.loc[mask, "spend_channel"] = df_raw.loc[mask, "spend_total"] * weight

    holidays = make_holidays(years=[2025, 2026])

    all_production_forecasts = []
    
    for channel, config in channel_configs.items():
        np.random.seed(42)
        df_channel = df_raw[df_raw["channel_group"] == channel].copy()
        df_channel = df_channel[df_channel["ds"] >= pd.Timestamp(TRAINING_START[channel])].sort_values("ds").reset_index(drop=True)
        if len(df_channel) < 60: continue

        df_channel = add_working_day(df_channel, config["working_days"])
        df_channel = add_calendar_regressors(df_channel)
        df_channel["spend_workday_base"] = df_channel["spend_channel"] * df_channel["is_working_day"]

        holidays_ch = get_channel_holidays(channel, holidays)
        
        if config["use_spend"] and config.get("force_nonnegative_spend", False):
            df_channel["spend_workday"] = df_channel["spend_workday_base"].shift(config.get("spend_lag", 0)).fillna(0)
            try:
                m_check = build_prophet(config, holidays_ch)
                m_check.fit(df_channel[train_cols_for(config)])
                coefs = regressor_coefficients(m_check)
                spend_row = coefs[coefs["regressor"] == "spend_workday"]
                if not spend_row.empty and float(spend_row["coef"].iloc[0]) < 0:
                    config = {**config, "use_spend": False}
            except:
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
            f["channel_group"] = channel.title()
            f["scenario"] = scenario_name
            f["spend_assumed"] = spend_assumed_series
            return f

        channel_lookback = int(config.get("spend_lookback_weeks", 8))
        
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

def get_goal_for_group(start_d, end_d, grupo_nome):
    col_map = {
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
    cols = col_map.get(grupo_nome.strip(), [])
    total = 0.0
    for c in cols:
        total += get_prorated_goal(df_goals, start_d, end_d, c)
    return total

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

now_utc = datetime.datetime.utcnow()
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

tab1, tab2, tab3 = st.tabs(["📈 Desempenho de Vendas", "🗺️ Mapa Regional (UF)", "💰 Investimento"])

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
        label_grupo = f"📁 {nome_exibicao.upper()}" if mostrar_detalhes else nome_exibicao
        
        meta_parc = get_goal_for_group(c_s, ref_datetime, grupo)
        meta_tot = get_goal_for_group(c_s, c_e, grupo)
        
        row_dict = {
            'Grupo': label_grupo,
            'Atual': agg_c[grupo],
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
                    'Grupo': f"\xa0\xa0\xa0\xa0\xa0\xa0└─ {ch.title()}",
                    'Atual': v_c,
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
                
    df_triplet = pd.DataFrame(rows)
    
    display_cols = ['Grupo', 'Atual', 'Meta (Parcial)', 'Meta (Total)', 'vs Anterior (Parcial)', 'vs Anterior (Total)']
    if view_option != "Ano Atual":
        display_cols.extend(['vs Ano Passado (Parcial)', 'vs Ano Passado (Total)'])
    if mostrar_previsao:
        display_cols.extend(['Previsão (Faltante)', 'Previsão (Total Projetado)'])
        
    df_table_fmt = df_triplet[display_cols].copy()
    df_table_fmt['Atual'] = df_table_fmt['Atual'].apply(format_br)
    
    color_cols = [c for c in display_cols if 'vs ' in c]
    styled_df = df_table_fmt.style.map(color_deltas, subset=color_cols)
    st.table(styled_df)

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
                        last_hist_map[g] = g_m.loc[g_m['Dia'].idxmax(), 'Vendas'] if tipo_graf_tend != "Acumulado" else g_m['Vendas'].sum()
                
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

            df_plot_trend['Formatado'] = df_plot_trend['Vendas'].apply(format_br)
            df_plot_trend['Data_Str'] = df_plot_trend['Data_Real'].dt.strftime('%d/%m/%Y')
            
            fig_trend = px.line(df_plot_trend, x='Dia', y='Vendas', color='Traço', markers=True)
            
            for trace in fig_trend.data:
                if "(Anterior)" in trace.name or "(Ano Passado)" in trace.name:
                    trace.line.dash = 'dash'
                    trace.opacity = 0.5
                elif "(Previsão)" in trace.name:
                    trace.line.dash = 'dot'
                    
            fig_trend.update_traces(hovertemplate="<b>Data Original: %{customdata[1]}</b><br>Vendas: %{customdata[0]}<extra></extra>",
                                    customdata=df_plot_trend[['Formatado', 'Data_Str']])
            fig_trend.update_layout(margin=dict(t=0, b=0, l=0, r=0), xaxis_title="Dias Decorridos", yaxis_title=f"Vendas ({tipo_graf_tend})")
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
        has_children = detalhe_plat or detalhe_tipo
        label_parent = f"📁 {m_name.upper()}" if has_children else m_name
        
        row_parent = compute_row(label_parent, df_c_inv, df_pp_inv, df_pf_inv, df_lp_inv, df_lf_inv, m_idx, df_global=df_c_global, goal_col=m_goal)
        rows_inv.append(row_parent)
        
        if detalhe_plat and not detalhe_tipo:
            for plat in plataformas_invest:
                p_df_c = df_c_inv[df_c_inv['plataforma'] == plat]
                p_df_pp = df_pp_inv[df_pp_inv['plataforma'] == plat]
                p_df_pf = df_pf_inv[df_pf_inv['plataforma'] == plat]
                p_df_lp = df_lp_inv[df_lp_inv['plataforma'] == plat]
                p_df_lf = df_lf_inv[df_lf_inv['plataforma'] == plat]
                
                row_p = compute_row(f"\xa0\xa0\xa0\xa0\xa0\xa0└─ {plat}", p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx, is_sub=True)
                if row_p['_val_c'] == 0 and row_p['_val_pf'] == 0 and row_p['_val_lf'] == 0: continue
                rows_inv.append(row_p)
                
        elif detalhe_tipo and not detalhe_plat:
            for cat in cat_cols:
                row_c = compute_row(f"\xa0\xa0\xa0\xa0\xa0\xa0└─ {cat.title()}", df_c_inv, df_pp_inv, df_pf_inv, df_lp_inv, df_lf_inv, m_idx, cat=cat, is_sub=True)
                if row_c['_val_c'] == 0 and row_c['_val_pf'] == 0 and row_c['_val_lf'] == 0: continue
                rows_inv.append(row_c)
                
        elif detalhe_plat and detalhe_tipo:
            for plat in plataformas_invest:
                p_df_c = df_c_inv[df_c_inv['plataforma'] == plat]
                p_df_pp = df_pp_inv[df_pp_inv['plataforma'] == plat]
                p_df_pf = df_pf_inv[df_pf_inv['plataforma'] == plat]
                p_df_lp = df_lp_inv[df_lp_inv['plataforma'] == plat]
                p_df_lf = df_lf_inv[df_lf_inv['plataforma'] == plat]
                
                row_p = compute_row(f"\xa0\xa0\xa0\xa0\xa0\xa0└─ 📁 {plat.upper()}", p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx, is_sub=True)
                if row_p['_val_c'] == 0 and row_p['_val_pf'] == 0 and row_p['_val_lf'] == 0: continue
                rows_inv.append(row_p)
                
                for cat in cat_cols:
                    row_c = compute_row(f"\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0└─ {cat.title()}", p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx, cat=cat, is_sub=True)
                    if row_c['_val_c'] == 0 and row_c['_val_pf'] == 0 and row_c['_val_lf'] == 0: continue
                    rows_inv.append(row_c)
    
    df_inv_table = pd.DataFrame(rows_inv)
    is_eff_map = df_inv_table['_is_eff'].to_dict()
    
    display_cols_inv = ['Métrica', 'Atual', 'Meta (Parcial)', 'Meta (Total)', 'vs Anterior (Parcial)', 'vs Anterior (Total)']
    if view_option != "Ano Atual":
        display_cols_inv.extend(['vs Ano Passado (Parcial)', 'vs Ano Passado (Total)'])
        
    df_inv_fmt = df_inv_table[display_cols_inv].copy()
    
    def style_inv_table(row):
        styles = [''] * len(row)
        is_efficiency = is_eff_map[row.name]
        
        for i, col in enumerate(row.index):
            if 'vs ' in col:
                val = row[col]
                if isinstance(val, str) and '(' in val:
                    try:
                        pct_str = val.split('(')[1].split('%')[0].replace('+', '')
                        if pct_str != 'N/A':
                            pct = float(pct_str)
                            intensity = min(abs(pct) / 50.0, 1.0)
                            alpha = 0.1 + (intensity * 0.35) 
                            
                            if is_efficiency:
                                if pct < 0:
                                    styles[i] = f'background-color: rgba(39, 174, 96, {alpha}); color: #000;'
                                elif pct > 0:
                                    styles[i] = f'background-color: rgba(231, 76, 60, {alpha}); color: #000;'
                            else:
                                if pct > 0:
                                    styles[i] = f'background-color: rgba(39, 174, 96, {alpha}); color: #000;'
                                elif pct < 0:
                                    styles[i] = f'background-color: rgba(231, 76, 60, {alpha}); color: #000;'
                    except:
                        pass
        return styles

    styled_inv_df = df_inv_fmt.style.map(color_deltas, subset=[c for c in display_cols_inv if 'vs ' in c]).apply(style_inv_table, axis=1)
    st.table(styled_inv_df)

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