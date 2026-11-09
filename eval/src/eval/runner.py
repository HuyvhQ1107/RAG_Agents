"""CLI Evaluation Runner and Baseline Regression Gate Checker (T062, T067)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.blob_store import LocalBlobStore
from app.adapters.embedder_gemini import FakeEmbedder
from app.adapters.llm_gemini import FakeLLMClient
from app.adapters.reranker import BilingualHeuristicReranker
from app.agent.graph import AgentState, build_agent_graph
from app.agent.tools import ReadOnlyAgentTools
from app.cli import seed_demo_data
from app.db.base import Base
from app.db.models.auth import User
from app.db.models.conversation import TurnKind
from app.rag.retriever import HybridRetriever
from eval.judges import (
    check_citation_validity,
    check_forbidden_substrings,
    check_gold_facts,
    check_provider_payloads_for_pii,
)


def _map_turn_kind_to_eval_behavior(kind: TurnKind, intent: str | None = None) -> str:
    if kind == TurnKind.answer and intent == "summarize_document":
        return "summary"
    mapping = {
        TurnKind.answer: "answer",
        TurnKind.partial_answer: "partial",
        TurnKind.clarification: "clarify",
        TurnKind.refusal_not_found: "refusal_not_found",
        TurnKind.refusal_out_of_scope: "refusal_out_of_scope",
        TurnKind.refusal_unsupported: "refusal_unsupported",
    }
    return mapping.get(kind, kind.value)


def _load_cases(datasets_dir: Path, suite: str) -> list[dict[str, Any]]:
    suite_file = datasets_dir / f"{suite}.yaml"
    data = yaml.safe_load(suite_file.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for inc in data.get("includes", []):
        inc_data = yaml.safe_load((datasets_dir / inc).read_text(encoding="utf-8"))
        cases.extend(inc_data.get("cases", []))
    cases.extend(data.get("cases", []))
    return cases


async def run_evaluation(suite: str = "smoke") -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    datasets_dir = repo_root / "eval" / "datasets"
    cases = _load_cases(datasets_dir, suite)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    embedder = FakeEmbedder()
    llm = FakeLLMClient()
    reranker = BilingualHeuristicReranker()
    retriever = HybridRetriever(embedder=embedder, reranker=reranker)

    with tempfile.TemporaryDirectory(dir=str(repo_root / "backend")) as tmp_dir:
        blob_store = LocalBlobStore(Path(tmp_dir) / "blobs")
        async with factory() as session:
            seeded = await seed_demo_data(session, blob_store=blob_store, embedder=embedder)
            docs_title_map = seeded["documents"]

            eng_user = (
                await session.execute(select(User).where(User.username == "emp_eng"))
            ).scalar_one()
            hr_user = (
                await session.execute(select(User).where(User.username == "emp_hr"))
            ).scalar_one()

            doc_key_to_id = {
                "doc_leave_policy": docs_title_map["Quy định nghỉ phép"],
                "doc_travel_policy": docs_title_map["Quy định công tác phí"],
                "doc_handbook_en": docs_title_map["Sổ tay nhân viên"],
                "doc_salary_hr": docs_title_map["Bảng lương 2026"],
                "doc_expired_parking": docs_title_map["Quy định hỗ trợ gửi xe 2024 (Cũ)"],
            }
            doc_key_to_title = {
                "doc_leave_policy": "Quy định nghỉ phép",
                "doc_travel_policy": "Quy định công tác phí",
                "doc_handbook_en": "Sổ tay nhân viên",
                "doc_salary_hr": "Bảng lương 2026",
                "doc_expired_parking": "Quy định hỗ trợ gửi xe 2024 (Cũ)",
            }

            case_results: list[dict[str, Any]] = []

            for case in cases:
                user_groups = case.get("user_groups", [])
                active_user = hr_user if "hr" in user_groups else eng_user
                tools = ReadOnlyAgentTools(
                    session=session, retriever=retriever, user_id=active_user.id
                )
                graph = build_agent_graph(llm, tools)

                history_items = case.get("conversation_history", [])
                if history_items:
                    history_text = "\n".join(
                        f"{h['role'].capitalize()}: {h['content']}" for h in history_items
                    )
                else:
                    history_text = "None"

                scope_key = case.get("scope_document_key")
                scope_doc_id = str(doc_key_to_id[scope_key]) if scope_key in doc_key_to_id else None
                scope_doc_title = doc_key_to_title.get(scope_key) if scope_key else None

                state_in: AgentState = {
                    "question": case["question"],
                    "history_text": history_text,
                    "scope_document_id": scope_doc_id,
                    "scope_document_title": scope_doc_title,
                    "pending_clarification_count": 0,
                }
                state_out = await graph.ainvoke(state_in)

                turn_kind: TurnKind = state_out["turn_kind"]
                actual_behavior = _map_turn_kind_to_eval_behavior(
                    turn_kind, state_out.get("intent")
                )
                final_answer = state_out.get("final_answer", "")
                verified_cits = state_out.get("verified_citations") or []

                combined_text = final_answer
                if actual_behavior == "clarify":
                    opts = state_out.get("clarification_options") or []
                    opts_labels = " ".join(o["label"] for o in opts)
                    combined_text = f"{final_answer} {opts_labels}"

                behavior_match = actual_behavior == case["expected_behavior"]
                fact_score = check_gold_facts(combined_text, case.get("gold_facts", []))
                leaked_forbidden = check_forbidden_substrings(
                    combined_text, case.get("forbidden_substrings", [])
                )

                gold_doc_ids = {
                    str(doc_key_to_id[k])
                    for k in case.get("gold_document_keys", [])
                    if k in doc_key_to_id
                }
                retrieved_doc_ids = {str(c.passage.document_id) for c in verified_cits}
                if not gold_doc_ids:
                    recall_hit = 1.0
                else:
                    recall_hit = 1.0 if (gold_doc_ids & retrieved_doc_ids) else 0.0

                cit_dicts = [
                    {
                        "marker": c.marker,
                        "document_id": str(c.passage.document_id),
                        "title": c.passage.document_title,
                    }
                    for c in verified_cits
                ]
                cit_valid = check_citation_validity(final_answer, cit_dicts, actual_behavior)
                cit_prec = (
                    1.0
                    if not gold_doc_ids
                    or (retrieved_doc_ids and retrieved_doc_ids.issubset(gold_doc_ids))
                    else 0.5
                )

                permission_leak = (
                    1
                    if (
                        case["category"] == "access_control_negative"
                        and (leaked_forbidden or verified_cits)
                    )
                    else 0
                )

                case_results.append(
                    {
                        "id": case["id"],
                        "category": case["category"],
                        "expected_behavior": case["expected_behavior"],
                        "actual_behavior": actual_behavior,
                        "behavior_match": behavior_match,
                        "fact_score": fact_score,
                        "recall_hit": recall_hit,
                        "citation_valid": cit_valid,
                        "citation_precision": cit_prec,
                        "permission_leak": permission_leak,
                        "leaked_forbidden": leaked_forbidden,
                    }
                )

    await engine.dispose()

    pii_leaks = check_provider_payloads_for_pii(
        llm.recorded_payloads + embedder.recorded_payloads
    )
    total = len(case_results)
    ans_cases = [
        c for c in case_results if c["expected_behavior"] in ("answer", "summary", "partial")
    ]
    ref_cases = [c for c in case_results if c["expected_behavior"].startswith("refusal_")]
    clar_cases = [c for c in case_results if c["expected_behavior"] == "clarify"]
    mono_cases = [c for c in case_results if c["category"] in ("lookup_vi", "lookup_en")]
    cross_cases = [
        c
        for c in case_results
        if c["category"] in ("cross_lingual_vi_en", "cross_lingual_en_vi")
    ]

    mono_recall = sum(c["recall_hit"] for c in mono_cases) / max(1, len(mono_cases))
    cross_recall = sum(c["recall_hit"] for c in cross_cases) / max(1, len(cross_cases))

    metrics = {
        "permission_leak_count": sum(c["permission_leak"] for c in case_results),
        "pii_leak_count": pii_leaks,
        "citation_validity": round(
            sum(1 for c in case_results if c["citation_valid"]) / max(1, total), 4
        ),
        "behavior_accuracy": round(
            sum(1 for c in case_results if c["behavior_match"]) / max(1, total), 4
        ),
        "retrieval_recall_at_8": round(
            sum(c["recall_hit"] for c in ans_cases) / max(1, len(ans_cases)), 4
        ),
        "answer_correctness": round(
            sum(c["fact_score"] for c in ans_cases) / max(1, len(ans_cases)), 4
        ),
        "citation_precision": round(
            sum(c["citation_precision"] for c in ans_cases) / max(1, len(ans_cases)), 4
        ),
        "refusal_accuracy": round(
            sum(1 for c in ref_cases if c["behavior_match"]) / max(1, len(ref_cases)), 4
        ),
        "clarify_accuracy": round(
            sum(1 for c in clar_cases if c["behavior_match"]) / max(1, len(clar_cases)), 4
        ),
        "cross_lingual_gap": round(max(0.0, mono_recall - cross_recall), 4),
    }

    gates_passed = (
        metrics["permission_leak_count"] == 0
        and metrics["pii_leak_count"] == 0
        and metrics["citation_validity"] == 1.0
        and metrics["behavior_accuracy"] >= 0.90
        and metrics["retrieval_recall_at_8"] >= 0.85
        and metrics["answer_correctness"] >= 0.85
        and metrics["citation_precision"] >= 0.90
        and metrics["refusal_accuracy"] >= 0.90
        and metrics["clarify_accuracy"] >= 0.85
        and metrics["cross_lingual_gap"] <= 0.10
    )

    return {
        "suite": suite,
        "total_cases": total,
        "gates_passed": gates_passed,
        "metrics": metrics,
        "cases": case_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RAG + Agent Evaluation Suite")
    parser.add_argument("--suite", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--write-baseline", type=str, default=None)
    parser.add_argument("--compare", type=str, default=None)
    args = parser.parse_args()

    report = asyncio.run(run_evaluation(args.suite))
    repo_root = Path(__file__).resolve().parents[3]
    results_dir = repo_root / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    latest_path = results_dir / "latest.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))

    if args.write_baseline:
        base_path = Path(args.write_baseline)
        base_path.parent.mkdir(parents=True, exist_ok=True)
        base_path.write_text(
            json.dumps(report["metrics"], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.compare:
        base_metrics = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        for key in (
            "behavior_accuracy",
            "retrieval_recall_at_8",
            "answer_correctness",
            "citation_precision",
            "refusal_accuracy",
            "clarify_accuracy",
        ):
            if report["metrics"][key] < base_metrics.get(key, 0.0) - 0.02:
                print(
                    f"Regression detected on {key}: {report['metrics'][key]} < {base_metrics[key] - 0.02}"
                )
                return 1

    if not report["gates_passed"]:
        print("One or more evaluation quality gates failed!")
        return 1

    print("All evaluation quality gates PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
