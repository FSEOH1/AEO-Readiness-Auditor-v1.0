"""JSON-LD syntax and basic structural checks; not a full Schema.org validator."""
import json


def _walk(value, path="$"):
    findings = []
    if isinstance(value, dict):
        if "@type" not in value and any(k in value for k in ["name", "headline", "description"]):
            findings.append((path, "Object has descriptive fields but no @type; verify whether it is intended as a typed entity."))
        for key, child in value.items():
            findings.extend(_walk(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            findings.extend(_walk(child, f"{path}[{i}]"))
    return findings


def run_schema_checks(page):
    schemas = page.get("schemas", [])
    errors = page.get("schema_errors", [])
    types = page.get("schema_types", [])
    findings = []
    if not schemas and not errors:
        findings.append({"category":"Structured data","check":"JSON-LD detected","status":"Review",
            "evidence":"No JSON-LD script detected in the fetched HTML.",
            "recommendation":"Add structured data only where it accurately represents visible page content and is appropriate for the page type.",
            "severity":"low","confidence":"high"})
    else:
        findings.append({"category":"Structured data","check":"JSON-LD syntax","status":"Fail" if errors else "Pass",
            "evidence":f"{len(schemas)} JSON-LD block(s) parsed; {len(errors)} syntax error(s).",
            "recommendation":"Fix malformed JSON-LD syntax. Then validate the properties and eligibility using appropriate validators.",
            "severity":"high" if errors else "info","confidence":"high"})
    findings.append({"category":"Structured data","check":"Schema @type detected","status":"Pass" if types else "Review",
        "evidence":", ".join(types) if types else "No @type values detected.",
        "recommendation":"Use accurate schema types; do not add types solely to chase visibility.",
        "severity":"medium" if schemas and not types else ("low" if not types else "info"),"confidence":"high"})
    if errors:
        for error in errors:
            findings.append({"category":"Structured data","check":f"JSON-LD block {error.get('block')} syntax error","status":"Fail",
                "evidence":error.get("error","Invalid JSON"),"recommendation":"Correct the JSON syntax in this block and rerun the audit.",
                "severity":"high","confidence":"high"})
    for schema in schemas:
        for path, message in _walk(schema):
            findings.append({"category":"Structured data","check":"Review untyped object","status":"Review",
                "evidence":f"{path}: {message}","recommendation":"Confirm this object is intentional and typed appropriately if it represents a Schema.org entity.",
                "severity":"low","confidence":"low"})
    return findings
