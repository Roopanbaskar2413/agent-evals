import sqlite3

DB_URI = "file:data/shop.db?mode=ro"

SCHEMA = """Tables:
customers(id INTEGER, name TEXT, city TEXT)
orders(id INTEGER, customer_id INTEGER, category TEXT, amount REAL, status TEXT, order_date TEXT)
Notes: status is one of delivered, cancelled, pending. order_date is YYYY-MM-DD text.
orders.customer_id = customers.id. Customer names look like 'Customer 12' where 12 is the id."""


def run_query(sql: str, limit: int = 20):
    if not sql.strip().lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed")
    con = sqlite3.connect(DB_URI, uri=True)
    try:
        return con.execute(sql).fetchmany(limit)
    finally:
        con.close()