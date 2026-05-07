import pandas as pd
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import unicodedata
import re

def sanitize_col(name):
    # Transliterate accented chars to ASCII equivalents (ã→a, ç→c, etc.)
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    name = name.strip()
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)  # replace special chars with _
    name = re.sub(r'_+', '_', name)               # collapse multiple underscores
    name = name.strip('_')                         # remove leading/trailing underscores
    return name[:64]                               # enforce MySQL's 64-char limit

password = quote_plus('?34TcU_7U9Hq')

engine = create_engine(
    f'mysql+mysqlconnector://alex.metzen:{password}'
    f'@mysql-bi-g.cyrjbg1j8gup.us-east-1.rds.amazonaws.com/mysql_bi_g',
    connect_args={'use_pure': True}
)

df = pd.read_csv(r"C:\Users\Álex Metzen\Desktop\Scripts e Dados\mar-de-2026-conta-contatos.csv")

# Show column mapping
for original, sanitized in zip(df.columns, [sanitize_col(c) for c in df.columns]):
    print(f'  "{original}" → "{sanitized}"')

df.columns = [sanitize_col(c) for c in df.columns]

# Write in chunks and catch the real error explicitly
try:
    with engine.begin() as conn:
        df.to_sql('mar_de', con=conn, if_exists='replace', index=False, chunksize=500)
    print("Done!")
except Exception as e:
    print(f"Error type: {type(e).__name__}")
    print(f"Error: {e}")

df.to_csv(r'C:\Users\Álex Metzen\Desktop\mar-de-clean.csv', index=False)
    