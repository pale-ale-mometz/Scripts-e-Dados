"""R76 (26/10/2026) — (a) remove a aba 🎯 Dashboard Gerencial do app (fica só no Lovable) e o perfil "gerencial"
(ger_password) que só existia para ela; (b) import de midia_app_tab.py (sub-aba 📣 8 da 📱) passa a ser tolerante:
se o módulo não estiver no deploy, a sub-aba mostra um aviso em vez de derrubar o script (26/10: ModuleNotFoundError
no Streamlit Cloud deixou CRM → Dashboard Gerencial em branco porque midia_app_tab.py não tinha sido commitado).

gerencial_tab.py continua no disco e no repo (o pipeline gerencial_dash e o Lovable seguem usando alex_ger_dash_dia);
só deixa de ser importado pelo app.py.

Idempotente: cada âncora é trocada só se a versão nova ainda não estiver no arquivo. Backup em app_bak_r76.py.
Uso:  .venv\\Scripts\\python.exe diagnostics\\patch_r76_remove_gerencial_import_seguro.py
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


# 1) set_page_config — sem o sidebar recolhido do perfil gerencial
once('                   initial_sidebar_state="collapsed" if st.session_state.get("perfil") == "gerencial" else "auto")  # R74\n',
     '                   initial_sidebar_state="auto")\n',
     "set_page_config sem condicional do perfil gerencial")

# 2) perfis de acesso — tira ger_password / "gerencial"
once('#   ger_password → "gerencial"  (só 🎯 Dashboard Gerencial; R74, 21/10/2026 — módulo gerencial_tab.py)\n'
     '# Sessões que só têm password_correct=True (smokes antigos) caem em "analista".\n'
     '_PERFIS_SENHA = [("analista", "app_password"), ("televendas", "tv_password"), ("gerencial", "ger_password")]\n'
     '_PERFIL_ROTULO = {"analista": "Analista — todas as abas", "televendas": "Televendas — só a aba 📞",\n'
     '                  "gerencial": "Gerencial — só a aba 🎯 Dashboard Gerencial"}\n',
     '#   R76 (26/10/2026): o perfil "gerencial" (ger_password, aba 🎯 Dashboard Gerencial) saiu — o Dashboard Gerencial vive só no Lovable.\n'
     '# Sessões que só têm password_correct=True (smokes antigos) caem em "analista".\n'
     '_PERFIS_SENHA = [("analista", "app_password"), ("televendas", "tv_password")]\n'
     '_PERFIL_ROTULO = {"analista": "Analista — todas as abas", "televendas": "Televendas — só a aba 📞"}\n',
     "perfis sem gerencial")

# 3) lista de abas — sem tab13
once('         ("tab12", "🔁 Retenção (Lake)"), ("tab13", "🎯 Dashboard Gerencial")]\n'
     '_ABAS_PERFIL = {"televendas": {"tab6"}, "gerencial": {"tab13"}}\n',
     '         ("tab12", "🔁 Retenção (Lake)")]   # R76: tab13 (🎯 Dashboard Gerencial) removida — só no Lovable\n'
     '_ABAS_PERFIL = {"televendas": {"tab6"}}\n',
     "_ABAS / _ABAS_PERFIL sem tab13")
once('tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab10, tab11, tab12, tab13 = (_abas_obj.get(v) for v, _ in _ABAS)\n',
     'tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab10, tab11, tab12 = (_abas_obj.get(v) for v, _ in _ABAS)\n',
     "desempacotamento das abas sem tab13")

# 4) bloco da TAB 13 — remove do cabeçalho até o fim da _aba_tab13 (é o último bloco do arquivo)
INI_T13 = ("\n# =====================================================================\n"
           "# TAB 13: 🎯 DASHBOARD GERENCIAL (R74, 21/10/2026)\n")
FIM_T13 = ("    gerencial_tab.render(df_raw=df_raw, df_goals=df_goals, df_fcst=df_fcst, df_cal=df_cal, cquery=cquery,\n"
           "                         reference_date=reference_date, perfil=_PERFIL)\n")
if INI_T13 in text:
    i0 = text.index(INI_T13)
    if text.count(FIM_T13) != 1:
        raise SystemExit(f"ERR fim do bloco da TAB 13 ({text.count(FIM_T13)}x)")
    i1 = text.index(FIM_T13) + len(FIM_T13)
    if i1 < i0:
        raise SystemExit("ERR bloco da TAB 13 fora de ordem")
    text = text[:i0] + "\n# R76 (26/10/2026): a TAB 13 (🎯 Dashboard Gerencial, R74) foi removida do app — vive só no Lovable (gerencial_tab.py fica no repo).\n" + text[i1:]
    changes.append("- bloco da TAB 13 removido")
else:
    changes.append("= bloco da TAB 13 (já removido)")

# 5) import tolerante do midia_app_tab
once('        import midia_app_tab\n'
     '        midia_app_tab.render(dict(\n'
     '            cquery=cquery, c_s=c_s, c_e=ref_datetime, p_s=p_s, p_e=p_partial, reference_date=reference_date, m_fim=_tv_m_fim,\n'
     '            meses_grafico=_tv_meses_grafico, kpi=_tv_kpi, n=_tv_n, delta=_tv_delta, pct=_tv_pct, note=_tv_note, titulo=_tv_titulo,\n'
     '            fonte=_tv_fonte, chart_mensal=_tv_chart_mensal, linhas_mensal=_tv_linhas_mensal, st_df=_st_df, format_br=format_br,\n'
     '            cores=_TV_CORES_A, tema=_CDT_THEME))\n',
     '        try:                               # R76: módulo ausente no deploy não pode derrubar as abas seguintes (CRM → Lake)\n'
     '            import midia_app_tab\n'
     '        except ImportError as _e8:\n'
     '            midia_app_tab = None\n'
     '            st.warning(f"Sub-aba indisponível: o módulo `midia_app_tab.py` não está neste deploy ({_e8}). "\n'
     '                       "Confira se o arquivo foi commitado junto com o app.py.", icon="⚠️")\n'
     '        if midia_app_tab is not None:\n'
     '            midia_app_tab.render(dict(\n'
     '                cquery=cquery, c_s=c_s, c_e=ref_datetime, p_s=p_s, p_e=p_partial, reference_date=reference_date, m_fim=_tv_m_fim,\n'
     '                meses_grafico=_tv_meses_grafico, kpi=_tv_kpi, n=_tv_n, delta=_tv_delta, pct=_tv_pct, note=_tv_note, titulo=_tv_titulo,\n'
     '                fonte=_tv_fonte, chart_mensal=_tv_chart_mensal, linhas_mensal=_tv_linhas_mensal, st_df=_st_df, format_br=format_br,\n'
     '                cores=_TV_CORES_A, tema=_CDT_THEME))\n',
     "import tolerante do midia_app_tab")

# guarda: nenhuma linha de CÓDIGO (fora de comentário) pode seguir citando tab13 / perfil gerencial / gerencial_tab
for _s in ("tab13", '"gerencial"', "gerencial_tab"):
    _n = sum(1 for _l in text.splitlines() if _s in _l and not _l.lstrip().startswith("#") and "R76" not in _l)
    if _n:
        raise SystemExit(f"ERR ainda há {_n} linha(s) de código com {_s!r}")

if text != orig:
    bak = APP.with_name("app_bak_r76.py")
    if not bak.exists():
        shutil.copyfile(APP, bak)
    write_app(text, bom, crlf)
print("\n".join(changes))
print(f"app.py: {len(text.splitlines())} linhas")
