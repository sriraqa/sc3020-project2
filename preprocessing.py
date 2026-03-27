#contains any code for reading inputs and any preprocessing necessary to make your algorithm work
import psycopg2
import json

def connect_db(dbname="tpch", user="postgres", password="", host="localhost", port="5432"):
    """Establish connection to PostgreSQL database."""
    conn = psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port
    )
    return conn

def get_qep(conn, sql_query):
    """Fetch the Query Execution Plan (QEP) as JSON."""
    cur = conn.cursor()
    cur.execute(f"EXPLAIN (FORMAT JSON, ANALYZE FALSE) {sql_query}")
    plan = cur.fetchone()[0][0]
    cur.close()
    return plan

def get_aqps(conn, sql_query):
    """
    Fetch Alternative Query Plans by disabling operators one at a time.
    Returns a dict of {operator_disabled: plan}
    """
    settings = {
        "hashjoin":  "enable_hashjoin",
        "nestloop":  "enable_nestloop",
        "mergejoin": "enable_mergejoin",
        "seqscan":   "enable_seqscan",
        "indexscan": "enable_indexscan",
    }

    aqps = {}
    cur = conn.cursor()

    for name, setting in settings.items():
        try:
            cur.execute(f"SET {setting} = off")
            cur.execute(f"EXPLAIN (FORMAT JSON, ANALYZE FALSE) {sql_query}")
            aqp = cur.fetchone()[0][0]
            aqps[name] = aqp
        except Exception as e:
            print(f"Could not get AQP for {name}: {e}")
            conn.rollback()
        finally:
            cur.execute(f"SET {setting} = on")

    cur.close()
    return aqps

def parse_plan_tree(plan_node, nodes=None):
    """
    Recursively walk the plan tree and extract all nodes.
    Returns a flat list of all nodes with their details.
    """
    if nodes is None:
        nodes = []

    node_info = {
        "type":        plan_node.get("Node Type"),
        "relation":    plan_node.get("Relation Name"),
        "alias":       plan_node.get("Alias"),
        "join_type":   plan_node.get("Join Type"),
        "condition":   plan_node.get("Hash Cond") or plan_node.get("Merge Cond") or plan_node.get("Join Filter"),
        "filter":      plan_node.get("Filter"),
        "total_cost":  plan_node.get("Total Cost"),
        "startup_cost":plan_node.get("Startup Cost"),
        "rows":        plan_node.get("Plan Rows"),
        "raw":         plan_node 
    }
    nodes.append(node_info)

    for child in plan_node.get("Plans", []):
        parse_plan_tree(child, nodes)

    return nodes