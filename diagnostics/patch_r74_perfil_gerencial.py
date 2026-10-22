"""R74 (21/10/2026) — perfil de acesso "gerencial" (senha `ger_password`) + aba 🎯 Dashboard Gerencial (módulo gerencial_tab.py).

Idempotente: cada âncora é trocada só se a versão nova ainda não estiver no arquivo. Backup em app_bak_r74.py.
Uso:  .venv\\Scripts\\python.exe diagnostics\\patch_r74_perfil_gerencial.py
"""
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _patchlib import APP, read_app, write_app  # noqa: E402

text, bom, crlf = read_app()
orig = text
changes = []


def once(old, new, label, regex=False):
    global text
    if new in text:
        changes.append(f"= {label} (já aplicado)")
        return
    if regex:
        m = re.search(old, text)
        if not m:
            raise SystemExit(f"ERR âncora não encontrada: {label}")
        text = text[: m.start()] + new + text[m.end():]
    else:
        if text.count(old) != 1:
            raise SystemExit(f"ERR âncora ausente ou duplicada ({text.count(old)}x): {label}")
        text = text.replace(old, new)
    changes.append(f"+ {label}")


# 1) perfis e senhas
once('_PERFIS_SENHA = [("analista", "app_password"), ("televendas", "tv_password")]',
     '_PERFIS_SENHA = [("analista", "app_password"), ("televendas", "tv_password"), ("gerencial", "ger_password")]',
     "_PERFIS_SENHA += gerencial")
once('_PERFIL_ROTULO = {"analista": "Analista — todas as abas", "televendas": "Televendas — só a aba 📞"}',
     '_PERFIL_ROTULO = {"analista": "Analista — todas as abas", "televendas": "Televendas — só a aba 📞",\n'
     '                  "gerencial": "Gerencial — só a aba 🎯 Dashboard Gerencial"}',
     "_PERFIL_ROTULO += gerencial")
once('#   app_password → "analista"   (todas as abas)          tv_password → "televendas" (só 📞 Televendas)',
     '#   app_password → "analista"   (todas as abas)          tv_password → "televendas" (só 📞 Televendas)\n'
     '#   ger_password → "gerencial"  (só 🎯 Dashboard Gerencial; R74, 21/10/2026 — módulo gerencial_tab.py)',
     "comentário dos perfis")

# 2) barra lateral recolhida para o perfil gerencial (set_page_config roda antes do gate; o perfil já está no session_state após o login)
once('st.set_page_config(page_title="Vendas Dashboard", page_icon="📊", layout="wide")',
     'st.set_page_config(page_title="Vendas Dashboard", page_icon="📊", layout="wide",\n'
     '                   initial_sidebar_state="collapsed" if st.session_state.get("perfil") == "gerencial" else "auto")  # R74',
     "set_page_config sidebar por perfil")

# 3) aba nova em _ABAS, perfil e unpack
once('("tab12", "🔁 Retenção (Lake)")]',
     '("tab12", "🔁 Retenção (Lake)"), ("tab13", "🎯 Dashboard Gerencial")]',
     "_ABAS += tab13")
once('_ABAS_PERFIL = {"televendas": {"tab6"}}',
     '_ABAS_PERFIL = {"televendas": {"tab6"}, "gerencial": {"tab13"}}',
     "_ABAS_PERFIL += gerencial")
once('tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab10, tab11, tab12 = (_abas_obj.get(v) for v, _ in _ABAS)',
     'tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab10, tab11, tab12, tab13 = (_abas_obj.get(v) for v, _ in _ABAS)',
     "unpack += tab13")

# 4) bloco da aba (fim do arquivo)
BLOCO = '''

# =====================================================================
# TAB 13: 🎯 DASHBOARD GERENCIAL (R74, 21/10/2026)
# =====================================================================
#   Porta o blueprint "Metas Comerciais CDT v6" (Claude Design): 01 Meta do mês · 02 Dia a dia · 03 Canais · 04 Leads e funil ·
#   05 Histórico, com barra própria (Período · Canal · Ajustes · Legenda · CSV). Código em gerencial_tab.py (ao lado do app.py —
#   vai junto no commit/deploy, como cdt_theme.py). Fontes: df_raw (vendas), df_goals (alex_metas), df_fcst (Prophet), df_cal,
#   alex_leads_diario e alex_ger_dash_dia (pipeline gt7 run gerencial_dash, depois do funil_journey na recarga).
#   Perfil "gerencial" (ger_password) vê só esta aba; o analista vê todas.
@_aba(tab13)
def _aba_tab13():
    global gerencial_tab
    import os, sys
    _d = os.path.dirname(os.path.abspath(__file__))
    if _d not in sys.path:          # AppTest/smokes não põem a pasta do app no sys.path (o `streamlit run` põe)
        sys.path.insert(0, _d)
    import gerencial_tab
    gerencial_tab.render(df_raw=df_raw, df_goals=df_goals, df_fcst=df_fcst, df_cal=df_cal, cquery=cquery,
                         reference_date=reference_date, perfil=_PERFIL)
'''
if "def _aba_tab13():" in text:
    once("    global gerencial_tab\n    import gerencial_tab\n",
         "    global gerencial_tab\n    import os, sys\n    _d = os.path.dirname(os.path.abspath(__file__))\n"
         "    if _d not in sys.path:          # AppTest/smokes não põem a pasta do app no sys.path (o `streamlit run` põe)\n"
         "        sys.path.insert(0, _d)\n    import gerencial_tab\n",
         "bloco tab13: sys.path guard")
else:
    text = text.rstrip("\n") + BLOCO
    changes.append("+ bloco tab13 no fim do arquivo")

if text != orig:
    bak = APP.with_name("app_bak_r74.py")
    if not bak.exists():
        shutil.copyfile(APP, bak)
    write_app(text, bom, crlf)
print("\n".join(changes))
print(f"app.py: {len(text.splitlines())} linhas")
