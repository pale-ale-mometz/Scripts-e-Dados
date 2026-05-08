import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import json
import urllib.request
import ssl

# 1. Configure the page (This must always be the very first Streamlit command)
st.set_page_config(page_title="MySQL Dashboard", page_icon="📊", layout="wide")

# --- AUTHENTICATION SECTION ---
def check_password():
    """Returns `True` if the user has the correct password."""
    
    # Check if the user is already authenticated in this session
    if st.session_state.get("password_correct", False):
        return True

    # If not, show the login screen
    st.title("🔒 Dashboard Login")
    password = st.text_input("Please enter the password:", type="password")

    if password:
        # Check against the password stored in secrets.toml
        if password == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            st.rerun() # Refresh the page to clear the login screen
        else:
            st.error("😕 Password incorrect. Please try again.")
            
    return False

# Stop the script here if the password hasn't been entered correctly
if not check_password():
    st.stop()

# --- MAIN DASHBOARD SECTION ---
st.title("📊 Vendas Dashboard")

st.info("Passo 1: Autenticado com sucesso. Tentando conectar ao banco de dados...")

# Initialize the database connection
try:
    conn = st.connection("mysql", type="sql")
    test_df = conn.query("SELECT 1")
except Exception as e:
    st.error(f"Falha na conexão: {e}")
    st.stop()

# 1. Load the Data safely with Cache
@st.cache_data(ttl=600)
def load_data():
    start_of_last_year = datetime.date.today().replace(year=datetime.date.today().year - 1, month=1, day=1)
    
    # We ask AWS to count the distinct CPFs for us and just return the daily totals!
    query = f"""
    SELECT 
        DATE(DT_FILIACAO) as data_venda, 
        uf, 
        tipo_venda, 
        COUNT(DISTINCT cpf) as Vendas
    FROM NOMINAL_VENDAS 
    WHERE DT_FILIACAO >= '{start_of_last_year}'
    GROUP BY DATE(DT_FILIACAO), uf, tipo_venda
    """
    
    df = conn.query(query)
    df['data_venda'] = pd.to_datetime(df['data_venda'])
    return df

df = load_data()

# 2. Time Logic (D-1 constraint)
reference_date = datetime.date.today() - datetime.timedelta(days=1)
ref_datetime = pd.to_datetime(reference_date)

this_week_start = ref_datetime - pd.to_timedelta(ref_datetime.weekday(), unit='D')
this_month_start = ref_datetime.replace(day=1)
this_year_start = ref_datetime.replace(month=1, day=1)

def filter_by_date(dataframe, start_date, end_date):
    mask = (dataframe['data_venda'] >= start_date) & (dataframe['data_venda'] <= end_date)
    return dataframe.loc[mask]

# --- UI: TABS FOR ORGANIZATION ---
tab1, tab2, tab3 = st.tabs(["📈 Desempenho de Vendas (KPIs)", "🗺️ Mapa Regional (UF)", "🛒 Tipo de Venda"])

def format_br(num):
    return f"{int(num):,}".replace(",", ".")

