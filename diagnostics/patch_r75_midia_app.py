"""R75 (23/10/2026) — 📱 App · sub-aba 📣 8 · Mídia do app (Singular) [módulo midia_app_tab.py] + 3 verbetes do glossário
(Instalação (Singular), Install orgânico × pago, CPI (Singular)).

Idempotente: cada âncora é trocada só se a versão nova ainda não estiver no arquivo. Backup em app_bak_r75.py.
Uso:  .venv\\Scripts\\python.exe diagnostics\\patch_r75_midia_app.py
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


# 1) glossário — 3 verbetes depois de 'Instalação (CleverTap · App Installed)'
ANC_GL = ("        o=\"CleverTap (API counts/trends)\", a=\"📱\", s=[\"App Installed\", \"Instalações CleverTap\"]),\n")
NOVOS_GL = ANC_GL + (
    "    'Instalação (Singular · tracker_installs)': dict(sec=\"App do Filiado\",\n"
    "        d=\"1ª abertura do app num aparelho novo vista pelo SDK da Singular, com atribuição de mídia: cada instalação recebe a rede e a campanha do último toque válido na janela de atribuição, ou vai para 'Organic'. É a régua oficial de Installs/Downloads nos relatórios (RMA, metas) desde 20/10/2026. Não é download da loja nem 1º login.\",\n"
    "        p=\"É a única régua que separa o que a mídia trouxe do que veio sozinho — e a que a Mesa já usava (os 529 k de agosto).\",\n"
    "        o=\"Singular (Reporting API → alex_singular_installs, GAS 09:30, janela D-8 → D-1)\", a=\"📱 🧲\", s=[\"Instalações (Singular)\", \"Instalações (Singular · régua oficial)\", \"Singular · installs (RMA)\", \"tracker_installs\", \"installs\"]),\n"
    "    'Install orgânico × pago (Singular)': dict(sec=\"App do Filiado\",\n"
    "        d=\"Pago = instalação atribuída a uma campanha de mídia (Google, Meta, TikTok, Jampp ou outra fonte rastreada); orgânico = sem toque de mídia na janela. No iOS o pago é subestimado: sem IDFA (ATT) o SDK não casa o clique com a instalação e ela cai em orgânico — compare Android e iOS separadamente e leia '% pago' só no Android.\",\n"
    "        p=\"Diz quanto do volume depende da mídia; o '% pago' do RMA mensal é pago ÷ total nesta régua.\",\n"
    "        o=\"Singular (vw_singular_downloads_dia)\", a=\"📱\", s=[\"Pago (atribuído a mídia)\", \"Orgânico (sem mídia)\", \"Instalações pagas (atribuídas a mídia)\", \"% pago\", \"is_organic\", \"ATT\"]),\n"
    "    'CPI (Singular)': dict(sec=\"Investimento e mídia\",\n"
    "        d=\"Custo por instalação: custo da campanha de Download (o que a rede reporta à Singular; Jampp pelo spend_brl do jampp.gs) ÷ instalações atribuídas pelo SDK (tracker_installs). Só campanhas com 'download' no nome — o custo da Singular cobre todas as campanhas da rede, inclusive as do site. 'CPI (rede)' usa as instalações que a própria rede declara (adn_installs); a Meta costuma declarar ~1,4× o SDK.\",\n"
    "        p=\"Compara a eficiência entre redes na mesma régua. Não é o investimento oficial (RESUMO_INVESTIMENTO_DIARIO): restatement e janela D-8 mudam o custo por alguns dias; a conciliação está na sub-aba 📣 8 da 📱.\",\n"
    "        o=\"Singular × Jampp (vw_singular_cpi_mes, vw_singular_campanha_dia)\", a=\"📱\", s=[\"CPI\", \"Custo por instalação\", \"CPI por rede\", \"CPI das campanhas de Download — Android\", \"cpi_rede\", \"installs_rede\", \"adn_installs\"]),\n"
)
once(ANC_GL, NOVOS_GL, "glossário: 3 verbetes Singular")

# 2) sub-aba nova na lista de tabs da 📱
once('"🔗 6 · Uso × conversão × LTV", "📡 7 · CleverTap · app e site"])',
     '"🔗 6 · Uso × conversão × LTV", "📡 7 · CleverTap · app e site", "📣 8 · Mídia do app (Singular)"])',
     "_ap_tabs += 📣 8")

# 3) bloco da sub-aba — logo antes do cabeçalho da TAB 8 (fim da _aba_tab7)
ANC_T8 = ("\n# =====================================================================\n"
          "# TAB 8: CRM — WhatsApp/SMS da Instância de Aquisição: gasto por disparo × vendas GA4 × CPA\n")
BLOCO = '''
    # =================================================================
    # 8 · MÍDIA DO APP (Singular) — R75 (23/10/2026): módulo midia_app_tab.py (ao lado do app.py, como gerencial_tab.py)
    #   Para a analista de mídia do app: campanhas de Download (CPI, CTR, rede × SDK), ritmo da meta Download APP, orgânico × pago
    #   por semana, instalações vindas de campanhas do site, reengajamentos, conciliação custo Singular × RESUMO, nomenclatura.
    #   Fontes: vw_singular_campanha_dia (nova, sql/singular_views.sql) · vw_singular_downloads_dia · alex_metas · RESUMO_INVESTIMENTO_DIARIO.
    # =================================================================
    with _ap_tabs[7]:
        import os as _os8, sys as _sys8
        _d8 = _os8.path.dirname(_os8.path.abspath(__file__))
        if _d8 not in _sys8.path:          # AppTest/smokes não põem a pasta do app no sys.path (o `streamlit run` põe)
            _sys8.path.insert(0, _d8)
        import midia_app_tab
        midia_app_tab.render(dict(
            cquery=cquery, c_s=c_s, c_e=ref_datetime, p_s=p_s, p_e=p_partial, reference_date=reference_date, m_fim=_tv_m_fim,
            meses_grafico=_tv_meses_grafico, kpi=_tv_kpi, n=_tv_n, delta=_tv_delta, pct=_tv_pct, note=_tv_note, titulo=_tv_titulo,
            fonte=_tv_fonte, chart_mensal=_tv_chart_mensal, linhas_mensal=_tv_linhas_mensal, st_df=_st_df, format_br=format_br,
            cores=_TV_CORES_A, tema=_CDT_THEME))
'''
if "with _ap_tabs[7]:" in text:
    changes.append("= bloco 📣 8 (já aplicado)")
else:
    if text.count(ANC_T8) != 1:
        raise SystemExit(f"ERR âncora do cabeçalho da TAB 8 ({text.count(ANC_T8)}x)")
    text = text.replace(ANC_T8, BLOCO + ANC_T8)
    changes.append("+ bloco 📣 8 no fim da _aba_tab7")

if text != orig:
    bak = APP.with_name("app_bak_r75.py")
    if not bak.exists():
        shutil.copyfile(APP, bak)
    write_app(text, bom, crlf)
print("\n".join(changes))
print(f"app.py: {len(text.splitlines())} linhas")
