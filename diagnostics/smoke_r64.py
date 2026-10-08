"""Smoke R64: sub-aba 3 — 'Leads enviados ao televendas', 'Leads discados no Escallo' e o controle de duplicados 🔁 (exige s11 R64 recarregado).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r64.py
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
    t += " " + " ".join(re.sub(r'<[^>]+>', ' ', c.value) for c in at.caption if c.value)
    return re.sub(r'\s+', ' ', t)


def checa(at, presentes, ausentes):
    t = texto(at); ok = True
    for s in presentes:
        p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
    for s in ausentes:
        p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)
    i = t.find("Controle de duplicados"); print("   ", t[i:i + 220] if i >= 0 else "   (sem 'Controle de duplicados')", flush=True)
    return ok


NOVOS = ["Leads enviados ao televendas em horário comercial", "Leads que viraram Negócio na esteira", "Leads discados no Escallo", "Controle de duplicados", "números únicos"]
ANTIGOS = ["Contatos no fluxo do televendas (no expediente)", "Contatos que entraram no fluxo", "Discados no Escallo (ativo, mesmo período)",
           "Leads enviados ao televendas (no expediente)", "Leads com Negócio que entrou em LEAD"]

at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, NOVOS, ANTIGOS)
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês (set/26)"):
    sys.exit(1)
ok = checa(at, NOVOS, ANTIGOS) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
