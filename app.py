import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import json
import urllib.request
import ssl

# --- 1. CONFIGURE PAGE & AUTHENTICATION ---
st.set_page_config(page_title="MySQL Dashboard", page_icon="📊", layout="wide")

def check_password():
    if st.session_state.get("password_correct", False):
        return True
    st.title("🔒 Dashboard Login")
    password = st.text_input("Please enter the password:", type="password")
    if password:
        if password == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            st.rerun() 
        else:
            st.error("😕 Password incorrect. Please try again.")
    return False

if not check_password():
    st.stop()

# --- 2. GLOBAL FORMATTING & HELPERS ---
def format_br(num): return f"{int(num):,}".replace(",", ".")
def format_money(num): return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_delta_str(curr, prev):
    if prev > 0:
        delta = ((curr - prev) / prev) * 100
        return f"{'+' if delta > 0 else ''}{delta:.1f}%"
    elif prev == 0 and curr > 0:
        return "+100.0%"
    return "N/A"

def fmt_val_delta(curr, prev):
    if prev == 0 and curr == 0:
        return "0 (N/A)"
    v_str = format_br(prev)
    d_str = get_delta_str(curr, prev)
    return f"{v_str} ({d_str})"

def fmt_val_delta_money(curr, prev):
    if prev == 0 and curr == 0:
        return "R$ 0,00 (N/A)"
    v_str = format_money(prev)
    d_str = get_delta_str(curr, prev)
    return f"{v_str} ({d_str})"

def color_deltas(val):
    if not isinstance(val, str) or '(' not in val:
        return ''
    try:
        pct_str = val.split('(')[1].split('%')[0].replace('+', '')
        if pct_str == 'N/A': return ''
        pct = float(pct_str)
        intensity = min(abs(pct) / 50.0, 1.0)
        alpha = 0.1 + (intensity * 0.35) 
        if pct > 0:
            return f'background-color: rgba(39, 174, 96, {alpha}); color: #000;'
        elif pct < 0:
            return f'background-color: rgba(231, 76, 60, {alpha}); color: #000;'
    except:
        pass
    return ''

# --- 3. DATABASE CONNECTIONS & DATA LOADERS ---
try:
    conn = st.connection("mysql", type="sql")
except Exception as e:
    st.error(f"Failed to connect to the database: {e}")
    st.stop()

@st.cache_data(ttl=86400) 
def get_brazil_geojson():
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url_geo = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
        with urllib.request.urlopen(url_geo, context=ctx) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

brazil_geo = get_brazil_geojson()

@st.cache_data(ttl=43200)
def load_calendar():
    try:
        query = "SELECT data AS data_ref, eh_dia_util AS is_dia_util FROM dim_calendario"
        cal = conn.query(query)
        cal['data_ref'] = pd.to_datetime(cal['data_ref'])
        return cal
    except Exception:
        dr = pd.date_range(start='2020-01-01', end='2030-12-31')
        return pd.DataFrame({'data_ref': dr, 'is_dia_util': (dr.weekday < 5).astype(int)})

@st.cache_data(ttl=43200) 
def load_data():
    start_of_last_year = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    query = f"SELECT data_venda, uf, tipo_venda, Vendas FROM RESUMO_VENDAS_DIARIAS WHERE data_venda >= '{start_of_last_year}'"
    df = conn.query(query)
    df['data_venda'] = pd.to_datetime(df['data_venda'])
    df['tipo_venda'] = df['tipo_venda'].fillna("Não Informado").astype(str).str.strip().str.title()
    return df

@st.cache_data(ttl=43200) 
def load_invest_data():
    start_of_last_year = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    query = f"SELECT data_investimento, canal, plataforma, branding, leads, venda, vol_leads, vol_vendas FROM RESUMO_INVESTIMENTO_DIARIO WHERE data_investimento >= '{start_of_last_year}'"
    try:
        df_inv = conn.query(query)
        df_inv['data_investimento'] = pd.to_datetime(df_inv['data_investimento'])
        df_inv['canal'] = df_inv['canal'].fillna("Não Informado").astype(str).str.strip().str.title()
        return df_inv
    except Exception:
        return pd.DataFrame(columns=['data_investimento', 'canal', 'plataforma', 'branding', 'leads', 'venda', 'vol_leads', 'vol_vendas'])

df_cal = load_calendar()
df_raw = load_data()
df_invest_raw = load_invest_data()

df = pd.merge(df_raw, df_cal, left_on='data_venda', right_on='data_ref', how='left')
df_invest = pd.merge(df_invest_raw, df_cal, left_on='data_investimento', right_on='data_ref', how='left')

df['is_dia_util'] = df['is_dia_util'].fillna(1)
df_invest['is_dia_util'] = df_invest['is_dia_util'].fillna(1)

# --- 4. DEFINING BUSINESS AGGREGATES ---
dig_list = ['website', 'app do filiado']
out_list = ['mgm', 'digital b2b2c', 'cdt sonhos', 'cdt sonhos maistodos', 'b2b2c', 'carlinhos maia', 'influenciadores', 'tutti']
tv_list  = ['televendas']
nac_list = dig_list + out_list + tv_list
fra_list = ['porta a porta', 'link do vendedor', 'app do vendedor']

group_map = {
    'Digital': dig_list,
    'Franquias': fra_list,
    'Outros': out_list,
    'Nacional': nac_list,
    'CDT': nac_list + fra_list
}

