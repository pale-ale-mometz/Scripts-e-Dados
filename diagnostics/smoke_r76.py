"""Smoke R76: app sobe sem exceção, sem a aba 🎯 Dashboard Gerencial e com a sub-aba 📣 8 · Mídia do app (Singular) viva;
perfil "gerencial" não existe mais (ger_password não abre nada).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r76.py
"""
import os, sys, time, pathlib, re
os.chdir(pathlib.Path(__file__).resolve().parents[1])
from streamlit.testing.v1 import AppTest


def run(at, label):
    t0 = time.time(); at.run()
    print(f"[{label}] run em {time.time() - t0:.0f}s | exceções: {len(at.exception)} | st.error: {len(at.error)}", flush=True)
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, 'stack_trace', '')[:1500])
    return not at.exception


def texto(at):
    t = " ".join(re.sub(r'<[^>]+>', ' ', m.value) for m in at.markdown if m.value)
    t += " " + " ".join(c.value for c in at.caption if c.value)
    return re.sub(r'\s+', ' ', t)


at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "analista · Semana Atual"):
    sys.exit(1)
ok = True
tabs = [t.label for t in at.tabs]
print(f"   abas de 1º nível ({len([x for x in tabs if x in ('📈 Desempenho de Vendas', '🔁 Retenção (Lake)', '🎯 Dashboard Gerencial')])} conhecidas): "
      + " | ".join(x for x in tabs if x.startswith(('📈', '🗺️', '💰', '📣 Campanhas', '🌐', '📞', '📱', '📨', '🧲', '🧭', '🔁', '🎯'))))
for s, deve in [("🎯 Dashboard Gerencial", False), ("🔁 Retenção (Lake)", True), ("📨 CRM", True), ("📣 8 · Mídia do app (Singular)", True)]:
    p = s in tabs; ok = ok and (p == deve)
    print(f"   {'OK ' if p == deve else 'FALHA'} aba {'presente' if deve else 'ausente'}: {s!r}", flush=True)
t = texto(at)
for s in ["Mídia do app — campanhas, CPI, ritmo da meta e efeito cruzado", "Perfil:"]:
    p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
for s in ["Sub-aba indisponível: o módulo `midia_app_tab.py`", "Meta do mês"]:
    p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)

# perfil gerencial não existe mais: sessão com perfil=gerencial cai em "nenhuma aba" (sem exceção) — e a senha não abre nada
at2 = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=600)
at2.session_state["password_correct"] = True
at2.session_state["perfil"] = "gerencial"
if not run(at2, "perfil gerencial (órfão)"):
    sys.exit(1)
n_tabs2 = len([t for t in at2.tabs if t.label.startswith(('📈', '🎯', '📞'))])
print(f"   {'OK ' if n_tabs2 == 0 else 'FALHA'} perfil gerencial sem abas: {n_tabs2}")
ok = ok and n_tabs2 == 0
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
