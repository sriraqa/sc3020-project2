#contains code for generating the annotations
# annotation.py
import sqlparse
from sqlparse.sql import IdentifierList, Identifier, Where, Comparison
from sqlparse.tokens import Keyword, DML, Punctuation
import re

def extract_tables(sql_query):
    """
    Extract table names and their aliases from the SQL query.
    Returns a dict of {alias: table_name}
    """
    tables = {}
    parsed = sqlparse.parse(sql_query)[0]
    tokens = [t for t in parsed.flatten()]
    
    # Look for FROM and JOIN keywords followed by table names
    i = 0
    while i < len(tokens):
        val = tokens[i].value.upper()
        if val in ('FROM', 'JOIN'):
            # next meaningful token is the table name
            j = i + 1
            while j < len(tokens) and tokens[j].value.strip() in ('', ','):
                j += 1
            if j < len(tokens):
                table_name = tokens[j].value.strip()
                # check if next token is an alias
                k = j + 1
                while k < len(tokens) and tokens[k].value.strip() == '':
                    k += 1
                if k < len(tokens) and tokens[k].ttype is not Keyword and \
                   tokens[k].value.upper() not in ('WHERE', 'ON', 'SET', 'JOIN',
                                                    'LEFT', 'RIGHT', 'INNER',
                                                    'OUTER', 'GROUP', 'ORDER',
                                                    'HAVING', 'LIMIT', ','):
                    alias = tokens[k].value.strip()
                    tables[alias] = table_name
                    tables[table_name] = table_name  # also map name to itself
                else:
                    tables[table_name] = table_name
        i += 1
    return tables


def extract_conditions(sql_query):
    """
    Extract WHERE clause conditions from the SQL query.
    Returns a list of condition strings.
    """
    conditions = []
    # Find WHERE clause using regex
    where_match = re.search(r'\bWHERE\b(.*?)(?:\bGROUP\b|\bORDER\b|\bHAVING\b|\bLIMIT\b|$)',
                            sql_query, re.IGNORECASE | re.DOTALL)
    if where_match:
        where_clause = where_match.group(1).strip()
        # Split by AND/OR
        parts = re.split(r'\bAND\b|\bOR\b', where_clause, flags=re.IGNORECASE)
        for part in parts:
            conditions.append(part.strip())
    return conditions


def get_node_cost(plan_node):
    """Extract total cost from a plan node."""
    return plan_node.get("Total Cost", 0)


def find_nodes_by_type(plan_node, target_types, found=None):
    """
    Recursively find all nodes matching target types in the plan tree.
    target_types: list of strings e.g. ["Hash Join", "Seq Scan"]
    """
    if found is None:
        found = []
    if plan_node.get("Node Type") in target_types:
        found.append(plan_node)
    for child in plan_node.get("Plans", []):
        find_nodes_by_type(child, target_types, found)
    return found


def annotate_scans(plan_node, tables, aqps):
    """
    Generate annotations for table scan nodes (Seq Scan, Index Scan, etc.)
    Returns a dict of {table_name: annotation_string}
    """
    annotations = {}
    scan_types = ["Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan"]
    scan_nodes = find_nodes_by_type(plan_node, scan_types)

    for node in scan_nodes:
        relation = node.get("Relation Name")
        node_type = node.get("Node Type")
        cost = node.get("Total Cost")

        if not relation:
            continue

        if node_type == "Seq Scan":
            # Check if a cheaper index scan was available
            annotation = (
                f"[{relation}] accessed using Sequential Scan (cost: {cost}). "
                f"All rows are read one by one because no usable index exists on "
                f"the filtered/joined column(s)."
            )
        elif node_type in ("Index Scan", "Index Only Scan"):
            index_name = node.get("Index Name", "an index")
            annotation = (
                f"[{relation}] accessed using Index Scan via '{index_name}' (cost: {cost}). "
                f"This is faster than a Sequential Scan as only matching rows are retrieved."
            )
        elif node_type == "Bitmap Heap Scan":
            annotation = (
                f"[{relation}] accessed using Bitmap Heap Scan (cost: {cost}). "
                f"A bitmap of matching rows is built first, then fetched from the table."
            )
        else:
            annotation = f"[{relation}] accessed using {node_type} (cost: {cost})."

        annotations[relation] = annotation

    return annotations


