"""R77 (27/10/2026) — explicadores para a analista de mídia do app e conferência das réguas.

app.py:
  1) 📡 7 · CleverTap: nota 📏 das três réguas reescrita + expander "📖 Como esta sub-aba é construída" (origem da mídia/utm_source agregada,
     como cada tabela e gráfico é montado, as três réguas de instalação e como cruzam com o lake) + coluna 'utm_source (top 3)' na tabela
     'Mídia (utm_source agrupado)'.
  2) 🎯 5 · Leads do app: nota de consistência com o funil (lead puro = cadastro freemium que ainda não filiou — conferido no Athena em
     27/10: jul 33.696 = 33.696 · ago 26.641 = 26.641 · set 27.997 = 27.997).
  3) 📨 CRM: aviso dos templates 'CDT - AQUI - …' (3535) fora da régua GT7 + coluna 'Número (de-para)' na tabela por UTM campaign.
midia_app_tab.py é trocado inteiro (R77) — não passa por aqui.

Idempotente: cada âncora é trocada só se a versão nova ainda não estiver no arquivo. Backup em app_bak_r77.py.
Uso:  .venv\\Scripts\\python.exe diagnostics\\patch_r77_explicadores.py
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


# ---------------------------------------------------------------------------------------------------------------------
# 1) 📡 7 — nota 📏 reescrita + guia da sub-aba
# ---------------------------------------------------------------------------------------------------------------------
ANC_NOTA = '''        _tv_note("<b>📏 Três réguas de “instalação” — e nenhuma é download da loja.</b> "
                 "<b>CleverTap · App Installed</b> = 1ª abertura do app com o SDK do CleverTap (um evento por aparelho novo). "
                 "<b>Singular · installs</b> = 1ª abertura vista pelo SDK do Singular, com atribuição de mídia (orgânico + pago) — é a régua do RMA. "
                 "<b>Downloads (1º login)</b> = 1º login no app pelo lake (sub-aba 1) — exige conta e chega com dias de atraso. "
                 "Leia as três lado a lado; não some nem troque uma pela outra. No iOS o pago do Singular cai em orgânico (ATT).", icon="📏")
        _ct_c1, _ct_c2 = st.columns(2)
'''
NOVA_NOTA = '''        _tv_note("<b>📏 Três réguas de “instalação” — e nenhuma é download da loja.</b> "
                 "<b>CleverTap · App Installed</b> = 1ª abertura do app com o SDK do CleverTap (um evento por aparelho novo, sem atribuição de mídia). "
                 "<b>Singular · installs</b> = 1ª abertura vista pelo SDK da Singular, com atribuição de mídia (orgânico + pago) — a régua oficial de "
                 "Installs/Downloads nos relatórios (20/10/2026). <b>Downloads (1º login)</b> = 1º login no app pelo lake (fl_data_login) — exige conta, "
                 "é por pessoa (CPF) e chega com dias de atraso. Os dois SDKs contam <b>aparelhos</b> e batem entre si (±2% nos últimos meses); o lake conta "
                 "<b>pessoas que criaram/entraram na conta</b> (~40% das instalações). Leia as três lado a lado; não some nem troque uma pela outra. "
                 "No iOS o pago da Singular cai em orgânico (ATT). Detalhes no guia 📖 abaixo.", icon="📏")
        # R77 (27/10/2026): guia da sub-aba — origem da mídia/utm_source, construção de cada bloco e as três réguas × lake
        with st.expander("📖 Como esta sub-aba é construída — de onde vem a 'mídia' (utm_source), como cada tabela/gráfico é montado e as três réguas de instalação"):
            st.markdown(
                "**De onde vem a 'Mídia (utm_source agrupado)'.** O site (cartaodetodos.com.br / adesão) e o app carregam o SDK do CleverTap. Quando "
                "alguém chega por um link com parâmetros UTM, o SDK dispara o evento **UTM Visited** com `utm_source`, `utm_campaign` e `utm_content` "
                "do link. Todo dia às 10:20 o `clevertap_export` baixa o export desse evento (janela D-8 → D-1) e agrega em `alex_clevertap_utm_dia` "
                "(dia × plataforma × utm_source × utm_campaign; `eventos` = visitas, `usuarios` = usuários únicos do dia). A coluna **Mídia** é o "
                "`utm_source` **agrupado por regras de nome** no app (`_ct_plat`): `google` / `adwords` / `youtube` → Google Ads / YouTube; `facebook` / "
                "`fb` / `ig` / `instagram` / `apps.facebook.com` → Meta; `tiktok*` → TikTok; `google-play` / `apple` / `app-store` → Loja de apps "
                "(aberturas do app vindas do install referrer da loja); `whatsapp*` / `zenvia*` → WhatsApp / SMS; `hs_*` / `hubspot` / `email` → "
                "E-mail / CRM; `jampp*` → Jampp; `chatgpt` / `gemini` / `perplexity` → IA; vazio ou `(not_set)` → não informado; **o resto cai em "
                "'Outros'** (redes de display/afiliados como `adsplay`, `raads`, `osmedia`, blogs, parceiros) — a coluna 'utm_source (top 3)' mostra o "
                "que compõe cada grupo. O que o seu link carrega em `utm_source` é exatamente o que aparece aqui: um `utm_source` novo fora dessas "
                "regras entra em 'Outros' até a regra ser ampliada.\\n\\n"
                "**Como cada bloco é montado.**\\n\\n"
                "| Bloco | Fonte | Construção |\\n|---|---|---|\\n"
                "| Cards do topo | `alex_clevertap_eventos_dia` (API counts/trends e counts/top), `vw_singular_downloads_dia`, `alex_app_dash_mes` | soma dos dias do Período de Análise (DAU = média dos dias); comparação = mesmo trecho do período anterior |\\n"
                "| Instalações — três réguas (7a) | CleverTap App Installed (counts/trends) · Singular installs (`vw_singular_downloads_dia`) · 1º login (`alex_app_dash_mes` s1_funil.downloads) | série **mensal**, uma linha por régua, sem join entre elas — são contagens independentes do mesmo mês |\\n"
                "| Aberturas por sistema (7a) | App Launched × OS (counts/top) | eventos (aberturas), não usuários |\\n"
                "| Orgânico × pago (7a-bis) | `vw_singular_downloads_dia` (installs, pago = `is_organic = 0`) | mensal, Android + iOS; a legenda do período soma os dias do Período de Análise |\\n"
                "| CPI por rede (7a-bis) | `vw_singular_cpi_mes` | custo da campanha de Download (adn_cost; Jampp spend_brl) ÷ installs SDK, só Android |\\n"
                "| Funil de push (7b) | Notification Sent / Push Impressions / Notification Viewed / Clicked (counts/trends e counts/top × Campaign type); piso = Charged·filiation até 24 h após clique (`alex_clevertap_charged` × `_notif_click`) | sequência de leitura, não coorte fechada |\\n"
                "| Visitas ao site por mídia (7c) | `alex_clevertap_utm_dia` | gráfico mensal empilhado por grupo de utm_source; tabelas: grupo × visitas no período e top 15 utm_campaign · utm_source |\\n\\n"
                "**As três réguas de instalação e como cruzam com o lake.**\\n\\n"
                "| Régua | Quem conta | Grão | Quando usar |\\n|---|---|---|---|\\n"
                "| CleverTap · App Installed | SDK do CleverTap na 1ª abertura do app | aparelho, por dia; sem mídia | conferir o volume do SDK e dimensionar a base de push/CRM |\\n"
                "| Singular · installs (`tracker_installs`) | SDK da Singular na 1ª abertura, com a rede/campanha do último toque (ou orgânico) | aparelho, por dia, por campanha; os últimos ~8 dias mudam (restatement) | **a régua oficial**: metas, RMA, CPI, pago × orgânico (📣 8) |\\n"
                "| Downloads · 1º login (lake) | `fl_data_login.data_app` — a pessoa entrou numa conta no app | pessoa (CPF), por mês; chega com dias de atraso; desde 28/09 recebe logins sem CPF em massa | a única que cruza por CPF com cadastro, compra e filiação (funil 📲 1, coortes de freemium) |\\n\\n"
                "Nenhuma das três é ligada linha a linha às outras: o cruzamento é **lado a lado, no mesmo mês**. O funil da 📲 1 encadeia Singular "
                "installs → 1º login → cadastro → compra como contagens do mesmo mês (não como coorte): por isso a instalação pode ser de um mês e o "
                "login de outro, e por isso o 1º login (pessoas com conta) fica em ~40% das instalações (aparelhos, muitos sem conta). Diferença entre "
                "CleverTap e Singular de poucos % é normal (SDKs diferentes, horário de corte e restatement); diferença grande indica SDK fora do ar numa "
                "versão do app.")
        _ct_c1, _ct_c2 = st.columns(2)
'''
once(ANC_NOTA, NOVA_NOTA, "📡 7: nota 📏 + guia da sub-aba")

ANC_TAB = '''            _ct_rows_p = [{'Mídia (utm_source agrupado)': k, 'Visitas': _tv_n(v), '% das visitas': _tv_pct(float(v), _ct_vis), '_level': 1, '_is_eff': False}
                          for k, v in _ct_pl.items()]
            _st_mt(_ct_rows_p or [{'Mídia (utm_source agrupado)': 'sem dados', '_level': 1}],
                                            ['Mídia (utm_source agrupado)', 'Visitas', '% das visitas'])
'''
NOVA_TAB = '''            # R77: top 3 utm_source de cada grupo, para a analista ver o que compõe cada 'mídia' (sobretudo 'Outros')
            _ct_src = (_ctu_m.assign(pl=_ctu_m['utm_source'].map(_ct_plat)).groupby(['pl', 'utm_source'], dropna=False)['eventos'].sum()
                       .reset_index().sort_values('eventos', ascending=False)) if not _ctu_m.empty else pd.DataFrame(columns=['pl', 'utm_source', 'eventos'])

            def _ct_top_src(pl):
                s = _ct_src[_ct_src['pl'] == pl].head(3)
                return " · ".join(f"{str(k)[:28]} {_tv_n(v)}" for k, v in zip(s['utm_source'], s['eventos'])) or "—"
            _ct_rows_p = [{'Mídia (utm_source agrupado)': k, 'Visitas': _tv_n(v), '% das visitas': _tv_pct(float(v), _ct_vis),
                           'utm_source (top 3)': _ct_top_src(k), '_level': 1, '_is_eff': False}
                          for k, v in _ct_pl.items()]
            _st_mt(_ct_rows_p or [{'Mídia (utm_source agrupado)': 'sem dados', '_level': 1}],
                                            ['Mídia (utm_source agrupado)', 'Visitas', '% das visitas', 'utm_source (top 3)'])
'''
once(ANC_TAB, NOVA_TAB, "📡 7: coluna 'utm_source (top 3)'")

# ---------------------------------------------------------------------------------------------------------------------
# 2) 🎯 5 — consistência lead puro × funil
# ---------------------------------------------------------------------------------------------------------------------
ANC_L5 = '''                       "lead veio; esta base diz o que ele FEZ depois — login, cartão digital, cashback.")
            k1, k2, k3, k4 = st.columns(4)
            _tv_kpi(k1, "🌡️", "Leads puros (nunca filiaram)", _tv_n(_tot_nf),
'''
NOVA_L5 = '''                       "lead veio; esta base diz o que ele FEZ depois — login, cartão digital, cashback.")
            st.caption("**Mesma definição do funil (📲 1), em outro corte.** 'Lead puro' = cadastro no app (`fl_plano_usuario.dt_criacao`) de um CPF "
                       "**sem nenhuma filiação** no histórico — exatamente o 'entrou como freemium' do funil **menos** os que já converteram (coorte por mês "
                       "de cadastro no funil = estoque de quem ainda não filiou aqui). Conferido no Athena em 27/10/2026, por mês de cadastro: jul/26 "
                       "33.696 = 33.696 · ago/26 26.641 = 26.641 · set/26 27.997 = 27.997. O funil mostra o **fluxo** (quantos entraram no mês); esta "
                       "sub-aba mostra o **estoque** (quantos ainda estão sem filiar hoje) — por isso os totais não são para somar nem comparar diretamente.")
            k1, k2, k3, k4 = st.columns(4)
            _tv_kpi(k1, "🌡️", "Leads puros (nunca filiaram)", _tv_n(_tot_nf),
'''
once(ANC_L5, NOVA_L5, "🎯 5: nota de consistência com o funil")

# ---------------------------------------------------------------------------------------------------------------------
# 3) 📨 CRM — templates de aquisição fora da régua GT7 (3535 'CDT - AQUI - …') + número provável por UTM
# ---------------------------------------------------------------------------------------------------------------------
ANC_CRM = '''        if _nums_sel is not None or _utm_sel:
            st.caption(f"🔎 Filtros ativos — gasto: **{_num_lbl}**"'''
NOVA_CRM = '''        # R77 (27/10/2026): varredura da aba — templates de AQUISIÇÃO sem 'GT7' no nome ('CDT - AQUI - disparo N leads sem CEP …', número 3535
        # Lia Disparos, set/26 R$ 5.208) ficam fora da régua e do preset 'c/ Lia' (que, por isso, hoje é igual ao 's/ Lia'). A planilha do time
        # de CRM conta esses disparos; a decisão de incluir 'AQUI' na régua muda o CPA publicado e está com o Álex — até lá, só o aviso.
        _aqui_fora = load_crm_aqui_fora()
        if not _aqui_fora.empty:
            _af12 = _aqui_fora[_aqui_fora['dia'] >= pd.Timestamp(reference_date) - pd.DateOffset(months=12)]
            if not _af12.empty:
                _af_m = _af12.groupby(_af12['dia'].dt.to_period('M'))['gasto_bd'].sum()
                _af_txt = " · ".join(f"{m.strftime('%m/%Y')}: {format_money(v)}" for m, v in _af_m.items() if v > 0)
                st.caption(f"⚠️ **Templates de aquisição fora da régua GT7** ('CDT - AQUI - …', sem 'GT7' no nome; números "
                           f"{', '.join(sorted(_af12['num_tel'].unique()))}): {_af_txt} na régua BD_CRM — a planilha do time de CRM conta esses "
                           "disparos, o dashboard ainda não (regra `GT7` no nome). Padronizar o nome com 'GT7' ou decidir a inclusão de 'AQUI' na régua.")
        if _nums_sel is not None or _utm_sel:
            st.caption(f"🔎 Filtros ativos — gasto: **{_num_lbl}**"'''
once(ANC_CRM, NOVA_CRM, "📨 CRM: aviso dos templates AQUI fora da régua GT7")

ANC_LD = '''def load_crm_cpa_num():
    try:
        return _load_crm_cpa_num_raw()
    except Exception:
        return pd.DataFrame(columns=_CPA_NUM_COLS)
'''
NOVO_LD = ANC_LD + '''

@st.cache_data(ttl=43200)
def _load_crm_aqui_fora_raw():
    """R77: disparos de aquisição com 'AQUI' no nome e SEM 'GT7' (ex.: 'CDT - AQUI - disparo 1 leads sem CEP 24/09', número 3535) — a planilha
    BD_CRM do time conta, a régua GT7 do dashboard não. Só para o aviso na aba 📨; não entra em nenhum número."""
    d = cquery("""SELECT report_date AS dia, COALESCE(channel_number, channel_name, '(sem canal)') AS num_tel,
                         ROUND(SUM(CASE WHEN status IN ('Enviada','Entregue','Lida') THEN total_messages ELSE 0 END) * 0.32, 2) AS gasto_bd
                  FROM alex_zenvia_template_status
                  WHERE UPPER(template_name) LIKE '%%AQUI%%' AND UPPER(template_name) NOT LIKE '%%GT7%%'
                    AND UPPER(template_name) NOT LIKE '%%AINDAPORAQUI%%'
                  GROUP BY 1, 2""", ttl=0)
    d['gasto_bd'] = pd.to_numeric(d['gasto_bd'], errors='coerce').fillna(0.0)
    d['num_tel'] = d['num_tel'].astype(str)
    d['dia'] = pd.to_datetime(d['dia'])
    return d[d['gasto_bd'] > 0]


def load_crm_aqui_fora():
    try:
        return _load_crm_aqui_fora_raw()
    except Exception:
        return pd.DataFrame(columns=['dia', 'num_tel', 'gasto_bd'])


# R77: de-para utm_campaign → número de origem pelo nome dos templates GT7 (claude-toolkit\\out\\depara_template_utm_2026.csv, status
# 'casado' = casamento exato/estrutural; 21/10/2026). Só para ROTULAR a tabela por UTM da aba 📨 — o custo continua sem UTM.
_CRM_UTM_NUM = {'crmjunho26': '9713', 'crmmarço26': '9713', 'crmfevereiro26': '9713', 'crmjaneiro26': '9713', 'crmabril26': '9713',
                'crmmaio26': '9713', 'crmetapascheckout': '9713', 'reguanutriçao2026': '9713'}
'''
once(ANC_LD, NOVO_LD, "loader load_crm_aqui_fora + de-para UTM→número")

ANC_UT = '''                _ut = _ut.sort_values('Vendas ' + _lbl_a, ascending=False)
                _ut.index.name = 'UTM campaign'
                _ut_show = _ut.reset_index().copy()
                for c in _ut.columns:
                    _ut_show[c] = _ut_show[c].map(lambda v: format_br(v))
'''
NOVA_UT = '''                _ut = _ut.sort_values('Vendas ' + _lbl_a, ascending=False)
                _ut.index.name = 'UTM campaign'
                _ut_show = _ut.reset_index().copy()
                for c in _ut.columns:
                    _ut_show[c] = _ut_show[c].map(lambda v: format_br(v))
                # R77: número de origem provável (de-para pelo nome dos templates GT7; só as UTMs casadas) — o gasto não tem UTM
                _ut_show.insert(1, 'Número (de-para)', _ut_show['UTM campaign'].map(lambda u: _CRM_UTM_NUM.get(str(u), '—')))
'''
once(ANC_UT, NOVA_UT, "📨 CRM: coluna 'Número (de-para)' na tabela por UTM")

ANC_UTC = '''                st.caption("GA4 (`alex_crm_wpp_sms_vendas/leads`, recorte mkt_direto): vendas = purchase, leads = generate_lead, pela utm_campaign do link. "
                           "Sem custo nesta tabela — o relatório da Zenvia não carrega UTM; a ligação template ↔ UTM depende da convenção de nome.")
'''
NOVA_UTC = '''                st.caption("GA4 (`alex_crm_wpp_sms_vendas/leads`, recorte mkt_direto): vendas = purchase, leads = generate_lead, pela utm_campaign do link. "
                           "Sem custo nesta tabela — o relatório da Zenvia não carrega UTM; a ligação template ↔ UTM depende da convenção de nome. "
                           "**Número (de-para)** = número de origem dos templates GT7 cujo nome casa com a UTM (ex.: 'GT7 - AQUI etapa 1 de 3 (Junho/26)' "
                           "no 9713 ↔ `crmjunho26`); '—' = UTM sem template casado (e-mail `Comunicacao_Base_NI`, promos, testes). Por isso o filtro de "
                           "número e o de UTM são independentes: o gasto nasce no número (Zenvia) e a venda nasce no link (GA4).")
'''
once(ANC_UTC, NOVA_UTC, "📨 CRM: legenda da tabela por UTM")

if text != orig:
    bak = APP.with_name("app_bak_r77.py")
    if not bak.exists():
        shutil.copyfile(APP, bak)
    write_app(text, bom, crlf)
print("\n".join(changes))
print(f"app.py: {len(text.splitlines())} linhas")
