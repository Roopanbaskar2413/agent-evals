.PHONY: demo report

demo:
	.venv/bin/python -m src.make_db
	.venv/bin/python -m src.make_questions
	.venv/bin/python -m src.baseline_sql

report:
	.venv/bin/python -m src.report