def get_agg_sums(df_slice):
    if df_slice.empty:
        return {'Digital': 0, 'Franquias': 0, 'Outros': 0, 'Nacional': 0, 'CDT': 0}
    dig = df_slice[df_slice['tipo_venda'].str.lower().isin(dig_list)]['Vendas'].sum()
    out = df_slice[df_slice['tipo_venda'].str.lower().isin(out_list)]['Vendas'].sum()
    nac = df_slice[df_slice['tipo_venda'].str.lower().isin(nac_list)]['Vendas'].sum()
    fra = df_slice[df_slice['tipo_venda'].str.lower().isin(fra_list)]['Vendas'].sum()
    cdt = df_slice['Vendas'].sum() 
    return {'Digital': dig, 'Franquias': fra, 'Outros': out, 'Nacional': nac, 'CDT': cdt}

def get_channel_sums(df_slice):
    if df_slice.empty: return {}
    return df_slice.groupby(df_slice['tipo_venda'].str.lower())['Vendas'].sum().to_dict()

def get_sales_goal(start_date, end_date, canais, filter_cal_type):
    days = (end_date - start_date).days + 1
    return days * 50 * max(1, len(canais))

def get_invest_goal(start_date, end_date, canais, plataformas, categorias, filter_cal_type):
    days = (end_date - start_date).days + 1
    return days * 1000 * max(1, len(plataformas))

# --- 5. GLOBAL SIDEBAR (TIME & CALENDAR LOGIC) ---
st.sidebar.title("🎛️ Controles Globais")

now_utc = datetime.datetime.utcnow()
now_sp = now_utc - datetime.timedelta(hours=3)

if now_sp.time() >= datetime.time(11, 30):
    reference_date = now_sp.date() - datetime.timedelta(days=1)
    hora_atualizacao = "Hoje às 11:30"
else:
    reference_date = now_sp.date() - datetime.timedelta(days=2)
    hora_atualizacao = "Ontem às 11:30"

st.sidebar.caption(f"🔄 **Base atualizada:** {hora_atualizacao}\n(Dados até {reference_date.strftime('%d/%m/%Y')})")
st.sidebar.divider()

view_option = st.sidebar.radio("Período de Análise:", [
    "Semana Atual", "Mês Atual", "Ano Atual", "Últimos 30 Dias", "Últimos 90 Dias", "Último 1 Ano"
])

filtro_dias = st.sidebar.radio("Dias de Operação:", [
    "Todos os dias", "Apenas Dias Úteis", "Apenas Fins de Semana/Feriados"
])

if filtro_dias == "Apenas Dias Úteis":
    df = df[df['is_dia_util'] == 1]
    df_invest = df_invest[df_invest['is_dia_util'] == 1]
elif filtro_dias == "Apenas Fins de Semana/Feriados":
    df = df[df['is_dia_util'] == 0]
    df_invest = df_invest[df_invest['is_dia_util'] == 0]

# --- UNIFIED DATE LOGIC ---
ref_datetime = pd.to_datetime(reference_date)

if view_option == "Semana Atual":
    c_s = ref_datetime - pd.to_timedelta(ref_datetime.weekday(), unit='D')
    c_e = c_s + pd.DateOffset(days=6)
    p_s, p_e = c_s - pd.DateOffset(weeks=1), c_e - pd.DateOffset(weeks=1)
    l_s, l_e = c_s - pd.DateOffset(weeks=52), c_e - pd.DateOffset(weeks=52)
elif view_option == "Mês Atual":
    c_s = ref_datetime.replace(day=1)
    c_e = c_s + pd.DateOffset(months=1) - pd.DateOffset(days=1)
    p_s = c_s - pd.DateOffset(months=1)
    p_e = c_s - pd.DateOffset(days=1)
    l_s = c_s - pd.DateOffset(years=1)
    l_e = l_s + pd.DateOffset(months=1) - pd.DateOffset(days=1)
elif view_option == "Ano Atual":
    c_s = ref_datetime.replace(month=1, day=1)
    c_e = c_s + pd.DateOffset(years=1) - pd.DateOffset(days=1)
    p_s, p_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
    l_s, l_e = p_s, p_e 
elif view_option == "Últimos 30 Dias":
    c_s, c_e = ref_datetime - pd.DateOffset(days=29), ref_datetime
    p_s, p_e = c_s - pd.DateOffset(days=30), c_e - pd.DateOffset(days=30)
    l_s, l_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
elif view_option == "Últimos 90 Dias":
    c_s, c_e = ref_datetime - pd.DateOffset(days=89), ref_datetime
    p_s, p_e = c_s - pd.DateOffset(days=90), c_e - pd.DateOffset(days=90)
    l_s, l_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
else: 
    c_s, c_e = ref_datetime - pd.DateOffset(years=1) + pd.DateOffset(days=1), ref_datetime
    p_s, p_e = c_s - pd.DateOffset(years=1), c_e - pd.DateOffset(years=1)
    l_s, l_e = c_s - pd.DateOffset(years=2), c_e - pd.DateOffset(years=2)

days_elapsed = (ref_datetime - c_s).days
p_partial = min(p_s + pd.DateOffset(days=days_elapsed), p_e)
l_partial = min(l_s + pd.DateOffset(days=days_elapsed), l_e)

