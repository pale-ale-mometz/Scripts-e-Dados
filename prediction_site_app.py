import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- Dataset ---
data = {0: 10, 1: 7, 2: 2, 3: 3, 4: 2, 5: 7, 6: 10, 7: 34, 8: 50, 9: 84, 10: 96, 11: 94, 12: 120, 13: 107, 14: 71}
df = pd.DataFrame(list(data.items()), columns=['hour', 'sales']).sort_values('hour')

# --- Config ---
PLATEAU_START   = 11
PLATEAU_END     = 13
PLATEAU_DROP    = 0.90   # plateau is 30% below the peak prediction
DECAY_RATE      = 0.90   # each post-plateau hour retains 72% of the previous
HISTORICAL_MAX  = 50_000

last_hour    = df['hour'].max()
sales_so_far = df['sales'].sum()
budget       = HISTORICAL_MAX - sales_so_far  # max we can still predict

# --- Degree 3 only used to predict hour 11 (plateau anchor) ---
coeffs = np.polyfit(df['hour'], df['sales'], deg=3)
plateau_value = round(max(0, np.polyval(coeffs, PLATEAU_START)) * PLATEAU_DROP)

# --- Build predictions ---
#   11–13 : plateau (flat)
#   14–23 : exponential decay from plateau
predicted = {}
prev = plateau_value
for h in range(last_hour + 1, 24):
    if PLATEAU_START <= h <= PLATEAU_END:
        predicted[h] = plateau_value
    else:
        prev = round(prev * DECAY_RATE)
        predicted[h] = max(0, prev)

# --- Apply budget cap (scale down proportionally if needed) ---
predicted_total = sum(predicted.values())
if predicted_total > budget:
    scale = budget / predicted_total
    predicted = {h: round(v * scale) for h, v in predicted.items()}

predicted_remaining = sum(predicted.values())

# --- Terminal output ---
print(f"\n{'='*45}")
print(f"  SAME-DAY SALES FORECAST (per hour)")
print(f"{'='*45}")
print(f"  Plateau : {PLATEAU_START}h–{PLATEAU_END}h @ {plateau_value:,} sales/h")
print(f"  Budget  : {budget:,} remaining of {HISTORICAL_MAX:,} max")
print(f"{'='*45}")
print(f"{'Hour':<8} {'Type':<12} {'Predicted Sales':>15}")
print(f"{'-'*37}")
for h, p in predicted.items():
    if PLATEAU_START <= h <= PLATEAU_END:
        kind = "plateau"
    elif h <= last_hour:
        kind = "actual"
    else:
        kind = "decay"
    print(f"  {h:02d}h    {kind:<12} {p:>10,}")

print(f"{'='*45}")
print(f"  Sales so far:        {sales_so_far:>10,}")
print(f"  Predicted remaining: {predicted_remaining:>10,}")
print(f"  Estimated day total: {sales_so_far + predicted_remaining:>10,}")
print(f"{'='*45}\n")

# --- Chart ---
all_hours     = list(range(24))
actual_vals   = [data.get(h, 0) if h <= last_hour else 0 for h in all_hours]
forecast_vals = [predicted.get(h, 0) if h > last_hour else 0 for h in all_hours]

# Smooth model curve for visualisation
curve_vals = []
prev_curve = plateau_value
for h in all_hours:
    if h <= last_hour:
        curve_vals.append(max(0, np.polyval(coeffs, h)))
    elif PLATEAU_START <= h <= PLATEAU_END:
        curve_vals.append(plateau_value)
    else:
        prev_curve = round(prev_curve * DECAY_RATE)
        curve_vals.append(max(0, prev_curve))

fig, ax = plt.subplots(figsize=(13, 5))
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")

ax.bar(all_hours, actual_vals,   color="#38bdf8", alpha=0.85, label="Actual",  width=0.6)
ax.bar(all_hours, forecast_vals, color="#f97316", alpha=0.60, label="Forecast", width=0.6)
ax.plot(all_hours, curve_vals, color="#a78bfa", linewidth=2, linestyle="--", label="Model curve")
ax.axvline(x=last_hour, color="#7c3aed", linestyle=":", linewidth=1.5, label="Now")
ax.axvspan(PLATEAU_START - 0.4, PLATEAU_END + 0.4, alpha=0.07, color="#f97316", label="Plateau zone")
ax.axhline(y=HISTORICAL_MAX / 24, color="#374151", linestyle=":", linewidth=1, label=f"Avg if flat ({HISTORICAL_MAX:,}/day)")

ax.set_xticks(all_hours)
ax.set_xticklabels([f"{h:02d}h" for h in all_hours], color="#6b7280", fontsize=9)
ax.tick_params(axis='y', colors="#6b7280")
ax.set_xlabel("Hour", color="#6b7280", labelpad=10)
ax.set_ylabel("Sales", color="#6b7280", labelpad=10)
ax.set_title("Same-Day Sales Forecast — Plateau + Decay Model", color="#f8fafc", fontsize=14, pad=16)

for spine in ax.spines.values():
    spine.set_visible(False)
ax.grid(axis='y', color="#1e2330", linewidth=0.8)
ax.legend(facecolor="#0d1117", edgecolor="#1e2330", labelcolor="#9ca3af", fontsize=9)
ax.annotate(
    f"So far: {sales_so_far:,}  |  Remaining: {predicted_remaining:,}  |  Est. total: {sales_so_far + predicted_remaining:,}  |  Cap: {HISTORICAL_MAX:,}",
    xy=(0.5, -0.18), xycoords='axes fraction', ha='center', color="#4b5563", fontsize=9
)

plt.tight_layout()
plt.savefig("sales_forecast.png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
plt.show()
print("Chart saved to sales_forecast.png")
