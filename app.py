from flask import Flask, render_template, request, redirect
from sqlalchemy import create_engine, inspect, MetaData, Table
import json

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

    for table in all_tables:
        join_graph_json[table] = {}
        schema_json[table] = {
            "columns": [col["name"] for col in inspector.get_columns(table)]
        }

        fks = inspector.get_foreign_keys(table)
        for fk in fks:
            referred_table = fk["referred_table"]
            from_col = fk["constrained_columns"][0]
            to_col = fk["referred_columns"][0]

            # Forward join
            join_graph_json[table][referred_table] = f"{table}.{from_col} = {referred_table}.{to_col}"

            # Reverse join
            if referred_table not in join_graph_json:
                join_graph_json[referred_table] = {}
            if table not in join_graph_json[referred_table]:
                join_graph_json[referred_table][table] = f"{referred_table}.{to_col} = {table}.{from_col}"

    # Optional: Save for debugging
    with open("join_graph.json", "w") as f:
        json.dump(join_graph_json, f, indent=4)

    return join_graph_json, schema_json



@app.route("/", methods=["GET", "POST"])
def select_database():
    if request.method == "POST":
        dbname = request.form.get("database")
        global join_graph, schema_info
        join_graph, schema_info = build_join_graph_and_schema(dbname)
        return redirect("/select_tables")
    return render_template("db_input.html")


@app.route("/select_tables", methods=["GET"])
def select_tables():
    if not join_graph:
        return redirect("/")
    tables = list(join_graph.keys())
    return render_template("table_selector.html", tables=tables, join_graph=join_graph, schema=schema_info)


@app.route("/submit_tables", methods=["POST"])
def submit_tables():
    selected_tables = request.form.getlist("tables")
    print("User selected tables:", selected_tables)
    return f"<h3>You selected: {', '.join(selected_tables)}</h3><a href='/'>🔙 Start Over</a>"


if __name__ == "__main__":
    app.run(debug=True)
