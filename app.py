import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import json
import urllib.request
import ssl

# 1. Configure the page 
st.set_page_config(page_title="MySQL Dashboard", page_icon="📊", layout="wide")

# --- AUTHENTICATION SECTION ---
def check_password():
    """Returns `True` if the user has the correct password."""
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

# --- MAIN DASHBOARD SECTION ---
st.title("📊 Vendas Dashboard")

try:
    conn = st.connection("mysql", type="sql")
except Exception as e:
    st.error(f"Failed to connect to the database: {e}")
    st.stop()

# --- MAP HELPER FUNCTION ---
@st.cache_data(ttl=86400) # Cache map file for 24 hours
def get_brazil_geojson():
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url_geo = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
        with urllib.request.urlopen(url_geo, context=ctx) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        return None

brazil_geo = get_brazil_geojson()

# --- 1. DATA LOAD FUNCTION (Reads from the new, fast table) ---
@st.cache_data(ttl=43200) 
def load_data():
    start_of_last_year = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    
    # Notice there is no GROUP BY or COUNT() here anymore. 
    # We are just downloading the pre-calculated numbers!
    query = f"""
    SELECT 
        data_venda, 
        uf, 
        tipo_venda, 
        Vendas
    FROM RESUMO_VENDAS_DIARIAS 
    WHERE data_venda >= '{start_of_last_year}'
    """
    
    df = conn.query(query)
    df['data_venda'] = pd.to_datetime(df['data_venda'])
    return df

# --- INVESTIMENTO: DATA LOAD ---
@st.cache_data(ttl=43200) 
def load_invest_data():
    start_of_last_year = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    
    query = f"""
    SELECT 
        data_investimento, 
        canal,
        plataforma,
        branding, 
        leads, 
        venda,
        vol_leads,
        vol_vendas
    FROM RESUMO_INVESTIMENTO_DIARIO 
    WHERE data_investimento >= '{start_of_last_year}'
    """
    try:
        df_inv = conn.query(query)
        df_inv['data_investimento'] = pd.to_datetime(df_inv['data_investimento'])
        return df_inv
    except Exception:
        return pd.DataFrame(columns=['data_investimento', 'canal', 'plataforma', 'branding', 'leads', 'venda', 'vol_leads', 'vol_vendas'])

df_invest = load_invest_data()

# --- MONEY FORMATTER ---
def format_money(num):
    # Formats to R$ 1.234,56
    return f"R$ {num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

df = load_data()

# --- 2. TIME LOGIC ---
reference_date = datetime.date.today() - datetime.timedelta(days=1)
ref_datetime = pd.to_datetime(reference_date)

this_week_start = ref_datetime - pd.to_timedelta(ref_datetime.weekday(), unit='D')
this_month_start = ref_datetime.replace(day=1)
this_year_start = ref_datetime.replace(month=1, day=1)

def filter_by_date(dataframe, start_date, end_date):
    mask = (dataframe['data_venda'] >= start_date) & (dataframe['data_venda'] <= end_date)
    return dataframe.loc[mask]

def format_br(num):
    return f"{int(num):,}".replace(",", ".")

# --- UI: TABS FOR ORGANIZATION ---
tab1, tab2, tab3, tab4 = st.tabs(["📈 Desempenho de Vendas", "🗺️ Mapa Regional (UF)", "🛒 Tipo de Venda", "💰 Investimento"])

