"""Smoke R58: sub-aba 💬 4 · Talkerchat após os pedidos do time (01/10): funil sem SAC, qualificado não cliente,
Vendas (CTN) por IDPV, expander de registro, Fluxo Lia separado, sales-ready fora, ranking por vendas (CTN).
Rodadas: Semana Atual (grão semanal) e Mês Atual (grão mensal). Dados reais (AppTest, perfil completo).
Exceções conhecidas do texto: rótulos antigos continuam no GLOSSARIO (sinônimos) — por isso só se testa a ausência
de textos que não estão no glossário ('Compra reportada (usuários)', 'Qualificação → sales-ready → distribuição').
Uso: $env:PYTHONIOENCODING='utf-8'; .venv\\Scripts\\python.exe diagnostics\\smoke_r58.py
"""
import os, sys, time, pathlib, re
os.chdir(pathlib.Path(__file__).resolve().parents[1])
from streamlit.testing.v1 import AppTest


def run(at, label):
    t0 = time.time(); at.run()
    errs = [e.value for e in at.error]
    print(f"[{label}] run em {time.time() - t0:.0f}s | exceções: {len(at.exception)} | st.error: {len(errs)}", flush=True)
    for e in at.exception:
        print("EXCEPTION:", str(e.value)[:300]); print(getattr(e, 'stack_trace', '')[:1500])
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
    for s in ("Funil Talkerchat — time humano (WhatsApp, sem SAC)", "Usuários únicos sem SAC", "Qualificados (CPF validado, não cliente)",
              "Vendas (CTN) — IDPVs humanos de Televendas", "└ pelo IDPV WhatsApp", "Régua nova (01/10", "Fluxo Lia — vendas da Lia no CTN",
              "Humano pelo IDPV WhatsApp (CTN)", "Ranking de atendentes — Vendas (CTN) por IDPV", "Vendas (CTN) — humano · Lia",
              "Funil por mês — usuários sem SAC × qualificados × humano"):
        p = s in t
        ok = ok and p
        print(f"   {'OK ' if p else 'FALHA'} presente: {s!r}")
    for s in ("Compra reportada (usuários)", "Qualificação → sales-ready → distribuição", "Ranking de atendentes — compras reportadas",
              "Compras reportadas → confirmadas", "Qualificados (com CPF)"):
        p = s not in t
        ok = ok and p
        print(f"   {'OK ' if p else 'FALHA'} ausente: {s!r}")
    for lbl in ("Usuários únicos sem SAC", "Qualificados (CPF validado, não cliente)", "Vendas (CTN) — IDPVs humanos de Televendas"):
        i = t.find(lbl)
        seg = t[i + len(lbl): i + len(lbl) + 60] if i >= 0 else ""
        vazio = "—" in seg[:12]
        print(f"   etapa {lbl!r}: {seg.strip()[:50]!r} {'(VAZIO)' if vazio else ''}")
        ok = ok and i >= 0 and not vazio
    exps = [e for e in at.expander if "Registro da operação" in (e.label or "")]
    print(f"   expander registro da operação: {len(exps)}")
    ok = ok and bool(exps)
    i = t.find("Sem IDPV casado"); print("   ", t[i:i + 160] if i >= 0 else "   (todos os atendentes com IDPV casado)")
    i = t.find("Período:"); print("   ", t[i:i + 110])
    try:
        n_pl = len(at.get("plotly_chart"))
    except Exception:
        n_pl = -1
    print(f"   plotly: {n_pl}")
    return ok


at = AppTest.from_file(str(pathlib.Path.cwd() / "app.py"), default_timeout=1800)
at.session_state["password_correct"] = True
if not run(at, "Semana Atual (grão semanal)"):
    sys.exit(1)
ok = checa(at, "semana")

r = [w for w in at.sidebar.radio if w.label.startswith("Período de Análise")][0]
r.set_value("Mês Atual")
if not run(at, "Mês Atual (grão mensal)"):
    sys.exit(1)
ok = checa(at, "mês") and ok
print("FIM", "OK" if ok else "COM FALHAS")
sys.exit(0 if ok else 1)
