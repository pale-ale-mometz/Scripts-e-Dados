# =============================================================================
# ALLOCATE FORECAST BY tipo_venda
# Takes the Prophet output and splits it across sales channels using the
# rolling 30-day mix from vw_diario_vendas_por_tipo.
# =============================================================================

import pandas as pd

LOOKBACK_DAYS = 30

# --- Load inputs -------------------------------------------------------------
forecast    = pd.read_csv("forecast_next_30_days.csv")
vendas_tipo = pd.read_csv("vw_diario_vendas_por_tipo.csv")

forecast["ds"]      = pd.to_datetime(forecast["ds"])
vendas_tipo["data"] = pd.to_datetime(vendas_tipo["data"])

# --- Compute rolling channel mix --------------------------------------------
cutoff = vendas_tipo["data"].max() - pd.Timedelta(days=LOOKBACK_DAYS)
recent = vendas_tipo[
    (vendas_tipo["data"] > cutoff) &
    (vendas_tipo["tipo_venda"].notna())
].copy()

mix = (recent.groupby("tipo_venda")["qtd_vendas"]
             .sum()
             .reset_index())
mix["pct_mix"] = mix["qtd_vendas"] / mix["qtd_vendas"].sum()

print(f"=== Channel mix (last {LOOKBACK_DAYS} days of actuals) ===")
print(f"Window: {recent['data'].min().date()} → {recent['data'].max().date()}")
print(mix.sort_values("pct_mix", ascending=False).to_string(index=False))
print(f"Sum of pct_mix (should = 1.0): {mix['pct_mix'].sum():.4f}\n")

# --- Cross-join forecast × channel mix --------------------------------------
forecast["_key"] = 1
mix_join = mix[["tipo_venda", "pct_mix"]].copy()
mix_join["_key"] = 1

allocated = forecast.merge(mix_join, on="_key").drop(columns="_key")

for col in ["yhat", "yhat_lower", "yhat_upper"]:
    allocated[col] = (allocated[col] * allocated["pct_mix"]).round(0).astype(int)

allocated = allocated[["ds", "tipo_venda", "pct_mix",
                       "yhat", "yhat_lower", "yhat_upper"]]
allocated = allocated.sort_values(["ds", "tipo_venda"]).reset_index(drop=True)
allocated["ds"] = allocated["ds"].dt.strftime("%Y-%m-%d")

# --- Save and report ---------------------------------------------------------
allocated.to_csv("forecast_by_tipo_venda.csv", index=False)

# --- Rollup: total per channel across the forecast horizon ------------------
totals = (allocated.groupby("tipo_venda", as_index=False)
                   .agg(yhat=("yhat", "sum"),
                        yhat_lower=("yhat_lower", "sum"),
                        yhat_upper=("yhat_upper", "sum")))
totals = totals.merge(mix[["tipo_venda", "pct_mix"]], on="tipo_venda")
totals = totals.sort_values("yhat", ascending=False).reset_index(drop=True)
totals["forecast_start"] = allocated["ds"].min()
totals["forecast_end"]   = allocated["ds"].max()

totals = totals[["tipo_venda", "pct_mix", "forecast_start", "forecast_end",
                 "yhat", "yhat_lower", "yhat_upper"]]
totals.to_csv("forecast_totals_by_tipo_venda.csv", index=False)

# --- Console summary --------------------------------------------------------
print(f"=== Allocation summary ===")
print(f"Daily rows written    : {len(allocated)}  (forecast_by_tipo_venda.csv)")
print(f"Total rows written    : {len(totals)}  (forecast_totals_by_tipo_venda.csv)")
print(f"Forecast horizon      : {allocated['ds'].min()} → {allocated['ds'].max()}")
print(f"Channels              : {allocated['tipo_venda'].nunique()}")
print(f"Sum of allocated yhat : {allocated['yhat'].sum():,}")
print(f"Sum of original yhat  : {forecast['yhat'].sum():,}  (should roughly match)")
print(f"\n=== Totals per channel through {allocated['ds'].max()} ===")
print(totals.to_string(index=False))
print("\nSaved: forecast_by_tipo_venda.csv, forecast_totals_by_tipo_venda.csv")