with tab1:
    st.header("Visão de Vendas")
    
    view_option = st.radio("Selecione o período:", ["Semana Atual", "Mês Atual", "Ano Atual"], horizontal=True)
    
    # --- DATE LOGIC: PARTIAL AND FULL PERIODS ---
    days_elapsed = (ref_datetime - current_start).days if 'current_start' in locals() else 0 # Fallback, calculated below
    
    if view_option == "Semana Atual":
        current_start = this_week_start
        days_elapsed = (ref_datetime - current_start).days
        
        prev_start = current_start - pd.DateOffset(weeks=1)
        prev_full_end = current_start - pd.DateOffset(days=1)
        prev_partial_end = prev_start + pd.DateOffset(days=days_elapsed)
        
        last_year_start = current_start - pd.DateOffset(weeks=52)
        last_year_full_end = last_year_start + pd.DateOffset(days=6)
        last_year_partial_end = last_year_start + pd.DateOffset(days=days_elapsed)
        
    elif view_option == "Mês Atual":
        current_start = this_month_start
        
        prev_start = current_start - pd.DateOffset(months=1)
        prev_full_end = current_start - pd.DateOffset(days=1)
        prev_partial_end = min(ref_datetime - pd.DateOffset(months=1), prev_full_end)
        
        last_year_start = current_start - pd.DateOffset(years=1)
        last_year_full_end = last_year_start + pd.DateOffset(months=1) - pd.DateOffset(days=1)
        last_year_partial_end = min(ref_datetime - pd.DateOffset(years=1), last_year_full_end)
        
    else: # Ano Atual
        current_start = this_year_start
        
        prev_start = current_start - pd.DateOffset(years=1)
        prev_full_end = current_start - pd.DateOffset(days=1) 
        prev_partial_end = min(ref_datetime - pd.DateOffset(years=1), prev_full_end)
        
        last_year_start = prev_start 
        last_year_full_end = prev_full_end
        last_year_partial_end = prev_partial_end

    def fmt_date(d):
        return d.strftime('%d/%m/%Y')

    # Create descriptive labels for tooltips
    atual_label = f"{fmt_date(current_start)} a {fmt_date(ref_datetime)}"
    prev_partial_label = f"{fmt_date(prev_start)} a {fmt_date(prev_partial_end)}"
    prev_full_label = f"{fmt_date(prev_start)} a {fmt_date(prev_full_end)}"
    last_partial_label = f"{fmt_date(last_year_start)} a {fmt_date(last_year_partial_end)}"
    last_full_label = f"{fmt_date(last_year_start)} a {fmt_date(last_year_full_end)}"

    # --- 1. TOTAL SALES CALCULATIONS ---
    df_current = filter_by_date(df, current_start, ref_datetime)
    df_prev_partial = filter_by_date(df, prev_start, prev_partial_end)
    df_prev_full = filter_by_date(df, prev_start, prev_full_end)
    df_last_partial = filter_by_date(df, last_year_start, last_year_partial_end)
    df_last_full = filter_by_date(df, last_year_start, last_year_full_end)
    
    sales_current = df_current['Vendas'].sum() if not df_current.empty else 0
    sales_prev_partial = df_prev_partial['Vendas'].sum() if not df_prev_partial.empty else 0
    sales_prev_full = df_prev_full['Vendas'].sum() if not df_prev_full.empty else 0
    sales_last_partial = df_last_partial['Vendas'].sum() if not df_last_partial.empty else 0
    sales_last_full = df_last_full['Vendas'].sum() if not df_last_full.empty else 0
    
    # Delta compares apples-to-apples (Current vs Partial)
    delta_prev = f"{((sales_current - sales_prev_partial) / sales_prev_partial * 100):.1f}%" if sales_prev_partial > 0 else "N/A"
    delta_last_year = f"{((sales_current - sales_last_partial) / sales_last_partial * 100):.1f}%" if sales_last_partial > 0 else "N/A"

    # --- RENDER KPI METRICS ---
    st.markdown("##### 📅 Datas de Referência")
    st.caption(f"**Atual:** {atual_label}")
    st.divider()

    st.markdown("###### 🌐 Vendas Totais")
    col1, col2, col3 = st.columns(3)
    col1.metric(f"Total ({view_option})", format_br(sales_current), help=atual_label)
    
    # We combine the partial and full values into one string: "Partial | Full"
    col2.metric("Anterior (Parcial | Total)", f"{format_br(sales_prev_partial)} | {format_br(sales_prev_full)}", delta_prev, help=f"Parcial: {prev_partial_label} \n Total: {prev_full_label}")
    
    if view_option != "Ano Atual":
        col3.metric("Ano Passado (Parcial | Total)", f"{format_br(sales_last_partial)} | {format_br(sales_last_full)}", delta_last_year, help=f"Parcial: {last_partial_label} \n Total: {last_full_label}")

    st.write("") 
    st.divider()

    # --- 2. SPECIFIC CHANNELS CALCULATIONS ---
    st.markdown("###### 📱 Canais Específicos")
    opcoes_canais = ['Website', 'App do Filiado', 'Televendas']
    canais_selecionados = st.multiselect("Filtre os canais desejados:", options=opcoes_canais, default=opcoes_canais)
    
    canais_alvo = [c.lower() for c in canais_selecionados]
    
    def get_canais_sales(df_period):
        if df_period.empty or 'tipo_venda' not in df_period.columns or not canais_alvo:
            return 0
        mask = df_period['tipo_venda'].astype(str).str.lower().str.strip().isin(canais_alvo)
        return df_period.loc[mask, 'Vendas'].sum()

    canais_current = get_canais_sales(df_current)
    canais_prev_partial = get_canais_sales(df_prev_partial)
    canais_prev_full = get_canais_sales(df_prev_full)
    canais_last_partial = get_canais_sales(df_last_partial)
    canais_last_full = get_canais_sales(df_last_full)

    delta_canais_prev = f"{((canais_current - canais_prev_partial) / canais_prev_partial * 100):.1f}%" if canais_prev_partial > 0 else "N/A"
    delta_canais_last_year = f"{((canais_current - canais_last_partial) / canais_last_partial * 100):.1f}%" if canais_last_partial > 0 else "N/A"

    col4, col5, col6 = st.columns(3)
    col4.metric(f"Canais Selecionados", format_br(canais_current), help=atual_label)
    col5.metric("Anterior (Parcial | Total)", f"{format_br(canais_prev_partial)} | {format_br(canais_prev_full)}", delta_canais_prev, help=f"Parcial: {prev_partial_label} \n Total: {prev_full_label}")
    if view_option != "Ano Atual":
        col6.metric("Ano Passado (Parcial | Total)", f"{format_br(canais_last_partial)} | {format_br(canais_last_full)}", delta_canais_last_year, help=f"Parcial: {last_partial_label} \n Total: {last_full_label}")

    st.divider()
    
