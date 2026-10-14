import json
import sqlite3
from src.make_db import DB_PATH, CITIES, CATEGORIES

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# Dev set (make_questions.py) already used: customer ids 3, 12, 27;
# months 1, 4, 8, 11; all 5 cities; all 4 categories; hard-tier (city,
# category) pairs (Chennai,books), (Delhi,gadgets), (Pune,toys), always
# with status='delivered'. Every held-out question below uses a parameter
# value, or a value+status combination, never used in the dev set.
# city-by-customers (easy) has no second dimension in the customers table
# (id, name, city only) and every city is already used in the dev set, so
# it has no valid held-out variant and is deliberately not replicated here.

HELDOUT_CUSTOMER_IDS = [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16]
HELDOUT_MONTHS = [2, 3, 5, 6, 7, 9, 10, 12]
HARD_CITY_CATEGORY_DELIVERED = [
    ("Mumbai", "clothing"), ("Kochi", "books"), ("Chennai", "toys"),
    ("Delhi", "clothing"), ("Pune", "gadgets"),
]
HARD_CITY_CATEGORY_PENDING = [
    ("Mumbai", "books"), ("Kochi", "toys"), ("Chennai", "clothing"), ("Delhi", "books"),
]


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

    # --- easy ---
    for n in HELDOUT_CUSTOMER_IDS:
        add(f"How many orders did Customer {n} place?",
            "SELECT COUNT(*) FROM orders WHERE customer_id = ?", (n,), "easy")

    for cat in CATEGORIES:
        add(f"How many delivered {cat} orders are there?",
            "SELECT COUNT(*) FROM orders WHERE category = ? AND status = 'delivered'",
            (cat,), "easy")
    for cat in CATEGORIES:
        add(f"How many pending {cat} orders are there?",
            "SELECT COUNT(*) FROM orders WHERE category = ? AND status = 'pending'",
            (cat,), "easy")

    add("What is the average amount of delivered orders?",
        "SELECT AVG(amount) FROM orders WHERE status = 'delivered'", (), "easy")
    add("What is the total amount of pending orders?",
        "SELECT SUM(amount) FROM orders WHERE status = 'pending'", (), "easy")
    add("What is the average amount of pending orders?",
        "SELECT AVG(amount) FROM orders WHERE status = 'pending'", (), "easy")
    add("How many pending orders are there in total?",
        "SELECT COUNT(*) FROM orders WHERE status = 'pending'", (), "easy")

    # --- medium ---
    for month in HELDOUT_MONTHS:
        add(f"How many orders were placed in {MONTHS[month - 1]}?",
            "SELECT COUNT(*) FROM orders WHERE order_date LIKE ?",
            (f"2026-{month:02d}-%",), "medium")
    for month in HELDOUT_MONTHS:
        add(f"What is the total amount of orders placed in {MONTHS[month - 1]}?",
            "SELECT SUM(amount) FROM orders WHERE order_date LIKE ?",
            (f"2026-{month:02d}-%",), "medium")

    # --- hard ---
    for city in CITIES:
        add(f"How many pending orders were placed by customers in {city}?",
            "SELECT COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id "
            "WHERE c.city = ? AND o.status = 'pending'", (city,), "hard")

    for city, cat in HARD_CITY_CATEGORY_DELIVERED:
        add(f"How many delivered {cat} orders were placed by customers in {city}?",
            "SELECT COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id "
            "WHERE c.city = ? AND o.category = ? AND o.status = 'delivered'",
            (city, cat), "hard")

    for city, cat in HARD_CITY_CATEGORY_PENDING:
        add(f"How many pending {cat} orders were placed by customers in {city}?",
            "SELECT COUNT(*) FROM orders o JOIN customers c ON o.customer_id = c.id "
            "WHERE c.city = ? AND o.category = ? AND o.status = 'pending'",
            (city, cat), "hard")

    for cat in CATEGORIES:
        add(f"What is the average amount of pending {cat} orders?",
            "SELECT AVG(amount) FROM orders WHERE category = ? AND status = 'pending'",
            (cat,), "hard")

    con.close()
    return items


if __name__ == "__main__":
    questions = build_questions()
    with open("data/questions_heldout.jsonl", "w") as f:
        for q in questions:
            f.write(json.dumps(q) + "\n")
    print(f"Wrote {len(questions)} held-out questions")
    for level in ("easy", "medium", "hard"):
        print(level, sum(q["difficulty"] == level for q in questions))
