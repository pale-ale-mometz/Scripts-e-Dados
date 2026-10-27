"""📣 8 · Mídia do app (Singular) — sub-aba da 📱 App para a analista de mídia que gere as campanhas do aplicativo.

R75 (23/10/2026). Módulo ao lado do app.py (vai junto no commit/deploy, como gerencial_tab.py e cdt_theme.py).
Chamado por app.py (`_aba_tab7`, `with _ap_tabs[7]`) com um dict `H` de helpers e contexto dos Controles Globais:
  cquery · c_s/c_e (Período de Análise, dia a dia) · p_s/p_e (comparação, mesmo trecho) · reference_date · m_fim
  meses_grafico(key) · kpi · n · delta · pct · note · titulo · fonte · chart_mensal · linhas_mensal · st_df · format_br · cores · tema

Fontes (MySQL mysql_bi_g, todas sobre alex_singular_installs — GAS singular.gs 09:30, janela D-8 → D-1):
  vw_singular_campanha_dia  dia × rede × campanha: installs (SDK, Android/iOS), installs_rede (o que a rede declara), impressões,
                            cliques, reengajamentos, custo (adn_cost Google/Meta/TikTok; Jampp = spend_brl), classe, nome_padrao
  vw_singular_downloads_dia dia × OS: installs, orgânico, pago, por rede
  alex_metas                "Download APP" (×1000) — meta mensal de instalações
  RESUMO_INVESTIMENTO_DIARIO canal 'App do Filiado' × plataforma — investimento oficial, para a conciliação com o custo Singular

Régua (decisão 20/10/2026): Installs/Downloads = Singular tracker_installs (orgânico + pago; pago = atribuído a mídia). iOS: o pago
é subestimado (ATT) — CPI e % pago só no Android. Custo Singular ≠ RESUMO (restatement, janela D-8). Nunca somar installs SDK com
installs da rede. Sem DATE_FORMAT/LIKE nas queries daqui (o % quebra no pymysql via cquery) — a classificação fica na view.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

VERSAO = "R75c · 27/10/2026 (bloco E · rótulos da compra)"

CLASSE_LBL = {
    'download': 'Download (app)', 'retargeting': 'Retargeting (Jampp RTGT)', 'site_venda': 'Site · Venda', 'site_lead': 'Site · Lead',
    'site_branding': 'Site · Branding', 'site_outra': 'Site · outra', 'organico': 'Orgânico', 'outra_fonte': 'Outra fonte (custom)',
}
REDES_PAGAS = ['Google', 'Meta', 'TikTok', 'Jampp', 'Outras fontes']
REDE_COL = {'Google': 'google', 'Meta': 'meta', 'TikTok': 'tiktok', 'Jampp': 'jampp', 'Outras fontes': 'outras_redes'}
_COLS_CAMP = ['dia', 'rede', 'source', 'campanha', 'classe', 'nome_padrao', 'installs_android', 'installs_ios', 'installs',
              'installs_rede', 'impressoes', 'cliques', 'reengajamentos', 'custo', 'custo_singular', 'installs_jampp']
_NUM_CAMP = _COLS_CAMP[6:]


# ----------------------------------------------------------------------------------------------------------------------
# loaders (cache 12 h, como os outros loaders do app)
# ----------------------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=43200)
def _load_campanhas(_cquery):
    d = _cquery("SELECT " + ", ".join(_COLS_CAMP) + " FROM vw_singular_campanha_dia WHERE dia >= '2025-01-01'", ttl=0)
    d['dia'] = pd.to_datetime(d['dia'])
    d['mes'] = d['dia'].dt.to_period('M').dt.to_timestamp()
    for c in _NUM_CAMP:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['nome_padrao'] = pd.to_numeric(d['nome_padrao'], errors='coerce')
    # o que a rede declara: adn_installs (Google/Meta/TikTok) ou os installs da própria Jampp (alex_jampp_campaigns)
    d['declara'] = d['installs_rede'].where(d['rede'] != 'Jampp', d['installs_jampp']).fillna(0)
    return d


@st.cache_data(ttl=43200)
def _load_dias(_cquery):
    d = _cquery("SELECT dia, os, installs, organico, pago, google, meta, tiktok, jampp, outras_redes, reengajamentos "
                "FROM vw_singular_downloads_dia", ttl=0)
    d['dia'] = pd.to_datetime(d['dia'])
    d['mes'] = d['dia'].dt.to_period('M').dt.to_timestamp()
    for c in ('installs', 'organico', 'pago', 'google', 'meta', 'tiktok', 'jampp', 'outras_redes', 'reengajamentos'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    return d


@st.cache_data(ttl=43200)
def _load_metas(_cquery):
    d = _cquery("SELECT Data_Corrigida AS mes, `Download APP` AS meta FROM alex_metas", ttl=0)
    d['mes'] = pd.to_datetime(d['mes']).dt.to_period('M').dt.to_timestamp()
    # a coluna vem como 450.878 (= 450.878 mil): mesma convenção do mesa_midia (×1000)
    d['meta'] = pd.to_numeric(d['meta'], errors='coerce') * 1000
    return d.dropna(subset=['meta'])


@st.cache_data(ttl=43200)
def _load_resumo_app(_cquery):
    d = _cquery("SELECT data_investimento AS dia, plataforma, venda FROM RESUMO_INVESTIMENTO_DIARIO WHERE canal = 'App do Filiado'", ttl=0)
    d['dia'] = pd.to_datetime(d['dia'])
    d['mes'] = d['dia'].dt.to_period('M').dt.to_timestamp()
    d['venda'] = pd.to_numeric(d['venda'], errors='coerce')
    return d


_COLS_COH = ['dia', 'rede', 'os', 'source', 'campanha', 'installs', 'cadastros_1d', 'cadastros_7d', 'cadastros_30d', 'cadastros_ltv',
             'compras_7d', 'compras_30d', 'compras_ltv', 'receita_compra_7d', 'receita_compra_30d', 'receita_compra_ltv', 'sessoes_7d', 'sessoes_30d',
             'retidos_1d', 'retidos_3d', 'retidos_7d', 'retidos_14d', 'retidos_30d', 'logins_7d', 'receita_total_ltv']


@st.cache_data(ttl=43200)
def _load_cohort(_cquery):
    """Fase 2 (26/10): coortes por dia de instalação × OS × rede × campanha (vw_singular_cohort_campanha_dia sobre alex_singular_cohort)."""
    d = _cquery("SELECT " + ", ".join(_COLS_COH) + " FROM vw_singular_cohort_campanha_dia", ttl=0)
    d['dia'] = pd.to_datetime(d['dia'])
    d['mes'] = d['dia'].dt.to_period('M').dt.to_timestamp()
    for c in _COLS_COH[5:]:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    return d


def _safe(fn, *a, cols=()):
    try:
        return fn(*a), None
    except Exception as e:
        return pd.DataFrame(columns=list(cols)), f"{type(e).__name__}: {str(e)[:300]}"


# ----------------------------------------------------------------------------------------------------------------------
# formatação
# ----------------------------------------------------------------------------------------------------------------------
def _brl(v, nd=2):
    if v is None or pd.isna(v):
        return "—"
    s = f"{float(v):,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "R$ " + s


def _num(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{int(round(float(v))):,}".replace(",", ".")


def _pct(a, b, nd=1):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or float(b) == 0:
        return "—"
    return f"{float(a) / float(b) * 100:.{nd}f}%".replace(".", ",")


def _razao(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or float(b) == 0:
        return "—"
    return f"{float(a) / float(b):.2f}×".replace(".", ",")


def _var(cur, prev):
    """Variação em texto curto (+12% / −8% / —) para colunas de tabela."""
    if cur is None or prev is None or pd.isna(cur) or pd.isna(prev) or float(prev) == 0:
        return "—"
    d = (float(cur) - float(prev)) / float(prev) * 100
    return f"{'+' if d > 0 else ''}{d:.0f}%"


def _jan(df, ini, fim):
    return df[(df['dia'] >= ini) & (df['dia'] <= fim)] if not df.empty else df


def _div_cpi(custo, installs):
    return (custo / installs) if installs and not pd.isna(installs) and installs > 0 and not pd.isna(custo) else float('nan')


# ----------------------------------------------------------------------------------------------------------------------
# render
# ----------------------------------------------------------------------------------------------------------------------
def render(H):
    cquery = H['cquery']
    c_s, c_e = pd.Timestamp(H['c_s']).normalize(), pd.Timestamp(H['c_e']).normalize()
    p_s, p_e = pd.Timestamp(H['p_s']).normalize(), pd.Timestamp(H['p_e']).normalize()
    kpi, n_, delta, pct, note, titulo, fonte = H['kpi'], H['n'], H['delta'], H['pct'], H['note'], H['titulo'], H['fonte']
    chart_mensal, linhas_mensal, st_df = H['chart_mensal'], H['linhas_mensal'], H['st_df']
    cores, tema = H.get('cores') or ['#166534', '#57a86f', '#b45309', '#8cc79e', '#94a3b8', '#0f172a', '#c8e3cf'], H.get('tema', False)
    tpl_a = 'cdt_a' if tema else 'plotly_white'
    tpl_b = 'cdt_b' if tema else 'plotly_white'

    camp, err1 = _safe(_load_campanhas, cquery, cols=_COLS_CAMP + ['mes'])
    dias, err2 = _safe(_load_dias, cquery, cols=['dia', 'os', 'installs', 'organico', 'pago', 'google', 'meta', 'tiktok', 'jampp', 'outras_redes', 'reengajamentos', 'mes'])
    metas, err3 = _safe(_load_metas, cquery, cols=['mes', 'meta'])
    resumo, err4 = _safe(_load_resumo_app, cquery, cols=['dia', 'plataforma', 'venda', 'mes'])

    st.markdown("### 📣 Mídia do app — campanhas, CPI, ritmo da meta e efeito cruzado (Singular)")
    h1, h2 = st.columns([3, 1.2])
    ult = camp['dia'].max() if not camp.empty else None
    h1.caption(
        f"Período: **{c_s:%d/%m/%Y}** a **{c_e:%d/%m/%Y}** (Período de Análise dos Controles Globais, dia a dia; comparação: "
        f"{p_s:%d/%m/%Y} a {p_e:%d/%m/%Y}, mesmo trecho). Régua: **instalação = 1ª abertura do app num aparelho novo vista pelo SDK da "
        "Singular** (`tracker_installs`), orgânico + pago, Android + iOS — a régua oficial de Installs/Downloads nos relatórios. "
        "Fontes: `vw_singular_campanha_dia` · `vw_singular_downloads_dia` (sobre `alex_singular_installs`, GAS 09:30, janela D-8 → D-1) · "
        "`alex_metas` (Download APP) · `RESUMO_INVESTIMENTO_DIARIO` (App do Filiado).")
    ult_txt = f"🗓️ {ult:%d/%m/%Y}" if ult is not None else "—"
    h2.markdown(
        "<div style='border:1px solid #e2e8f0;border-radius:10px;padding:7px 12px;background:#fff;'>"
        "<div style='font-size:10.5px;color:#64748b;font-weight:600;'>Singular · último dia carregado</div>"
        f"<div style='font-size:13px;color:#0f172a;font-weight:700;'>{ult_txt}</div></div>", unsafe_allow_html=True)
    for e, t in ((err1, 'vw_singular_campanha_dia'), (err2, 'vw_singular_downloads_dia'), (err3, 'alex_metas'), (err4, 'RESUMO_INVESTIMENTO_DIARIO')):
        if e:
            st.error(f"⚠️ Falha ao ler `{t}`: `{e}`")
    if camp.empty:
        st.warning("⚠️ `vw_singular_campanha_dia` vazia ou inexistente. Crie a view (claude-toolkit `sql/singular_views.sql`, R75) e ♻️ Recarregue os dados.")
        return

    if ult is not None and c_e > ult:
        st.info(f"⏳ A Singular está carregada até **{ult:%d/%m/%Y}** (carga D-8 → D-1 às 09:30); o período pede até {c_e:%d/%m/%Y} — os dias que faltam "
                "aparecem como zero. Dias dos últimos ~8 dias ainda mudam (atribuição tardia e restatement das redes).")

    cp, cpp = _jan(camp, c_s, c_e), _jan(camp, p_s, p_e)
    dp, dpp = _jan(dias, c_s, c_e), _jan(dias, p_s, p_e)

    # ---------------------------------------------------------------- KPIs do período
    def _tot(df, col, **f):
        d = df
        for k, v in f.items():
            d = d[d[k].isin(v)] if isinstance(v, (list, tuple, set)) else d[d[k] == v]
        return float(d[col].sum()) if not d.empty else None

    inst, inst_p = _tot(dp, 'installs'), _tot(dpp, 'installs')
    pago, pago_p = _tot(dp, 'pago'), _tot(dpp, 'pago')
    and_pago, and_inst = _tot(dp, 'pago', os='Android'), _tot(dp, 'installs', os='Android')
    ios_pago, ios_inst = _tot(dp, 'pago', os='iOS'), _tot(dp, 'installs', os='iOS')
    dl, dlp = cp[cp['classe'] == 'download'], cpp[cpp['classe'] == 'download']
    dl_and = dl[dl['installs_android'] >= dl['installs_ios']]          # campanhas de Download com Android dominante
    dlp_and = dlp[dlp['installs_android'] >= dlp['installs_ios']]
    custo_dl, custo_dlp = _tot(dl, 'custo'), _tot(dlp, 'custo')
    cpi_and = _div_cpi(_tot(dl_and, 'custo') or 0, _tot(dl_and, 'installs'))
    cpi_and_p = _div_cpi(_tot(dlp_and, 'custo') or 0, _tot(dlp_and, 'installs'))
    assist = _tot(cp, 'installs', classe=['site_venda', 'site_lead', 'site_branding', 'site_outra'])
    assist_p = _tot(cpp, 'installs', classe=['site_venda', 'site_lead', 'site_branding', 'site_outra'])
    reeng, reeng_p = _tot(cp, 'reengajamentos'), _tot(cpp, 'reengajamentos')

    k1, k2, k3, k4 = st.columns(4)
    kpi(k1, "📲", "Instalações (Singular · régua oficial)", f"{n_(inst)} {delta(inst, inst_p)}",
        f"Android {n_(and_inst)} · iOS {n_(ios_inst)} · orgânico + pago (SDK)")
    kpi(k2, "💸", "Instalações pagas (atribuídas a mídia)", f"{n_(pago)} {delta(pago, pago_p)}",
        f"{pct(pago, inst)} do total · Android {pct(and_pago, and_inst)} pago · iOS {pct(ios_pago, ios_inst)} (ATT)", color="#2e8a4f")
    kpi(k3, "🏷️", "CPI das campanhas de Download — Android", f"{_brl(cpi_and)} {delta(cpi_and if not pd.isna(cpi_and) else None, cpi_and_p if not pd.isna(cpi_and_p) else None)}",
        f"custo {_brl(custo_dl, 0)} ÷ instalações das campanhas Android · custo Singular/Jampp, não a RESUMO", color="#0f172a")
    kpi(k4, "🔁", "Instalações vindas de campanhas do site", f"{n_(assist)} {delta(assist, assist_p)}",
        f"{pct(assist, inst)} do total · Search/Pmax/Lead/Branding · reengajamentos {n_(reeng)} {delta(reeng, reeng_p)}", color="#b45309")

    note("<b>📏 Como ler.</b> <b>Instalação (SDK)</b> = o que o SDK da Singular viu; <b>instalação (rede)</b> = o que Google/Meta/TikTok/Jampp "
         "declaram — divergem por natureza (janelas e view-through), nunca some as duas. <b>Pago</b> = instalação com um toque de mídia na janela "
         "de atribuição; no iOS o ATT joga o pago em orgânico, por isso CPI e % pago são lidos no Android. <b>Custo</b> = o que a rede reporta à "
         "Singular (Jampp: spend_brl do jampp.gs) — serve para comparar redes; o investimento oficial continua sendo a RESUMO (bloco D). "
         "Os últimos ~8 dias mudam (atribuição tardia, restatement).", icon="📏")

    mg = H['meses_grafico']('t7_sg8_ano')

    # ==================================================================================================================
    # A · campanhas de Download — por rede e por campanha; rede diz × SDK vê
    # ==================================================================================================================
    titulo("A · Campanhas de Download — desempenho por rede e por campanha",
           f"{c_s:%d/%m} a {c_e:%d/%m} · instalações SDK × rede · CTR · custo · CPI · variação vs {p_s:%d/%m}–{p_e:%d/%m}", "A")
    a1, a2 = st.columns([1, 1.5])
    with a1:
        g = dl.groupby('rede', as_index=False)[['installs', 'declara', 'impressoes', 'cliques', 'custo']].sum()
        gp = dlp.groupby('rede')[['installs', 'custo']].sum()
        rows = []
        for _, r in g.sort_values('installs', ascending=False).iterrows():
            pi = float(gp.loc[r['rede'], 'installs']) if r['rede'] in gp.index else None
            pc = float(gp.loc[r['rede'], 'custo']) if r['rede'] in gp.index else None
            rows.append({'Rede': r['rede'], 'Instalações (SDK)': _num(r['installs']), '% do pago': _pct(r['installs'], _tot(dl, 'installs')),
                         'vs comp.': _var(r['installs'], pi), 'Rede declara': _num(r['declara']) if r['declara'] > 0 else "—",
                         'Custo': _brl(r['custo'], 0), 'CPI': _brl(_div_cpi(r['custo'], r['installs'])),
                         'CPI comp.': _brl(_div_cpi(pc, pi)) if pi else "—"})
        tot_r = {'Rede': 'Total Download', 'Instalações (SDK)': _num(g['installs'].sum()), '% do pago': '100%',
                 'vs comp.': _var(g['installs'].sum(), dlp['installs'].sum() if not dlp.empty else None),
                 'Rede declara': _num(g['declara'].sum()), 'Custo': _brl(g['custo'].sum(), 0),
                 'CPI': _brl(_div_cpi(g['custo'].sum(), g['installs'].sum())),
                 'CPI comp.': _brl(_div_cpi(dlp['custo'].sum(), dlp['installs'].sum())) if not dlp.empty else "—"}
        st_df(pd.DataFrame(rows + [tot_r]), csv=g, csv_nome="singular_download_por_rede", use_container_width=True, hide_index=True)
        fonte("vw_singular_campanha_dia · classe = download (campanhas com 'download' no nome + Jampp UA). 'Rede declara' = adn_installs "
              "(Google/Meta/TikTok) ou os installs que a Jampp reporta (alex_jampp_campaigns). Instalações pagas fora das campanhas de Download "
              "(Search, Pmax, Lead, Branding) estão no bloco C.")
    with a2:
        gc = (dl.groupby(['rede', 'campanha'], as_index=False)[['installs', 'installs_android', 'installs_ios', 'declara', 'impressoes', 'cliques', 'custo']].sum()
              .sort_values('installs', ascending=False))
        gcp = dlp.groupby(['rede', 'campanha'])[['installs', 'custo']].sum()
        rows = []
        for _, r in gc.iterrows():
            k = (r['rede'], r['campanha'])
            pi = float(gcp.loc[k, 'installs']) if k in gcp.index else None
            pc = float(gcp.loc[k, 'custo']) if k in gcp.index else None
            nome = r['campanha'] if isinstance(r['campanha'], str) else '(sem nome)'
            rows.append({'Rede': r['rede'], 'Campanha': (nome[:70] + '…') if len(nome) > 70 else nome,
                         'Instalações': _num(r['installs']), 'And. / iOS': f"{_num(r['installs_android'])} / {_num(r['installs_ios'])}",
                         'vs comp.': _var(r['installs'], pi),
                         'Rede declara': (_num(r['declara']) + " (" + _razao(r['declara'], r['installs']) + ")") if r['declara'] > 0 else "—",
                         'Impressões': _num(r['impressoes']) if r['impressoes'] > 0 else "—",
                         'Cliques': _num(r['cliques']) if r['cliques'] > 0 else "—",
                         'CTR': _pct(r['cliques'], r['impressoes'], 2) if r['impressoes'] > 0 else "—",
                         'Custo': _brl(r['custo'], 0) if r['custo'] > 0 else "—",
                         'CPI': _brl(_div_cpi(r['custo'], r['installs'])) if r['custo'] > 0 else "—",
                         'CPI comp.': _brl(_div_cpi(pc, pi)) if pi and pc else "—"})
        st_df(pd.DataFrame(rows), csv=gc, csv_nome="singular_download_por_campanha", use_container_width=True, hide_index=True, height=min(60 + 35 * max(len(rows), 1), 520))
        fonte("uma linha por campanha (unified_campaign_name) · CTR = cliques ÷ impressões declarados pela rede · CPI = custo ÷ instalações SDK · "
              "'Rede declara' traz a razão rede ÷ SDK (Meta costuma declarar ~1,4×; Google ≈ 1×) · Jampp: custo e cliques da alex_jampp_campaigns.")

    # rede diz × SDK vê — série mensal da razão
    a3, a4 = st.columns(2)
    with a3:
        m = camp[(camp['classe'] == 'download') & (camp['mes'].isin(list(mg))) & (camp['rede'].isin(['Google', 'Meta', 'TikTok']))]
        if not m.empty:
            gm = m.groupby(['mes', 'rede'], as_index=False)[['installs', 'installs_rede']].sum()
            gm = gm[gm['installs'] > 0]
            gm['valor'] = gm['installs_rede'] / gm['installs'] * 100
            gm = gm.rename(columns={'rede': 'serie'})[['mes', 'serie', 'valor']]
            linhas_mensal(gm, "Rede diz × SDK vê — instalações declaradas pela rede em % das do SDK", "% (100% = igual)", pct=True, rotulos=True,
                          subtitle="campanhas de Download · acima de 100% a rede conta mais que o SDK (view-through, janelas mais longas)")
            fonte("vw_singular_campanha_dia · adn_installs ÷ tracker_installs por mês × rede (Google/Meta/TikTok)")
        else:
            titulo("Rede diz × SDK vê", "sem dados nos meses do gráfico", "B")
    with a4:
        m = camp[(camp['classe'] == 'download') & (camp['mes'].isin(list(mg)))]
        if not m.empty:
            gm = m.groupby(['mes', 'rede'], as_index=False)['installs'].sum().rename(columns={'rede': 'serie', 'installs': 'valor'})
            chart_mensal(gm[['mes', 'serie', 'valor']], "Instalações pagas por rede (campanhas de Download)", "instalações / mês", stacked=True, rotulos=True,
                         subtitle="Google · Meta · TikTok · Jampp — só campanhas de Download (o restante do pago está no bloco C)",
                         fonte="vw_singular_campanha_dia")

    # ==================================================================================================================
    # B · ritmo da meta (pacing) e orgânico × pago por semana
    # ==================================================================================================================
    mes_ref = c_e.replace(day=1)
    dias_mes = mes_ref.days_in_month
    meta = float(metas.loc[metas['mes'] == mes_ref, 'meta'].iloc[0]) if (not metas.empty and (metas['mes'] == mes_ref).any()) else None
    mtd = dias[(dias['dia'] >= mes_ref) & (dias['dia'] <= c_e)]
    real = float(mtd['installs'].sum()) if not mtd.empty else 0.0
    d_dec = max(int((min(c_e, ult if ult is not None else c_e) - mes_ref).days) + 1, 1)
    d_rest = max(dias_mes - d_dec, 0)
    fim_real = min(c_e, ult) if ult is not None else c_e
    ult7 = dias[(dias['dia'] > fim_real - pd.Timedelta(days=7)) & (dias['dia'] <= fim_real)]
    med7 = float(ult7['installs'].sum()) / 7 if not ult7.empty else None
    proj = real / d_dec * dias_mes if d_dec else None
    titulo("B · Ritmo da meta de instalações (Download APP) e orgânico × pago por semana",
           f"mês de referência {mes_ref:%m/%Y} · realizado até {min(c_e, ult if ult is not None else c_e):%d/%m} · meta de alex_metas", "A")
    b1, b2, b3, b4 = st.columns(4)
    kpi(b1, "🎯", f"Meta do mês ({mes_ref:%m/%Y})", n_(meta) if meta else "sem meta", "alex_metas · Download APP (instalações Singular)")
    kpi(b2, "📈", "Realizado no mês (MTD)", f"{n_(real)}" + (f" <span style='font-size:13px;color:#64748b;'>· {pct(real, meta)} da meta</span>" if meta else ""),
        f"{d_dec} dia(s) decorrido(s) de {dias_mes} · meta linear até aqui {n_(meta * d_dec / dias_mes) if meta else '—'}", color="#2e8a4f")
    kpi(b3, "⏱️", "Ritmo necessário × ritmo atual", (f"{n_((meta - real) / d_rest) if meta and d_rest else '—'} / dia" if meta else "—"),
        f"para bater a meta nos {d_rest} dias restantes · média dos últimos 7 dias {n_(med7)} / dia", color="#0f172a")
    kpi(b4, "🔮", "Projeção linear do mês", n_(proj) if proj else "—",
        (f"{pct(proj, meta)} da meta · " if meta and proj else "") + "realizado ÷ dias decorridos × dias do mês — os últimos 8 dias ainda sobem", color="#b45309")

    bb1, bb2 = st.columns([1.6, 1])
    with bb1:
        # diário: pago por rede + orgânico (barras empilhadas), período dos Controles Globais
        dd = dp.groupby('dia', as_index=False)[['organico', 'google', 'meta', 'tiktok', 'jampp', 'outras_redes']].sum()
        if not dd.empty:
            long = dd.melt(id_vars='dia', var_name='serie', value_name='valor')
            lbl = {'google': 'Google', 'meta': 'Meta', 'tiktok': 'TikTok', 'jampp': 'Jampp', 'outras_redes': 'Outras fontes', 'organico': 'Orgânico'}
            long['serie'] = long['serie'].map(lbl)
            ordem = ['Google', 'Jampp', 'Meta', 'TikTok', 'Outras fontes', 'Orgânico']
            titulo("Instalações por dia — pago por rede + orgânico", f"{c_s:%d/%m} a {c_e:%d/%m} · barras empilhadas · Android + iOS", "A")
            fig = px.bar(long, x='dia', y='valor', color='serie', category_orders={'serie': ordem},
                         color_discrete_sequence=[cores[0], cores[1], cores[2], cores[3], cores[4], cores[6]], template=tpl_a)
            fig.update_layout(height=330, xaxis_title='', yaxis_title='instalações / dia', legend_title_text='', barmode='stack', bargap=0.15)
            fig.update_xaxes(tickformat='%d/%m')
            if ult is not None:
                x0 = max(ult - pd.Timedelta(days=7), c_s)
                if x0 <= min(c_e, ult):
                    fig.add_vrect(x0=x0, x1=min(c_e, ult) + pd.Timedelta(days=0.5), fillcolor='#f1f5f9', opacity=0.6, line_width=0,
                                  annotation_text='últimos 8 dias · ainda mudam', annotation_position='top left', annotation_font_size=10)
            st.plotly_chart(fig, use_container_width=True)
            fonte("vw_singular_downloads_dia · faixa cinza = janela de recarga D-8 (atribuição tardia e restatement)")
    with bb2:
        if meta and not mtd.empty:
            cum = mtd.groupby('dia', as_index=False)['installs'].sum().sort_values('dia')
            cum['Realizado (acumulado)'] = cum['installs'].cumsum()
            cum['Meta linear'] = [meta * ((d - mes_ref).days + 1) / dias_mes for d in cum['dia']]
            titulo("Acumulado do mês × meta linear", f"{mes_ref:%m/%Y} · meta {n_(meta)}", "B")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=cum['dia'], y=cum['Meta linear'], name='Meta linear', mode='lines', line=dict(color=cores[4], width=2, dash='dot')))
            fig.add_trace(go.Scatter(x=cum['dia'], y=cum['Realizado (acumulado)'], name='Realizado', mode='lines+markers', line=dict(color=cores[0], width=2.5), marker=dict(size=6)))
            fig.update_layout(template=tpl_b, height=330, xaxis_title='', yaxis_title='', showlegend=True,
                              legend=dict(orientation='h', x=0, y=1.08, title_text=''))
            fig.update_xaxes(tickformat='%d/%m', range=[mes_ref - pd.Timedelta(days=0.5), mes_ref + pd.Timedelta(days=dias_mes - 0.5)])
            st.plotly_chart(fig, use_container_width=True)
            fonte("vw_singular_downloads_dia × alex_metas · meta linear = meta × dias decorridos ÷ dias do mês (a instalação não é linear: promoções e fins de semana pesam)")
        else:
            titulo("Acumulado do mês × meta linear", "sem meta de Download APP para o mês de referência em alex_metas", "B")

    # semanas: orgânico × pago por OS
    sem = dias[(dias['dia'] >= c_s - pd.Timedelta(days=56)) & (dias['dia'] <= c_e)].copy()
    if not sem.empty:
        sem['semana'] = sem['dia'] - pd.to_timedelta(sem['dia'].dt.weekday, unit='D')
        w = sem.groupby('semana', as_index=False)[['installs', 'organico', 'pago']].sum()
        wa = sem[sem['os'] == 'Android'].groupby('semana')[['installs', 'pago']].sum()
        wi = sem[sem['os'] == 'iOS'].groupby('semana')[['installs', 'pago']].sum()
        nd = sem.groupby('semana')['dia'].nunique()
        rows = []
        for _, r in w.sort_values('semana', ascending=False).iterrows():
            s = r['semana']
            rows.append({'Semana (seg)': f"{s:%d/%m}" + (f" · {int(nd[s])} d" if nd[s] < 7 else ""), 'Instalações': _num(r['installs']),
                         'Orgânico': _num(r['organico']), 'Pago': _num(r['pago']), '% pago': _pct(r['pago'], r['installs']),
                         'Android % pago': _pct(wa.loc[s, 'pago'], wa.loc[s, 'installs']) if s in wa.index else "—",
                         'iOS % pago (ATT)': _pct(wi.loc[s, 'pago'], wi.loc[s, 'installs']) if s in wi.index else "—",
                         'Orgânico ÷ pago': _razao(r['organico'], r['pago'])})
        titulo("Orgânico × pago por semana (últimas 8 semanas + período)", "semanas de segunda a domingo · 'Orgânico ÷ pago' lê o halo da mídia: quanto orgânico cada instalação paga acompanha", "A")
        st_df(pd.DataFrame(rows), csv=w, csv_nome="singular_organico_pago_semana", use_container_width=True, hide_index=True)
        fonte("vw_singular_downloads_dia · semanas parciais marcadas com o nº de dias · no iOS o pago é subestimado (ATT)")

    # ==================================================================================================================
    # C · instalações vindas de campanhas do site + reengajamentos
    # ==================================================================================================================
    titulo("C · Efeito cruzado — instalações vindas de campanhas que não são de Download, e reengajamentos",
           f"{c_s:%d/%m} a {c_e:%d/%m} · o custo dessas campanhas é do site (não entra no CPI do app)", "A")
    c1, c2 = st.columns(2)
    with c1:
        sc = cp[cp['classe'].isin(['site_venda', 'site_lead', 'site_branding', 'site_outra', 'outra_fonte', 'retargeting'])]
        g = (sc.groupby(['classe', 'rede', 'campanha'], as_index=False)[['installs', 'installs_android', 'installs_ios', 'reengajamentos', 'custo']].sum()
             .sort_values('installs', ascending=False))
        g = g[g['installs'] > 0].head(25)
        gp = cpp.groupby(['classe', 'rede', 'campanha'])['installs'].sum()
        rows = []
        for _, r in g.iterrows():
            k = (r['classe'], r['rede'], r['campanha'])
            nome = r['campanha'] if isinstance(r['campanha'], str) else '(sem nome)'
            rows.append({'Tipo': CLASSE_LBL.get(r['classe'], r['classe']), 'Rede': r['rede'], 'Campanha': (nome[:60] + '…') if len(nome) > 60 else nome,
                         'Instalações': _num(r['installs']), 'And. / iOS': f"{_num(r['installs_android'])} / {_num(r['installs_ios'])}",
                         'vs comp.': _var(r['installs'], float(gp.loc[k]) if k in gp.index else None),
                         'Custo da campanha (site)': _brl(r['custo'], 0) if r['custo'] > 0 else "—"})
        st_df(pd.DataFrame(rows) if rows else pd.DataFrame([{'Tipo': 'sem instalações fora das campanhas de Download no período'}]),
              csv=g, csv_nome="singular_installs_campanhas_site", use_container_width=True, hide_index=True, height=min(60 + 35 * max(len(rows), 1), 480))
        fonte("vw_singular_campanha_dia · classe ≠ download/organico · top 25 · 'Custo da campanha (site)' = custo total da campanha visto pela Singular "
              "(todos os OS) — é gasto do site, serve só para dimensionar; não calcule CPI com ele.")
        st.caption(f"No período: **{n_(assist)}** instalações pagas vieram de campanhas de Venda/Lead/Branding do site ({pct(assist, pago)} do pago). "
                   "É efeito cruzado da mídia do site no app — argumento para o planejamento conjunto, não para mudar o CPI das campanhas de Download.")
    with c2:
        rg = cp[cp['reengajamentos'] > 0]
        g = (rg.groupby(['classe', 'rede', 'campanha'], as_index=False)[['reengajamentos', 'installs', 'custo']].sum()
             .sort_values('reengajamentos', ascending=False).head(20))
        gp = cpp.groupby(['classe', 'rede', 'campanha'])['reengajamentos'].sum()
        rows = []
        for _, r in g.iterrows():
            k = (r['classe'], r['rede'], r['campanha'])
            nome = r['campanha'] if isinstance(r['campanha'], str) else '(sem nome)'
            rows.append({'Tipo': CLASSE_LBL.get(r['classe'], r['classe']), 'Rede': r['rede'], 'Campanha': (nome[:60] + '…') if len(nome) > 60 else nome,
                         'Reengajamentos': _num(r['reengajamentos']), 'vs comp.': _var(r['reengajamentos'], float(gp.loc[k]) if k in gp.index else None),
                         'Instalações': _num(r['installs']),
                         'Custo ÷ reeng.': _brl(_div_cpi(r['custo'], r['reengajamentos'])) if r['custo'] > 0 and r['classe'] in ('download', 'retargeting') else "—"})
        st_df(pd.DataFrame(rows) if rows else pd.DataFrame([{'Tipo': 'sem reengajamentos no período'}]),
              csv=g, csv_nome="singular_reengajamentos", use_container_width=True, hide_index=True, height=min(60 + 35 * max(len(rows), 1), 480))
        fonte("vw_singular_campanha_dia · tracker_reengagements = app já instalado reaberto após um toque de mídia (re-engagement attribution) · "
              "'Custo ÷ reeng.' só quando o custo é da própria campanha de app (Download/Retargeting); para campanhas do site fica '—'.")
        st.caption(f"Reengajamentos no período: **{n_(reeng)}** {delta(reeng, reeng_p)} — concentrados nas campanhas de Lead/Cadastro da Meta (retargeting de quem já tem o app).")

    # ==================================================================================================================
    # D · conciliação de custo (Singular × RESUMO) e higiene de nomenclatura
    # ==================================================================================================================
    titulo("D · Conciliação de custo (Singular × RESUMO) e nomenclatura das campanhas",
           "por mês × plataforma · a diferença esperada é pequena e positiva no RESUMO (Jampp fora da Singular, restatement, câmbio)", "A")
    d1, d2 = st.columns([1.4, 1])
    with d1:
        meses_d = list(mg)
        sg = camp[(camp['classe'] == 'download') & (camp['mes'].isin(meses_d))].groupby(['mes', 'rede'])['custo'].sum()
        rs = resumo[resumo['mes'].isin(meses_d)].groupby(['mes', 'plataforma'])['venda'].sum() if not resumo.empty else pd.Series(dtype=float)
        plat = {'Google': 'Google', 'Meta': 'Meta', 'TikTok': 'TikTok', 'Jampp': 'Jampp'}
        rows = []
        for mes in meses_d:
            tot_s = tot_r = 0.0
            for rede, pl in plat.items():
                s = float(sg.get((mes, rede), 0.0)); r = float(rs.get((mes, pl), 0.0)) if not rs.empty else 0.0
                tot_s += s; tot_r += r
                if s or r:
                    rows.append({'Mês': f"{mes:%m/%Y}", 'Plataforma': rede, 'Custo Singular (Download)': _brl(s, 0), 'RESUMO (App do Filiado)': _brl(r, 0),
                                 'Δ RESUMO − Singular': _brl(r - s, 0), 'Δ %': _pct(r - s, s) if s else "—"})
            rows.append({'Mês': f"{mes:%m/%Y}", 'Plataforma': 'Total', 'Custo Singular (Download)': _brl(tot_s, 0), 'RESUMO (App do Filiado)': _brl(tot_r, 0),
                         'Δ RESUMO − Singular': _brl(tot_r - tot_s, 0), 'Δ %': _pct(tot_r - tot_s, tot_s) if tot_s else "—"})
        csv = pd.DataFrame([{'mes': m, 'rede': k, 'custo_singular': float(v)} for (m, k), v in sg.items()])
        st_df(pd.DataFrame(rows), csv=csv, csv_nome="singular_x_resumo_custo", use_container_width=True, hide_index=True)
        fonte("Singular: adn_cost das campanhas de Download (Google/Meta/TikTok) e spend_brl Jampp (alex_jampp_campaigns) · RESUMO_INVESTIMENTO_DIARIO canal "
              "'App do Filiado', coluna venda (sp_update_resumo_investimento: campanhas com 'download' no nome + Jampp). Diferenças grandes (> 10%) = "
              "campanha de Download fora da taxonomia, conta não conectada à Singular ou restatement ainda não recarregado.")
    with d2:
        nm = cp[(cp['nome_padrao'] == 0) & (cp['installs'] > 0)]
        g = nm.groupby(['rede', 'campanha'], as_index=False)[['installs', 'custo']].sum().sort_values('installs', ascending=False).head(20)
        rows = [{'Rede': r['rede'], 'Campanha fora do padrão GT7_…': r['campanha'], 'Instalações': _num(r['installs']), 'Custo': _brl(r['custo'], 0) if r['custo'] > 0 else "—"}
                for _, r in g.iterrows()]
        st_df(pd.DataFrame(rows) if rows else pd.DataFrame([{'Rede': '✓', 'Campanha fora do padrão GT7_…': 'todas as campanhas Google/Meta/TikTok com instalação seguem a taxonomia'}]),
              csv=g, csv_nome="singular_campanhas_fora_padrao", use_container_width=True, hide_index=True)
        fonte("vw_singular_campanha_dia · nome_padrao = 0 (Google/Meta/TikTok sem prefixo GT7_) — 'Copy 1 of …' e nomes antigos quebram a classificação "
              "Download/Lead/Venda da RESUMO e da conciliação; renomear na plataforma. Jampp tem taxonomia própria (UA/RTGT) e fica fora.")
        sem_custo = dl.groupby(['rede', 'campanha'], as_index=False)[['installs', 'custo']].sum()
        sem_custo = sem_custo[(sem_custo['installs'] >= 50) & (sem_custo['custo'] <= 0)]
        if not sem_custo.empty:
            st.caption("⚠️ Campanhas de Download **com instalação e sem custo** no período: "
                       + " · ".join(f"{r['rede']} — {str(r['campanha'])[:50]} ({_num(r['installs'])})" for _, r in sem_custo.head(5).iterrows())
                       + ". Jampp: nome da campanha não casa com a alex_jampp_campaigns; Google/Meta/TikTok: conta sem data connector de custo na Singular.")


    # ==================================================================================================================
    # E · coortes (fase 2, 26/10): o que a instalação vira — cadastro, compra, sessões, retenção — por rede e campanha
    # ==================================================================================================================
    coh, err5 = _safe(_load_cohort, cquery, cols=_COLS_COH + ['mes'])
    titulo("E · O que a instalação vira — cadastro, compra, sessões e retenção por rede e campanha (coortes Singular)",
           "coorte = quem instalou no dia; 7d/30d = fez o evento até 7/30 dias depois · só coortes maduras entram nas taxas", "A")
    if err5 or coh.empty:
        st.caption("Coortes ainda indisponíveis: " + (f"`{err5}`" if err5 else "`vw_singular_cohort_campanha_dia` sem linhas") +
                   " — fase 2 da Singular (`gas/singular_cohort.gs` → `alex_singular_cohort`, carga 09:45 e backfill desde abr/25).")
        return
    ult_c = coh['dia'].max()
    mat7, mat30 = min(c_e, ult_c - pd.Timedelta(days=7)), min(c_e, ult_c - pd.Timedelta(days=30))
    cp_k = camp.groupby(['dia', 'rede', 'campanha', 'classe'], as_index=False)[['installs', 'custo']].sum()

    def _janela(df, a, b):
        return df[(df['dia'] >= a) & (df['dia'] <= b)] if not df.empty else df

    def _taxas(chave):
        """Tabela por `chave` (rede ou campanha): installs maduros, % cadastro 7d, % compra no app 7d/30d (evento), R$ do evento ÷ install, sessões/install,
        % retidos 7d, custo ÷ cadastro 7d e custo ÷ compra 30d (só onde há custo = campanhas de Download)."""
        i7, i30 = _janela(cp_k, c_s, mat7), _janela(cp_k, c_s, mat30)
        c7, c30 = _janela(coh, c_s, mat7), _janela(coh, c_s, mat30)
        if chave == 'campanha':
            i7, i30 = i7[i7['classe'] == 'download'], i30[i30['classe'] == 'download']
            keys = ['rede', 'campanha']
        else:
            keys = ['rede']
        g7 = i7.groupby(keys)[['installs', 'custo']].sum(); g30 = i30.groupby(keys)[['installs', 'custo']].sum()
        k7 = c7.groupby(keys)[['cadastros_7d', 'compras_7d', 'sessoes_7d', 'retidos_7d']].sum()
        k30 = c30.groupby(keys)[['compras_30d', 'receita_compra_ltv', 'compras_ltv']].sum()
        rows = []
        for idx in g7.sort_values('installs', ascending=False).index:
            inst7 = float(g7.loc[idx, 'installs']); cst7 = float(g7.loc[idx, 'custo'])
            inst30 = float(g30.loc[idx, 'installs']) if idx in g30.index else 0.0; cst30 = float(g30.loc[idx, 'custo']) if idx in g30.index else 0.0
            if inst7 <= 0:
                continue
            cad = float(k7.loc[idx, 'cadastros_7d']) if idx in k7.index else 0.0
            cmp7 = float(k7.loc[idx, 'compras_7d']) if idx in k7.index else 0.0
            ses = float(k7.loc[idx, 'sessoes_7d']) if idx in k7.index else 0.0
            ret = float(k7.loc[idx, 'retidos_7d']) if idx in k7.index else 0.0
            cmp30 = float(k30.loc[idx, 'compras_30d']) if idx in k30.index else 0.0
            rec = float(k30.loc[idx, 'receita_compra_ltv']) if idx in k30.index else 0.0
            r = {'Rede': idx[0] if isinstance(idx, tuple) else idx}
            if chave == 'campanha':
                nome = idx[1] if isinstance(idx[1], str) else '(sem nome)'
                r['Campanha'] = (nome[:60] + '…') if len(nome) > 60 else nome
            r.update({'Instalações (coortes maduras)': _num(inst7), 'Cadastro 7d': _pct(cad, inst7), 'Compra no app 7d (evento)': _pct(cmp7, inst7, 2),
                      'Compra no app 30d (evento)': _pct(cmp30, inst30, 2) if inst30 > 0 else "—", 'R$ do evento (ltv) ÷ install': _brl(rec / inst30) if inst30 > 0 else "—",
                      'Sessões ÷ install (7d)': _razao(ses, inst7), 'Retidos 7d': _pct(ret, inst7),
                      'Custo ÷ cadastro 7d': _brl(cst7 / cad) if cst7 > 0 and cad > 0 else "—",
                      'Custo ÷ compra no app 30d': _brl(cst30 / cmp30) if cst30 > 0 and cmp30 > 0 else "—"})
            rows.append(r)
        return pd.DataFrame(rows), pd.concat([g7.add_suffix('_7'), k7, g30.add_suffix('_30'), k30], axis=1).reset_index()

    e1, e2 = st.columns([1, 1.6])
    with e1:
        t, raw = _taxas('rede')
        st_df(t if not t.empty else pd.DataFrame([{'Rede': 'sem coortes maduras no período'}]), csv=raw, csv_nome="singular_coortes_por_rede",
              use_container_width=True, hide_index=True)
        fonte(f"vw_singular_cohort_campanha_dia × vw_singular_campanha_dia · coortes 7d = instalações de {c_s:%d/%m} a {mat7:%d/%m}; 30d até {mat30:%d/%m} "
              f"(última coorte carregada {ult_c:%d/%m}) · custo só das campanhas de Download.")
    with e2:
        t, raw = _taxas('campanha')
        st_df(t if not t.empty else pd.DataFrame([{'Rede': 'sem coortes maduras no período'}]), csv=raw, csv_nome="singular_coortes_por_campanha",
              use_container_width=True, hide_index=True, height=min(60 + 35 * max(len(t), 1), 480))
        fonte("campanhas de Download · 'Compra no app (evento)' = sng_ecommerce_purchase visto pela Singular, qualquer produto (R$ ~5,50 por evento; "
              "NÃO é filiação confirmada — conferência de 27/10: não é comparável ao NOMINAL por construção e o valor não é o da adesão; a confirmação "
              "depende do time do app) · 'Cadastro' = App Lead (~69% dos installs em 7d, coerente com o cadastro).")
    e3, e4 = st.columns(2)
    with e3:
        # janela fixa das últimas coortes com 30 dias fechados (não segue o Período: num período recente não haveria coorte madura)
        rt_a, rt_b = ult_c - pd.Timedelta(days=60), ult_c - pd.Timedelta(days=30)
        base30 = _janela(coh, rt_a, rt_b)
        inst30 = _janela(cp_k, rt_a, rt_b).groupby('rede')['installs'].sum()
        if not base30.empty and not inst30.empty:
            rr = base30.groupby('rede')[['retidos_1d', 'retidos_3d', 'retidos_7d', 'retidos_14d', 'retidos_30d']].sum()
            pts = []
            for rede, row in rr.iterrows():
                den = float(inst30.get(rede, 0))
                if den <= 0:
                    continue
                for dcol, dd in (('retidos_1d', 1), ('retidos_3d', 3), ('retidos_7d', 7), ('retidos_14d', 14), ('retidos_30d', 30)):
                    pts.append({'dia': dd, 'serie': rede, 'valor': float(row[dcol]) / den * 100})
            if pts:
                dfp = pd.DataFrame(pts)
                titulo("Curva de retenção por rede — % da coorte que voltou ao app", f"instalações de {rt_a:%d/%m} a {rt_b:%d/%m} (últimas coortes com 30 dias fechados) · Retained Users ÷ installs", "B")
                fig = px.line(dfp, x='dia', y='valor', color='serie', markers=True, color_discrete_sequence=cores, template=tpl_b)
                fig.update_traces(line_width=2.5, marker_size=7)
                fig.update_layout(height=320, xaxis_title='dias após a instalação', yaxis_title='', showlegend=True, legend=dict(orientation='h', x=0, y=1.08, title_text=''))
                fig.update_yaxes(ticksuffix='%'); fig.update_xaxes(tickvals=[1, 3, 7, 14, 30])
                st.plotly_chart(fig, use_container_width=True)
                fonte("alex_singular_cohort · App Retained Users por período · a Singular só fecha a retenção em período encerrado (ltv = 0 por desenho)")
    with e4:
        mm = coh[(coh['mes'].isin(list(mg))) & (coh['dia'] <= ult_c - pd.Timedelta(days=7))]
        im = cp_k[(cp_k['dia'].dt.to_period('M').dt.to_timestamp().isin(list(mg))) & (cp_k['dia'] <= ult_c - pd.Timedelta(days=7))].copy()
        if not mm.empty and not im.empty:
            im['mes'] = im['dia'].dt.to_period('M').dt.to_timestamp()
            den = im.groupby(['mes', 'rede'])['installs'].sum()
            num = mm.groupby(['mes', 'rede'])['cadastros_7d'].sum()
            j = pd.concat([num, den], axis=1).dropna()
            j = j[j['installs'] > 0]
            if not j.empty:
                j['valor'] = j['cadastros_7d'] / j['installs'] * 100
                lm = j.reset_index().rename(columns={'rede': 'serie'})[['mes', 'serie', 'valor']]
                lm = lm[lm['serie'].isin(['Google', 'Meta', 'TikTok', 'Jampp', 'Orgânico'])]
                linhas_mensal(lm, "Cadastro em 7 dias por rede — % das instalações do mês", "%", pct=True, rotulos=True,
                              subtitle="instalações até 7 dias antes da última coorte carregada · a Singular só tem coortes desde abr/25 (backfill)")
                fonte("vw_singular_cohort_campanha_dia (App Lead 7d) ÷ vw_singular_campanha_dia (installs)")
    note("<b>🧪 Como ler as coortes.</b> Uma coorte é o conjunto de quem instalou num dia; '7d' conta quem fez o evento até 7 dias depois, então os últimos 7 dias "
         "do período ficam fora das taxas (e 30 dias para as de 30d). <b>Cadastro</b> (App Lead) é o evento mais estável. <b>Compra no app (evento)</b> é o evento de compra que o SDK da Singular vê, de qualquer produto "
         "— R$ ~5,50 por evento em média, ou seja, não é a adesão; a venda oficial continua sendo o NOMINAL (a confirmação do que o evento carrega "
         "depende do time do app). <b>Orgânico</b> no iOS carrega mídia (ATT). As métricas de conversão da API medem o SITE (os = Web/Unknown) e "
         "ficaram fora da carga (27/10); a carga diária traz 7 métricas: cadastro, compra, receita, sessões, retidos, logins, receita total.", bg="#f8fafc", icon="🧪")
