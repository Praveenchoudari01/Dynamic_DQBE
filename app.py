from flask import Flask, render_template, request, redirect
from sqlalchemy import create_engine, inspect, MetaData, Table, text

app = Flask(__name__)
join_graph = {}
schema_info = {}

def build_join_graph_and_schema(database):
    username = 'root'
    password = '1619'
    host = 'localhost'
    port = 3306

    engine = create_engine(f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}")
    metadata = MetaData()
    metadata.reflect(bind=engine)
    inspector = inspect(engine)
    
    all_tables = {
        table_name: Table(table_name, metadata, autoload_with=engine)
        for table_name in inspector.get_table_names()
    }

    join_graph_json = {}
    schema_json = {}

    with engine.connect() as conn:
        for table_name, table_obj in all_tables.items():
            try:
                # ✅ Execute raw SQL using `text`
                result = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`"))
                row_count = result.scalar()

                if row_count == 0:
                    continue  # Skip empty tables

                # ✅ Build schema info (columns)
                schema_json[table_name] = {
                    "columns": [col["name"] for col in inspector.get_columns(table_name)]
                }

                # ✅ Build join graph
                join_graph_json[table_name] = {}
                fks = inspector.get_foreign_keys(table_name)
                for fk in fks:
                    referred_table = fk["referred_table"]
                    from_col = fk["constrained_columns"][0]
                    to_col = fk["referred_columns"][0]

                    # Forward join
                    join_graph_json[table_name][referred_table] = f"{table_name}.{from_col} = {referred_table}.{to_col}"

                    # Reverse join
                    if referred_table not in join_graph_json:
                        join_graph_json[referred_table] = {}
                    if table_name not in join_graph_json[referred_table]:
                        join_graph_json[referred_table][table_name] = f"{referred_table}.{to_col} = {table_name}.{from_col}"
            except Exception as e:
                print(f"Skipping table `{table_name}` due to error: {e}")

    return join_graph_json, schema_json


@app.route("/", methods=["GET", "POST"])
def select_database():
    username = 'root'
    password = '1619'
    host = 'localhost'
    port = 3306

    engine = create_engine(f"mysql+pymysql://{username}:{password}@{host}:{port}")

    with engine.connect() as conn:
        result = conn.execute(text("SHOW DATABASES"))
        databases = [row[0] for row in result.fetchall()]

    if request.method == "POST":
        dbname = request.form.get("database")
        global join_graph, schema_info
        join_graph, schema_info = build_join_graph_and_schema(dbname)
        return redirect("/select")

    return render_template("db_input.html", databases=databases)


@app.route("/select", methods=["GET"])
def select():
    if not schema_info:
        return redirect("/")
    return render_template("column_selector.html", schema=schema_info)


@app.route("/submit", methods=["POST"])
def submit():
    selected_columns = request.form.getlist("columns")
    selected_tables = list(set(col.split('.')[0] for col in selected_columns))
    return render_template("results.html", tables=selected_tables, columns=selected_columns)


if __name__ == "__main__":
    app.run(debug=True)
