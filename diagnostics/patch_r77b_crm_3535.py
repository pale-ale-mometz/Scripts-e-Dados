"""R77b (27/10/2026) — aba 📨 CRM: régua do número 3535 (Lia Disparos) em três visões.

Pedido do Álex: "3535 tem alguns disparos com os conteúdos de Aquisição. Faça uma visualização sem e outra com o total do 3535 e uma
terceira com apenas os 3535 claramente linkados à mesa de aquisição ('AQUI …' ou outro indicador)."
Investigação (27/10): no nosso relatório (middleware, instância × canal desde o v6) o 3535 só aparece em 24, 25 e 28/09/2026 — 3 templates
'CDT - AQUI - disparo N leads sem CEP …' (20.772 msgs, R$ 5.208,32 na régua BD_CRM, R$ 5.713,92 cobrados), sender 3, sem 'GT7' no nome.
Hoje 'todo o 3535' = '3535 de aquisição'; a 3ª visão existe para quando o número receber disparos que não são de aquisição.

Mudanças (exige R77):
  - `_load_crm_cpa_num_raw` passa a trazer TODOS os templates com flags `gt7` / `aqui` (dia × número × gt7 × aqui) — o filtro GT7 sai do SQL;
    `_load_crm_funil_raw` ganha a flag `aqui`.
  - Rádio "Número 3535 (Lia Disparos) na régua do gasto": Fora (régua GT7 — padrão) · Todo o 3535 · Só 3535 de aquisição ('AQUI'/'GT7' no nome).
    O gasto do topo (KPIs, buckets, tabela dia a dia) é sempre recomposto de `_cn8` pela régua escolhida + filtro de número; o funil de
    entrega no escopo "Instância de Aquisição" segue a mesma régua. O aviso ⚠️ dos templates AQUI fora da régua só aparece na visão 'Fora'.
  - O canal CRM da aba 💰 Investimento (load_zenvia_gt7) e o RMA continuam na régua GT7 pura — não mudam aqui.

Idempotente. Backup em app_bak_r77b.py.  Uso:  .venv\\Scripts\\python.exe diagnostics\\patch_r77b_crm_3535.py
"""
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _patchlib import APP, read_app, write_app  # noqa: E402

text, bom, crlf = read_app()
orig = text
changes = []


def once(old, new, label):
    global text
    if new in text:
        changes.append(f"= {label} (já aplicado)")
        return
    if text.count(old) != 1:
        raise SystemExit(f"ERR âncora ausente ou duplicada ({text.count(old)}x): {label}")
    text = text.replace(old, new)
    changes.append(f"+ {label}")


# 1) loader por número: todos os templates, com flags gt7/aqui ---------------------------------------------------------
once('''_CPA_NUM_COLS = ['dia', 'num_tel', 'numero', 'gasto_zenvia', 'gasto_bd']


@st.cache_data(ttl=43200)
def _load_crm_cpa_num_raw():
    d = cquery("""SELECT report_date AS dia,
                         COALESCE(channel_number, channel_name, '(sem canal)') AS num_tel,
                         COALESCE(channel_name, '(sem canal - antes de 2026)') AS numero,
                         ROUND(SUM(total_cost), 2) AS gasto_zenvia,
                         ROUND(SUM(CASE WHEN status IN ('Enviada','Entregue','Lida') THEN total_messages ELSE 0 END) * 0.32, 2) AS gasto_bd
                  FROM alex_zenvia_template_status
                  WHERE UPPER(template_name) LIKE '%%GT7%%'
                  GROUP BY 1, 2, 3""", ttl=0)
    for c in ['gasto_zenvia', 'gasto_bd']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0)
''', '''_CPA_NUM_COLS = ['dia', 'num_tel', 'numero', 'gt7', 'aqui', 'gasto_zenvia', 'gasto_bd']


@st.cache_data(ttl=43200)
def _load_crm_cpa_num_raw():
    """R77b: TODOS os templates, dia × número × flags (gt7 = 'GT7' no nome; aqui = 'AQUI' no nome). A régua (GT7, ou GT7 + 3535) é
    aplicada na aba 📨 por `_crm_regua_mask`, não no SQL — assim o 3535 (Lia Disparos) pode entrar em três visões."""
    d = cquery("""SELECT report_date AS dia,
                         COALESCE(channel_number, channel_name, '(sem canal)') AS num_tel,
                         COALESCE(channel_name, '(sem canal - antes de 2026)') AS numero,
                         CASE WHEN UPPER(template_name) LIKE '%%GT7%%' THEN 1 ELSE 0 END AS gt7,
                         CASE WHEN UPPER(template_name) LIKE '%%AQUI%%' AND UPPER(template_name) NOT LIKE '%%AINDAPORAQUI%%' THEN 1 ELSE 0 END AS aqui,
                         ROUND(SUM(total_cost), 2) AS gasto_zenvia,
                         ROUND(SUM(CASE WHEN status IN ('Enviada','Entregue','Lida') THEN total_messages ELSE 0 END) * 0.32, 2) AS gasto_bd
                  FROM alex_zenvia_template_status
                  GROUP BY 1, 2, 3, 4, 5""", ttl=0)
    for c in ['gasto_zenvia', 'gasto_bd']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0)
    for c in ['gt7', 'aqui']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0).astype(int)
''', "loader _load_crm_cpa_num_raw com flags gt7/aqui")

