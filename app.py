from flask import Flask, render_template, request, redirect
from sqlalchemy import create_engine, inspect, MetaData, Table, text
from collections import deque
import json

app = Flask(__name__)
join_graph = {}
schema_info = {}

# ---------- Utility Functions ----------

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
        for table_name in all_tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`"))
                row_count = result.scalar()

                if row_count == 0:
                    continue  # Skip empty tables

                schema_json[table_name] = {
                    "columns": [col["name"] for col in inspector.get_columns(table_name)]
                }

                join_graph_json.setdefault(table_name, {})
                fks = inspector.get_foreign_keys(table_name)
                for fk in fks:
                    referred_table = fk["referred_table"]
                    from_col = fk["constrained_columns"][0]
                    to_col = fk["referred_columns"][0]

                    join_graph_json[table_name][referred_table] = f"{table_name}.{from_col} = {referred_table}.{to_col}"
                    join_graph_json.setdefault(referred_table, {})
                    join_graph_json[referred_table][table_name] = f"{referred_table}.{to_col} = {table_name}.{from_col}"
            except Exception as e:
                print(f"Skipping table `{table_name}` due to error: {e}")

    print("[DEBUG] Join Graph JSON:")
    print(json.dumps(join_graph_json, indent=2))

    return join_graph_json, schema_json

def generate_joins(tables, join_graph):
    print(f"[DEBUG] Generating joins for tables: {tables}")
    if not tables or len(tables) == 1:
        return []

    base_table = tables[0]
    needed_tables = set(tables[1:])
    visited = set()
    queue = deque()
    parent = {}
    edge_map = {}

    queue.append(base_table)
    visited.add(base_table)
    parent[base_table] = None

    while queue:
        current = queue.popleft()
        for neighbor, condition in join_graph.get(current, {}).items():
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
                parent[neighbor] = current
                edge_map[(current, neighbor)] = condition

    joins = []
    for table in tables[1:]:
        if table not in parent:
            print(f"[WARN] Could not find join path from {base_table} to {table}")
            continue

        path = []
        current = table
        while parent[current] is not None:
            prev = parent[current]
            path.append((prev, current))
            current = prev
        path.reverse()

        for a, b in path:
            condition = join_graph[a][b] if b in join_graph[a] else join_graph[b][a]
            joins.append((b, condition))

    print(f"[DEBUG] Join edges: {joins}")
    return [f"JOIN {table} ON {condition}" for table, condition in joins]

def build_dynamic_sql(selected_columns, filters, group_by, aggregations, join_graph):
    tables = set()
    all_exprs = selected_columns + group_by + [agg['column'] for agg in aggregations] + filters
    for expr in all_exprs:
        if '.' in expr:
            tables.add(expr.split('.')[0])
    tables = list(tables)

    print(f"[DEBUG] Tables involved in query: {tables}")
    print(f"[DEBUG] Join Graph:\n{json.dumps(join_graph, indent=2)}")

    if not tables:
        return "-- No valid tables found to build query --"

    base_table = tables[0]

    select_parts = list(selected_columns)
    for agg in aggregations:
        part = f"{agg['function']}({agg['column']})"
        if agg.get("alias"):
            part += f" AS {agg['alias']}"
        select_parts.append(part)

    select_clause = "SELECT " + ", ".join(select_parts)
    join_clauses = generate_joins(tables, join_graph)
    from_clause = f"FROM {base_table}"
    if join_clauses:
        from_clause += "\n" + "\n".join(join_clauses)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    group_by_clause = f"GROUP BY {', '.join(group_by)}" if group_by else ""

    sql = f"""{select_clause}
{from_clause}
{where_clause}
{group_by_clause};""".strip()

    print(f"[DEBUG] Generated SQL:\n{sql}")
    return sql

# ---------- Routes ----------

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
        print("[INFO] Database selected:", dbname)
        return redirect("/select")

    return render_template("db_input.html", databases=databases)

@app.route("/select", methods=["GET"])
def select():
    global schema_info
    if not schema_info:
        return redirect("/")
    return render_template("column_selector.html", schema=schema_info)

@app.route("/submit", methods=["POST"])
def submit():
    global schema_info
    selected_columns = request.form.getlist("columns")
    selected_tables = list(set(col.split('.')[0] for col in selected_columns))
    return render_template("results.html", tables=selected_tables, columns=selected_columns)

@app.route("/build_query", methods=["POST"])
def build_query():
    global join_graph

    selected_columns = request.form.getlist("columns")
    filters = request.form.getlist("filters")
    group_by = request.form.getlist("group_by")

    agg_funcs = request.form.getlist("aggregation_function")
    agg_cols = request.form.getlist("aggregation_column")
    agg_aliases = request.form.getlist("aggregation_alias")

    aggregations = []
    for f, c, a in zip(agg_funcs, agg_cols, agg_aliases):
        if f and c:
            aggregations.append({
                "function": f,
                "column": c,
                "alias": a or None
            })

    sql_query = build_dynamic_sql(
        selected_columns=selected_columns,
        filters=filters,
        group_by=group_by,
        aggregations=aggregations,
        join_graph=join_graph
    )

    return render_template("query_result.html", query=sql_query)

if __name__ == "__main__":
    app.run(debug=True)