# --- COMPARATIVO GRÁFICO DIÁRIO ---
    st.subheader("Comparativo Gráfico Diário")
    
    # 1. Toggles for layout and cumulative logic
    col_chart1, col_chart2 = st.columns(2)
    chart_view = col_chart1.selectbox("Selecione os dados para o gráfico:", ["Vendas Totais", "Canais Selecionados"])
    tipo_grafico = col_chart2.radio("Visualização:", ["Diário", "Acumulado"], horizontal=True)
    
    df_c = df_current.copy()
    df_p = df_prev_full.copy()
    df_l = df_last_full.copy()
    
    if chart_view == "Canais Selecionados" and canais_alvo:
        df_c = df_c[df_c['tipo_venda'].astype(str).str.lower().str.strip().isin(canais_alvo)]
        df_p = df_p[df_p['tipo_venda'].astype(str).str.lower().str.strip().isin(canais_alvo)]
        df_l = df_l[df_l['tipo_venda'].astype(str).str.lower().str.strip().isin(canais_alvo)]
        
    df_c_grp = df_c.groupby('data_venda')['Vendas'].sum().reset_index()
    df_p_grp = df_p.groupby('data_venda')['Vendas'].sum().reset_index()
    df_l_grp = df_l.groupby('data_venda')['Vendas'].sum().reset_index()
    
    cs_dt, ps_dt, ls_dt = pd.to_datetime(current_start), pd.to_datetime(prev_start), pd.to_datetime(last_year_start)
    df_c_grp['Dia do Período'] = (df_c_grp['data_venda'] - cs_dt).dt.days + 1
    df_p_grp['Dia do Período'] = (df_p_grp['data_venda'] - ps_dt).dt.days + 1
    df_l_grp['Dia do Período'] = (df_l_grp['data_venda'] - ls_dt).dt.days + 1
    
    # Sort dates sequentially so cumulative math works correctly
    df_c_grp = df_c_grp.sort_values('Dia do Período')
    df_p_grp = df_p_grp.sort_values('Dia do Período')
    df_l_grp = df_l_grp.sort_values('Dia do Período')

    # Apply Cumulative sum if selected
    if tipo_grafico == "Acumulado":
        df_c_grp['Vendas'] = df_c_grp['Vendas'].cumsum()
        df_p_grp['Vendas'] = df_p_grp['Vendas'].cumsum()
        df_l_grp['Vendas'] = df_l_grp['Vendas'].cumsum()
    
    # Create reference dictionaries to map Day X of Previous/Last Year to Day X of Current
    ref_prev = dict(zip(df_p_grp['Dia do Período'], df_p_grp['Vendas']))
    ref_last = dict(zip(df_l_grp['Dia do Período'], df_l_grp['Vendas']))

    df_c_grp['Período'] = 'Atual'
    df_p_grp['Período'] = 'Anterior'
    df_l_grp['Período'] = 'Ano Passado'
    
    if view_option == "Ano Atual":
        dfs_to_concat = [df_c_grp, df_l_grp]
    else:
        dfs_to_concat = [df_c_grp, df_p_grp, df_l_grp]
        
    # Reset index to completely prevent Plotly hover mismatch bugs
    df_plot = pd.concat(dfs_to_concat).reset_index(drop=True)
    
    if not df_plot.empty:
        df_plot['Formatado'] = df_plot['Vendas'].apply(format_br)
        df_plot['Data_Real'] = df_plot['data_venda'].dt.strftime('%d/%m/%Y')
        
        # Bring the historical values into the current row for delta calculations
        df_plot['Val_Anterior'] = df_plot['Dia do Período'].map(ref_prev).fillna(0)
        df_plot['Val_AnoPassado'] = df_plot['Dia do Período'].map(ref_last).fillna(0)

        def get_delta_str(curr, prev):
            if prev > 0:
                delta = ((curr - prev) / prev) * 100
                sign = "+" if delta > 0 else ""
                return f"{sign}{delta:.1f}%"
            return "N/A"

        df_plot['Delta_Anterior'] = df_plot.apply(lambda r: get_delta_str(r['Vendas'], r['Val_Anterior']), axis=1)
        df_plot['Delta_AnoPassado'] = df_plot.apply(lambda r: get_delta_str(r['Vendas'], r['Val_AnoPassado']), axis=1)
        
        # Build a dynamic tooltip that ONLY shows deltas when hovering on the 'Atual' line
        def build_hover(row):
            txt = f"<b>Data real: {row['Data_Real']}</b><br>Vendas: {row['Formatado']}"
            if row['Período'] == 'Atual':
                txt += "<br>---"
                if view_option != "Ano Atual":
                    txt += f"<br>vs Anterior: <b>{row['Delta_Anterior']}</b>"
                txt += f"<br>vs Ano Passado: <b>{row['Delta_AnoPassado']}</b>"
            return txt

        df_plot['Tooltip'] = df_plot.apply(build_hover, axis=1)
        
        # Passing tooltip via hover_data forces Plotly to respect the indexing!
        fig = px.line(df_plot, x='Dia do Período', y='Vendas', color='Período', markers=True,
                      hover_data={"Tooltip": True, "Dia do Período": False, "Vendas": False, "Período": False},
                      color_discrete_map={'Atual': '#4C78A8', 'Anterior': '#F58518', 'Ano Passado': '#E45756'})
        
        fig.update_traces(hovertemplate="%{customdata[0]}<extra></extra>")
        fig.update_layout(xaxis_title=f"Dias Decorridos ({view_option})", yaxis_title=f"Volume de Vendas ({tipo_grafico})")
        st.plotly_chart(fig, width='stretch')
    else:
        st.info("Nenhum dado encontrado para gerar o gráfico.")

