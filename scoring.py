"""Transparent weighted scoring and issue prioritisation."""
import re

CATEGORY_WEIGHTS = {
    "Content answerability": 30,
    "Question coverage": 10,
    "Evidence and trust": 10,
    "Freshness": 5,
    "Content quality": 5,
    "Metadata": 10,
    "Structure": 10,
    "Indexability": 5,
    "Canonical": 5,
    "Accessibility": 3,
    "Technical": 3,
    "Internal linking": 2,
    "Structured data": 2,
}


def enrich_and_score(findings):
    """Score checks by category weight. Findings are signals, not an AI visibility prediction."""
    if not findings:
        return [], {"score": 0, "max_score": 100, "label": "No findings"}
    per_category = {}
    for f in findings:
        per_category.setdefault(f["category"], []).append(f)
    enriched = []
    total = 0.0
    used_weight = 0.0
    for category, items in per_category.items():
        weight = CATEGORY_WEIGHTS.get(category, 1)
        # Each check within a category shares the category weight; Pass=1, Review=.5, Warning=.25, Fail=0.
        check_weight = weight / max(1, len(items))
        for item in items:
            status = item.get("status", "Review").lower()
            value = {"pass": 1.0, "review": 0.5, "warning": 0.25, "fail": 0.0, "not assessed": 0.5}.get(status, 0.5)
            # "info" status is a positive informational finding and should not reduce score.
            if status == "info":
                value = 1.0
            score = check_weight * value
            total += score
            used_weight += check_weight
            severity = item.get("severity", "low")
            if severity == "high":
                priority = "P1"
            elif severity == "medium":
                priority = "P2"
            elif severity == "low":
                priority = "P3"
            else:
                priority = "Info"
            enriched.append({**item, "category_weight": weight, "score_awarded": round(score, 2),
                             "score_possible": round(check_weight, 2), "priority": priority})
    # Normalise for any categories not represented in this page's checks.
    max_possible = sum(CATEGORY_WEIGHTS.values())
    score = round(100 * total / max_possible) if max_possible else 0
    label = "Strong observable signals" if score >= 85 else "Good foundation; improvements remain" if score >= 70 else "Several areas need review" if score >= 50 else "Significant issues to investigate"
    enriched.sort(key=lambda x: ({"P1":0, "P2":1, "P3":2, "Info":3}.get(x["priority"], 4), -x["score_possible"]))
    return enriched, {"score": score, "max_score": 100, "label": label}


def executive_summary(findings):
    active = [f for f in findings if f.get("status", "").lower() in {"fail", "warning", "review"}]
    return {
        "total_checks": len(findings),
        "issues": len(active),
        "p1": sum(1 for f in active if f.get("priority") == "P1"),
        "p2": sum(1 for f in active if f.get("priority") == "P2"),
        "p3": sum(1 for f in active if f.get("priority") == "P3"),
    }
