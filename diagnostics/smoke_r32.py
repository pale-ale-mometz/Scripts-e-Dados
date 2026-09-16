"""Smoke R32: sub-aba Talkerchat (API) da aba Televendas — KPIs bot×humano, tempos, ranking, heatmap, motivos, estoque;
grão semanal (Semana Atual) e mensal (Mês Atual); radio do heatmap. Dados reais (AppTest), 3 rodadas.
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r32.py
"""
import os, sys, time, pathlib, re
os.chdir(pathlib.Path(__file__).resolve().parents[1])
from streamlit.testing.v1 import AppTest


def run(at, label):
    t0 = time.time(); at.run()
    errs = [e.value for e in at.error]
    print(f"[{label}] run em {time.time() - t0:.0f}s | exceções: {len(at.exception)} | st.error: {len(errs)}")
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, 'stack_trace', '')[:1200])
    for e in errs:
        print("ST.ERROR:", str(e)[:200])
    return not at.exception


def texto(at):
    t = " ".join(re.sub(r'<[^>]+>', ' ', m.value) for m in at.markdown if m.value)
    t += " " + " ".join(c.value for c in at.caption if c.value)
    return re.sub(r'\s+', ' ', t)


def checa(at, label):
    t = texto(at)
    ok = True
    for s in ("Espera até um humano assumir (mediana)", "Duração do atendimento humano (mediana)",
              "Estoque de tickets abertos (hoje)", "Só bot (Lia) × humano — tickets", "Ranking de atendentes",
              "Mapa de calor — dia da semana × hora", "Motivos de fechamento (close_reason_id", "Estoque de tickets abertos — retrato",
              "Tempos no período", "Bot × humano de verdade", "API pública do Talkerchat"):
        p = s in t
        ok = ok and p
        print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}")
    for s in ("v_alex_talkerchat)", "export do Talkerchat (alex_talkerchat via"):
        p = s not in t
        ok = ok and p
        print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}")
    aviso = "ainda não tem as seções da API" in " ".join(w.value for w in at.warning if w.value)
    print(f"   aviso 'sem seções da API': {aviso} (esperado False)"); ok = ok and not aviso
    # KPIs da sub-aba: valor do 1º KPI (usuários) e estoque não podem ser '—'
    for lbl in ("Usuários únicos (tel-8) no período", "Estoque de tickets abertos (hoje)", "Espera até um humano assumir (mediana)"):
        i = t.find(lbl)
        seg = t[i + len(lbl): i + len(lbl) + 40] if i >= 0 else ""
        vazio = seg.strip().startswith("—")
        print(f"   KPI {lbl!r}: {seg.strip()[:36]!r} {'(VAZIO)' if vazio else ''}")
        ok = ok and i >= 0 and not vazio
    i = t.find("Período:"); print("   ", t[i:i + 110])
    n_df = len(at.dataframe)
    try:
        n_pl = len(at.get("plotly_chart"))
    except Exception:
        n_pl = -1
    print(f"   dataframes: {n_df} · plotly: {n_pl}")
    return ok


at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual (grão semanal)"):
    sys.exit(1)
ok = checa(at, "semana")
t = texto(at)
print("   grão semanal:", "grão semanal" in t)

r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Mês Atual")
if not run(at, "Mês Atual (grão mensal)"):
    sys.exit(1)
ok = checa(at, "mês") and ok
print("   grão mensal:", "grão mensal" in texto(at))

hm = [w for w in at.radio if w.key == 't6_s7_hm']
print("   radio heatmap presente:", bool(hm))
if hm:
    hm[0].set_value("% com humano")
    if not run(at, "heatmap % com humano"):
        sys.exit(1)
    ok = ("Mapa de calor — dia da semana × hora" in texto(at)) and ok
print("FIM", "OK" if ok else "COM FALHAS")
sys.exit(0 if ok else 1)
