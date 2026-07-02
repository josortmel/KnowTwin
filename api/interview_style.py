"""Interview style adaptation -- phrasing-only directives.

Determines interview style from employee profile (comm_style) + dynamic
signals (turn length, hedging, fatigue). Style directives affect question
PHRASING, never claim extraction, novelty, or turn_value math.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional

_HEDGE_WORDS = re.compile(
    r'\b(maybe|perhaps|i think|probably|i guess|not sure|kind of|sort of|might)\b',
    re.IGNORECASE,
)

VALID_STYLES = frozenset({"technical", "relational"})


@dataclass
class StyleDirective:
    framing: str
    follow_up_style: str
    length_guidance: str

    def to_dict(self) -> dict:
        return asdict(self)


def determine_style(
    comm_style: Optional[str],
    turn_texts: list[str],
) -> StyleDirective:
    """Compute style directive from profile + dynamic turn signals."""
    if comm_style == "technical":
        framing = (
            "Focus on architecture decisions, system dependencies, and technical tradeoffs. "
            "Use precise terminology."
        )
        follow_up = "Ask for specifics: data flows, failure modes, dependency chains."
    elif comm_style == "relational":
        framing = (
            "Focus on team dynamics, handoff processes, and interpersonal knowledge. "
            "Use conversational, empathetic phrasing."
        )
        follow_up = "Ask about who they work with, how decisions are communicated, informal agreements."
    else:
        framing = "Explore the topic broadly, then drill into specifics."
        follow_up = "Ask open-ended follow-ups, then narrow down."

    length_guidance = "Moderate length responses expected."

    if not turn_texts:
        return StyleDirective(framing=framing, follow_up_style=follow_up,
                              length_guidance=length_guidance)

    word_counts = [len(t.split()) for t in turn_texts]
    avg_words = sum(word_counts) / len(word_counts)

    if avg_words < 20:
        follow_up = "Ask specific, closed questions. Offer concrete examples to choose from."
        length_guidance = "Short answers detected — use targeted yes/no or multiple-choice prompts."

    recent_texts = turn_texts[-3:]
    hedge_count = sum(len(_HEDGE_WORDS.findall(t)) for t in recent_texts)
    if hedge_count >= 3:
        follow_up = (
            "Reformulate without pressure. Offer concrete scenarios "
            "instead of abstract questions."
        )
        length_guidance = "Vague responses detected — ground questions in specific situations."

    if len(word_counts) >= 3:
        recent = word_counts[-3:]
        if all(recent[i] < recent[i - 1] for i in range(1, len(recent))):
            follow_up = (
                "Keep prompts short. Focus only on critical remaining entities. "
                "Offer to pause if needed."
            )
            length_guidance = "Fatigue detected — prioritize critical gaps, minimize question length."

    return StyleDirective(framing=framing, follow_up_style=follow_up,
                          length_guidance=length_guidance)