def get_period_stats(start_d, end_d_partial, end_d_full):
    total_days = (end_d_full - start_d).days + 1
    elapsed_days = (end_d_partial - start_d).days + 1
    wd_total = df_cal[(df_cal['data_ref'] >= start_d) & (df_cal['data_ref'] <= end_d_full)]['is_dia_util'].sum()
    wd_elapsed = df_cal[(df_cal['data_ref'] >= start_d) & (df_cal['data_ref'] <= end_d_partial)]['is_dia_util'].sum()
    return total_days, elapsed_days, wd_total, wd_elapsed

t_days_c, e_days_c, w_tot_c, w_ela_c = get_period_stats(c_s, ref_datetime, c_e)
t_days_p, e_days_p, w_tot_p, w_ela_p = get_period_stats(p_s, p_partial, p_e)
t_days_l, e_days_l, w_tot_l, w_ela_l = get_period_stats(l_s, l_partial, l_e)


# --- UI: TABS FOR ORGANIZATION ---
st.title("📊 Vendas Dashboard")
tab1, tab2, tab3 = st.tabs(["📈 Desempenho de Vendas", "🗺️ Mapa Regional (UF)", "💰 Investimento"])

# =====================================================================
# TAB 1: DESEMPENHO DE VENDAS
# =====================================================================
with tab1:
    st.header("Visão Integrada de Vendas")
    st.info(f"**Status do Período ({view_option}):** Decorridos **{e_days_c} de {t_days_c} dias** no calendário. | **Dias Úteis Decorridos:** Atual: {w_ela_c} | Anterior: {w_ela_p} | Ano Passado: {w_ela_l}")

    df_slice_c = df[(df['data_venda'] >= c_s) & (df['data_venda'] <= ref_datetime)]
    df_slice_pp = df[(df['data_venda'] >= p_s) & (df['data_venda'] <= p_partial)]
    df_slice_pf = df[(df['data_venda'] >= p_s) & (df['data_venda'] <= p_e)]
    df_slice_lp = df[(df['data_venda'] >= l_s) & (df['data_venda'] <= l_partial)]
    df_slice_lf = df[(df['data_venda'] >= l_s) & (df['data_venda'] <= l_e)]

    agg_c = get_agg_sums(df_slice_c)
    agg_pp = get_agg_sums(df_slice_pp)
    agg_pf = get_agg_sums(df_slice_pf)
    agg_lp = get_agg_sums(df_slice_lp)
    agg_lf = get_agg_sums(df_slice_lf)
    
    ch_c = get_channel_sums(df_slice_c)
    ch_pp = get_channel_sums(df_slice_pp)
    ch_pf = get_channel_sums(df_slice_pf)
    ch_lp = get_channel_sums(df_slice_lp)
    ch_lf = get_channel_sums(df_slice_lf)

    goal_vendas = get_sales_goal(c_s, ref_datetime, ['CDT'], filtro_dias)
    pct_goal = agg_c['CDT'] / goal_vendas if goal_vendas > 0 else 0
    st.markdown(f"🎯 **Progresso da Meta de Vendas (CDT):** {format_br(agg_c['CDT'])} / {format_br(goal_vendas)} atingidos (**{pct_goal*100:.1f}%**)")
    st.progress(min(max(pct_goal, 0.0), 1.0))
    st.divider()

    st.subheader("Análise Detalhada por Canal")
    mostrar_detalhes = st.checkbox("Mostrar detalhamento por canal (Expandir Grupos)")
    
    rows = []
    for grupo in ['Digital', 'Franquias', 'Outros', 'Nacional', 'CDT']:
        nome_exibicao = "CDT (Total)" if grupo == 'CDT' else grupo
        label_grupo = f"📁 {nome_exibicao.upper()}" if mostrar_detalhes else nome_exibicao
        
        rows.append({
            'Grupo': label_grupo,
            'Atual': agg_c[grupo],
            'vs Anterior (Parcial)': fmt_val_delta(agg_c[grupo], agg_pp[grupo]),
            'vs Anterior (Total)': fmt_val_delta(agg_c[grupo], agg_pf[grupo]),
            'vs Ano Passado (Parcial)': fmt_val_delta(agg_c[grupo], agg_lp[grupo]),
            'vs Ano Passado (Total)': fmt_val_delta(agg_c[grupo], agg_lf[grupo]),
        })
        
        if mostrar_detalhes:
            for ch in group_map[grupo]:
                v_c, v_pp, v_pf, v_lp, v_lf = ch_c.get(ch, 0), ch_pp.get(ch, 0), ch_pf.get(ch, 0), ch_lp.get(ch, 0), ch_lf.get(ch, 0)
                if v_c == 0 and v_pf == 0 and v_lf == 0: continue 
                
                rows.append({
                    'Grupo': f"\xa0\xa0\xa0\xa0\xa0\xa0└─ {ch.title()}",
                    'Atual': v_c,
                    'vs Anterior (Parcial)': fmt_val_delta(v_c, v_pp),
                    'vs Anterior (Total)': fmt_val_delta(v_c, v_pf),
                    'vs Ano Passado (Parcial)': fmt_val_delta(v_c, v_lp),
                    'vs Ano Passado (Total)': fmt_val_delta(v_c, v_lf),
                })
                
    df_triplet = pd.DataFrame(rows)
    
    display_cols = ['Grupo', 'Atual', 'vs Anterior (Parcial)', 'vs Anterior (Total)']
    if view_option != "Ano Atual":
        display_cols.extend(['vs Ano Passado (Parcial)', 'vs Ano Passado (Total)'])
        
    df_table_fmt = df_triplet[display_cols].copy()
    df_table_fmt['Atual'] = df_table_fmt['Atual'].apply(format_br)
    
    styled_df = df_table_fmt.style.map(color_deltas, subset=display_cols[2:])
    st.dataframe(styled_df, use_container_width=True, hide_index=True)

    col_pie, col_trend = st.columns([1, 2])
    
    with col_pie:
        st.markdown("**Representatividade**")
        tipo_visao_pizza = st.radio("Nível de Visualização:", ["Grupos (Exclusivos CDT)", "Canais Específicos"], horizontal=True, key='pie_rad')
        
        if tipo_visao_pizza == "Grupos (Exclusivos CDT)":
            v_dig = df_slice_c[df_slice_c['tipo_venda'].str.lower().isin(dig_list)]['Vendas'].sum()
            v_tv = df_slice_c[df_slice_c['tipo_venda'].str.lower().isin(tv_list)]['Vendas'].sum()
            v_out = df_slice_c[df_slice_c['tipo_venda'].str.lower().isin(out_list)]['Vendas'].sum()
            v_fra = df_slice_c[df_slice_c['tipo_venda'].str.lower().isin(fra_list)]['Vendas'].sum()
            sum_known = v_dig + v_tv + v_out + v_fra
            v_rest = max(0, df_slice_c['Vendas'].sum() - sum_known)
            
            pie_data = [
                {'Categoria': 'Digital', 'Vendas': v_dig},
                {'Categoria': 'Televendas', 'Vendas': v_tv},
                {'Categoria': 'Outros', 'Vendas': v_out},
                {'Categoria': 'Franquias', 'Vendas': v_fra}
            ]
            if v_rest > 0: pie_data.append({'Categoria': 'Restante', 'Vendas': v_rest})
            df_pie = pd.DataFrame(pie_data)
        else:
            df_pie = df_slice_c.groupby('tipo_venda')['Vendas'].sum().reset_index()
            df_pie.rename(columns={'tipo_venda': 'Categoria'}, inplace=True)
            
        df_pie = df_pie[df_pie['Vendas'] > 0]
        
        if not df_pie.empty:
            fig_pie = px.pie(df_pie, names='Categoria', values='Vendas', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label', hovertemplate="<b>%{label}</b><br>Vendas: %{value}<extra></extra>")
            fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_pie, use_container_width=True, key='pie_chart_t1')
        else:
            st.info("Sem dados para o gráfico de pizza.")
            
    with col_trend:
        st.markdown("**Tendência Diária / Acumulada**")
        
        col_gt1, col_gt2 = st.columns(2)
        tipo_visao_tend = col_gt1.radio("Nível de Visualização:", ["Grupos de Canais", "Canais Específicos"], horizontal=True, key='tend_rad')
        tipo_graf_tend = col_gt2.radio("Soma do Gráfico:", ["Diário", "Acumulado"], horizontal=True)
        
        if tipo_visao_tend == "Grupos de Canais":
            canais_grafico = st.multiselect("Selecione os Grupos:", options=['Digital', 'Franquias', 'Outros', 'Nacional', 'CDT'], default=['CDT'], key='t1_grp_sel')
        else:
            opcoes_ch_raw = sorted([str(c).title() for c in df_slice_c['tipo_venda'].unique()])
            canais_grafico = st.multiselect("Selecione os Canais:", options=opcoes_ch_raw, default=opcoes_ch_raw[:3] if opcoes_ch_raw else [], key='t1_can_sel')
            
        col_g1, col_g2 = st.columns(2)
        show_prev = col_g1.checkbox("Comparar com Período Anterior")
        show_last_yr = col_g2.checkbox("Comparar com Ano Passado")

        def get_trend_data(t_start, t_end, label_suffix, max_actual_date=None):
            end_bound = min(t_end, max_actual_date) if max_actual_date else t_end
            df_t = df[(df['data_venda'] >= t_start) & (df['data_venda'] <= end_bound)]
            if df_t.empty: return pd.DataFrame()
            
            res_dfs = []
            
            if tipo_visao_tend == "Grupos de Canais":
                if 'CDT' in canais_grafico:
                    d = df_t.groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'CDT'
                    res_dfs.append(d)
                if 'Nacional' in canais_grafico:
                    d = df_t[df_t['tipo_venda'].str.lower().isin(nac_list)].groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'Nacional'
                    res_dfs.append(d)
                if 'Franquias' in canais_grafico:
                    d = df_t[df_t['tipo_venda'].str.lower().isin(fra_list)].groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'Franquias'
                    res_dfs.append(d)
                if 'Digital' in canais_grafico:
                    d = df_t[df_t['tipo_venda'].str.lower().isin(dig_list)].groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'Digital'
                    res_dfs.append(d)
                if 'Outros' in canais_grafico:
                    d = df_t[df_t['tipo_venda'].str.lower().isin(out_list)].groupby('data_venda')['Vendas'].sum().reset_index()
                    d['Grupo'] = 'Outros'
                    res_dfs.append(d)
            else:
                if canais_grafico:
                    mask = df_t['tipo_venda'].str.title().isin(canais_grafico)
                    d = df_t[mask].groupby(['data_venda', 'tipo_venda'])['Vendas'].sum().reset_index()
                    d.rename(columns={'tipo_venda': 'Grupo'}, inplace=True)
                    d['Grupo'] = d['Grupo'].str.title()
                    res_dfs.append(d)

            if not res_dfs: return pd.DataFrame()
            
            res = pd.concat(res_dfs)
            res['Dia'] = (res['data_venda'] - t_start).dt.days + 1
            res['Traço'] = res['Grupo'] + label_suffix
            res['Data_Real'] = res['data_venda']
            res = res.sort_values(['Grupo', 'Dia'])
            
            if tipo_graf_tend == "Acumulado":
                res['Vendas'] = res.groupby('Traço')['Vendas'].cumsum()
                
            return res

        df_main = get_trend_data(c_s, c_e, "", max_actual_date=ref_datetime)
        plot_dfs = [df_main] if not df_main.empty else []
        
        if show_prev:
            df_prev_plot = get_trend_data(p_s, p_e, " (Anterior)")
            if not df_prev_plot.empty: plot_dfs.append(df_prev_plot)
            
        if show_last_yr and view_option != "Ano Atual":
            df_last_plot = get_trend_data(l_s, l_e, " (Ano Passado)")
            if not df_last_plot.empty: plot_dfs.append(df_last_plot)

        if plot_dfs:
            df_plot_trend = pd.concat(plot_dfs)
            df_plot_trend['Formatado'] = df_plot_trend['Vendas'].apply(format_br)
            df_plot_trend['Data_Str'] = df_plot_trend['Data_Real'].dt.strftime('%d/%m/%Y')
            
            fig_trend = px.line(df_plot_trend, x='Dia', y='Vendas', color='Traço', markers=True)
            
            for trace in fig_trend.data:
                if "(Anterior)" in trace.name or "(Ano Passado)" in trace.name:
                    trace.line.dash = 'dash'
                    
            fig_trend.update_traces(hovertemplate="<b>Data Original: %{customdata[1]}</b><br>Vendas: %{customdata[0]}<extra></extra>",
                                    customdata=df_plot_trend[['Formatado', 'Data_Str']])
            fig_trend.update_layout(margin=dict(t=0, b=0, l=0, r=0), xaxis_title="Dias Decorridos", yaxis_title=f"Vendas ({tipo_graf_tend})")
            st.plotly_chart(fig_trend, use_container_width=True, key='trend_chart_t1')
        else:
            st.info("Sem dados para o gráfico de tendência.")


