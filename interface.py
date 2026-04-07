import json
import os

from nicegui import ui

from annotation import generate_annotations
from preprocessing import connect_db, get_aqps, get_qep


def _build_tree_text(node, prefix="", is_last=True):
    connector = "└── " if is_last else "├── "
    node_type = node.get("Node Type", "Unknown")
    relation = node.get("Relation Name", "")
    cost = node.get("Total Cost", "?")
    condition = (
        node.get("Hash Cond")
        or node.get("Merge Cond")
        or node.get("Index Cond")
        or node.get("Filter")
        or ""
    )

    line = f"{prefix}{connector}{node_type}"
    if relation:
        line += f" on {relation}"
    line += f"  [cost: {cost}]"
    if condition:
        line += f"\n{prefix}{'    ' if is_last else '│   '}   cond: {condition}"

    result = line + "\n"

    children = node.get("Plans", [])
    child_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(children):
        result += _build_tree_text(child, child_prefix, is_last=(i == len(children) - 1))
    return result


def _format_annotations(sql, result):
    blocks = [sql.strip(), ""]

    scans = result.get("scans", {})
    joins = result.get("joins", [])
    others = result.get("others", [])

    if scans:
        blocks.append("=== Table Access ===")
        blocks.extend(f"- {note}" for note in scans.values())
        blocks.append("")
    if joins:
        blocks.append("=== Join Operations ===")
        blocks.extend(f"- {note}" for note in joins)
        blocks.append("")
    if others:
        blocks.append("=== Other Operations ===")
        blocks.extend(f"- {note}" for note in others)

    return "\n".join(blocks).strip()


def launch_gui():
    state = {"conn": None}

    ui.dark_mode().enable()
    ui.page_title("SC3020 - Query Plan Annotator")

    with ui.column().classes("w-full p-6 gap-4"):
        ui.label("SC3020 - Query Plan Annotator").classes("text-2xl font-bold")

        with ui.card().classes("w-full"):
            ui.label("Database Connection").classes("text-lg font-semibold")
            with ui.row().classes("w-full gap-2"):
                host_input = ui.input("Host", value=os.environ.get("PGHOST", "127.0.0.1")).classes("w-40")
                port_input = ui.input("Port", value=os.environ.get("PGPORT", "5432")).classes("w-32")
                db_input = ui.input("Database", value=os.environ.get("PGDATABASE", "tpch")).classes("w-40")
                user_input = ui.input("Username", value=os.environ.get("PGUSER", "postgres")).classes("w-40")
                password_input = ui.input("Password", password=True, password_toggle_button=True, value=os.environ.get("PGPASSWORD", "")).classes("w-48")

            conn_status = ui.label("Not connected").classes("text-grey-5")

            def connect_action():
                if state["conn"]:
                    try:
                        state["conn"].close()
                    except Exception:
                        pass
                    state["conn"] = None

                try:
                    state["conn"] = connect_db(
                        dbname=db_input.value,
                        user=user_input.value,
                        password=password_input.value,
                        host=host_input.value,
                        port=port_input.value,
                    )
                    conn_status.text = f"Connected to '{db_input.value}' as {user_input.value}"
                    conn_status.classes(remove="text-grey-5 text-negative", add="text-positive")
                    ui.notify("Connected to database", type="positive")
                except Exception as e:
                    conn_status.text = "Connection failed"
                    conn_status.classes(remove="text-grey-5 text-positive", add="text-negative")
                    ui.notify(f"Connection failed: {e}", type="negative")

            ui.button("Connect to DB", on_click=connect_action).props("color=primary")

        def annotate_action():
            if not state["conn"]:
                ui.notify("Please connect to a database first", type="warning")
                return

            sql = (sql_input.value or "").strip()
            if not sql:
                ui.notify("Please enter an SQL query", type="warning")
                return

            try:
                qep = get_qep(state["conn"], sql)
                aqps = get_aqps(state["conn"], sql)
                result = generate_annotations(sql, qep, aqps)

                annotated_output.content = _format_annotations(sql, result)
                qep_tree_output.content = _build_tree_text(qep["Plan"], prefix="")
                qep_json_output.content = json.dumps(qep, indent=2)
                ui.notify("Annotation complete", type="positive")
            except Exception as e:
                ui.notify(f"Error while annotating query: {e}", type="negative")

        with ui.row().classes("w-full gap-4 items-stretch"):
            with ui.card().classes("w-1/2"):
                ui.label("SQL Query").classes("text-lg font-semibold")
                sql_input = ui.textarea(
                    label="SQL",
                    placeholder="SELECT * FROM customer C, orders O WHERE C.c_custkey = O.o_custkey",
                ).props("autogrow outlined").classes("w-full")

                ui.button("Annotate Query", on_click=annotate_action).props("color=primary size=md")

                ui.label("Annotated Output").classes("text-lg font-semibold mt-2")
                annotated_output = ui.code("").classes("w-full max-h-96 overflow-auto")

            with ui.card().classes("w-1/2"):
                ui.label("Query Execution Plan (Tree View)").classes("text-lg font-semibold")
                qep_tree_output = ui.code("").classes("w-full max-h-72 overflow-auto")

                ui.label("Raw QEP (JSON)").classes("text-lg font-semibold mt-2")
                qep_json_output = ui.code("").classes("w-full max-h-72 overflow-auto")

    ui.run(title="SC3020 - Query Plan Annotator", reload=False)