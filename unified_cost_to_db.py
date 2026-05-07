import os
import pandas as pd
import mysql.connector
from dotenv import load_dotenv

# --- Configuration ---
folder = r"C:\Users\Álex Metzen\Desktop\Scripts e Dados"
load_dotenv(os.path.join(folder, ".env"))

DB_CONFIG = {
    "host":     os.getenv("MYSQL_HOST"),
    "user":     os.getenv("MYSQL_USER"),
    "password": os.getenv("MYSQL_PASSWORD"),
    "database": os.getenv("MYSQL_DB"),
    "port":     int(os.getenv("MYSQL_PORT", 3306)),
}

TABLE_NAME = "lc_tbl_adspends_csv"

# --- 1. Read and merge the three CSVs ---
files = {
    "spend_meta":   "Supermetrics - Ad Spends - Meta.csv",
    "spend_google": "Supermetrics - Ad Spends - Google.csv",
    "spend_tiktok": "Supermetrics - Ad Spends - Tiktok.csv",
}

all_dates = pd.date_range("2025-01-01", "2026-03-31", freq="D")
result = pd.DataFrame({"dt": all_dates})

for col, filename in files.items():
    path = os.path.join(folder, filename)
    try:
        df = pd.read_csv(path, header=0)
        df.columns = ["dt", "cost"]
        df["dt"] = pd.to_datetime(df["dt"], format="%Y-%m-%d")
        df["cost"] = pd.to_numeric(df["cost"], errors="coerce").fillna(0.0)
        df = df.groupby("dt", as_index=False)["cost"].sum().rename(columns={"cost": col})
        result = result.merge(df, on="dt", how="left")
        result[col] = result[col].fillna(0.0)
        print(f"✓ Loaded {filename}")
    except FileNotFoundError:
        print(f"✗ File not found: {filename} — column will be all zeros")
        result[col] = 0.0

print(f"\n{len(result)} rows ready to upload.\n")

# --- 2. Connect to MySQL and create/replace the table ---
conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

cursor.execute(f"DROP TABLE IF EXISTS `{TABLE_NAME}`;")
cursor.execute(f"""
    CREATE TABLE `{TABLE_NAME}` (
        `dt`           DATE NOT NULL PRIMARY KEY,
        `spend_meta`   DECIMAL(12,2) NOT NULL DEFAULT 0.00,
        `spend_google` DECIMAL(12,2) NOT NULL DEFAULT 0.00,
        `spend_tiktok` DECIMAL(12,2) NOT NULL DEFAULT 0.00
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""")
print(f"✓ Table `{TABLE_NAME}` created.")

# --- 3. Bulk insert ---
insert_sql = f"""
    INSERT INTO `{TABLE_NAME}` (dt, spend_meta, spend_google, spend_tiktok)
    VALUES (%s, %s, %s, %s)
"""
rows = [
    (
        row["dt"].strftime("%Y-%m-%d"),
        round(row["spend_meta"], 2),
        round(row["spend_google"], 2),
        round(row["spend_tiktok"], 2),
    )
    for _, row in result.iterrows()
]
cursor.executemany(insert_sql, rows)
conn.commit()
print(f"✓ {cursor.rowcount} rows inserted.")

# --- 4. Update the view ---
VIEW_SQL = """
CREATE OR REPLACE VIEW `vw_prophet_input` AS
WITH `csv_spend` AS (
    SELECT
        `dt`,
        `spend_meta`,
        `spend_google`,
        `spend_tiktok`
    FROM `lc_tbl_adspends_csv`
    WHERE `dt` BETWEEN '2025-01-01' AND '2026-03-31'
),
`sales` AS (
    SELECT
        CAST(`NOMINAL_VENDAS`.`DT_FILIACAO` AS DATE) AS `dt`,
        COUNT(0) AS `qtd_vendas`
    FROM `NOMINAL_VENDAS`
    WHERE CAST(`NOMINAL_VENDAS`.`DT_FILIACAO` AS DATE) BETWEEN '2025-01-01' AND '2026-03-31'
    GROUP BY CAST(`NOMINAL_VENDAS`.`DT_FILIACAO` AS DATE)
)
SELECT
    `cal`.`data`                                              AS `ds`,
    COALESCE(`s`.`qtd_vendas`, 0)                             AS `y`,
    COALESCE(`c`.`spend_meta`, 0)                             AS `spend_meta`,
    COALESCE(`c`.`spend_google`, 0)                           AS `spend_google`,
    COALESCE(`c`.`spend_tiktok`, 0)                           AS `spend_tiktok`,
    ( COALESCE(`c`.`spend_meta`, 0)
    + COALESCE(`c`.`spend_google`, 0)
    + COALESCE(`c`.`spend_tiktok`, 0) )                       AS `spend_total`,
    `cal`.`eh_dia_util`                                       AS `is_working_day`,
    `cal`.`dia_semana_iso`                                    AS `weekday_iso`,
    `cal`.`mes`                                               AS `month_num`,
    `cal`.`dia`                                               AS `day_of_month`,
    CEILING(`cal`.`dia` / 7.0)                                AS `week_of_month`
FROM `dim_calendario` `cal`
LEFT JOIN `csv_spend`  `c` ON `c`.`dt` = `cal`.`data`
LEFT JOIN `sales`      `s` ON `s`.`dt` = `cal`.`data`
WHERE `cal`.`data` BETWEEN '2025-01-01' AND '2026-03-31'
ORDER BY `cal`.`data`;
"""

cursor.execute(VIEW_SQL)
conn.commit()
print("✓ View `vw_prophet_input` updated (now uses CSV spends + TikTok).")

cursor.close()
conn.close()
print("\nAll done!")