# =====================================================================
# TAB 2: ANÁLISE GEOGRÁFICA COMPARATIVA
# =====================================================================
with tab2:
    st.header("Análise Geográfica Comparativa (UF)")
    st.markdown(f"**Período analisado:** {c_s.strftime('%d/%m/%Y')} a {ref_datetime.strftime('%d/%m/%Y')}")
    st.write("")
    
    col_map_left, col_map_right = st.columns(2)
    
    def render_map_column(col_obj, map_id, default_group):
        with col_obj:
            st.subheader(f"Mapa {map_id}")
            
            tipo_filtro_mapa = st.radio(f"Nível de Filtro:", ["Grupos de Canais", "Canais Específicos"], horizontal=True, key=f"t2_rad_{map_id}")
            
            if tipo_filtro_mapa == "Grupos de Canais":
                grupos_sel_mapa = st.multiselect(f"Selecione os Grupos:", ['Digital', 'Franquias', 'Outros', 'Nacional', 'CDT'], default=[default_group], key=f"t2_grp_sel_{map_id}")
                canais_mapa_alvo = []
                for g in grupos_sel_mapa:
                    canais_mapa_alvo.extend(group_map[g])
                canais_mapa_alvo = list(set(canais_mapa_alvo))
            else:
                opcoes_canais_brutos = sorted([str(c) for c in df_raw['tipo_venda'].dropna().unique()])
                canais_mapa_raw = st.multiselect(f"Selecione os Canais:", options=opcoes_canais_brutos, default=opcoes_canais_brutos[:2] if opcoes_canais_brutos else [], key=f"t2_can_sel_{map_id}")
                canais_mapa_alvo = [c.lower() for c in canais_mapa_raw]
            
            mask_map = (df['data_venda'] >= c_s) & (df['data_venda'] <= ref_datetime) & (df['tipo_venda'].str.lower().isin(canais_mapa_alvo))
            df_map = df.loc[mask_map].copy()
            
            if not df_map.empty:
                df_map['uf'] = df_map['uf'].str.upper()
                uf_sales = df_map.groupby('uf')['Vendas'].sum().reset_index()
                total_map_sales = uf_sales['Vendas'].sum()
                
                # Plot Mapa
                if brazil_geo:
                    fig_map = px.choropleth(
                        uf_sales, geojson=brazil_geo, locations='uf', featureidkey='properties.sigla',
                        color='Vendas', color_continuous_scale="Blues"
                    )
                    fig_map.update_geos(fitbounds="locations", visible=False)
                    fig_map.update_traces(customdata=[format_br(v) for v in uf_sales['Vendas']], hovertemplate="<b>%{location}</b><br>Vendas: %{customdata}<extra></extra>")
                    fig_map.update_layout(margin={"r":0,"t":20,"l":0,"b":0})
                    st.plotly_chart(fig_map, use_container_width=True, key=f"plotly_map_{map_id}")
                else:
                    st.warning("Mapa do Brasil não carregado. Exibindo apenas barras.")
                
                # Plot Gráfico de Barras
                df_sorted = uf_sales.sort_values(by='Vendas', ascending=True).copy()
                df_sorted["Perc"] = (df_sorted["Vendas"] / total_map_sales * 100).round(1).astype(str) + "%"
                df_sorted["Vendas_Formatadas"] = df_sorted["Vendas"].apply(format_br) + " (" + df_sorted["Perc"] + ")"
                
                fig_bar_uf = px.bar(df_sorted, x='Vendas', y='uf', orientation='h', title="Ranking por UF", text="Vendas_Formatadas")
                fig_bar_uf.update_traces(textposition='outside', cliponaxis=False, hovertemplate="<b>%{y}</b><br>Vendas: %{text}<extra></extra>")
                fig_bar_uf.update_layout(margin={"r":80,"t":40,"l":0,"b":0}, yaxis_title="")
                st.plotly_chart(fig_bar_uf, use_container_width=True, key=f"plotly_bar_{map_id}")
            else:
                st.info("Nenhuma venda encontrada para os filtros selecionados.")

    render_map_column(col_map_left, "1", "Digital")
    render_map_column(col_map_right, "2", "Franquias")


