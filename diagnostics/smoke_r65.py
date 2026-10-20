"""Smoke R65: sub-abas 📞 9 · Fechamento WhatsApp e 10 · WhatsApp mês a mês (formato do deck Saray). Último Mês (set/26 fechado):
as duas sub-abas renderizam sem exceção, com o funil de setembro e a comparação set × ago; o seletor de mês existe (key t6_w2a_mes).
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r65.py
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
    try:
        t += " " + " ".join(tb.label for tb in at.tabs)
    except Exception:
        pass
    return re.sub(r'\s+', ' ', t)


def checa(at, presentes, ausentes=()):
    t = texto(at); ok = True
    for s in presentes:
        p = s in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}", flush=True)
    for s in ausentes:
        p = s not in t; ok = ok and p; print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}", flush=True)
    return ok


at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual"):
    sys.exit(1)
# Semana Atual (out/26): grão semanal na aba, mas o fechamento é mensal → padrão = último mês fechado (setembro)
ok = checa(at, ["📊 9 · Fechamento WhatsApp", "↔️ 10 · WhatsApp mês a mês", "Resultados do WhatsApp — Fechamento Setembro",
                "FUNIL DE VENDAS: DESEMPENHO DE SETEMBRO", "Os resultados do canal WhatsApp — setembro vs agosto",
                "Pontos de atenção", "Série mensal (mês cheio"])
sel = [w for w in at.selectbox if getattr(w, 'key', '') == 't6_w2a_mes']
print(f"   {'OK ' if sel else 'FALHA'} selectbox t6_w2a_mes presente", flush=True)
ok = ok and bool(sel)
# verbete novo no glossário entra em at.markdown
ok = checa(at, ["Fechamento WhatsApp (funil do deck)"]) and ok

r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Último Mês")
if not run(at, "Último Mês (set/26)"):
    sys.exit(1)
ok = checa(at, ["Resultados do WhatsApp — Fechamento Setembro", "setembro vs agosto"]) and ok
print("FIM", "OK" if ok else "COM FALHAS", flush=True)
sys.exit(0 if ok else 1)
