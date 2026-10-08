"""Smoke R61: textos de 'piso' do qualificado removidos na sub-aba 💬 4 · Talkerchat (régua sem SAC e por fila). Dados reais (AppTest).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r61.py
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
    i = t.find("Qualificado = CPF lido"); print("   ", t[i:i + 160] if i >= 0 else "   (sem 'Qualificado = CPF lido')", flush=True)
    return ok


ANTIGOS = ["Em correção desde 05/10", "piso (ver nota", "piso (nota 🧭)", "backfill em andamento", "É um piso"]

at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
ok = checa(at, [], ANTIGOS)
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês (set/26 — régua sem SAC)"):
    sys.exit(1)
ok = checa(at, ["backfill concluído 07/10", "CPF lido (objeto de contato) e não cadastrado"], ANTIGOS) and ok
r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Mês Atual")
if not run(at, "Mês Atual (out/26)"):
    sys.exit(1)
ok = checa(at, [], ANTIGOS) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