def annotate_joins(plan_node, aqps):
    """
    Generate annotations for join nodes by comparing QEP cost vs AQP costs.
    Returns a list of annotation strings.
    """
    annotations = []
    join_types = ["Hash Join", "Nested Loop", "Merge Join"]
    join_nodes = find_nodes_by_type(plan_node, join_types)

    if not join_nodes:
        return annotations

    qep_cost = plan_node.get("Total Cost", 0)

    # Get AQP costs for comparison
    aqp_costs = {}
    for disabled_op, aqp_plan in aqps.items():
        aqp_cost = aqp_plan["Plan"].get("Total Cost", 0)
        aqp_costs[disabled_op] = aqp_cost

    for node in join_nodes:
        join_type = node.get("Node Type")
        condition = (node.get("Hash Cond") or
                     node.get("Merge Cond") or
                     node.get("Join Filter") or
                     "N/A")
        cost = node.get("Total Cost")

        # Build cost comparison string
        comparisons = []
        if join_type == "Hash Join" and "hashjoin" in aqp_costs:
            alt_cost = aqp_costs["hashjoin"]
            ratio = round(alt_cost / cost, 1) if cost > 0 else "N/A"
            comparisons.append(f"disabling Hash Join increases cost to {alt_cost} (~{ratio}x)")

        if join_type != "Nested Loop" and "nestloop" in aqp_costs:
            alt_cost = aqp_costs["nestloop"]
            if alt_cost != qep_cost:
                ratio = round(alt_cost / cost, 1) if cost > 0 else "N/A"
                comparisons.append(f"Nested Loop would cost {alt_cost} (~{ratio}x)")

        if join_type != "Merge Join" and "mergejoin" in aqp_costs:
            alt_cost = aqp_costs["mergejoin"]
            if alt_cost != qep_cost:
                ratio = round(alt_cost / cost, 1) if cost > 0 else "N/A"
                comparisons.append(f"Merge Join would cost {alt_cost} (~{ratio}x)")

        comparison_str = "; ".join(comparisons) if comparisons else "no cheaper alternative found"

        annotation = (
            f"[JOIN on {condition}] implemented using {join_type} (cost: {cost}). "
            f"Reason: {comparison_str}."
        )
        annotations.append(annotation)

    return annotations


def annotate_groupby_sort(plan_node):
    """
    Generate annotations for GROUP BY, ORDER BY, and aggregation nodes.
    Returns a list of annotation strings.
    """
    annotations = []
    agg_types = ["Aggregate", "HashAggregate", "GroupAggregate",
                 "Sort", "Incremental Sort"]
    nodes = find_nodes_by_type(plan_node, agg_types)

    for node in nodes:
        node_type = node.get("Node Type")
        cost = node.get("Total Cost")

        if node_type in ("Aggregate", "HashAggregate"):
            annotation = (
                f"[AGGREGATION] performed using {node_type} (cost: {cost}). "
                f"Rows are grouped and aggregate functions (e.g. COUNT, SUM) are computed."
            )
        elif node_type == "GroupAggregate":
            annotation = (
                f"[GROUP BY] implemented using GroupAggregate (cost: {cost}). "
                f"Input is pre-sorted by the grouping key before aggregation."
            )
        elif node_type in ("Sort", "Incremental Sort"):
            sort_key = node.get("Sort Key", [])
            annotation = (
                f"[SORT] on {sort_key} using {node_type} (cost: {cost}). "
                f"Required for ORDER BY or as preparation for a Merge Join / GroupAggregate."
            )
        annotations.append(annotation)

    return annotations


def generate_annotations(sql_query, qep, aqps):
    """
    Master function — takes SQL, QEP, and AQPs and returns
    a dict of all annotations organized by type.
    """
    plan_node = qep["Plan"]
    tables = extract_tables(sql_query)
    conditions = extract_conditions(sql_query)

    # Generate all annotation types
    scan_annotations  = annotate_scans(plan_node, tables, aqps)
    join_annotations  = annotate_joins(plan_node, aqps)
    other_annotations = annotate_groupby_sort(plan_node)

    return {
        "scans":  scan_annotations,   # dict: {table_name: annotation}
        "joins":  join_annotations,   # list of strings
        "others": other_annotations,  # list of strings
        "tables": tables,
        "conditions": conditions
    }