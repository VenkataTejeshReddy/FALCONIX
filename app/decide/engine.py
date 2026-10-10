# Owner: Laptop B
"""INX – Policy decision engine.

Evaluates the sorted policy rules from the scenario YAML against the
current :class:`CaseRecord` and produces a :class:`Decision`.

**The LLM never makes the decision.** All routing outcomes are determined
exclusively by rules loaded from ``config/<scenario>.yaml``.

Rule evaluation
---------------
Rules are evaluated in priority order. All matching rules fire.
Lowest priority number (highest severity) sets the route and workflow status,
while ALL reasons from all firing rules are preserved.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import ScenarioConfig, load_scenario
from app.schemas import (
    CaseRecord,
    Decision,
    DocumentType,
    FieldStatus,
    IssueKind,
    Route,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


def _build_eval_context(case: CaseRecord, config: ScenarioConfig) -> dict[str, Any]:
    """Build the safe, read-only namespace for rule expression evaluation."""
    # Check issue kinds
    issue_kinds = {issue.kind for issue in case.issues}

    has_conflict = case.has_conflict() or IssueKind.conflict in issue_kinds
    has_unreliable = case.has_unreliable() or IssueKind.unreliable in issue_kinds
    has_unclear = (
        any(f.status == FieldStatus.unclear for f in case.fields.values())
        or IssueKind.unclear in issue_kinds
    )

    # Missing documents or missing required fields
    has_missing_docs = bool(case.missing_documents) or IssueKind.missing_document in issue_kinds
    has_missing_fields = (
        any(f.status == FieldStatus.missing for f in case.fields.values())
        or IssueKind.missing in issue_kinds
    )
    has_missing = has_missing_docs or has_missing_fields

    # Unknown documents
    has_unknown_doc = (
        any(d.doc_type == DocumentType.unknown for d in case.documents)
        or IssueKind.unknown_type in issue_kinds
    )

    # Poor quality
    has_poor_quality = (
        any(d.quality_verdict == "poor" for d in case.documents)
        or IssueKind.poor_quality in issue_kinds
    )

    # All required docs present
    present_doc_types = {d.doc_type.value for d in case.documents}
    all_required_docs_present = all(
        rd in present_doc_types for rd in config.required_doc_types
    ) and not case.missing_documents

    # All required fields valid
    all_req_fields_valid = True
    if not case.fields or not case.documents:
        all_req_fields_valid = False
    else:
        for doc_name, doc_spec in config.documents.items():
            if not doc_spec.required:
                continue
            for fname, fspec in doc_spec.fields.items():
                if fspec.required:
                    k = CaseRecord.field_key(doc_name, fname)
                    fr = case.fields.get(k)
                    if fr is None or fr.status != FieldStatus.valid:
                        all_req_fields_valid = False
                        break

    # all_valid: no issues of any kind AND all required docs present AND all required fields valid
    all_valid = (
        len(case.issues) == 0
        and all_required_docs_present
        and all_req_fields_valid
        and not (
            has_conflict
            or has_unreliable
            or has_unclear
            or has_missing
            or has_unknown_doc
            or has_poor_quality
        )
    )

    return {
        "__builtins__": {},
        "has_conflict": has_conflict,
        "has_unreliable": has_unreliable,
        "has_unclear": has_unclear,
        "has_missing": has_missing,
        "has_unknown_doc": has_unknown_doc,
        "has_poor_quality": has_poor_quality,
        "all_valid": all_valid,
        "doc_types": [d.doc_type.value for d in case.documents],
    }


import ast


def _eval_ast_node(node: ast.AST, context: dict[str, Any]) -> Any:
    """Recursively evaluate safe AST expression nodes against context."""
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body, context)
    elif isinstance(node, ast.Name):
        return bool(context.get(node.id, False))
    elif isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_ast_node(node.operand, context)
    elif isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_ast_node(v, context) for v in node.values)
        elif isinstance(node.op, ast.Or):
            return any(_eval_ast_node(v, context) for v in node.values)
    elif isinstance(node, ast.Compare):
        left = _eval_ast_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_ast_node(comparator, context)
            if isinstance(op, ast.Eq) and not (left == right):
                return False
            elif isinstance(op, ast.NotEq) and not (left != right):
                return False
        return True
    return False


def _eval_rule(expression: str, context: dict[str, Any]) -> bool:
    """Safely evaluate a rule expression string against *context* using AST."""
    try:
        expr = expression.strip()
        if expr in context:
            return bool(context[expr])
        tree = ast.parse(expr, mode="eval")
        return bool(_eval_ast_node(tree, context))
    except Exception as e:
        logger.warning(f"Error evaluating rule expression {expression!r}: {e}")
        return False


def decide(case: CaseRecord, config: Optional[ScenarioConfig] = None) -> None:
    """Evaluate policy rules and attach the :class:`Decision` to *case*.

    Rules are evaluated in priority order. All matching rules fire.
    Lowest priority number (highest severity) sets route and status, while
    all reasons are kept. Empty or unknown input results in HUMAN_REVIEW.
    """
    if not case.scenario:
        decision = Decision(
            route=Route.HUMAN_REVIEW,
            workflow_status=WorkflowStatus.review_required,
            reasons=["Empty scenario: unclassified case requires human review."],
            rule_ids=[],
        )
        case.decision = decision
        case.workflow_status = decision.workflow_status
        return

    cfg = config or load_scenario(case.scenario)

    # Empty case guard
    if not case.documents and not case.fields:
        decision = Decision(
            route=Route.HUMAN_REVIEW,
            workflow_status=WorkflowStatus.review_required,
            reasons=["Empty submission with no documents or fields attached."],
            rule_ids=[],
        )
        case.decision = decision
        case.workflow_status = decision.workflow_status
        return

    context = _build_eval_context(case, cfg)
    sorted_rules = cfg.sorted_rules

    fired_rules = []
    for rule in sorted_rules:
        if _eval_rule(rule.condition, context):
            fired_rules.append(rule)

    if not fired_rules:
        decision = Decision(
            route=Route.HUMAN_REVIEW,
            workflow_status=WorkflowStatus.review_required,
            reasons=["No matching policy rule fired; defaulted to human review."],
            rule_ids=[],
        )
        case.decision = decision
        case.workflow_status = decision.workflow_status
        return

    # Fired rules: lowest priority number sets route and status (first in sorted list)
    best_rule = fired_rules[0]
    final_route = Route(best_rule.route)
    final_status = WorkflowStatus(best_rule.status)

    # Safety invariant: Never turn unknown/invalid into approved or PROCESS
    if (
        final_route == Route.PROCESS
        or final_status == WorkflowStatus.approved
    ) and not context["all_valid"]:
        final_route = Route.HUMAN_REVIEW
        final_status = WorkflowStatus.review_required

    all_rule_ids = [r.id for r in fired_rules]
    all_reasons = [r.display_reason.strip() for r in fired_rules if r.display_reason.strip()]

    decision = Decision(
        route=final_route,
        workflow_status=final_status,
        reasons=all_reasons,
        rule_ids=all_rule_ids,
    )
    case.decision = decision
    case.workflow_status = final_status
