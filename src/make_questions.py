import json
import sqlite3
from src.make_db import DB_PATH, CITIES, CATEGORIES

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def one(con, sql, params=()):
    value = con.execute(sql, params).fetchone()[0]
    return round(value, 2) if isinstance(value, float) else value


def build_questions():
    con = sqlite3.connect(DB_PATH)
    items = []

    def add(question, sql, params, difficulty):
        items.append({
            "id": len(items) + 1,
            "question": question,
            "expected": one(con, sql, params),
            "difficulty": difficulty,
        })

    add("How many orders are there in total?",
        "SELECT COUNT(*) FROM orders", (), "easy")
    add("What is the total amount of delivered orders?",
        "SELECT SUM(amount) FROM orders WHERE status = 'delivered'", (), "easy")
    add("What is the average amount of cancelled orders?",
        "SELECT AVG(amount) FROM orders WHERE status = 'cancelled'", (), "easy")

    for cat in CATEGORIES:
        add(f"How many orders are in the {cat} category?",
            "SELECT COUNT(*) FROM orders WHERE category = ?", (cat,), "easy")

    for city in CITIES:
        add(f"How many customers live in {city}?",
            "SELECT COUNT(*) FROM customers WHERE city = ?", (city,), "easy")

    for n in (3, 12, 27):
        add(f"How many orders did Customer {n} place?",
            "SELECT COUNT(*) FROM orders WHERE customer_id = ?", (n,), "easy")

    for month in (1, 4, 8, 11):
        add(f"How many orders were placed in {MONTHS[month - 1]}?",
            "SELECT COUNT(*) FROM orders WHERE order_date LIKE ?",
            (f"2026-{month:02d}-%",), "medium")

    for city in CITIES:
        add(f"What is the total amount of orders placed by customers in {city}?",
            "SELECT SUM(o.amount) FROM orders o JOIN customers c "
            "ON o.customer_id = c.id WHERE c.city = ?", (city,), "medium")

    for city, cat in [("Chennai", "books"), ("Delhi", "gadgets"), ("Pune", "toys")]:
        add(f"How many delivered {cat} orders were placed by customers in {city}?",
            "SELECT COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id "
            "WHERE c.city = ? AND o.category = ? AND o.status = 'delivered'",
            (city, cat), "hard")

    for cat in CATEGORIES:
        add(f"What is the average amount of delivered {cat} orders?",
            "SELECT AVG(amount) FROM orders WHERE category = ? AND status = 'delivered'",
            (cat,), "hard")

    con.close()
    return items


if __name__ == "__main__":
    questions = build_questions()
    with open("data/questions.jsonl", "w") as f:
        for q in questions:
            f.write(json.dumps(q) + "\n")
    print(f"Wrote {len(questions)} questions")
    for level in ("easy", "medium", "hard"):
        print(level, sum(q["difficulty"] == level for q in questions))