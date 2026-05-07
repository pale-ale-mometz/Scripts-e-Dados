import pandas as pd
import os

# --- Configuration ---
folder = r"C:\Users\Álex Metzen\Desktop\Scripts e Dados"
files = [
    "Supermetrics - Ad Spends - Meta.csv",
    "Supermetrics - Ad Spends - Google.csv",
    "Supermetrics - Ad Spends - Tiktok.csv",
]
output_file = os.path.join(folder, "Ad Spends - Combined.csv")

# --- Build a complete date range ---
all_dates = pd.date_range(start="2025-01-01", end="2026-03-31", freq="D")
result = pd.DataFrame({"Date": all_dates, "Total Cost": 0.0})

# --- Read each file and add its costs ---
for file in files:
    path = os.path.join(folder, file)
    try:
        df = pd.read_csv(path, header=0)
        # Use the first two columns regardless of their header names
        df.columns = ["Date", "Cost"]
        df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d")
        df["Cost"] = pd.to_numeric(df["Cost"], errors="coerce").fillna(0.0)
        # Group by date in case a file has duplicate dates
        df = df.groupby("Date", as_index=False)["Cost"].sum()
        # Merge and add
        result = result.merge(df, on="Date", how="left")
        result["Total Cost"] += result["Cost"].fillna(0.0)
        result.drop(columns="Cost", inplace=True)
        print(f"✓ Loaded {file}")
    except FileNotFoundError:
        print(f"✗ File not found: {file} — skipping")

# --- Format and save ---
result["Date"] = result["Date"].dt.strftime("%Y-%m-%d")
result.to_csv(output_file, index=False)
print(f"\nDone! Output saved to:\n{output_file}")