import mysql.connector
conn = mysql.connector.connect(host="mysql-bi-g.cyrjbg1j8gup.us-east-1.rds.amazonaws.com", user="alex.metzen", password="?34TcU_7U9Hq")
print(conn.is_connected())
conn.close()