# =====================================================================
# TAB 3: ANÁLISE DE INVESTIMENTO
# =====================================================================
with tab3:
    st.header("Análise de Investimento")
    st.info(f"**Status do Período ({view_option}):** Decorridos **{e_days_c} de {t_days_c} dias** no calendário. | **Dias Úteis Decorridos:** Atual: {w_ela_c} | Anterior: {w_ela_p} | Ano Passado: {w_ela_l}")
    
    col_filt1, col_filt2, col_filt3 = st.columns(3)
    
    opcoes_canais_inv = sorted([str(c) for c in df_invest_raw['canal'].dropna().unique()])
    canais_invest = col_filt1.multiselect("Canal:", options=opcoes_canais_inv, default=opcoes_canais_inv, key='t3_can_inv')
    categorias_invest = col_filt2.multiselect("Categoria:", ["Branding", "Leads", "Venda"], default=["Branding", "Leads", "Venda"], key='t3_cat_inv')
    
    todas_plataformas = ["Google", "Meta", "TikTok", "Adsplay", "Actionpay", "CRM"]
    plataformas_invest = col_filt3.multiselect("Plataforma:", todas_plataformas, default=todas_plataformas, key='t3_plat_inv')
    
    df_inv_filt = df_invest[
        (df_invest['canal'].isin(canais_invest)) & 
        (df_invest['plataforma'].isin(plataformas_invest))
    ].copy()
    
    cat_cols = [c.lower() for c in categorias_invest]
    if cat_cols and not df_inv_filt.empty:
        df_inv_filt['Total_Investido'] = df_inv_filt[cat_cols].sum(axis=1)
    else:
        df_inv_filt['Total_Investido'] = 0

    st.divider()

    def filter_inv_date(df_i, start, end):
        mask = (df_i['data_investimento'] >= start) & (df_i['data_investimento'] <= end)
        return df_i.loc[mask]

    def get_inv_metrics(df_slice, cat=None):
        if df_slice.empty: return 0, 0, 0
        v_leads = df_slice['vol_leads'].sum()
        v_vendas = df_slice['vol_vendas'].sum()
        
        if cat:
            tot_inv = df_slice[cat].sum()
            cpl = tot_inv / v_leads if v_leads > 0 else 0
            cpa = tot_inv / v_vendas if v_vendas > 0 else 0
        else:
            tot_inv = df_slice['Total_Investido'].sum()
            c_leads = df_slice['leads'].sum()
            c_vendas = df_slice['venda'].sum()
            cpl = c_leads / v_leads if v_leads > 0 else 0
            cpa = c_vendas / v_vendas if v_vendas > 0 else 0
            
        return tot_inv, cpl, cpa

    def compute_row(label, df_c, df_pp, df_pf, df_lp, df_lf, metric_idx, cat=None):
        m_c = get_inv_metrics(df_c, cat)[metric_idx]
        m_pp = get_inv_metrics(df_pp, cat)[metric_idx]
        m_pf = get_inv_metrics(df_pf, cat)[metric_idx]
        m_lp = get_inv_metrics(df_lp, cat)[metric_idx]
        m_lf = get_inv_metrics(df_lf, cat)[metric_idx]
        
        return {
            'Métrica': label,
            'Atual': format_money(m_c),
            'vs Anterior (Parcial)': fmt_val_delta_money(m_c, m_pp),
            'vs Anterior (Total)': fmt_val_delta_money(m_c, m_pf),
            'vs Ano Passado (Parcial)': fmt_val_delta_money(m_c, m_lp),
            'vs Ano Passado (Total)': fmt_val_delta_money(m_c, m_lf),
            '_val_c': m_c,
            '_val_pf': m_pf,
            '_val_lf': m_lf,
            '_is_eff': True if metric_idx in [1, 2] else False
        }

    inv_current_total = filter_inv_date(df_inv_filt, c_s, ref_datetime)['Total_Investido'].sum()
    goal_invest = get_invest_goal(c_s, ref_datetime, canais_invest, plataformas_invest, categorias_invest, filtro_dias)
    pct_goal_inv = inv_current_total / goal_invest if goal_invest > 0 else 0
    st.markdown(f"🎯 **Progresso da Meta de Investimento:** {format_money(inv_current_total)} / {format_money(goal_invest)} utilizados (**{pct_goal_inv*100:.1f}%**)")
    st.progress(min(max(pct_goal_inv, 0.0), 1.0))
    st.divider()

    st.subheader("Indicadores de Eficiência")
    
    col_det1, col_det2 = st.columns(2)
    detalhe_plat = col_det1.checkbox("Mostrar detalhamento por plataforma", key='t3_det_plat')
    detalhe_tipo = col_det2.checkbox("Mostrar detalhamento por tipo de investimento", key='t3_det_tipo')
    
    df_c_inv = filter_inv_date(df_inv_filt, c_s, ref_datetime)
    df_pp_inv = filter_inv_date(df_inv_filt, p_s, p_partial)
    df_pf_inv = filter_inv_date(df_inv_filt, p_s, p_e)
    df_lp_inv = filter_inv_date(df_inv_filt, l_s, l_partial)
    df_lf_inv = filter_inv_date(df_inv_filt, l_s, l_e)

    metrics = [(0, '💸 Total Investido'), (1, '🎯 CPL (Custo por Lead)'), (2, '🛒 CPA (Custo por Venda)')]
    rows_inv = []

    for m_idx, m_name in metrics:
        has_children = detalhe_plat or detalhe_tipo
        label_parent = f"📁 {m_name.upper()}" if has_children else m_name
        
        row_parent = compute_row(label_parent, df_c_inv, df_pp_inv, df_pf_inv, df_lp_inv, df_lf_inv, m_idx)
        rows_inv.append(row_parent)
        
        if detalhe_plat and not detalhe_tipo:
            for plat in plataformas_invest:
                p_df_c = df_c_inv[df_c_inv['plataforma'] == plat]
                p_df_pp = df_pp_inv[df_pp_inv['plataforma'] == plat]
                p_df_pf = df_pf_inv[df_pf_inv['plataforma'] == plat]
                p_df_lp = df_lp_inv[df_lp_inv['plataforma'] == plat]
                p_df_lf = df_lf_inv[df_lf_inv['plataforma'] == plat]
                
                row_p = compute_row(f"\xa0\xa0\xa0\xa0\xa0\xa0└─ {plat}", p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx)
                if row_p['_val_c'] == 0 and row_p['_val_pf'] == 0 and row_p['_val_lf'] == 0: continue
                rows_inv.append(row_p)
                
        elif detalhe_tipo and not detalhe_plat:
            for cat in cat_cols:
                row_c = compute_row(f"\xa0\xa0\xa0\xa0\xa0\xa0└─ {cat.title()}", df_c_inv, df_pp_inv, df_pf_inv, df_lp_inv, df_lf_inv, m_idx, cat=cat)
                if row_c['_val_c'] == 0 and row_c['_val_pf'] == 0 and row_c['_val_lf'] == 0: continue
                rows_inv.append(row_c)
                
        elif detalhe_plat and detalhe_tipo:
            for plat in plataformas_invest:
                p_df_c = df_c_inv[df_c_inv['plataforma'] == plat]
                p_df_pp = df_pp_inv[df_pp_inv['plataforma'] == plat]
                p_df_pf = df_pf_inv[df_pf_inv['plataforma'] == plat]
                p_df_lp = df_lp_inv[df_lp_inv['plataforma'] == plat]
                p_df_lf = df_lf_inv[df_lf_inv['plataforma'] == plat]
                
                row_p = compute_row(f"\xa0\xa0\xa0\xa0\xa0\xa0└─ 📁 {plat.upper()}", p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx)
                if row_p['_val_c'] == 0 and row_p['_val_pf'] == 0 and row_p['_val_lf'] == 0: continue
                rows_inv.append(row_p)
                
                for cat in cat_cols:
                    row_c = compute_row(f"\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0└─ {cat.title()}", p_df_c, p_df_pp, p_df_pf, p_df_lp, p_df_lf, m_idx, cat=cat)
                    if row_c['_val_c'] == 0 and row_c['_val_pf'] == 0 and row_c['_val_lf'] == 0: continue
                    rows_inv.append(row_c)
    
    df_inv_table = pd.DataFrame(rows_inv)
    is_eff_map = df_inv_table['_is_eff'].to_dict()
    
    display_cols_inv = ['Métrica', 'Atual', 'vs Anterior (Parcial)', 'vs Anterior (Total)']
    if view_option != "Ano Atual":
        display_cols_inv.extend(['vs Ano Passado (Parcial)', 'vs Ano Passado (Total)'])
        
    df_inv_fmt = df_inv_table[display_cols_inv].copy()
    
    def style_inv_table(row):
        styles = [''] * len(row)
        is_efficiency = is_eff_map[row.name]
        
        for i, col in enumerate(row.index):
            if col in ['vs Anterior (Parcial)', 'vs Anterior (Total)', 'vs Ano Passado (Parcial)', 'vs Ano Passado (Total)']:
                val = row[col]
                if isinstance(val, str) and '(' in val:
                    try:
                        pct_str = val.split('(')[1].split('%')[0].replace('+', '')
                        if pct_str != 'N/A':
                            pct = float(pct_str)
                            intensity = min(abs(pct) / 50.0, 1.0)
                            alpha = 0.1 + (intensity * 0.35) 
                            
                            if is_efficiency:
                                if pct < 0:
                                    styles[i] = f'background-color: rgba(39, 174, 96, {alpha}); color: #000;'
                                elif pct > 0:
                                    styles[i] = f'background-color: rgba(231, 76, 60, {alpha}); color: #000;'
                            else:
                                if pct > 0:
                                    styles[i] = f'background-color: rgba(39, 174, 96, {alpha}); color: #000;'
                                elif pct < 0:
                                    styles[i] = f'background-color: rgba(231, 76, 60, {alpha}); color: #000;'
                    except:
                        pass
        return styles

    styled_inv_df = df_inv_fmt.style.apply(style_inv_table, axis=1)
    st.dataframe(styled_inv_df, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Análise Gráfica")
    
    col_inv_t1, col_inv_t2 = st.columns(2)
    grafico_metrica = col_inv_t1.selectbox("Selecione a métrica para o gráfico:", 
                                   ["Total Investido", "CPL", "CPA", "Leads (Volume)", "Vendas (Volume)"], key='t3_met_sel')
    tipo_graf_tend_inv = col_inv_t2.radio("Visualização:", ["Diário", "Acumulado"], horizontal=True, key='t3_rad_tend')
    
    col_ig1, col_ig2 = st.columns(2)
    show_prev_inv = col_ig1.checkbox("Comparar com Período Anterior", key='t3_chk_prev')
    show_last_yr_inv = col_ig2.checkbox("Comparar com Ano Passado", key='t3_chk_last')

    def get_inv_trend_data(t_start, t_end, label_suffix, max_actual_date=None):
        end_bound = min(t_end, max_actual_date) if max_actual_date else t_end
        df_t = df_inv_filt[(df_inv_filt['data_investimento'] >= t_start) & (df_inv_filt['data_investimento'] <= end_bound)]
        if df_t.empty: return pd.DataFrame()
        
        grp = df_t.groupby('data_investimento')[['Total_Investido', 'leads', 'vol_leads', 'venda', 'vol_vendas']].sum().reset_index()
        grp = grp.sort_values('data_investimento')
        
        if tipo_graf_tend_inv == "Acumulado":
            grp['Total_Investido'] = grp['Total_Investido'].cumsum()
            grp['leads'] = grp['leads'].cumsum()
            grp['vol_leads'] = grp['vol_leads'].cumsum()
            grp['venda'] = grp['venda'].cumsum()
            grp['vol_vendas'] = grp['vol_vendas'].cumsum()
            
        if grafico_metrica == "Total Investido":
            grp['Y'] = grp['Total_Investido']
            grp['Formatado'] = grp['Y'].apply(format_money)
        elif grafico_metrica == "CPL":
            grp['Y'] = grp.apply(lambda r: r['leads'] / r['vol_leads'] if r['vol_leads'] > 0 else 0, axis=1)
            grp['Formatado'] = grp['Y'].apply(format_money)
        elif grafico_metrica == "CPA":
            grp['Y'] = grp.apply(lambda r: r['venda'] / r['vol_vendas'] if r['vol_vendas'] > 0 else 0, axis=1)
            grp['Formatado'] = grp['Y'].apply(format_money)
        elif grafico_metrica == "Leads (Volume)":
            grp['Y'] = grp['vol_leads']
            grp['Formatado'] = grp['Y'].apply(format_br)
        elif grafico_metrica == "Vendas (Volume)":
            grp['Y'] = grp['vol_vendas']
            grp['Formatado'] = grp['Y'].apply(format_br)
            
        grp['Dia'] = (grp['data_investimento'] - t_start).dt.days + 1
        grp['Traço'] = grafico_metrica + label_suffix
        grp['Data_Real'] = grp['data_investimento']
        
        return grp

    plot_dfs_inv = []
    df_main_inv = get_inv_trend_data(c_s, c_e, "", max_actual_date=ref_datetime)
    if not df_main_inv.empty: plot_dfs_inv.append(df_main_inv)
    
    if show_prev_inv:
        df_prev_plot_inv = get_inv_trend_data(p_s, p_e, " (Anterior)")
        if not df_prev_plot_inv.empty: plot_dfs_inv.append(df_prev_plot_inv)
        
    if show_last_yr_inv and view_option != "Ano Atual":
        df_last_plot_inv = get_inv_trend_data(l_s, l_e, " (Ano Passado)")
        if not df_last_plot_inv.empty: plot_dfs_inv.append(df_last_plot_inv)

    if plot_dfs_inv:
        df_plot_trend_inv = pd.concat(plot_dfs_inv)
        df_plot_trend_inv['Data_Str'] = df_plot_trend_inv['Data_Real'].dt.strftime('%d/%m/%Y')
        
        fig_line = px.line(df_plot_trend_inv, x='Dia', y='Y', color='Traço', markers=True)
        
        for trace in fig_line.data:
            if "(Anterior)" in trace.name or "(Ano Passado)" in trace.name:
                trace.line.dash = 'dash'
                
        fig_line.update_traces(hovertemplate="<b>Data Original: %{customdata[1]}</b><br>Valor: %{customdata[0]}<extra></extra>",
                                customdata=df_plot_trend_inv[['Formatado', 'Data_Str']])
        fig_line.update_layout(margin=dict(t=0, b=0, l=0, r=0), xaxis_title="Dias Decorridos", yaxis_title=f"{grafico_metrica} ({tipo_graf_tend_inv})")
        st.plotly_chart(fig_line, use_container_width=True, key='t3_trend_chart_new')
    else:
        st.info("Sem dados para o gráfico de tendência.")