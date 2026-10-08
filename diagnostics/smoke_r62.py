"""Smoke R62: fila SAC (desde 04/10) na sub-aba 💬 4 · Talkerchat. Depois da recarga do S7 (televendas_dash R62), Semana Atual e Mês
Atual (out/26) devem mostrar o funil por fila com 'filas Triagem/SAC'; Último Mês (set/26) mantém a régua sem SAC com o motivo 189 na nota.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r62.py
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
    i = t.find("ficaram na triagem"); print("   ", t[i:i + 160] if i >= 0 else "   (sem 'ficaram na triagem')", flush=True)
    return ok


FILA = ["Funil Talkerchat — time humano (fila Televendas)", "filas Triagem/SAC", "já clientes / SAC"]
ANTIGOS = ["ficaram na fila Triagem ·", "redirecionados ao SAC", "close_reason 4 (Transferido para SAC)"]

at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, FILA, ANTIGOS)
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Mês Atual")
if not run(at, "Mês Atual (out/26)"):
    sys.exit(1)
# R60b: com menos de 14 dias de outubro o app usa o grão semanal e a semana de 28/09 (mista) entra no período → régua 'sem SAC'
# até 14/10; a partir daí o funil por fila entra sozinho.
_t = texto(at)
if "28/09" in _t and "grão semanal" in _t:
    print("   (período começa em 28/09 — semana mista: esperado o funil 'sem SAC')")
    ok = checa(at, ["Funil Talkerchat — time humano (WhatsApp, sem SAC)", "'Informou que já é cliente' (desde 04/10, fila SAC)"],
               ["Funil Talkerchat — time humano (fila Televendas)"] + ANTIGOS) and ok
else:
    ok = checa(at, FILA, ANTIGOS) and ok
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês (set/26 — régua sem SAC)"):
    sys.exit(1)
ok = checa(at, ["Funil Talkerchat — time humano (WhatsApp, sem SAC)", "'Informou que já é cliente' (desde 04/10, fila SAC)"],
           ["Funil Talkerchat — time humano (fila Televendas)"] + ANTIGOS) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