# régua compartilhada (topo e funil) — definida ao lado dos loaders
once('''def load_crm_cpa_num():
    try:
        return _load_crm_cpa_num_raw()
    except Exception:
        return pd.DataFrame(columns=_CPA_NUM_COLS)
''', '''def load_crm_cpa_num():
    try:
        return _load_crm_cpa_num_raw()
    except Exception:
        return pd.DataFrame(columns=_CPA_NUM_COLS)


# R77b: as três visões do 3535 (Lia Disparos) na régua do gasto da aba 📨. Investigação 27/10: no relatório do middleware o 3535 só tem
# 3 templates 'CDT - AQUI - disparo N leads sem CEP …' (24, 25 e 28/09/2026; R$ 5.208 na régua BD_CRM), sem 'GT7' no nome.
_CRM_REG_3535 = {"Fora (régua GT7 — padrão)": 'fora', "Todo o 3535": 'todo', "Só 3535 de aquisição ('AQUI'/'GT7' no nome)": 'aqui'}


def _crm_regua_mask(df, regua):
    """Linhas que entram na régua da Instância de Aquisição: templates GT7 + (conforme a visão) o número 3535 inteiro ou só os de aquisição."""
    m = df['gt7'] == 1
    if regua == 'todo':
        m = m | (df['num_tel'] == '3535')
    elif regua == 'aqui':
        m = m | ((df['num_tel'] == '3535') & ((df['aqui'] == 1) | (df['gt7'] == 1)))
    return m
''', "_CRM_REG_3535 + _crm_regua_mask")

# 2) funil: flag aqui -------------------------------------------------------------------------------------------------------
once('''_FUNIL_COLS = ['dia', 'canal', 'gt7', 'numero', 'num_tel', 'enviadas', 'entregues', 'lidas', 'nao_disparadas', 'custo']  # R70 numero · R71 num_tel
''', '''_FUNIL_COLS = ['dia', 'canal', 'gt7', 'aqui', 'numero', 'num_tel', 'enviadas', 'entregues', 'lidas', 'nao_disparadas', 'custo']  # R70 numero · R71 num_tel · R77b aqui
''', "_FUNIL_COLS + aqui")
once('''                         CASE WHEN UPPER(template_name) LIKE '%%GT7%%' THEN 1 ELSE 0 END AS gt7,
                         COALESCE(channel_name, '(sem canal - antes de 2026)') AS numero,
                         COALESCE(channel_number, channel_name, '(sem canal)') AS num_tel,
                         SUM(CASE WHEN status_code IN (2, 3, 4, 6) THEN total_messages ELSE 0 END) AS enviadas,
                         SUM(CASE WHEN status_code IN (3, 4) THEN total_messages ELSE 0 END) AS entregues,
                         SUM(CASE WHEN status_code = 4 THEN total_messages ELSE 0 END) AS lidas,
                         SUM(CASE WHEN status_code IN (1, 5, 8) THEN total_messages ELSE 0 END) AS nao_disparadas,
                         SUM(total_cost) AS custo
                  FROM alex_zenvia_template_status
                  GROUP BY 1, 2, 3, 4, 5""", ttl=0)
    for c in ['enviadas', 'entregues', 'lidas', 'nao_disparadas', 'custo']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0).astype(float)
    d['gt7'] = pd.to_numeric(d['gt7'], errors='coerce').fillna(0).astype(int)
''', '''                         CASE WHEN UPPER(template_name) LIKE '%%GT7%%' THEN 1 ELSE 0 END AS gt7,
                         CASE WHEN UPPER(template_name) LIKE '%%AQUI%%' AND UPPER(template_name) NOT LIKE '%%AINDAPORAQUI%%' THEN 1 ELSE 0 END AS aqui,
                         COALESCE(channel_name, '(sem canal - antes de 2026)') AS numero,
                         COALESCE(channel_number, channel_name, '(sem canal)') AS num_tel,
                         SUM(CASE WHEN status_code IN (2, 3, 4, 6) THEN total_messages ELSE 0 END) AS enviadas,
                         SUM(CASE WHEN status_code IN (3, 4) THEN total_messages ELSE 0 END) AS entregues,
                         SUM(CASE WHEN status_code = 4 THEN total_messages ELSE 0 END) AS lidas,
                         SUM(CASE WHEN status_code IN (1, 5, 8) THEN total_messages ELSE 0 END) AS nao_disparadas,
                         SUM(total_cost) AS custo
                  FROM alex_zenvia_template_status
                  GROUP BY 1, 2, 3, 4, 5, 6""", ttl=0)
    for c in ['enviadas', 'entregues', 'lidas', 'nao_disparadas', 'custo']:
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0).astype(float)
    d['gt7'] = pd.to_numeric(d['gt7'], errors='coerce').fillna(0).astype(int)
    d['aqui'] = pd.to_numeric(d['aqui'], errors='coerce').fillna(0).astype(int)   # R77b
''', "_load_crm_funil_raw com flag aqui")

