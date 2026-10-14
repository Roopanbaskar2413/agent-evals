import random
import sqlite3
from pathlib import Path

DB_PATH = Path("data/shop.db")
CITIES = ["Chennai", "Mumbai", "Delhi", "Pune", "Kochi"]
CATEGORIES = ["books", "toys", "gadgets", "clothing"]
STATUSES = ["delivered", "delivered", "delivered", "cancelled", "pending"]


def build() -> None:
    random.seed(42)
    DB_PATH.parent.mkdir(exist_ok=True)
    DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY, customer_id INTEGER, category TEXT,
            amount REAL, status TEXT, order_date TEXT
        );
        """
    )
    for i in range(1, 41):
        con.execute(
            "INSERT INTO customers VALUES (?, ?, ?)",
            (i, f"Customer {i}", random.choice(CITIES)),
        )
    for i in range(1, 301):
        date = f"2026-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
        con.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
            (
                i,
                random.randint(1, 40),
                random.choice(CATEGORIES),
                round(random.uniform(5, 500), 2),
                random.choice(STATUSES),
                date,
            ),
        )
    con.commit()
    con.close()


if __name__ == "__main__":
    build()
    print(f"Built {DB_PATH}")