with tab2:
    st.header("Análise Geográfica (UF)")
    
    col1, col2 = st.columns(2)
    start_map = col1.date_input("Data de Início", value=this_month_start.date(), key="map_start")
    end_map = col2.date_input("Data de Fim", value=reference_date, key="map_end")
    
    df_map = filter_by_date(df, pd.to_datetime(start_map), pd.to_datetime(end_map))
    
    if not df_map.empty:
        df_map['uf'] = df_map['uf'].str.upper()
        uf_sales = df_map.groupby('uf')['Vendas'].sum().reset_index()
        
        if brazil_geo:
            fig_map = px.choropleth(
                uf_sales, geojson=brazil_geo, locations='uf', featureidkey='properties.sigla',
                color='Vendas', color_continuous_scale="Blues",
                title=f"Vendas por Estado ({start_map.strftime('%d/%m/%Y')} - {end_map.strftime('%d/%m/%Y')})"
            )
            fig_map.update_geos(fitbounds="locations", visible=False)
            fig_map.update_traces(customdata=[format_br(v) for v in uf_sales['Vendas']], hovertemplate="<b>%{location}</b><br>Vendas: %{customdata}<extra></extra>")
            st.plotly_chart(fig_map, width='stretch')
        else:
            st.warning("Não foi possível carregar o mapa do Brasil. Exibindo apenas o gráfico de barras.")
        
        df_sorted = uf_sales.sort_values(by='Vendas', ascending=True).copy()
        df_sorted["Vendas_Formatadas"] = df_sorted["Vendas"].apply(format_br)
        
        fig_bar_uf = px.bar(df_sorted, x='Vendas', y='uf', orientation='h', title="Ranking por UF", text="Vendas_Formatadas")
        fig_bar_uf.update_traces(textposition='auto', hovertemplate="<b>%{y}</b><br>Vendas: %{text}<extra></extra>")
        st.plotly_chart(fig_bar_uf, width='stretch')
    else:
        st.info("Nenhuma venda encontrada para o período selecionado.")

