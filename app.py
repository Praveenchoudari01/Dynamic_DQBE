from flask import Flask, render_template, request, redirect
from sqlalchemy import create_engine, inspect, MetaData, Table, text
from collections import deque
import json

app = Flask(__name__)

join_graph = {}
schema_info = {}
current_db = None

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
                if result.scalar() == 0:
                    continue

                schema_json[table_name] = {
                    "columns": [col["name"] for col in inspector.get_columns(table_name)]
                }

                join_graph_json.setdefault(table_name, {})
                fks = inspector.get_foreign_keys(table_name)
                for fk in fks:
                    referred_table = fk["referred_table"]
                    from_cols = fk["constrained_columns"]
                    to_cols = fk["referred_columns"]

                    conditions = []
                    for from_col, to_col in zip(from_cols, to_cols):
                        conditions.append(f"{table_name}.{from_col} = {referred_table}.{to_col}")
                    join_condition = " AND ".join(conditions)

                    join_graph_json.setdefault(table_name, {}).setdefault(referred_table, []).append(join_condition)
                    join_graph_json.setdefault(referred_table, {}).setdefault(table_name, []).append(join_condition)

            except Exception as e:
                print(f"Skipping table `{table_name}` due to error: {e}")

    return join_graph_json, schema_json

def generate_joins(tables, join_graph):
    if not tables or len(tables) == 1:
        return []

    base_table = tables[0]
    visited = set()
    queue = deque()
    parent = {}
    queue.append(base_table)
    visited.add(base_table)
    parent[base_table] = None

    while queue:
        current = queue.popleft()
        for neighbor in join_graph.get(current, {}):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
                parent[neighbor] = current

    joins = []
    for table in tables[1:]:
        if table not in parent:
            continue

        path = []
        current = table
        while parent[current] is not None:
            prev = parent[current]
            path.append((prev, current))
            current = prev
        path.reverse()

        for a, b in path:
            conditions = join_graph[a][b] if b in join_graph[a] else join_graph[b][a]
            condition = ' AND '.join(conditions) if isinstance(conditions, list) else conditions
            joins.append((b, condition))

    return [f"JOIN {table} ON {condition}" for table, condition in joins]

def build_dynamic_sql(selected_columns, filters, group_by, aggregations, join_graph):
    tables = set()
    all_exprs = selected_columns + group_by + [agg['column'] for agg in aggregations] + filters
    for expr in all_exprs:
        if '.' in expr:
            tables.add(expr.split('.')[0])
    tables = list(tables)

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
        global join_graph, schema_info, current_db
        join_graph, schema_info = build_join_graph_and_schema(dbname)
        current_db = dbname
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
    selected_columns = request.form.getlist("columns")
    selected_tables = list(set(col.split('.')[0] for col in selected_columns))
    return render_template("results.html", tables=selected_tables, columns=selected_columns)

@app.route("/build_query", methods=["POST"])
def build_query():
    global join_graph, current_db

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

    username = 'root'
    password = '1619'
    host = 'localhost'
    port = 3306

    engine = create_engine(f"mysql+pymysql://{username}:{password}@{host}:{port}/{current_db}")

    result_data = []
    column_names = []

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql_query))
            column_names = result.keys()
            result_data = result.fetchall()
    except Exception as e:
        print(f"[ERROR] Failed to execute query: {e}")

    return render_template("query_result.html", query=sql_query, rows=result_data, columns=column_names)

if __name__ == "__main__":
    app.run(debug=True)
