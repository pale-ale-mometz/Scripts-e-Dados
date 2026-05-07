import streamlit as st
import pandas as pd

# 1. Configure the page
st.set_page_config(page_title="MySQL Dashboard", page_icon="📊", layout="wide")
st.title("📊 My Data Dashboard")

# 2. Initialize the database connection
# The "mysql" string matches the [connections.mysql] header in secrets.toml
try:
    conn = st.connection("mysql", type="sql")
    st.success("Successfully connected to the MySQL database!", icon="✅")
except Exception as e:
    st.error(f"Failed to connect to the database: {e}")
    st.stop() # Stops the script from running further if the connection fails

# 3. Query the data safely
# We wrap the query in a function to take advantage of caching. 
# ttl=600 means Streamlit will cache the results for 10 minutes.
@st.cache_data(ttl=600) 
def load_data(query):
    # conn.query returns a pandas DataFrame directly
    return conn.query(query)

# 4. Fetch your tables (Replace this with your actual SQL query)
sql_query = "SELECT * FROM NOMINAL_VENDAS LIMIT 100;"
df = load_data(sql_query)

# 5. Build the dashboard interface
st.header("Raw Data Explorer")

# Add a filter as an example
if not df.empty:
    columns = df.columns.tolist()
    selected_col = st.selectbox("Select a column to filter by:", columns)
    
    # Display the dataframe
    st.dataframe(df, use_container_width=True)
    
    # Example of a quick bar chart (requires numeric data)
    # st.bar_chart(df, x="SomeCategoryColumn", y="SomeNumericColumn")
else:
    st.warning("The query returned no results.")