# 3) aba: rádio da régua do 3535 + gasto recomposto de _cn8 --------------------------------------------------------------------
once('''        _cn8 = load_crm_cpa_num()
        _cl8, _cv8 = load_crm_wpp_sms()
        _fx1, _fx2 = st.columns([1.15, 1])
''', '''        _cn8 = load_crm_cpa_num()
        _cl8, _cv8 = load_crm_wpp_sms()
        # R77b: as três visões do 3535 (Lia Disparos) — fora (régua GT7), todo o número, só os de aquisição ('AQUI'/'GT7' no nome)
        _reg3535_lbl = st.radio("Número 3535 (Lia Disparos) na régua do gasto:", list(_CRM_REG_3535.keys()), index=0, horizontal=True, key='t8_reg_3535',
                                help="Os disparos do 3535 não levam 'GT7' no nome ('CDT - AQUI - disparo N leads sem CEP …', 24–28/09/2026, R$ 5.208) e por "
                                     "isso ficam fora da régua padrão. 'Todo o 3535' soma tudo que saiu pelo número; 'Só 3535 de aquisição' soma só os "
                                     "templates do 3535 com 'AQUI' ou 'GT7' no nome (hoje as duas visões coincidem). Vale para o gasto do topo e para o "
                                     "funil de entrega no escopo Instância de Aquisição; o canal CRM da aba 💰 e o RMA seguem na régua GT7 pura.")
        _reg3535 = _CRM_REG_3535[_reg3535_lbl]
        _cnr = _cn8[_crm_regua_mask(_cn8, _reg3535)] if not _cn8.empty else _cn8
        _fx1, _fx2 = st.columns([1.15, 1])
''', "📨 CRM: rádio da régua do 3535")
once('''                _num_opts = (_cn8[_cn8['dia'] >= pd.Timestamp(reference_date) - pd.DateOffset(months=12)]
                             .groupby(['num_tel', 'numero'])['gasto_zenvia'].sum().sort_values(ascending=False).reset_index()) if not _cn8.empty else pd.DataFrame(columns=['num_tel', 'numero'])
''', '''                _num_opts = (_cnr[_cnr['dia'] >= pd.Timestamp(reference_date) - pd.DateOffset(months=12)]
                             .groupby(['num_tel', 'numero'])['gasto_zenvia'].sum().sort_values(ascending=False).reset_index()) if not _cnr.empty else pd.DataFrame(columns=['num_tel', 'numero'])
''', "📨 CRM: opções de número pela régua")
once('''        if _nums_sel is not None and not _cn8.empty:
            _gz0, _gb0 = _c8['gasto_zenvia'].copy(), _c8['gasto_bd'].copy()
            _g8 = _cn8[_cn8['num_tel'].isin(_nums_sel)].groupby('dia')[['gasto_zenvia', 'gasto_bd']].sum()
            _c8['gasto_zenvia'] = _c8['dia'].map(_g8['gasto_zenvia']).fillna(0.0)
            _c8['gasto_bd'] = _c8['dia'].map(_g8['gasto_bd']).fillna(0.0)
            if not (_c8['gasto_bd'] > 0).any():
                st.warning(f"Nenhum custo de templates GT7 para **{_num_lbl}** — voltando para todos os números.")
                _c8['gasto_zenvia'], _c8['gasto_bd'] = _gz0, _gb0
                _nums_sel, _num_lbl = None, "todos os números"
''', '''        if not _cnr.empty:
            # R77b: o gasto do topo é sempre recomposto de _cnr (régua do 3535 escolhida) × filtro de número; dias só com custo do 3535
            # (sem template GT7 e sem venda) entram como linhas novas em _c8
            _gz0, _gb0 = _c8['gasto_zenvia'].copy(), _c8['gasto_bd'].copy()
            _cns = _cnr[_cnr['num_tel'].isin(_nums_sel)] if _nums_sel is not None else _cnr
            _g8 = _cns.groupby('dia')[['gasto_zenvia', 'gasto_bd']].sum()
            _novos = sorted(set(_g8.index) - set(_c8['dia']))
            if _novos:
                _c8 = pd.concat([_c8, pd.DataFrame({'dia': _novos})], ignore_index=True).fillna(0.0).sort_values('dia').reset_index(drop=True)
            _c8['gasto_zenvia'] = _c8['dia'].map(_g8['gasto_zenvia']).fillna(0.0)
            _c8['gasto_bd'] = _c8['dia'].map(_g8['gasto_bd']).fillna(0.0)
            if _nums_sel is not None and not (_c8['gasto_bd'] > 0).any():
                st.warning(f"Nenhum custo na régua escolhida para **{_num_lbl}** — voltando para todos os números.")
                _nums_sel, _num_lbl = None, "todos os números"
                _g8 = _cnr.groupby('dia')[['gasto_zenvia', 'gasto_bd']].sum()
                _c8['gasto_zenvia'] = _c8['dia'].map(_g8['gasto_zenvia']).fillna(0.0)
                _c8['gasto_bd'] = _c8['dia'].map(_g8['gasto_bd']).fillna(0.0)
''', "📨 CRM: gasto recomposto pela régua")
once('''        _aqui_fora = load_crm_aqui_fora()
        if not _aqui_fora.empty:
''', '''        _aqui_fora = load_crm_aqui_fora() if _reg3535 == 'fora' else pd.DataFrame(columns=['dia', 'num_tel', 'gasto_bd'])   # R77b: só na visão 'Fora'
        if not _aqui_fora.empty:
''', "📨 CRM: aviso AQUI só na visão 'Fora'")
once('''        if _nums_sel is not None or _utm_sel:
            st.caption(f"🔎 Filtros ativos — gasto: **{_num_lbl}**"''', '''        if _reg3535 != 'fora':
            st.caption(f"🔎 Régua do gasto: **templates GT7 + {_reg3535_lbl}** — diferente da régua GT7 pura do canal CRM da aba 💰 e do RMA.")
        if _nums_sel is not None or _utm_sel:
            st.caption(f"🔎 Filtros ativos — gasto: **{_num_lbl}**"''', "📨 CRM: caption da régua")
once('''            _ESC_GT7 = "Instância de Aquisição (templates GT7)"
''', '''            _ESC_GT7 = "Instância de Aquisição (templates GT7" + ("" if _reg3535 == 'fora' else " + " + _reg3535_lbl) + ")"
''', "📨 funil: rótulo do escopo")
once('''            _fb = _f8 if _esc8 == _ESC_ALL else _f8[_f8['gt7'] == 1]
''', '''            _fb = _f8 if _esc8 == _ESC_ALL else _f8[_crm_regua_mask(_f8, _reg3535)]   # R77b: mesma régua do topo
''', "📨 funil: escopo pela régua")

if text != orig:
    bak = APP.with_name("app_bak_r77b.py")
    if not bak.exists():
        shutil.copyfile(APP, bak)
    write_app(text, bom, crlf)
print("\n".join(changes))
print(f"app.py: {len(text.splitlines())} linhas")
