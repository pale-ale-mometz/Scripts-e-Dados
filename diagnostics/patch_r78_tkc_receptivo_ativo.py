"""R78 (16/11/2026) — aba 📞 Televendas: funil do Talkerchat pela regra receptivo × ativo.

Decisão do Álex (16/11, números validados): ticket e lead do funil do Talkerchat = conversas que o cliente iniciou (receptivas) + envios
nossos que o cliente respondeu. O disparo em massa abre um ticket por destinatário mesmo sem resposta (out/26: 74.434 tickets de campanha,
6.034 respondidos); esses tickets saem do funil.

Dados (claude-toolkit, televendas_dash R73/R73b): colunas `origem` / `campanha` / `respondeu` em alex_talkerchat_api; seções novas no
agregado — s7f_talkerchat, s7f_tempos, s7f_hora, s7f_motivo, s7f_estoque (só os tickets do funil) e s7_campanha (por disparo). As seções
s7_* antigas continuam contando tudo.

Mudanças no app:
  - 7 · Talkerchat: S passa a ser s7f_talkerchat quando o agregado já tem a seção (senão segue s7_talkerchat, com aviso); tempos, mapa de
    hora, motivos e estoque leem as versões s7f_*. Atendentes (s7_atendente) e vendas CTN (nv_*, s7_nv_dia, s7_hora_nv) não mudam.
  - Nota 📌 "O que conta neste funil" no topo da sub-aba, com o total de tickets, receptivos, envios e os envios sem resposta que ficaram fora.
  - Expander 📣 "Envios nossos (tickets ativos)": KPIs e tabela por disparo (enviados, responderam, % resposta, atendente, CPF, abertos, compras).
  - 9 · Fechamento WhatsApp e 10 · WhatsApp mês a mês leem a mesma seção s7f_talkerchat (mesma regra), com a regra citada na fonte.
  - Glossário: verbete "Ticket receptivo × ativo (Talkerchat)".

Idempotente. Backup em app_bak_r78.py.  Uso:  .venv\\Scripts\\python.exe diagnostics\\patch_r78_tkc_receptivo_ativo.py
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
    n = text.count(old)
    assert n == 1, f"{label}: esperado 1 ocorrência, achei {n}"
    text = text.replace(old, new)
    changes.append(f"+ {label}")


# 1) seção base da sub-aba
once('''    with _tv_tabs[3]:
        S = 's7_talkerchat'
''', '''    with _tv_tabs[3]:
        # R78 (16/11/2026): funil pela regra receptivo × ativo. S0 = tudo (inclui envios sem resposta), usado só na nota 📌 e no bloco 📣;
        # S e as seções de tempos / hora / motivo / estoque leem as versões filtradas (s7f_*) quando o agregado já as tem.
        S0 = 's7_talkerchat'
        _tkf_ok = (not _tvd.empty) and bool((_tvd['secao'] == 's7f_talkerchat').any())
        S = 's7f_talkerchat' if _tkf_ok else S0

        def _s7x(secao):
            return secao.replace('s7_', 's7f_', 1) if _tkf_ok else secao
''', "7 · Talkerchat: S = s7f_talkerchat")

# 2) seções auxiliares
once("d = _tvd[(_tvd['secao'] == 's7_tempos') & (_tvd['mes'].isin(list(meses)))]",
     "d = _tvd[(_tvd['secao'] == _s7x('s7_tempos')) & (_tvd['mes'].isin(list(meses)))]", "tempos (KPIs)")
once("        _est = _tvd[_tvd['secao'] == 's7_estoque']\n",
     "        _est = _tvd[_tvd['secao'] == _s7x('s7_estoque')]\n", "estoque")
once("_tv_long('s7_tempos', [", "_tv_long(_s7x('s7_tempos'), [", "tempos (série)")
once("_tv_val('s7_tempos', f'{_nm}_n')", "_tv_val(_s7x('s7_tempos'), f'{_nm}_n')", "tempos (tabela)")
once("_hr = _tv_pivot7('s7_hora')", "_hr = _tv_pivot7(_s7x('s7_hora'))", "mapa de hora")
once("_mot = _tv_pivot7('s7_motivo')", "_mot = _tv_pivot7(_s7x('s7_motivo'))", "motivos")

# 3) nota da regra, antes dos KPIs
once('''        # ---- KPIs linha 1: volume e conversão ----
        k1, k2, k3, k4 = st.columns(4)
''', '''        # ---- R78: o que conta neste funil (receptivo × ativo) ----
        _tk_all = _tv_val(S0, 'tickets'); _tl_all = _tv_val(S0, 'leads')
        _tk_rec = _tv_val(S0, 'tickets_receptivos'); _tk_atv = _tv_val(S0, 'tickets_ativos'); _tk_atv_r = _tv_val(S0, 'tickets_ativos_resp')
        _tk_fora = (_tk_atv - (_tk_atv_r or 0)) if _tk_atv is not None else None
        if _tkf_ok and _tk_all:
            _tv_note(
                f"<b>O que conta neste funil.</b> Entram as conversas que o <b>cliente iniciou</b> (tickets receptivos) e os <b>envios nossos "
                f"que o cliente respondeu</b>. Quando disparamos uma mensagem em massa, o Talkerchat abre um ticket para cada destinatário, "
                f"mesmo que a pessoa nunca responda; esses tickets sem resposta não são atendimento e ficam fora de todos os números desta "
                f"sub-aba. No período: {_tv_n(_tk_all)} tickets ao todo, sendo {_tv_n(_tk_rec)} receptivos e {_tv_n(_tk_atv)} envios nossos "
                f"({_tv_n(_tk_atv_r)} com resposta). <b>{_tv_n(_tk_fora)} envios sem resposta ficaram fora</b> ({_tv_pct(_tk_fora, _tk_all)} "
                f"dos tickets). Usuários únicos: {_tv_n(_tl_all)} contando tudo, {_tv_n(tl)} no funil. Os envios, disparo a disparo, estão "
                f"no bloco 📣 mais abaixo.",
                bg="#eff6ff", icon="📌")
        elif not _tkf_ok:
            st.caption("ℹ️ O agregado ainda não tem o funil pela regra receptivo × ativo (seções s7f_*): os números abaixo contam também os "
                       "envios em massa sem resposta. Rode `gt7 run televendas_dash --arg only=s7 --arg nv=skip` e recarregue os dados.")

        # ---- KPIs linha 1: volume e conversão ----
        k1, k2, k3, k4 = st.columns(4)
''', "nota 📌 da regra")

# 4) bloco de envios por disparo, antes do registro da operação
once('''        # ---- R58: compra reportada (tabulação do atendente/bot) sai do funil e fica como registro da operação ----
''', '''        # ---- R78: envios nossos (tickets ativos) — enviados × responderam por disparo ----
        if _tkf_ok:
            _cp = _tv_pivot7('s7_campanha')
            _tk_camp = _tv_val(S0, 'tickets_ativos_campanha')
            _cp_resp = float(_cp['responderam'].sum()) if (not _cp.empty and 'responderam' in _cp.columns) else None
            _tk_outros = (_tk_atv - (_tk_camp or 0)) if _tk_atv is not None else None
            with st.expander(f"📣 Envios nossos (tickets ativos) — {_tv_n(_tk_atv)} no período, {_tv_n(_tk_atv_r)} com resposta"):
                st.caption("Ticket ativo = a primeira mensagem da conversa foi nossa: disparo em massa (campanha), fluxo automático ou "
                           "atendente. Só os que o cliente respondeu entram no funil acima; os demais ficam registrados aqui.")
                v1, v2, v3, v4 = st.columns(4)
                _tv_kpi(v1, "📣", "Tickets de disparo em massa", _tv_n(_tk_camp),
                        f"{0 if _cp.empty else len(_cp)} disparos no período · um ticket por destinatário", color="#1d4ed8")
                _tv_kpi(v2, "↩️", "Responderam ao disparo", f"{_tv_n(_cp_resp)} · {_tv_pct(_cp_resp, _tk_camp)}",
                        "o cliente mandou ao menos uma mensagem no ticket aberto pelo disparo", color="#1d4ed8")
                _tv_kpi(v3, "🤝", "Outros envios nossos", _tv_n(_tk_outros),
                        "fluxo automático ou atendente que iniciou a conversa", color="#1d4ed8")
                _tv_kpi(v4, "🚫", "Envios sem resposta (fora do funil)", f"{_tv_n(_tk_fora)} · {_tv_pct(_tk_fora, _tk_all)}",
                        "fatia de todos os tickets do período", color="#64748b")
                if not _cp.empty:
                    for _c in ('enviados', 'responderam', 'com_humano', 'com_cpf', 'abertos', 'compras'):
                        if _c not in _cp.columns:
                            _cp[_c] = 0
                    _cp = _cp.sort_values('enviados', ascending=False)
                    _cpt = pd.DataFrame({
                        'Disparo': _cp['dim'].values,
                        'Enviados': _cp['enviados'].astype(int).values,
                        'Responderam': _cp['responderam'].astype(int).values,
                        '% resposta': (_cp['responderam'] / _cp['enviados'].replace(0, pd.NA) * 100).astype(float).round(1).values,
                        'Chegaram a atendente': _cp['com_humano'].astype(int).values,
                        'Com CPF': _cp['com_cpf'].astype(int).values,
                        'Ainda abertos': _cp['abertos'].astype(int).values,
                        'Compras reportadas': _cp['compras'].astype(int).values,
                    })
                    _st_df(_cpt, use_container_width=True, hide_index=True)
                else:
                    st.caption("Nenhum disparo em massa no período (o nome do disparo só existe de out/2026 em diante).")
                _tv_fonte("alex_tv_dash_mes · s7_campanha e s7_talkerchat (pipeline televendas_dash, R73) · origem do ticket pela 1ª mensagem "
                          "(alex_talkerchat_api.origem / campanha / respondeu)")

        # ---- R58: compra reportada (tabulação do atendente/bot) sai do funil e fica como registro da operação ----
''', "bloco 📣 envios por disparo")

# 5) sub-abas 9 e 10 (formato do deck): mesma regra
once('''    _w2_s7 = _tvd_m[_tvd_m['secao'] == 's7_talkerchat'] if not _tvd_m.empty else _tvd_m
''', '''    # R78: mesma regra do funil (receptivos + envios com resposta) quando o agregado já tem a seção filtrada
    _w2_sec = 's7f_talkerchat' if ((not _tvd_m.empty) and bool((_tvd_m['secao'] == 's7f_talkerchat').any())) else 's7_talkerchat'
    _w2_s7 = _tvd_m[_tvd_m['secao'] == _w2_sec] if not _tvd_m.empty else _tvd_m
''', "9/10 · seção s7f_talkerchat")
once('''_tv_fonte("alex_tv_dash_mes · s7_talkerchat (pipeline televendas_dash) · Talkerchat (tickets, filas, CPF do objeto de contato) × NOMINAL_VENDAS por IDPV")''',
     '''_tv_fonte(f"alex_tv_dash_mes · {_w2_sec} (pipeline televendas_dash) · Talkerchat (tickets, filas, CPF do objeto de contato) × NOMINAL_VENDAS por IDPV"
                          + (" · tickets = conversas iniciadas pelo cliente + envios nossos com resposta (envio em massa sem resposta fica fora)" if _w2_sec == 's7f_talkerchat' else ""))''',
     "9 · fonte com a regra")
once('''_tv_fonte("alex_tv_dash_mes · s7_talkerchat · variação = mês cheio vs mês cheio (sem corte de mesmo trecho)")''',
     '''_tv_fonte(f"alex_tv_dash_mes · {_w2_sec} · variação = mês cheio vs mês cheio (sem corte de mesmo trecho)"
                              + (" · tickets = receptivos + envios nossos com resposta" if _w2_sec == 's7f_talkerchat' else ""))''',
     "10 · fonte com a regra")

# 6) glossário
once('''    'Fechamento WhatsApp (funil do deck)': dict(sec="WhatsApp (Talkerchat)",
''', '''    'Ticket receptivo × ativo (Talkerchat)': dict(sec="WhatsApp (Talkerchat)",
        d="Receptivo = a conversa começou com uma mensagem do cliente. Ativo = a primeira mensagem foi nossa: disparo em massa (campanha), fluxo automático ou atendente. O disparo em massa abre um ticket para cada destinatário, mesmo que a pessoa nunca responda. Desde 16/11/2026 o funil do Talkerchat (sub-abas 📞 7, 9 e 10) conta os tickets receptivos e os ativos que o cliente respondeu; envio sem resposta fica fora e aparece só no bloco 📣 Envios nossos.",
        p="Out/26: 314.271 tickets ao todo, 245.590 no funil (74.434 de disparo em massa, 6.034 respondidos). Antes de out/26 nenhum ticket vem marcado como campanha. Resposta que chega mais de 7 dias depois do envio não é vista; quem responde depois de o ticket fechar abre um ticket novo, que conta como receptivo.",
        o="alex_talkerchat_api.origem / campanha / respondeu (1ª mensagem do ticket em alex_talkerchat_msg) → alex_tv_dash_mes · s7f_* e s7_campanha", a="📞",
        s=["Ticket receptivo", "Ticket ativo", "Envios nossos", "Disparo em massa", "Tickets de disparo em massa", "Responderam ao disparo", "Envios sem resposta (fora do funil)"]),
    'Fechamento WhatsApp (funil do deck)': dict(sec="WhatsApp (Talkerchat)",
''', "glossário: verbete receptivo × ativo")

if text != orig:
    bak = APP.with_name("app_bak_r78.py")
    if not bak.exists():
        shutil.copyfile(APP, bak)
    write_app(text, bom, crlf)
print("\n".join(changes))
print(f"app.py: {len(text.splitlines())} linhas")
