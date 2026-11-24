from pathlib import Path
from app.db import get_conn


def main():
    schema_path = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.execute(sql)
    print("Schema applied.")


if __name__ == "__main__":
    main()