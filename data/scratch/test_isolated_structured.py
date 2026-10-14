import ollama
from pydantic import BaseModel

MODEL = "llama3.2"


class Answer(BaseModel):
    number: float


CASES = [
    (2, "What is the total amount of delivered orders?", "[(39064.32,)]"),
    (3, "What is the average amount of cancelled orders?", "[(291.521724137931,)]"),
    (20, "What is the total amount of orders placed by customers in Chennai?", "[(20232.22,)]"),
    (21, "What is the total amount of orders placed by customers in Mumbai?", "[(21055.43,)]"),
    (22, "What is the total amount of orders placed by customers in Delhi?", "[(9772.15,)]"),
    (23, "What is the total amount of orders placed by customers in Pune?", "[(9913.59,)]"),
    (24, "What is the total amount of orders placed by customers in Kochi?", "[(15603.82,)]"),
]

for qid, question, query_result in CASES:
    content = f"{question}\nQuery result: {query_result}"
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": content}],
        format=Answer.model_json_schema(),
        options={"temperature": 0},
    )
    answer = Answer.model_validate_json(response["message"]["content"])
    query_value = float(query_result.strip("[](),"))
    print(f"id={qid:>2}  query_value={query_value}  returned_number={answer.number}")
