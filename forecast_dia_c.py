# =============================================================================
# SALES FORECASTING WITH FACEBOOK PROPHET
# Input: vw_diario_vendas_custos (MySQL) or exported CSV
# =============================================================================

# --- INSTALL (run once in your terminal) -------------------------------------
# pip install prophet pandas sqlalchemy pymysql matplotlib

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics

# =============================================================================
# CAMPAIGN DATES CONFIG
# List every date (past and future) on which each campaign runs.
# Past dates are used to fit the regressor coefficient.
# Future dates tell the model to apply that coefficient during forecasting.
# Format: "YYYY-MM-DD"
# =============================================================================

DUPLA_DATES = [
    # --- past campaign days (add any historical Dupla dates here) ---
    # "2025-MM-DD",
    # --- confirmed future ---
    "2026-04-22",
]

UNO_DATES = [
    # --- past campaign days (add any historical Uno dates here) ---
    # "2025-MM-DD",
    # --- confirmed future ---
    "2026-04-23",
    "2026-04-24",
    "2026-04-25",
    "2026-04-26",
    "2026-04-27",
    "2026-04-28",
    "2026-04-29",
    "2026-04-30",
]

# Convert to sets of Timestamps for fast lookup
_dupla_dates = pd.to_datetime(DUPLA_DATES)
_uno_dates   = pd.to_datetime(UNO_DATES)

# =============================================================================
# PRODUCTION FORECAST WINDOW
# Hardcoded to the exact period requested: 2026-04-22 → 2026-04-30.
# Training data is expected to run up to 2026-04-21 (i.e. the CSV exported
# from vw_diario_vendas_custos should cover up to and including 2026-04-21).
# =============================================================================

FORECAST_START = pd.Timestamp("2026-04-22")
FORECAST_END   = pd.Timestamp("2026-04-30")


# =============================================================================
# 1. LOAD DATA
#    Choose Option A (MySQL) or Option B (CSV) — comment out the other one
# =============================================================================

# --- Option A: Load directly from MySQL --------------------------------------
# from sqlalchemy import create_engine
#
# engine = create_engine(
#     "mysql+pymysql://<USER>:<PASSWORD>@<HOST>:<PORT>/mysql_bi_g"
# )
# df_raw = pd.read_sql("SELECT * FROM vw_diario_vendas_custos ORDER BY ds", engine)

# --- Option B: Load from CSV (export view from DBeaver as CSV first) ---------
df_raw = pd.read_csv("vw_diario_vendas_custos.csv")

