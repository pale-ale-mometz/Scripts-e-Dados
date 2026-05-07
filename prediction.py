import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

data = {0: 15, 1: 10, 2: 3, 3: 4, 4: 2, 5: 9, 6: 18, 7: 84, 8: 495, 9: 1074, 10: 1374, 11: 1295, 12: 1046, 13: 943, 14: 1213}

df           = pd.DataFrame(list(data.items()), columns=['hour', 'sales']).sort_values('hour')
last_hour    = df['hour'].max()
last_value   = data[last_hour]
sales_so_far = df['sales'].sum()
HISTORICAL_MAX   = 50_000
AFTERNOON_ANCHOR = 17
EOD_HOUR         = 23
budget           = HISTORICAL_MAX - sales_so_far

# --- Two anchor options ---
ideal_target_h17 = round(data[9] * 0.90)                   # 5,200 (ignores cap)
budget_target_h17 = round(budget * 0.30)                   # ~30% of remaining budget at peak

# ⬇ CHOOSE YOUR MODE HERE
MODE = "A"  # "A" = honour anchor | "B" = honour budget cap

if MODE == "A":
    target_h17  = ideal_target_h17
    apply_cap   = False
    mode_label  = "Anchor priority (5pm = 8am × 90%)"
else:
    target_h17  = budget_target_h17
    apply_cap   = True
    mode_label  = "Budget priority (hard cap at 50k)"

target_h23  = round(max(data.values()) * 0.05)
decay_rate  = (target_h23 / target_h17) ** (1 / (EOD_HOUR - AFTERNOON_ANCHOR))

# --- Build predictions ---
predicted = {}
for h in range(last_hour + 1, 24):
    if h < AFTERNOON_ANCHOR:
        steps_total  = AFTERNOON_ANCHOR - last_hour
        steps_done   = h - last_hour
        predicted[h] = round(last_value + (target_h17 - last_value) * steps_done / steps_total)
    elif h == AFTERNOON_ANCHOR:
        predicted[h] = target_h17
    else:
        predicted[h] = round(target_h17 * decay_rate ** (h - AFTERNOON_ANCHOR))

# Budget cap only applied in mode B
if apply_cap:
    total = sum(predicted.values())
    if total > budget:
        scale    = budget / total
        predicted = {h: round(v * scale) for h, v in predicted.items()}

predicted_remaining = sum(predicted.values())
estimated_total     = sales_so_far + predicted_remaining

# --- Terminal output ---
print(f"\n  Mode: {mode_label}")
print(f"  8am actual:       {data[8]:,}")
print(f"  Ideal 5pm target: {ideal_target_h17:,}  (8am × 0.90)")
print(f"  Budget 5pm target:{budget_target_h17:,}  (budget × 0.30)")
print(f"  Applied 5pm:      {target_h17:,}")
print(f"  Remaining budget: {budget:,}")
print(f"  Derived decay:    {decay_rate:.3f}/h\n")

print(f"{'='*45}")
print(f"{'Hour':<8} {'Type':<14} {'Predicted':>10} {'vs Budget':>10}")
print(f"{'-'*45}")
running = sales_so_far
for h, p in predicted.items():
    running += p
    over     = "⚠ OVER" if running > HISTORICAL_MAX else ""
    kind     = "ramp ↗" if h < AFTERNOON_ANCHOR else ("anchor ◆" if h == AFTERNOON_ANCHOR else "decay ↘")
    print(f"  {h:02d}h    {kind:<14} {p:>8,}   {running:>8,} {over}")

print(f"{'='*45}")
print(f"  Sales so far:        {sales_so_far:>10,}")
print(f"  Predicted remaining: {predicted_remaining:>10,}")
print(f"  Estimated day total: {estimated_total:>10,}")
print(f"  Historical cap:      {HISTORICAL_MAX:>10,}")
if estimated_total > HISTORICAL_MAX:
    print(f"  ⚠  Exceeds cap by:   {estimated_total - HISTORICAL_MAX:>10,}")
print(f"{'='*45}\n")

# --- Chart ---
all_hours     = list(range(24))
actual_vals   = [data.get(h, 0) for h in all_hours]
forecast_vals = [predicted.get(h, 0) for h in all_hours]
curve_vals    = [data[h] if h <= last_hour else predicted[h] for h in all_hours]

fig, ax = plt.subplots(figsize=(13, 5))
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")

ax.bar([h for h in all_hours if h <= last_hour],
       [actual_vals[h] for h in all_hours if h <= last_hour],
       color="#38bdf8", alpha=0.85, label="Actual", width=0.6)
ax.bar([h for h in all_hours if h > last_hour],
       [forecast_vals[h] for h in all_hours if h > last_hour],
       color="#f97316", alpha=0.60, label="Forecast", width=0.6)
ax.plot(all_hours, curve_vals, color="#a78bfa", linewidth=2, linestyle="--", label="Model curve")
ax.axvline(x=last_hour,        color="#7c3aed", linestyle=":", linewidth=1.5, label="Now")
ax.axvline(x=AFTERNOON_ANCHOR, color="#f97316", linestyle=":", linewidth=1.2,
           label=f"5pm anchor ({target_h17:,})")
ax.scatter([AFTERNOON_ANCHOR], [target_h17], color="#f97316", zorder=5, s=60)

# Show cap line only in mode B
if apply_cap:
    ax.axhline(y=budget / (24 - last_hour), color="#374151", linestyle=":",
               linewidth=1, label=f"Avg remaining budget")

ax.set_xticks(all_hours)
ax.set_xticklabels([f"{h:02d}h" for h in all_hours], color="#6b7280", fontsize=9)
ax.tick_params(axis='y', colors="#6b7280")
ax.set_xlabel("Hour", color="#6b7280", labelpad=10)
ax.set_ylabel("Sales", color="#6b7280", labelpad=10)
ax.set_title(f"Same-Day Sales Forecast — {mode_label}", color="#f8fafc", fontsize=14, pad=16)

for spine in ax.spines.values():
    spine.set_visible(False)
ax.grid(axis='y', color="#1e2330", linewidth=0.8)
ax.legend(facecolor="#0d1117", edgecolor="#1e2330", labelcolor="#9ca3af", fontsize=9)
ax.annotate(
    f"So far: {sales_so_far:,}  |  Remaining: {predicted_remaining:,}  |  "
    f"Est. total: {estimated_total:,}  |  Cap: {HISTORICAL_MAX:,}",
    xy=(0.5, -0.18), xycoords='axes fraction', ha='center', color="#4b5563", fontsize=9
)

plt.tight_layout()
plt.savefig("sales_forecast.png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
plt.show()
print(f"Chart saved — Mode {MODE}: {mode_label}")