with tab1:
    st.header("Visão de Vendas")
    
    view_option = st.radio("Selecione o período:", ["Semana Atual", "Mês Atual", "Ano Atual"], horizontal=True)
    
    if view_option == "Semana Atual":
        current_start = this_week_start
        prev_start = current_start - pd.DateOffset(weeks=1)
        prev_end = current_start - pd.DateOffset(days=1)
        last_year_start = current_start - pd.DateOffset(weeks=52)
        last_year_end = last_year_start + pd.DateOffset(days=6)
        
    elif view_option == "Mês Atual":
        current_start = this_month_start
        prev_start = current_start - pd.DateOffset(months=1)
        prev_end = current_start - pd.DateOffset(days=1)
        last_year_start = current_start - pd.DateOffset(years=1)
        last_year_end = ref_datetime - pd.DateOffset(years=1)
        
    else: # Ano Atual
        current_start = this_year_start
        prev_start = current_start - pd.DateOffset(years=1)
        prev_end = ref_datetime - pd.DateOffset(years=1)
        last_year_start = prev_start 
        last_year_end = prev_end

    def fmt_date(d):
        return d.strftime('%d/%m/%Y')

    atual_label = f"{fmt_date(current_start)} a {fmt_date(ref_datetime)}"
    prev_label = f"{fmt_date(prev_start)} a {fmt_date(prev_end)}"
    last_year_label = f"{fmt_date(last_year_start)} a {fmt_date(last_year_end)}"

    # 1. Total Sales Calculations (Using SUM instead of LEN)
    df_current = filter_by_date(df, current_start, ref_datetime)
    df_prev = filter_by_date(df, prev_start, prev_end)
    df_last_year = filter_by_date(df, last_year_start, last_year_end)
    
    sales_current = df_current['Vendas'].sum() if not df_current.empty else 0
    sales_prev = df_prev['Vendas'].sum() if not df_prev.empty else 0
    sales_last_year = df_last_year['Vendas'].sum() if not df_last_year.empty else 0
    
    delta_prev = f"{((sales_current - sales_prev) / sales_prev * 100):.1f}%" if sales_prev > 0 else "N/A"
    delta_last_year = f"{((sales_current - sales_last_year) / sales_last_year * 100):.1f}%" if sales_last_year > 0 else "N/A"

    # --- RENDER KPI METRICS ---
    st.markdown("##### 📅 Datas de Referência")
    if view_option != "Ano Atual":
        st.caption(f"**Atual:** {atual_label} &nbsp; | &nbsp; **Anterior:** {prev_label} &nbsp; | &nbsp; **Ano Passado:** {last_year_label}")
    else:
        st.caption(f"**Atual:** {atual_label} &nbsp; | &nbsp; **Ano Passado:** {last_year_label}")
    st.divider()

    st.markdown("###### 🌐 Vendas Totais")
    col1, col2, col3 = st.columns(3)
    col1.metric(f"Total ({view_option})", format_br(sales_current), help=atual_label)
    col2.metric("vs Período Anterior", format_br(sales_prev), delta_prev, help=prev_label)
    if view_option != "Ano Atual":
        col3.metric("vs Mesmo Período Ano Passado", format_br(sales_last_year), delta_last_year, help=last_year_label)

    st.write("") 
    st.divider()

    st.markdown("###### 📱 Canais Específicos")
    
    opcoes_canais = ['Website', 'App do Filiado', 'Televendas']
    canais_selecionados = st.multiselect(
        "Filtre os canais desejados:",
        options=opcoes_canais,
        default=opcoes_canais 
    )
    
    canais_alvo = [c.lower() for c in canais_selecionados]
    
    # 2. Specific Channel Calculations (Using SUM instead of LEN)
    def get_canais_sales(df_period):
        if df_period.empty or 'tipo_venda' not in df_period.columns or not canais_alvo:
            return 0
        mask = df_period['tipo_venda'].astype(str).str.lower().str.strip().isin(canais_alvo)
        return df_period.loc[mask, 'Vendas'].sum()

    canais_current = get_canais_sales(df_current)
    canais_prev = get_canais_sales(df_prev)
    canais_last_year = get_canais_sales(df_last_year)

    delta_canais_prev = f"{((canais_current - canais_prev) / canais_prev * 100):.1f}%" if canais_prev > 0 else "N/A"
    delta_canais_last_year = f"{((canais_current - canais_last_year) / canais_last_year * 100):.1f}%" if canais_last_year > 0 else "N/A"

    col4, col5, col6 = st.columns(3)
    col4.metric(f"Canais Selecionados", format_br(canais_current), help=atual_label)
    col5.metric("vs Período Anterior", format_br(canais_prev), delta_canais_prev, help=prev_label)
    if view_option != "Ano Atual":
        col6.metric("vs Mesmo Período Ano Passado", format_br(canais_last_year), delta_canais_last_year, help=last_year_label)

    st.divider()

    st.subheader("Comparativo Gráfico")
    
    chart_view = st.radio("Selecione os dados para o gráfico:", ["Vendas Totais", "Canais Selecionados"], horizontal=True)
    
    if chart_view == "Vendas Totais":
        v_curr, v_prev, v_last = sales_current, sales_prev, sales_last_year
    else:
        v_curr, v_prev, v_last = canais_current, canais_prev, canais_last_year

    chart_data = pd.DataFrame({
        "Período": ["Atual", "Anterior", "Ano Passado"] if view_option != "Ano Atual" else ["Atual", "Ano Passado"],
        "Vendas": [v_curr, v_prev, v_last] if view_option != "Ano Atual" else [v_curr, v_prev],
        "Intervalo de Datas": [atual_label, prev_label, last_year_label] if view_option != "Ano Atual" else [atual_label, last_year_label]
    })
    
    chart_data["Vendas_Formatadas"] = chart_data["Vendas"].apply(format_br)
    
    fig = px.bar(chart_data, x="Período", y="Vendas", color="Período", text="Vendas_Formatadas",
                 hover_data={"Intervalo de Datas": True, "Período": False, "Vendas": False, "Vendas_Formatadas": False},
                 color_discrete_sequence=px.colors.qualitative.Pastel)
    
    fig.update_traces(
        textposition='auto',
        hovertemplate="<b>%{x}</b><br>Vendas: %{text}<br>Período: %{customdata[0]}<extra></extra>"
    )
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.header("Análise Geográfica (UF)")
    
    col1, col2 = st.columns(2)
    start_map = col1.date_input("Data de Início", value=this_month_start.date(), key="map_start")
    end_map = col2.date_input("Data de Fim", value=reference_date, key="map_end")
    
    df_map = filter_by_date(df, pd.to_datetime(start_map), pd.to_datetime(end_map))
    
    if not df_map.empty:
        df_map['uf'] = df_map['uf'].str.upper()
        # Group by UF and SUM the vendas instead of counting rows
        uf_sales = df_map.groupby('uf')['Vendas'].sum().reset_index()
        
        if brazil_geo:
            fig_map = px.choropleth(
                uf_sales,
                geojson=brazil_geo,
                locations='uf', 
                featureidkey='properties.sigla',
                color='Vendas',
                color_continuous_scale="Blues",
                title=f"Vendas por Estado ({start_map.strftime('%d/%m/%Y')} - {end_map.strftime('%d/%m/%Y')})"
            )
            fig_map.update_geos(fitbounds="locations", visible=False)
            fig_map.update_traces(
                customdata=[format_br(v) for v in uf_sales['Vendas']],
                hovertemplate="<b>%{location}</b><br>Vendas: %{customdata}<extra></extra>"
            )
            st.plotly_chart(fig_map, use_container_width=True)
        else:
            st.warning("Não foi possível carregar o mapa do Brasil. Exibindo apenas o gráfico de barras.")
        
        df_sorted = uf_sales.sort_values(by='Vendas', ascending=True).copy()
        df_sorted["Vendas_Formatadas"] = df_sorted["Vendas"].apply(format_br)
        
        fig_bar_uf = px.bar(df_sorted, x='Vendas', y='uf', orientation='h', 
                            title="Ranking por UF", text="Vendas_Formatadas")
        
        fig_bar_uf.update_traces(
            textposition='auto',
            hovertemplate="<b>%{y}</b><br>Vendas: %{text}<extra></extra>"
        )
        st.plotly_chart(fig_bar_uf, use_container_width=True)
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
        
        # Group by tipo_venda and SUM the vendas instead of counting rows
        tipo_sales = df_tipo.groupby('tipo_venda_clean')['Vendas'].sum().reset_index()
        tipo_sales = tipo_sales.sort_values(by='Vendas', ascending=False).copy()
        tipo_sales["Vendas_Formatadas"] = tipo_sales["Vendas"].apply(format_br)
        
        fig_pie = px.pie(tipo_sales, names='tipo_venda_clean', values='Vendas', 
                         title=f"Distribuição de Vendas ({start_tipo.strftime('%d/%m/%Y')} - {end_tipo.strftime('%d/%m/%Y')})",
                         hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
        
        fig_pie.update_traces(textposition='inside', textinfo='percent+label',
                              hovertemplate="<b>%{label}</b><br>Vendas: %{value}<extra></extra>")
        
        fig_bar_tipo = px.bar(tipo_sales.sort_values(by='Vendas', ascending=True), 
                              x='Vendas', y='tipo_venda_clean', orientation='h', 
                              title="Ranking por Tipo de Venda", text="Vendas_Formatadas",
                              color_discrete_sequence=['#92C5DE'])
        
        fig_bar_tipo.update_traces(textposition='auto',
                                   hovertemplate="<b>%{y}</b><br>Vendas: %{text}<extra></extra>")
        
        col_chart1, col_chart2 = st.columns([1, 1])
        with col_chart1:
            st.plotly_chart(fig_pie, use_container_width=True)
        with col_chart2:
            st.plotly_chart(fig_bar_tipo, use_container_width=True)
            
    else:
        st.info("Nenhuma venda encontrada para o período selecionado.")