df_raw = df_raw.rename(columns={
    "custo_total": "spend_total",
    "eh_dia_util": "is_working_day",
})
df_raw["ds"] = pd.to_datetime(df_raw["ds"])
df_raw["weekday_iso"]   = df_raw["ds"].dt.isocalendar().day
df_raw["month_num"]     = df_raw["ds"].dt.month
df_raw["day_of_month"]  = df_raw["ds"].dt.day
df_raw["week_of_month"] = ((df_raw["day_of_month"] - 1) // 7) + 1

# =============================================================================
# 2. PREPARE DATA
# =============================================================================

df = df_raw.copy()

# Ensure correct types
df["ds"]             = pd.to_datetime(df["ds"])
df["y"]              = pd.to_numeric(df["y"],              errors="coerce")
df["spend_total"]    = pd.to_numeric(df["spend_total"],    errors="coerce").fillna(0)
df["is_working_day"] = pd.to_numeric(df["is_working_day"], errors="coerce").fillna(0)
df["weekday_iso"]    = pd.to_numeric(df["weekday_iso"],    errors="coerce")
df["month_num"]      = pd.to_numeric(df["month_num"],      errors="coerce")
df["day_of_month"]   = pd.to_numeric(df["day_of_month"],   errors="coerce")
df["week_of_month"]  = pd.to_numeric(df["week_of_month"],  errors="coerce")

# Single Saturday dummy — uses all ~52 Saturday observations for a stable
# coefficient estimate.
df["is_saturday"] = (df["ds"].dt.dayofweek == 5).astype(int)

# spend_workday = spend_total × is_working_day
# Zeroes out spend on weekends so the Saturday dummy works without
# interference from the positive spend coefficient on low-spend days.
df["spend_workday"] = df["spend_total"] * df["is_working_day"]

# log_spend_workday — log1p transform of spend_workday.
# Captures diminishing returns: the marginal impact of each extra R$ of spend
# shrinks as spend grows. This prevents wild extrapolation when forecast spend
# is 7–10× higher than the training-period average.
df["log_spend_workday"] = np.log1p(df["spend_workday"])

# --- Campaign regressors -----------------------------------------------------
# Column names in the view are "dupla" and "uno".
# If already present in the CSV (exported from updated view), use them directly.
# Otherwise derive from the config lists above (e.g. first run before migration).
if "dupla" in df.columns:
    df["dupla"] = pd.to_numeric(df["dupla"], errors="coerce").fillna(0).astype(int)
else:
    df["dupla"] = df["ds"].isin(_dupla_dates).astype(int)

if "uno" in df.columns:
    df["uno"] = pd.to_numeric(df["uno"], errors="coerce").fillna(0).astype(int)
else:
    df["uno"] = df["ds"].isin(_uno_dates).astype(int)

print(f"  dupla — {df['dupla'].sum()} flagged training days")
print(f"  uno   — {df['uno'].sum()} flagged training days")

# post_dupla — demand exhaustion lag.
# = 1 on the working day immediately following a Dupla campaign day.
# The model will fit a negative coefficient, capturing the market-saturation
# effect: a big Dupla day depletes the addressable pool for the next day.
# Only fires on working days (weekends don't suffer the same carry-over).
df["post_dupla"] = (
    df["dupla"].shift(1).fillna(0).astype(int)   # previous day was Dupla
    * df["is_working_day"]                         # only on working days
)
print(f"  post_dupla — {df['post_dupla'].sum()} flagged training days")

# Sort and reset index
df = df.sort_values("ds").reset_index(drop=True)

# Quick sanity check
print("=== Data Overview ===")
print(f"Date range : {df['ds'].min().date()}  →  {df['ds'].max().date()}")
print(f"Total rows : {len(df)}")
print(f"Total sales: {df['y'].sum():,.0f}")
print(f"Zero-sales days: {(df['y'] == 0).sum()}")
print(f"Missing y  : {df['y'].isna().sum()}")
print(df.head())

# Check for extreme outliers
threshold = df["y"].quantile(0.99)
print(f"\n99th percentile: {threshold:.0f} sales")
print("Top outlier days:")
print(df[df["y"] > threshold][["ds", "y", "spend_total"]].to_string())

# =============================================================================
# 3. DEFINE BRAZILIAN HOLIDAYS
# =============================================================================

def make_holidays(years: list) -> pd.DataFrame:
    """Returns Brazilian national + moveable holidays and end-of-month markers.

    Notes:
    - fim_mes uses lower_window=-2 (2-day run-up) to capture subscription
      renewal build-up. This also covers quarter-end months adequately.
    - fim_trimestre was tested and removed: it competed with fim_mes on the
      same dates and diluted both effects.
    """
    records = []
    for y in years:
        # Fixed national holidays
        records += [
            {"ds": f"{y}-01-01", "holiday": "ano_novo"},
            {"ds": f"{y}-04-21", "holiday": "tiradentes"},
            {"ds": f"{y}-05-01", "holiday": "dia_trabalho"},
            {"ds": f"{y}-09-07", "holiday": "independencia"},
            {"ds": f"{y}-10-12", "holiday": "nossa_senhora"},
            {"ds": f"{y}-11-02", "holiday": "finados"},
            {"ds": f"{y}-11-15", "holiday": "proclamacao_republica"},
            {"ds": f"{y}-12-25", "holiday": "natal"},
        ]

        # End-of-month spike with 2-day run-up window
        for month in range(1, 13):
            last_day = (pd.Timestamp(year=y, month=month, day=1)
                        + pd.offsets.MonthEnd(0))
            if pd.Timestamp("2025-01-01") <= last_day <= pd.Timestamp("2026-05-31"):
                records.append({
                    "ds"           : str(last_day.date()),
                    "holiday"      : "fim_mes",
                    "lower_window" : -2,
                    "upper_window" :  0,
                })

    # Moveable holidays
    moveable = [
        {"ds": "2025-03-03", "holiday": "carnaval"},
        {"ds": "2025-03-04", "holiday": "carnaval"},
        {"ds": "2026-02-16", "holiday": "carnaval"},
        {"ds": "2026-02-17", "holiday": "carnaval"},
        {"ds": "2025-04-18", "holiday": "sexta_santa"},
        {"ds": "2026-04-03", "holiday": "sexta_santa"},
        {"ds": "2025-06-19", "holiday": "corpus_christi"},
        {"ds": "2026-06-04", "holiday": "corpus_christi"},
    ]

    holidays_df = pd.DataFrame(records + moveable)
    holidays_df["ds"] = pd.to_datetime(holidays_df["ds"])
    for col in ["lower_window", "upper_window"]:
        if col not in holidays_df.columns:
            holidays_df[col] = 0
        else:
            holidays_df[col] = holidays_df[col].fillna(0).astype(int)
    return holidays_df

holidays = make_holidays(years=[2025, 2026])

# =============================================================================
# 4. TRAIN / VALIDATION SPLIT
# =============================================================================

FORECAST_HORIZON = 30    # fixed window for validation / CV (do not change)
SALES_FLOOR      = 200

# Production window is fixed: 2026-04-22 → 2026-04-30 (9 days).
# Training data must cover up to 2026-04-21 for PROD_HORIZON to equal 9.
last_training_date = df["ds"].max()
PROD_HORIZON       = (FORECAST_END - last_training_date).days

if PROD_HORIZON < 1:
    raise ValueError(
        f"Training data ends on {last_training_date.date()} but FORECAST_START "
        f"is {FORECAST_START.date()}. Export a CSV that covers up to "
        f"{(FORECAST_START - pd.Timedelta(days=1)).date()} and re-run."
    )

print(f"\nProduction forecast: {FORECAST_START.date()} → {FORECAST_END.date()} ({PROD_HORIZON} days)")

cutoff_date = df["ds"].max() - pd.Timedelta(days=FORECAST_HORIZON)

df_train    = df[df["ds"] <= cutoff_date].copy()
df_val      = df[df["ds"] >  cutoff_date].copy()

# ------------------------------------------------------------------
# Data-derived Saturday / Sunday floors (training data only)
# ------------------------------------------------------------------
sat_floor = int(
    df_train[df_train["ds"].dt.dayofweek == 5]["y"].quantile(0.10)
)
sun_floor = int(
    df_train[df_train["ds"].dt.dayofweek == 6]["y"].quantile(0.25)
)
print(f"\nSaturday floor (10th pct of training Saturdays): {sat_floor:,} sales")
print(f"Sunday floor   (10th pct of training Sundays)  : {sun_floor:,} sales")
print(f"General sales floor                            : {SALES_FLOOR} sales")

print(f"\n=== Train/Val Split ===")
print(f"Train : {df_train['ds'].min().date()} → {df_train['ds'].max().date()}  ({len(df_train)} rows)")
print(f"Val   : {df_val['ds'].min().date()}   → {df_val['ds'].max().date()}    ({len(df_val)} rows)")

# =============================================================================
# HELPER: populate campaign columns on a future dataframe
# =============================================================================

def fill_campaign_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """Add dupla / uno columns to a future dataframe from the config lists."""
    frame["dupla"] = frame["ds"].isin(_dupla_dates).astype(int)
    frame["uno"]   = frame["ds"].isin(_uno_dates).astype(int)
    return frame

# =============================================================================
# 5 + 6 + 7 + 8. MODEL COMPARISON: with spend vs without spend
# =============================================================================

def build_and_evaluate(use_spend: bool, df_train: pd.DataFrame) -> dict:
    label = "WITH spend" if use_spend else "WITHOUT spend"
    print(f"\n--- Training evaluation model {label} ---")

    m = Prophet(
        yearly_seasonality      = False,
        weekly_seasonality      = False,
        daily_seasonality       = False,
        holidays                = holidays,
        holidays_prior_scale    = 10.0,
        changepoint_prior_scale = 0.3,
        n_changepoints          = 35,
        interval_width          = 0.90,
    )
    m.add_seasonality(name="weekly",  period=7,    fourier_order=5)
    m.add_seasonality(name="monthly", period=30.5, fourier_order=2)
    m.add_regressor("is_saturday", standardize=False, prior_scale=100.0)

    # Campaign regressors — always included regardless of spend variant.
    m.add_regressor("dupla",      standardize=False, prior_scale=10.0, mode="additive")
    m.add_regressor("uno",        standardize=False, prior_scale=10.0, mode="additive")
    # Exhaustion lag: negative coefficient expected (day-after Dupla dampening)
    m.add_regressor("post_dupla", standardize=False, prior_scale=10.0, mode="additive")

    train_cols = ["ds", "y", "is_saturday", "dupla", "uno", "post_dupla"]
    if use_spend:
        # log1p-transformed spend — prevents linear extrapolation outside training range
        m.add_regressor("log_spend_workday", standardize=True, prior_scale=0.5)
        train_cols.append("log_spend_workday")

    m.fit(df_train[train_cols])

    df_cv = cross_validation(
        m,
        initial  = "270 days",
        period   = "30 days",
        horizon  = "30 days",
        parallel = None
    )
    df_perf = performance_metrics(df_cv)

    print(f"  Avg MAE  : {df_perf['mae'].mean():.0f}")
    print(f"  Avg RMSE : {df_perf['rmse'].mean():.0f}")
    print(f"\n=== Cross-Validation Performance ({label}) ===")
    print(df_perf[["horizon", "mae", "mape", "rmse"]].to_string(index=False))

    return {"label": label, "model": m, "cv": df_cv, "perf": df_perf}


results_with    = build_and_evaluate(use_spend=True,  df_train=df_train)
results_without = build_and_evaluate(use_spend=False, df_train=df_train)

print("\n=== COMPARISON SUMMARY ===")
for r in [results_with, results_without]:
    print(f"{r['label']:20s}  MAE={r['perf']['mae'].mean():.0f}  RMSE={r['perf']['rmse'].mean():.0f}")

winner = min([results_with, results_without], key=lambda r: r["perf"]["mae"].mean())
print(f"\nWinner: {winner['label']}")

# =============================================================================
# EVALUATION FORECAST — validation metrics and plots
# =============================================================================

eval_model = winner["model"]

future_eval = eval_model.make_future_dataframe(
    periods         = FORECAST_HORIZON,
    freq            = "D",
    include_history = True
)
future_eval["is_saturday"] = (future_eval["ds"].dt.dayofweek == 5).astype(int)
future_eval["is_working_day_future"] = (future_eval["ds"].dt.dayofweek < 5).astype(int)

# Merge known campaign flags for historical rows; derive from config for future rows
future_eval = future_eval.merge(
    df[["ds", "dupla", "uno"]], on="ds", how="left"
)
# For future dates not in training data, derive from the config lists
mask_future = future_eval["dupla"].isna()
future_eval.loc[mask_future, "dupla"] = \
    future_eval.loc[mask_future, "ds"].isin(_dupla_dates).astype(int)
future_eval.loc[mask_future, "uno"] = \
    future_eval.loc[mask_future, "ds"].isin(_uno_dates).astype(int)
future_eval[["dupla", "uno"]] = \
    future_eval[["dupla", "uno"]].fillna(0).astype(int)

# post_dupla for eval dataframe: lag of dupla flag, working days only
future_eval["is_working_day_eval"] = (future_eval["ds"].dt.dayofweek < 5).astype(int)
future_eval["post_dupla"] = (
    future_eval["dupla"].shift(1).fillna(0).astype(int)
    * future_eval["is_working_day_eval"]
)
future_eval = future_eval.drop(columns=["is_working_day_eval"], errors="ignore")

if winner["label"] == "WITH spend":
    future_eval = future_eval.merge(
        df[["ds", "spend_total", "is_working_day"]], on="ds", how="left"
    )
    last_train = df_train["ds"].max()
    avg_spend  = df_train["spend_total"].tail(28).mean()
    future_eval.loc[future_eval["ds"] > last_train, "spend_total"]    = avg_spend
    future_eval.loc[future_eval["ds"] > last_train, "is_working_day"] = \
        future_eval.loc[future_eval["ds"] > last_train, "is_working_day_future"]
    future_eval["spend_workday"]     = \
        future_eval["spend_total"] * future_eval["is_working_day"]
    future_eval["log_spend_workday"] = np.log1p(future_eval["spend_workday"])

future_eval = future_eval.drop(columns=["is_working_day_future"], errors="ignore")

forecast_eval = eval_model.predict(future_eval)
forecast_eval["yhat"] = forecast_eval["yhat"].clip(lower=SALES_FLOOR)
forecast_eval.loc[forecast_eval["ds"].dt.dayofweek == 5, "yhat"] = \
    forecast_eval.loc[forecast_eval["ds"].dt.dayofweek == 5, "yhat"].clip(lower=sat_floor)
forecast_eval.loc[forecast_eval["ds"].dt.dayofweek == 6, "yhat"] = \
    forecast_eval.loc[forecast_eval["ds"].dt.dayofweek == 6, "yhat"].clip(lower=sun_floor)
forecast_eval["yhat_lower"] = forecast_eval["yhat_lower"].clip(lower=0)

# --- Validation metrics ------------------------------------------------------
val_forecast = forecast_eval[forecast_eval["ds"].isin(df_val["ds"])][
    ["ds", "yhat", "yhat_lower", "yhat_upper"]
]
val_merged = df_val[["ds", "y"]].merge(val_forecast, on="ds")

mae  = (val_merged["y"] - val_merged["yhat"]).abs().mean()
mape = ((val_merged["y"] - val_merged["yhat"]).abs()
        / val_merged["y"].replace(0, np.nan)).mean() * 100
rmse = np.sqrt(((val_merged["y"] - val_merged["yhat"]) ** 2).mean())

print(f"\n=== Evaluation Validation (last {FORECAST_HORIZON} days) ===")
print(f"MAE : {mae:.1f}  |  MAPE : {mape:.1f}%  |  RMSE : {rmse:.1f}")
print(f"(Saturday floor applied: {sat_floor:,})")

val_merged_full = df_val[["ds", "y", "is_working_day"]].merge(val_forecast, on="ds")
val_merged_full["dow"] = val_merged_full["ds"].dt.dayofweek

for day_type, lbl in [(1, "Working days"), (0, "Weekends/holidays")]:
    subset = val_merged_full[val_merged_full["is_working_day"] == day_type]
    if len(subset) == 0:
        continue
    mae_s  = (subset["y"] - subset["yhat"]).abs().mean()
    mape_s = ((subset["y"] - subset["yhat"]).abs()
               / subset["y"].replace(0, np.nan)).mean() * 100
    print(f"\n{lbl} (n={len(subset)}):")
    print(f"  MAE  : {mae_s:.0f}  |  MAPE : {mape_s:.1f}%")
    print(subset[["ds", "y", "yhat"]].to_string(index=False))

print("\n--- Weekend breakdown (Sat vs Sun) ---")
for dow, lbl in [(5, "Saturdays"), (6, "Sundays")]:
    subset = val_merged_full[val_merged_full["dow"] == dow]
    if len(subset) == 0:
        continue
    mae_s = (subset["y"] - subset["yhat"]).abs().mean()
    print(f"  {lbl} (n={len(subset)}): MAE={mae_s:.0f}")
    print(subset[["ds", "y", "yhat"]].to_string(index=False))

# =============================================================================
# PRODUCTION FORECAST — retrain winner on FULL dataset
# =============================================================================

print("\n--- Refitting winner on full dataset for production forecast ---")

m_prod = Prophet(
    yearly_seasonality      = False,
    weekly_seasonality      = False,
    daily_seasonality       = False,
    holidays                = holidays,
    holidays_prior_scale    = 10.0,
    changepoint_prior_scale = 0.3,
    n_changepoints          = 35,
    interval_width          = 0.90,
)
m_prod.add_seasonality(name="weekly",  period=7,    fourier_order=5)
m_prod.add_seasonality(name="monthly", period=30.5, fourier_order=2)
m_prod.add_regressor("is_saturday",        standardize=False, prior_scale=100.0)
m_prod.add_regressor("dupla",             standardize=False, prior_scale=10.0, mode="additive")
m_prod.add_regressor("uno",               standardize=False, prior_scale=10.0, mode="additive")
m_prod.add_regressor("post_dupla",        standardize=False, prior_scale=10.0, mode="additive")

prod_train_cols = ["ds", "y", "is_saturday", "dupla", "uno", "post_dupla"]
if winner["label"] == "WITH spend":
    m_prod.add_regressor("log_spend_workday", standardize=True, prior_scale=0.5)
    prod_train_cols.append("log_spend_workday")

m_prod.fit(df[prod_train_cols])

future_prod = m_prod.make_future_dataframe(
    periods         = PROD_HORIZON,
    freq            = "D",
    include_history = False
)

future_prod["is_saturday"] = (future_prod["ds"].dt.dayofweek == 5).astype(int)

# Campaign flags for forecast period — driven entirely by the config lists
future_prod = fill_campaign_flags(future_prod)

# post_dupla for production: the day after each Dupla date gets flag = 1
# (working days only — if Dupla falls on Friday, Monday gets the flag)
_post_dupla_dates = set()
for d in _dupla_dates:
    candidate = d + pd.Timedelta(days=1)
    while candidate.dayofweek >= 5:          # skip to next working day
        candidate += pd.Timedelta(days=1)
    _post_dupla_dates.add(candidate)
future_prod["post_dupla"] = future_prod["ds"].isin(_post_dupla_dates).astype(int)
print(f"  post_dupla flags in forecast: {future_prod['post_dupla'].sum()} days "
      f"({[d.date() for d in sorted(_post_dupla_dates)]})")

if winner["label"] == "WITH spend":
    # Planned daily investment per date (sourced from media plan, Apr 22-30 2026).
    # Weekends (Apr 25-26) have lower budgets; Apr 22 and Apr 30 have peak budgets.
    # Any date not listed here falls back to the 30-day rolling average.
    planned_spend_by_date = {
        pd.Timestamp("2026-04-22"): 58_828,
        pd.Timestamp("2026-04-23"): 41_840,
        pd.Timestamp("2026-04-24"): 41_840,
        pd.Timestamp("2026-04-25"): 34_993,
        pd.Timestamp("2026-04-26"): 34_993,
        pd.Timestamp("2026-04-27"): 41_840,
        pd.Timestamp("2026-04-28"): 41_840,
        pd.Timestamp("2026-04-29"): 41_840,
        pd.Timestamp("2026-04-30"): 55_533,
    }
    avg_spend_30d = df["spend_total"].tail(30).mean()
    future_prod["spend_total"] = future_prod["ds"].map(planned_spend_by_date).fillna(avg_spend_30d)
    future_prod["is_working_day"]    = (future_prod["ds"].dt.dayofweek < 5).astype(int)
    future_prod["spend_workday"]     = \
        future_prod["spend_total"] * future_prod["is_working_day"]
    future_prod["log_spend_workday"] = np.log1p(future_prod["spend_workday"])

    print(f"\nSpend assumption for Apr 22-30 (from media plan):")
    print(f"  {'Date':<14} {'Planned Spend':>15}")
    print(f"  {'-'*30}")
    for ds, spend in sorted(planned_spend_by_date.items()):
        print(f"  {ds.strftime('%a %d %b'):<14} {spend:>15,.0f}")
    print(f"  {'-'*30}")
    print(f"  {'Total':<14} {sum(planned_spend_by_date.values()):>15,.0f}")
    print(f"  (Fallback for unlisted dates: {avg_spend_30d:,.2f}  [30-day avg])")

forecast_prod = m_prod.predict(future_prod)

# Apply floors (same logic as evaluation model)
forecast_prod["yhat"] = forecast_prod["yhat"].clip(lower=SALES_FLOOR)
forecast_prod.loc[forecast_prod["ds"].dt.dayofweek == 5, "yhat"] = \
    forecast_prod.loc[forecast_prod["ds"].dt.dayofweek == 5, "yhat"].clip(lower=sat_floor)
forecast_prod.loc[forecast_prod["ds"].dt.dayofweek == 6, "yhat"] = \
    forecast_prod.loc[forecast_prod["ds"].dt.dayofweek == 6, "yhat"].clip(lower=sun_floor)
forecast_prod["yhat_lower"] = forecast_prod["yhat_lower"].clip(lower=0)

# Print forecast to console
print(f"\n=== Production Forecast — Apr 22–30 2026 ===")
print(f"{'Date':<14} {'Dupla':>6} {'Uno':>5} {'yhat':>9} {'lower':>9} {'upper':>9}")
print("-" * 57)
for _, row in forecast_prod.iterrows():
    dupla_flag = "✓" if row["ds"] in _dupla_dates else " "
    uno_flag   = "✓" if row["ds"] in _uno_dates   else " "
    print(f"{row['ds'].strftime('%a %d %b'):<14} "
          f"{dupla_flag:>6} {uno_flag:>5} "
          f"{row['yhat']:>9,.0f} "
          f"{row['yhat_lower']:>9,.0f} "
          f"{row['yhat_upper']:>9,.0f}")
print("-" * 57)
print(f"{'Total (yhat)':<20} {forecast_prod['yhat'].sum():>9,.0f}")
print(f"{'Total (lower)':<20} {forecast_prod['yhat_lower'].sum():>9,.0f}")
print(f"{'Total (upper)':<20} {forecast_prod['yhat_upper'].sum():>9,.0f}")

# =============================================================================
# 9. PLOTS
# =============================================================================

# --- 9a. Full evaluation forecast (history + validation) ---------------------
fig1 = eval_model.plot(forecast_eval, figsize=(14, 5))
plt.title(f"Prophet Evaluation Forecast — Daily Sales ({winner['label']})")
plt.xlabel("Date")
plt.ylabel("Sales")
plt.tight_layout()
plt.savefig("forecast_plot.png", dpi=150)
plt.show()

# --- 9b. Components (evaluation model) ---------------------------------------
fig2 = eval_model.plot_components(forecast_eval, figsize=(14, 10))
plt.tight_layout()
plt.savefig("components_plot.png", dpi=150)
plt.show()

# --- 9c. Actual vs Predicted on validation set -------------------------------
fig3, ax = plt.subplots(figsize=(12, 4))
ax.plot(val_merged["ds"], val_merged["y"],
        label="Actual", color="steelblue", linewidth=2)
ax.plot(val_merged["ds"], val_merged["yhat"],
        label="Predicted", color="darkorange", linewidth=2, linestyle="--")
ax.fill_between(
    val_merged["ds"],
    val_merged["yhat_lower"],
    val_merged["yhat_upper"],
    alpha=0.2, color="darkorange", label="90% interval"
)
ax.set_title(
    f"Validation — Last {FORECAST_HORIZON} Days  |  "
    f"MAE: {mae:.0f}  |  MAPE: {mape:.1f}%"
)
ax.legend()
ax.set_xlabel("Date")
ax.set_ylabel("Sales")
plt.tight_layout()
plt.savefig("validation_plot.png", dpi=150)
plt.show()

# --- 9d. CV performance by horizon -------------------------------------------
df_perf = winner["perf"].copy()
df_perf["horizon_days"] = df_perf["horizon"].dt.days

fig4, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
ax1.plot(df_perf["horizon_days"], df_perf["mae"],
         color="steelblue", linewidth=2, marker="o", markersize=3)
ax1.set_title(f"Cross-Validation Performance — {winner['label']}")
ax1.set_ylabel("MAE (sales/day)")
ax1.grid(True, alpha=0.3)
ax2.plot(df_perf["horizon_days"], df_perf["mape"] * 100,
         color="darkorange", linewidth=2, marker="o", markersize=3)
ax2.set_ylabel("MAPE (%)")
ax2.set_xlabel("Horizon (days ahead)")
ax2.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("cv_performance_plot.png", dpi=150)
plt.show()

# --- 9e. Production forecast -------------------------------------------------
fig5, ax = plt.subplots(figsize=(12, 4))
ax.plot(forecast_prod["ds"], forecast_prod["yhat"],
        color="darkorange", linewidth=2, label="Forecast")
ax.fill_between(
    forecast_prod["ds"],
    forecast_prod["yhat_lower"],
    forecast_prod["yhat_upper"],
    alpha=0.2, color="darkorange", label="90% interval"
)

# Mark campaign days on the production chart
dupla_in_period = forecast_prod[forecast_prod["ds"].isin(_dupla_dates)]
uno_in_period   = forecast_prod[forecast_prod["ds"].isin(_uno_dates)]
if not dupla_in_period.empty:
    ax.scatter(dupla_in_period["ds"], dupla_in_period["yhat"],
               color="royalblue", zorder=5, label="Campanha Dupla", s=60)
if not uno_in_period.empty:
    ax.scatter(uno_in_period["ds"], uno_in_period["yhat"],
               color="mediumseagreen", zorder=5, label="Campanha Uno", s=60)

ax.set_title(
    f"Production Forecast — Apr 22–30 2026  |  "
    f"Total: {forecast_prod['yhat'].sum():,.0f} sales  "
    f"(model: {winner['label']})"
)
ax.set_ylabel("Sales")
ax.set_xlabel("Date")
ax.legend()
ax.grid(True, alpha=0.3)
plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
plt.tight_layout()
plt.savefig("month_forecast_plot.png", dpi=150)
plt.show()

# =============================================================================
# 10. EXPORT PRODUCTION FORECAST TO CSV
# =============================================================================

output_cols = ["ds", "yhat", "yhat_lower", "yhat_upper",
               "trend", "weekly", "monthly", "holidays"]
output_cols = [c for c in output_cols if c in forecast_prod.columns]

forecast_prod[output_cols].to_csv("forecast_next_30_days.csv", index=False)

print(f"\nProduction forecast saved : forecast_next_30_days.csv")
print(f"Covers                    : {FORECAST_START.date()} → {FORECAST_END.date()}")
print(f"Rows                      : {len(forecast_prod)}")
print("Plots saved               : forecast_plot.png, components_plot.png,")
print("                            validation_plot.png, cv_performance_plot.png,")
print("                            month_forecast_plot.png")