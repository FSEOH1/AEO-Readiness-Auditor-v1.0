"""Heuristic content answerability checks; findings require editorial review."""
import re


def run_content_checks(page):
    text = page.get("main_text") or page.get("body_text") or ""
    words = re.findall(r"\b[\w'-]+\b", text)
    opening = " ".join(words[:140])
    paragraphs = page.get("paragraphs", [])
    answer_first = len(words) >= 30 and bool(re.search(
        r"\b(is|are|means|refers to|helps|allows|provides|costs|requires|includes|works by|can be|typically|usually|consists of)\b",
        opening, re.I
    ))
    faq_heading = bool(re.search(r"\b(faqs|frequently asked questions|common questions)\b", " ".join(page.get("headings", {}).get("h2", [])), re.I))
    questions = page.get("question_headings", [])
    short_paras = [p for p in paragraphs if 20 <= len(re.findall(r"\b[\w'-]+\b", p)) <= 100]
    source_terms = re.compile(r"\b(source|according to|study|report|research|data from|official|published by)\b", re.I)
    evidence_signal = bool(source_terms.search(text))
    freshness_signal = bool(re.search(r"\b(updated|last reviewed|published|modified)\b", text[:2500], re.I))
    unique_paragraphs = len(set(p.lower() for p in paragraphs if len(p) > 80))
    duplicate_paragraphs = max(0, len([p for p in paragraphs if len(p) > 80]) - unique_paragraphs)
    return [
        {"category":"Content answerability","check":"Direct answer near the beginning","status":"Pass" if answer_first else "Review",
         "evidence":opening[:400] or "No readable opening content", "recommendation":"Answer the primary question clearly near the beginning, then provide detail and caveats.",
         "severity":"medium" if not answer_first else "info", "confidence":"medium"},
        {"category":"Content answerability","check":"Concise, self-contained paragraphs","status":"Pass" if short_paras else "Review",
         "evidence":f"{len(short_paras)} paragraphs contain 20–100 words", "recommendation":"Use concise paragraphs where they improve clarity; do not shorten content just to meet a word range.",
         "severity":"low" if not short_paras else "info", "confidence":"high"},
        {"category":"Question coverage","check":"Questions addressed in headings","status":"Pass" if questions else "Review",
         "evidence":f"{len(questions)} question-form H2/H3/H4 headings", "recommendation":"Add useful question-led sections when they match the audience's information needs.",
         "severity":"low" if not questions else "info", "confidence":"high"},
        {"category":"Question coverage","check":"FAQ section signal","status":"Pass" if faq_heading else "Review",
         "evidence":"FAQ-style heading detected" if faq_heading else "No FAQ-style heading detected",
         "recommendation":"Include an FAQ only if it genuinely helps users; an FAQ is not universally required for AEO.",
         "severity":"low" if not faq_heading else "info", "confidence":"high"},
        {"category":"Evidence and trust","check":"Evidence/source language signal","status":"Pass" if evidence_signal else "Review",
         "evidence":"Source-related wording detected" if evidence_signal else "No common source-related terms detected; linked citations were not semantically verified",
         "recommendation":"Support consequential claims with primary sources, data, methodology, or named experts. Manually verify that evidence is credible.",
         "severity":"medium" if not evidence_signal else "info", "confidence":"low"},
        {"category":"Freshness","check":"Visible freshness signal","status":"Pass" if freshness_signal else "Review",
         "evidence":"Publication/update wording detected" if freshness_signal else "No obvious publication/update wording in extracted text",
         "recommendation":"Where freshness matters, show accurate publication or review dates and maintain the underlying facts.",
         "severity":"low" if not freshness_signal else "info", "confidence":"low"},
        {"category":"Content quality","check":"Repeated long paragraphs","status":"Pass" if duplicate_paragraphs == 0 else "Warning",
         "evidence":f"{duplicate_paragraphs} repeated paragraph(s) over 80 characters within this page",
         "recommendation":"Review repeated copy for accidental duplication; repeated boilerplate may be intentional.",
         "severity":"medium" if duplicate_paragraphs else "info", "confidence":"high"},
    ]
