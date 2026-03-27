#main file that invokes all the necessary procedures from these three files
from preprocessing import connect_db, get_qep, get_aqps, parse_plan_tree
import json

conn = connect_db(
    dbname="TPC-H",
    user="postgres",   
    password="12345", 
    host="localhost",
    port="5432"
)

sql = "SELECT * FROM customer C, orders O WHERE C.c_custkey = O.o_custkey"

qep = get_qep(conn, sql)
print("=== QEP ===")
print(json.dumps(qep, indent=2))

# Get AQPs
aqps = get_aqps(conn, sql)
print("\n=== AQP Costs ===")
for name, plan in aqps.items():
    cost = plan["Plan"]["Total Cost"]
    print(f"  Without {name}: total cost = {cost}")

nodes = parse_plan_tree(qep["Plan"])
print("\n=== Plan Nodes ===")
for n in nodes:
    print(f"  {n['type']} on {n['relation'] or 'N/A'} — cost: {n['total_cost']}")

conn.close()