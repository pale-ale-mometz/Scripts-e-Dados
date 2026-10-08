"""Smoke R60: sub-aba 💬 4 · Talkerchat com funil por fila (Triagem × Televendas). Mês Atual (out/26) deve mostrar o funil por fila;
Último Mês (set/26) deve manter o funil 'sem SAC' do R58. Dados reais (AppTest).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r60.py
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


def checa(at, presentes, ausentes):
    t = texto(at); ok = True
    for s in presentes:
        p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
    for s in ausentes:
        p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)
    i = t.find("Chegaram à fila Televendas"); print("   ", t[i:i + 140] if i >= 0 else "   (sem 'Chegaram à fila')", flush=True)
    i = t.find("Período:"); print("   ", t[i:i + 100], flush=True)
    return ok


FILA = ["Funil Talkerchat — time humano (fila Televendas)", "Chegaram à fila Televendas", "Funil por fila (desde 30/09)",
        "Triagem × Lia vendas × humano — tickets (por fila)", "Funil por mês — por fila (desde 30/09)"]
SEMSAC = ["Funil Talkerchat — time humano (WhatsApp, sem SAC)", "Régua nova (01/10"]

at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, [], [])
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Mês Atual")
if not run(at, "Mês Atual (out/26)"):
    sys.exit(1)
# R60b: o funil por fila só entra quando o período começa em 30/09 ou depois. Com poucos dias de outubro o app usa o grão
# semanal e a semana de 28/09 (mista) cai na régua 'sem SAC' — a partir da semana de 05/10 passa a ser o funil por fila.
_t = texto(at)
if "28/09" in _t and "grão semanal" in _t:
    print("   (período começa em 28/09 — semana mista: esperado o funil 'sem SAC')")
    ok = checa(at, SEMSAC, ["Funil Talkerchat — time humano (fila Televendas)"]) and ok
else:
    ok = checa(at, FILA, ["Funil Talkerchat — time humano (WhatsApp, sem SAC)"]) and ok
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês (set/26)"):
    sys.exit(1)
ok = checa(at, SEMSAC, ["Funil Talkerchat — time humano (fila Televendas)"]) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
