#!/usr/bin/env python3
"""Prompt enhancement primitives for Codex Control."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptVariant:
    id: str
    title: str
    summary: str
    prompt: str
    action: str = "interactive"
    profile: str = "maximum-power"
    web: str = "live"


VALID_ACTIONS = {"interactive", "exec", "review"}
VALID_PROFILES = {"maximum-power", "pro-default", "spark-fast", "safe-explore", "deep-review", "autonomous-workspace"}
VALID_WEB = {"live", "cached", "disabled", "config"}


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text or "Improve this project to the highest practical quality."


def _mentions_any(text: str, words: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(word in low for word in words)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "ai-variant"


def _task_context(raw: str, project_context: str = "") -> str:
    context = (
        "User request:\n"
        f"{raw}\n\n"
        "Work from the selected project. Read the relevant local files first, preserve "
        "the existing architecture where it is sound, and verify the result before finishing."
    )
    if project_context.strip():
        context += "\n\nProject context:\n" + project_context.strip()
    return context


def enhance_prompt(raw_text: str, project_context: str = "") -> list[PromptVariant]:
    raw = _clean(raw_text)
    context = _task_context(raw, project_context)
    variants: list[PromptVariant] = []

    variants.append(PromptVariant(
        id="best-upfront",
        title="Best Upfront",
        summary="Research when needed, implement end to end, polish, and validate.",
        prompt=(
            "Use $best-upfront-codex. Deliver the best practical version upfront.\n\n"
            f"{context}\n\n"
            "Before editing, identify the real user workflow and the highest-leverage "
            "implementation path. Then implement the change, refine the user-facing "
            "experience, run the relevant checks, inspect the result, and report exactly "
            "what changed."
        ),
    ))

    variants.append(PromptVariant(
        id="original",
        title="Use As Written",
        summary="Pass your prompt through unchanged.",
        prompt=raw,
    ))

    variants.append(PromptVariant(
        id="power-build",
        title="Power Build",
        summary="Direct execution with strong defaults and minimal ceremony.",
        prompt=(
            f"{context}\n\n"
            "Implement this directly. Keep the work cohesive, avoid unrelated churn, "
            "and make the first result genuinely usable. Run the narrowest reliable "
            "verification checks before finalizing."
        ),
    ))

    variants.append(PromptVariant(
        id="architect",
        title="Architect Then Build",
        summary="Use for bigger changes that need structure before edits.",
        prompt=(
            f"{context}\n\n"
            "First map the current structure and choose a maintainable architecture. "
            "Then implement the highest-value slice without turning the codebase into a "
            "rewrite. Prefer clear module boundaries, durable names, and validation that "
            "will keep future work honest."
        ),
    ))

    variants.append(PromptVariant(
        id="research-grade",
        title="Research Grade",
        summary="Verify current facts and primary docs before implementation.",
        prompt=(
            f"{context}\n\n"
            "Start with source-of-truth research for any current APIs, packages, docs, "
            "or product behavior involved. Use primary sources. Then implement the "
            "best-supported approach and include citations or local references for any "
            "important external assumptions."
        ),
    ))

    if _mentions_any(raw, ("bug", "fix", "broken", "error", "crash", "fail", "traceback")):
        variants.append(PromptVariant(
            id="bug-hunt",
            title="Bug Hunt",
            summary="Reproduce or isolate first, then fix with a tight verification.",
            prompt=(
                f"{context}\n\n"
                "Treat this as a bug investigation. Reproduce or isolate the failure "
                "first, identify the smallest high-confidence fix, implement it, and run "
                "a focused check that would have caught the bug."
            ),
        ))

    if _mentions_any(raw, ("ui", "gui", "design", "visual", "premium", "screen", "layout")):
        variants.append(PromptVariant(
            id="product-polish",
            title="Product Polish",
            summary="Best for visible UI/UX work that needs screenshot validation.",
            prompt=(
                f"{context}\n\n"
                "Treat this as production UI work. Make the primary workflow obvious, "
                "use dense professional controls, avoid placeholder screens, verify text "
                "fit and visual hierarchy, then launch the app and inspect screenshots "
                "before finalizing."
            ),
        ))

    variants.append(PromptVariant(
        id="deep-review",
        title="Deep Review",
        summary="Use when you want risks, defects, and test gaps before edits.",
        prompt=(
            f"{context}\n\n"
            "Review before editing. Prioritize bugs, regressions, security concerns, "
            "maintainability risks, and missing verification. If changes are clearly "
            "needed, implement them after the review with focused checks."
        ),
        action="review",
        profile="deep-review",
        web="config",
    ))

    seen: set[str] = set()
    unique: list[PromptVariant] = []
    for variant in variants:
        if variant.id in seen:
            continue
        seen.add(variant.id)
        unique.append(variant)
    return unique[:6]


def model_variant_request(raw_text: str, project_context: str = "") -> str:
    raw = _clean(raw_text)
    context = project_context.strip() or "No project snapshot is available."
    return (
        "You are improving prompts for a local Codex CLI GUI. "
        "Return only JSON, with no markdown and no commentary.\n\n"
        "Create 4 prompt variants for the request below. Each variant must be useful, "
        "distinct, and ready to pass directly to Codex. Do not tell Codex to ask clarifying "
        "questions unless that is the core purpose of the variant. Do not modify files; this "
        "is only prompt drafting.\n\n"
        "Allowed action values: interactive, exec, review.\n"
        "Allowed profile values: maximum-power, pro-default, spark-fast, safe-explore, deep-review, autonomous-workspace.\n"
        "Allowed web values: live, cached, disabled, config.\n\n"
        "JSON shape:\n"
        "{\n"
        '  "variants": [\n'
        '    {"title": "Best Upfront", "summary": "Short chooser text", "prompt": "Full prompt", "action": "interactive", "profile": "maximum-power", "web": "live"}\n'
        "  ]\n"
        "}\n\n"
        f"User request:\n{raw}\n\n"
        f"Project context:\n{context}\n"
    )


def _extract_json(text: str) -> object:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def parse_model_variants(text: str, raw_text: str, project_context: str = "") -> list[PromptVariant]:
    try:
        payload = _extract_json(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return enhance_prompt(raw_text, project_context)

    if isinstance(payload, dict):
        items = payload.get("variants", [])
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    variants: list[PromptVariant] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or f"AI Variant {index + 1}").strip()[:48]
        summary = str(item.get("summary") or "Model-generated prompt option.").strip()[:140]
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue
        action = str(item.get("action") or "interactive").strip()
        profile = str(item.get("profile") or "maximum-power").strip()
        web = str(item.get("web") or "live").strip()
        variants.append(PromptVariant(
            id="ai-" + _slug(title),
            title=title,
            summary=summary,
            prompt=prompt,
            action=action if action in VALID_ACTIONS else "interactive",
            profile=profile if profile in VALID_PROFILES else "maximum-power",
            web=web if web in VALID_WEB else "live",
        ))
        if len(variants) >= 6:
            break

    return variants or enhance_prompt(raw_text, project_context)
