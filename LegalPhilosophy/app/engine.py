from __future__ import annotations

from .domain import FROZEN_SECTIONS, SourceDocument, StudyResult, validate_result


SECTION_KEYWORDS = (
    ("Abstract Right", ("property", "contract", "wrong", "财产", "契约", "不法", "权利")),
    ("Morality", ("morality", "intention", "responsibility", "道德", "动机", "责任")),
    ("Family", ("family", "marriage", "家庭", "婚姻")),
    ("Civil Society", ("civil society", "poverty", "labour", "justice", "市民社会", "贫困", "劳动", "司法")),
    ("International Law", ("international", "war", "treaty", "国际法", "战争", "条约")),
    ("World History", ("history", "world spirit", "世界历史", "历史")),
    ("State", ("state", "constitution", "government", "freedom", "国家", "宪法", "政府", "自由")),
)


def classify_section(question: str) -> str:
    q = question.casefold()
    for section, words in SECTION_KEYWORDS:
        if any(word.casefold() in q for word in words):
            return section
    return "Preface / Introduction"


def build_study_result(question: str, docs: list[SourceDocument]) -> StudyResult:
    if not question or not question.strip():
        raise ValueError("study question is required")
    roles = {doc.role for doc in docs if doc.validation_status == "PASS"}
    if "AUTHORITATIVE_SCHOLARSHIP" not in roles or "LEGAL_AUTHORITY" not in roles:
        raise RuntimeError("current scholarship + legal authority evidence required")
    section = classify_section(question)
    refs = tuple(doc.source_id for doc in docs)
    result = StudyResult(
        question=question.strip(),
        section=section,
        status="PASS",
        source_refs=refs,
        evidence_requirements=(
            "Separate primary text from scholarship, legal authority, case evidence and model inference.",
            "For any quotation or section-specific claim, require a verified primary-edition source before treating it as primary text.",
            "Preserve conflicting interpretations instead of silently averaging them.",
        ),
        five_why=(
            f"Why does the question matter inside {section} rather than as a slogan?",
            "Why would the proposed principle count as right/freedom rather than preference or power?",
            "Why would the supporting institution or rule be justified for people who reject the conclusion?",
            "Why might the strongest counterexample defeat or narrow the principle?",
            "Why should the final judgment survive source, historical and institutional disagreement?",
        ),
        reversal_tests=(
            "Reverse the favored party: would the principle still be accepted?",
            "Replace the historical institution with a modern one: which premises survive?",
            "Assume the strongest scholarly interpretation is wrong: which source-grounded claims remain?",
        ),
        counterexample_prompts=(
            "Find a case where the principle protects formal freedom but worsens substantive dependency.",
            "Find a conflict between individual right and institutional/general-welfare justification.",
        ),
        model_inference=(
            "The system generated a study/falsification framework from the frozen domain model and current source identities; "
            "it did not infer a legal answer, fabricate a quotation, or certify a primary-text interpretation."
        ),
        boundary="Educational legal-philosophy study only; not individualized legal advice.",
    )
    validate_result(result)
    if section not in FROZEN_SECTIONS:
        raise AssertionError("classifier escaped frozen scope")
    return result