with tab3:
    st.header("Composição por Tipo de Venda")
    
    col1, col2 = st.columns(2)
    start_tipo = col1.date_input("Data de Início", value=this_month_start.date(), key="tipo_start")
    end_tipo = col2.date_input("Data de Fim", value=reference_date, key="tipo_end")
    
    df_tipo = filter_by_date(df, pd.to_datetime(start_tipo), pd.to_datetime(end_tipo))
    
    if not df_tipo.empty:
        df_tipo['tipo_venda_clean'] = df_tipo['tipo_venda'].fillna("Não Informado").astype(str).str.title()
        tipo_sales = df_tipo.groupby('tipo_venda_clean')['Vendas'].sum().reset_index()
        tipo_sales = tipo_sales.sort_values(by='Vendas', ascending=False).copy()
        tipo_sales["Vendas_Formatadas"] = tipo_sales["Vendas"].apply(format_br)
        
        fig_pie = px.pie(tipo_sales, names='tipo_venda_clean', values='Vendas', 
                         title=f"Distribuição de Vendas ({start_tipo.strftime('%d/%m/%Y')} - {end_tipo.strftime('%d/%m/%Y')})",
                         hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label', hovertemplate="<b>%{label}</b><br>Vendas: %{value}<extra></extra>")
        
        fig_bar_tipo = px.bar(tipo_sales.sort_values(by='Vendas', ascending=True), 
                              x='Vendas', y='tipo_venda_clean', orientation='h', 
                              title="Ranking por Tipo de Venda", text="Vendas_Formatadas", color_discrete_sequence=['#92C5DE'])
        fig_bar_tipo.update_traces(textposition='auto', hovertemplate="<b>%{y}</b><br>Vendas: %{text}<extra></extra>")
        
        col_chart1, col_chart2 = st.columns([1, 1])
        with col_chart1:
            st.plotly_chart(fig_pie, width='stretch')
        with col_chart2:
            st.plotly_chart(fig_bar_tipo, width='stretch')
            
    else:
        st.info("Nenhuma venda encontrada para o período selecionado.")
        
with tab4:
    st.header("Análise de Investimento")
    
    # --- GLOBAL FILTERS FOR INVESTMENTS ---
    col_filt1, col_filt2, col_filt3 = st.columns(3)
    canais_invest = col_filt1.multiselect("Canal:", ["Website", "App do Filiado"], default=["Website"])
    categorias_invest = col_filt2.multiselect("Categoria:", ["Branding", "Leads", "Venda"], default=["Branding", "Leads", "Venda"])
    
    # Add Platform Filter
    todas_plataformas = ["Google", "Meta", "TikTok", "Adsplay", "Actionpay"]
    plataformas_invest = col_filt3.multiselect("Plataforma:", todas_plataformas, default=todas_plataformas)
    
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

    # --- 1. KPI METRICS (Partial & Full Logic) ---
    st.subheader("Indicadores de Investimento")
    view_opt_inv = st.radio("Selecione o período para os KPIs:", ["Semana Atual", "Mês Atual", "Ano Atual"], horizontal=True, key="rad_inv")
    
    days_elapsed = (ref_datetime - current_start).days if 'current_start' in locals() else 0
    
    if view_opt_inv == "Semana Atual":
        inv_curr_start = this_week_start
        days_elap = (ref_datetime - inv_curr_start).days
        inv_prev_start = inv_curr_start - pd.DateOffset(weeks=1)
        inv_prev_full_end = inv_curr_start - pd.DateOffset(days=1)
        inv_prev_partial_end = inv_prev_start + pd.DateOffset(days=days_elap)
        inv_last_start = inv_curr_start - pd.DateOffset(weeks=52)
        inv_last_full_end = inv_last_start + pd.DateOffset(days=6)
        inv_last_partial_end = inv_last_start + pd.DateOffset(days=days_elap)
        
    elif view_opt_inv == "Mês Atual":
        inv_curr_start = this_month_start
        inv_prev_start = inv_curr_start - pd.DateOffset(months=1)
        inv_prev_full_end = inv_curr_start - pd.DateOffset(days=1)
        inv_prev_partial_end = min(ref_datetime - pd.DateOffset(months=1), inv_prev_full_end)
        inv_last_start = inv_curr_start - pd.DateOffset(years=1)
        inv_last_full_end = inv_last_start + pd.DateOffset(months=1) - pd.DateOffset(days=1)
        inv_last_partial_end = min(ref_datetime - pd.DateOffset(years=1), inv_last_full_end)
        
    else: # Ano Atual
        inv_curr_start = this_year_start
        inv_prev_start = inv_curr_start - pd.DateOffset(years=1)
        inv_prev_full_end = inv_curr_start - pd.DateOffset(days=1) 
        inv_prev_partial_end = min(ref_datetime - pd.DateOffset(years=1), inv_prev_full_end)
        inv_last_start = inv_prev_start 
        inv_last_full_end = inv_prev_full_end
        inv_last_partial_end = inv_prev_partial_end

    def filter_inv_date(df_i, start, end):
        mask = (df_i['data_investimento'] >= start) & (df_i['data_investimento'] <= end)
        return df_i.loc[mask]

    def calc_metrics(df_period):
        if df_period.empty:
            return 0, 0, 0
        tot_inv = df_period['Total_Investido'].sum()
        c_leads, v_leads = df_period['leads'].sum(), df_period['vol_leads'].sum()
        c_vendas, v_vendas = df_period['venda'].sum(), df_period['vol_vendas'].sum()
        
        cpl = c_leads / v_leads if v_leads > 0 else 0
        cpa = c_vendas / v_vendas if v_vendas > 0 else 0
        return tot_inv, cpl, cpa

    # Fetch metrics
    inv_curr, cpl_curr, cpa_curr = calc_metrics(filter_inv_date(df_inv_filt, inv_curr_start, ref_datetime))
    inv_prev_part, cpl_prev_part, cpa_prev_part = calc_metrics(filter_inv_date(df_inv_filt, inv_prev_start, inv_prev_partial_end))
    inv_prev_full, cpl_prev_full, cpa_prev_full = calc_metrics(filter_inv_date(df_inv_filt, inv_prev_start, inv_prev_full_end))
    inv_last_part, cpl_last_part, cpa_last_part = calc_metrics(filter_inv_date(df_inv_filt, inv_last_start, inv_last_partial_end))
    inv_last_full, cpl_last_full, cpa_last_full = calc_metrics(filter_inv_date(df_inv_filt, inv_last_start, inv_last_full_end))

    def get_delta(curr, prev):
        return f"{((curr - prev) / prev * 100):.1f}%" if prev > 0 else "N/A"

    # Deltas
    d_inv_prev, d_inv_last = get_delta(inv_curr, inv_prev_part), get_delta(inv_curr, inv_last_part)
    d_cpl_prev, d_cpl_last = get_delta(cpl_curr, cpl_prev_part), get_delta(cpl_curr, cpl_last_part)
    d_cpa_prev, d_cpa_last = get_delta(cpa_curr, cpa_prev_part), get_delta(cpa_curr, cpa_last_part)

    def fmt_d(d): return d.strftime('%d/%m/%Y')
    lbl_curr = f"{fmt_d(inv_curr_start)} a {fmt_d(ref_datetime)}"
    lbl_prev_p = f"{fmt_d(inv_prev_start)} a {fmt_d(inv_prev_partial_end)}"
    lbl_prev_f = f"{fmt_d(inv_prev_start)} a {fmt_d(inv_prev_full_end)}"
    lbl_last_p = f"{fmt_d(inv_last_start)} a {fmt_d(inv_last_partial_end)}"
    lbl_last_f = f"{fmt_d(inv_last_start)} a {fmt_d(inv_last_full_end)}"

    def safe_str(v1, v2): return f"{format_money(v1)} | {format_money(v2)}".replace("$", "\$")

    # Render Total Investido
    st.markdown("###### 💸 Gastos Totais")
    col_i1, col_i2, col_i3 = st.columns(3)
    col_i1.metric(f"Total Investido ({view_opt_inv})", format_money(inv_curr), help=lbl_curr)
    col_i2.metric("Anterior (Parcial | Total)", safe_str(inv_prev_part, inv_prev_full), d_inv_prev, help=f"Parcial: {lbl_prev_p}\n\nTotal: {lbl_prev_f}")
    if view_opt_inv != "Ano Atual":
        col_i3.metric("Ano Passado (Parcial | Total)", safe_str(inv_last_part, inv_last_full), d_inv_last, help=f"Parcial: {lbl_last_p}\n\nTotal: {lbl_last_f}")

    st.write("")
    
    # Render CPL
    st.markdown("###### 🎯 CPL (Custo por Lead)")
    col_l1, col_l2, col_l3 = st.columns(3)
    col_l1.metric(f"CPL Atual", format_money(cpl_curr), d_cpl_prev, delta_color="inverse", help=lbl_curr)
    col_l2.metric("Anterior (Parcial | Total)", safe_str(cpl_prev_part, cpl_prev_full), d_cpl_prev, delta_color="inverse", help=f"Parcial: {lbl_prev_p}\n\nTotal: {lbl_prev_f}")
    if view_opt_inv != "Ano Atual":
        col_l3.metric("Ano Passado (Parcial | Total)", safe_str(cpl_last_part, cpl_last_full), d_cpl_last, delta_color="inverse", help=f"Parcial: {lbl_last_p}\n\nTotal: {lbl_last_f}")

    st.write("")

    # Render CPA
    st.markdown("###### 🛒 CPA (Custo por Venda)")
    col_v1, col_v2, col_v3 = st.columns(3)
    col_v1.metric(f"CPA Atual", format_money(cpa_curr), d_cpa_prev, delta_color="inverse", help=lbl_curr)
    col_v2.metric("Anterior (Parcial | Total)", safe_str(cpa_prev_part, cpa_prev_full), d_cpa_prev, delta_color="inverse", help=f"Parcial: {lbl_prev_p}\n\nTotal: {lbl_prev_f}")
    if view_opt_inv != "Ano Atual":
        col_v3.metric("Ano Passado (Parcial | Total)", safe_str(cpa_last_part, cpa_last_full), d_cpa_last, delta_color="inverse", help=f"Parcial: {lbl_last_p}\n\nTotal: {lbl_last_f}")

    st.divider()

    # --- 2. CHARTS (DYNAMIC Y-AXIS) ---
    st.subheader("Análise Gráfica")
    
    col_date1, col_date2, col_metric = st.columns([1, 1, 2])
    start_date_inv = col_date1.date_input("Data de Início", value=this_month_start.date(), key="inv_start")
    end_date_inv = col_date2.date_input("Data de Fim", value=reference_date, key="inv_end")
    grafico_metrica = col_metric.selectbox("Selecione a métrica para o gráfico:", 
                                           ["Total Investido", "CPL", "CPA", "Leads (Volume)", "Vendas (Volume)"])

    df_graficos_inv = filter_inv_date(df_inv_filt, pd.to_datetime(start_date_inv), pd.to_datetime(end_date_inv))

    st.markdown(f"###### Evolução de {grafico_metrica} ({start_date_inv.strftime('%d/%m/%Y')} a {end_date_inv.strftime('%d/%m/%Y')})")

    if not df_graficos_inv.empty:
        # Aggregate daily data
        df_line_grp = df_graficos_inv.groupby('data_investimento')[['Total_Investido', 'leads', 'vol_leads', 'venda', 'vol_vendas']].sum().reset_index()
        
        # Calculate dynamic Y and formatting based on selection
        if grafico_metrica == "Total Investido":
            df_line_grp['Y'] = df_line_grp['Total_Investido']
            df_line_grp['Formatado'] = df_line_grp['Y'].apply(format_money)
            hover_template = "<b>%{x|%d/%m/%Y}</b><br>Investimento: %{customdata[0]}<extra></extra>"
        
        elif grafico_metrica == "CPL":
            df_line_grp['Y'] = df_line_grp.apply(lambda r: r['leads'] / r['vol_leads'] if r['vol_leads'] > 0 else 0, axis=1)
            df_line_grp['Formatado'] = df_line_grp['Y'].apply(format_money)
            hover_template = "<b>%{x|%d/%m/%Y}</b><br>CPL Diário: %{customdata[0]}<extra></extra>"
        
        elif grafico_metrica == "CPA":
            df_line_grp['Y'] = df_line_grp.apply(lambda r: r['venda'] / r['vol_vendas'] if r['vol_vendas'] > 0 else 0, axis=1)
            df_line_grp['Formatado'] = df_line_grp['Y'].apply(format_money)
            hover_template = "<b>%{x|%d/%m/%Y}</b><br>CPA Diário: %{customdata[0]}<extra></extra>"
            
        elif grafico_metrica == "Leads (Volume)":
            df_line_grp['Y'] = df_line_grp['vol_leads']
            df_line_grp['Formatado'] = df_line_grp['Y'].apply(format_br)
            hover_template = "<b>%{x|%d/%m/%Y}</b><br>Volume de Leads: %{customdata[0]}<extra></extra>"
            
        elif grafico_metrica == "Vendas (Volume)":
            df_line_grp['Y'] = df_line_grp['vol_vendas']
            df_line_grp['Formatado'] = df_line_grp['Y'].apply(format_br)
            hover_template = "<b>%{x|%d/%m/%Y}</b><br>Volume de Vendas: %{customdata[0]}<extra></extra>"

        # Draw the dynamic line chart
        fig_line = px.line(df_line_grp, x='data_investimento', y='Y', 
                           markers=True, color_discrete_sequence=['#4C78A8'])
        
        fig_line.update_traces(hovertemplate=hover_template, customdata=df_line_grp[['Formatado']])
        fig_line.update_layout(yaxis_title=grafico_metrica)
        st.plotly_chart(fig_line, width='stretch')

        st.write("")
        
        # Pie Chart
        st.markdown(f"###### Composição do Investimento ({start_date_inv.strftime('%d/%m/%Y')} a {end_date_inv.strftime('%d/%m/%Y')})")
        if cat_cols:
            pie_data = []
            for cat in cat_cols:
                val = df_graficos_inv[cat].sum()
                if val > 0:
                    pie_data.append({"Categoria": cat.title(), "Valor": val})
            
            if pie_data:
                df_pie_plot = pd.DataFrame(pie_data)
                df_pie_plot["Formatado"] = df_pie_plot["Valor"].apply(format_money)
                
                fig_pie_inv = px.pie(df_pie_plot, names='Categoria', values='Valor', hole=0.4,
                                     color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_pie_inv.update_traces(textposition='inside', textinfo='percent+label',
                                          hovertemplate="<b>%{label}</b><br>Valor: %{customdata[0]}<extra></extra>",
                                          customdata=df_pie_plot[['Formatado']])
                st.plotly_chart(fig_pie_inv, width='stretch')
            else:
                st.info("Investimento zerado nas categorias selecionadas para este período.")
    else:
        st.info("Nenhum dado encontrado para o período selecionado.")