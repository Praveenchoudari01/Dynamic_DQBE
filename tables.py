from sqlalchemy import create_engine, inspect, MetaData, Table
import json

# Database connection
username = 'root'
password = '1619'
host = 'localhost'
port = 3306
database = 'cleanroom'

engine = create_engine(f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}")
metadata = MetaData()
metadata.reflect(bind=engine)
inspector = inspect(engine)

# Reflect all tables
all_tables = {
    table_name: Table(table_name, metadata, autoload_with=engine)
    for table_name in inspector.get_table_names()
}

# Build join graph in string format (for JSON)
join_graph_json = {}

for table in all_tables:
    join_graph_json[table] = {}
    fks = inspector.get_foreign_keys(table)

    for fk in fks:
        referred_table = fk["referred_table"]
        from_col = fk["constrained_columns"][0]
        to_col = fk["referred_columns"][0]

        # Add forward join
        join_graph_json[table][referred_table] = f"{table}.{from_col} = {referred_table}.{to_col}"

        # Add reverse join
        if referred_table not in join_graph_json:
            join_graph_json[referred_table] = {}
        if table not in join_graph_json[referred_table]:
            join_graph_json[referred_table][table] = f"{referred_table}.{to_col} = {table}.{from_col}"

# Save to JSON file
with open("join_graph.json", "w") as f:
    json.dump(join_graph_json, f, indent=4)

print("✅ join_graph saved to join_graph.json")
