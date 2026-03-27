#main file that invokes all the necessary procedures from these three files
from preprocessing import connect_db, get_qep, get_aqps
from annotation import generate_annotations

conn = connect_db(
    dbname="TPC-H",
    user="postgres",   
    password="12345", 
    host="localhost",
    port="5432"
)

sql = "SELECT * FROM customer C, orders O WHERE C.c_custkey = O.o_custkey"

qep  = get_qep(conn, sql)
aqps = get_aqps(conn, sql)
result = generate_annotations(sql, qep, aqps)

print("=== SCAN ANNOTATIONS ===")
for table, note in result["scans"].items():
    print(f"\n{note}")

print("\n=== JOIN ANNOTATIONS ===")
for note in result["joins"]:
    print(f"\n{note}")

print("\n=== OTHER ANNOTATIONS ===")
for note in result["others"]:
    print(f"\n{note}")

conn.close()