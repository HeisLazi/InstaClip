"""Deterministic transcript story analysis shared by short and long-form tools."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable

STORY_GRAPH_VERSION = 2

_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "was", "we", "were", "with", "you", "your", "establish", "show", "story", "whether",
}
_ROLE_TERMS = {
    "setup": {
        "begin", "challenge", "first", "goal", "going", "plan", "rules", "start",
        "started", "today", "try", "trying", "welcome",
    },
    "escalation": {
        "almost", "bad", "because", "but", "close", "hard", "harder", "lost",
        "problem", "suddenly", "then", "until", "wait", "wrong",
    },
    "payoff": {
        "complete", "completed", "done", "end", "final", "finally", "finish",
        "finished", "result", "reveal", "revealed", "success", "win", "winner", "won",
    },
    "reaction": {
        "crazy", "damn", "laugh", "laughed", "omg", "wow", "yoh", "yooh",
    },
    "callback": {"again", "before", "earlier", "remember", "said", "told"},
}
_TRANSITION_TERMS = {
    "after", "anyway", "later", "meanwhile", "next", "now", "second", "then",
}
_STREAM_TYPE_TERMS = {
    "challenge": {"challenge", "rules", "winner", "finish", "attempt", "round", "versus", "vs", "compete"},
    "reaction": {"react", "reaction", "watch", "video", "clip", "trailer", "episode"},
    "gaming": {"game", "gaming", "match", "ranked", "level", "boss", "round", "win", "lose"},
    "irl_event": {"irl", "outside", "restaurant", "event", "trip", "travel", "meet", "arrive", "venue"},
    "discussion": {"podcast", "discussion", "debate", "topic", "opinion", "question", "interview"},
    "dating_social": {"date", "dating", "blind", "girl", "boy", "couple", "balloon", "relationship"},
    "sports_watchalong": {"game", "team", "score", "quarter", "goal", "match", "player", "coach"},
}
_STREAM_CONTRACTS = {
    "challenge": ["premise and rules", "participants and stakes", "meaningful attempts", "escalation or setback", "decisive result", "aftermath"],
    "reaction": ["source context", "first impression", "important reveals", "strong reactions", "final verdict"],
    "gaming": ["match objective", "early state", "turning points", "clutch or failure", "result and reaction"],
    "irl_event": ["destination or plan", "arrival and setup", "key interactions", "main event", "aftermath"],
    "discussion": ["central question", "positions", "supporting examples", "strongest disagreement", "conclusion"],
    "dating_social": ["format and participants", "first impressions", "escalating interactions", "decision or reveal", "reactions"],
    "sports_watchalong": ["match context", "early momentum", "turning points", "decisive play", "result and reaction"],
    "variety": ["premise", "key segments", "escalation", "strongest payoff", "resolution"],
}


def _words(value: str) -> list[str]:
    return _WORD_RE.findall(value.lower())


def _content_tokens(value: str) -> set[str]:
    return {word for word in _words(value) if word not in _STOPWORDS and len(word) > 1}


def infer_stream_type(story_graph: dict[str, Any], brief: str = "") -> dict[str, Any]:
    """Infer the stream format so selection can follow the right story contract."""
    text = f"{brief} " + " ".join(str(beat.get("text") or "") for beat in story_graph.get("beats", []))
    tokens = _content_tokens(text)
    ranked = []
    for stream_type, terms in _STREAM_TYPE_TERMS.items():
        hits = sorted(tokens & terms)
        score = len(hits) / max(2, len(terms) ** 0.5)
        if stream_type == "challenge" and "challenge" in hits:
            score += 0.8
        if stream_type == "reaction" and ({"react", "reaction"} & set(hits)):
            score += 0.65
        ranked.append((score, stream_type, hits))
    score, stream_type, hits = max(ranked, default=(0.0, "variety", []))
    if score < 0.3:
        stream_type = "variety"
        hits = []
    confidence = _clamp(0.4 + min(0.5, score * 0.18), 0.35, 0.95)
    return {
        "inferredType": stream_type,
        "confidence": round(confidence, 4),
        "evidence": hits,
        "storyContract": list(_STREAM_CONTRACTS.get(stream_type, _STREAM_CONTRACTS["variety"])),
    }


def stream_story_contract(stream_type: str) -> list[str]:
    return list(_STREAM_CONTRACTS.get(stream_type, _STREAM_CONTRACTS["variety"]))


def match_required_events(story_graph: dict[str, Any], required_events: Iterable[str]) -> list[dict[str, Any]]:
    """Resolve must-include descriptions to timestamped beats and annotate them."""
    beats = list(story_graph.get("beats", []))
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    ignored = {"part", "segment", "moment", "scene", "section", "bit"}
    for raw_query in required_events:
        query = " ".join(str(raw_query or "").split()).strip()
        key = query.lower()
        if not query or key in seen:
            continue
        seen.add(key)
        query_tokens = _content_tokens(query) - ignored
        if not query_tokens:
            continue
        ranked = []
        for index, beat in enumerate(beats):
            local_text = str(beat.get("text") or "")
            local_tokens = _content_tokens(local_text)
            context_beats = beats[max(0, index - 1):min(len(beats), index + 2)]
            context_text = " ".join(str(item.get("text") or "") for item in context_beats)
            context_tokens = _content_tokens(context_text)
            local_coverage = len(query_tokens & local_tokens) / len(query_tokens)
            context_coverage = len(query_tokens & context_tokens) / len(query_tokens)
            exact = 1.0 if key in local_text.lower() else 0.0
            similarity = SequenceMatcher(None, key, local_text.lower()[:max(len(key) * 4, 120)]).ratio()
            score = local_coverage * 0.68 + context_coverage * 0.2 + exact * 0.08 + similarity * 0.04
            ranked.append((score, local_coverage, context_coverage, beat, context_beats))
        score, local_coverage, context_coverage, beat, context_beats = max(
            ranked, key=lambda item: item[0], default=(0.0, 0.0, 0.0, None, []),
        )
        matched = bool(beat and score >= 0.42 and context_coverage >= 0.5)
        if matched:
            beat.setdefault("requiredEvents", []).append(query)
        matches.append({
            "query": query,
            "matched": matched,
            "beatIds": [beat["id"]] if matched else [],
            "sourceStart": round(float(beat["start"]), 3) if matched else None,
            "sourceEnd": round(float(beat["end"]), 3) if matched else None,
            "confidence": round(score, 4),
            "evidence": str(beat.get("text") or "")[:240] if matched else "",
            "contextBeatIds": [item["id"] for item in context_beats] if matched else [],
        })
    story_graph["requiredEvents"] = matches
    return matches


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalise_segments(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for index, raw in enumerate(transcript.get("segments", [])):
        try:
            start = max(0.0, float(raw.get("start") or 0))
            end = float(raw.get("end") or 0)
        except (TypeError, ValueError):
            continue
        text = " ".join(str(raw.get("text") or "").split())
        if end <= start or not text:
            continue
        segments.append({"index": index, "start": start, "end": end, "text": text})
    return sorted(segments, key=lambda item: (item["start"], item["end"]))


def _starts_new_beat(segment: dict[str, Any], current: list[dict[str, Any]]) -> bool:
    if not current:
        return False
    gap = segment["start"] - current[-1]["end"]
    span = current[-1]["end"] - current[0]["start"]
    first_word = (_words(segment["text"]) or [""])[0]
    if gap > 8 or span >= 60:
        return True
    return span >= 28 and first_word in _TRANSITION_TERMS


def _group_segments(segments: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for segment in segments:
        if _starts_new_beat(segment, current):
            groups.append(current)
            current = []
        current.append(segment)
    if current:
        groups.append(current)
    return groups


def _title(text: str, role: str, index: int) -> str:
    words = [word for word in re.split(r"\s+", text.strip()) if word]
    while words and words[0].lower().strip(".,!?") in {"and", "but", "so", "then", "um", "uh", "yeah"}:
        words.pop(0)
    candidate = " ".join(words[:10]).strip(" .,!?:;-")
    if candidate:
        candidate = candidate[0].upper() + candidate[1:]
    return candidate[:72] or f"{role.title()} {index + 1}"


def _best_title_line(
    group: list[dict[str, Any]], role: str, brief_tokens: set[str], index: int,
) -> str:
    role_terms = _ROLE_TERMS.get(role, set())
    ranked = []
    for segment in group:
        tokens = _content_tokens(segment["text"])
        relevance = len(tokens & brief_tokens) / max(1, len(brief_tokens)) if brief_tokens else 0
        role_hits = len(tokens & role_terms)
        ranked.append((relevance * 0.65 + min(1.0, role_hits / 2) * 0.35, segment["text"]))
    return _title(max(ranked, key=lambda item: item[0])[1], role, index)


def _narrative_arc(beats: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    """Map transcript beats onto a setup-to-resolution dramatic spine."""
    if not beats:
        return []

    def position(beat: dict[str, Any]) -> float:
        return float(beat.get("start") or 0) / max(1.0, duration)

    early = [beat for beat in beats if position(beat) <= 0.3] or beats[:max(1, len(beats) // 3)]
    setup = max(
        early,
        key=lambda beat: float(beat.get("briefRelevance") or 0) * 0.45
        + float(beat.get("hookScore") or 0) * 0.2
        + (0.35 if beat.get("role") == "setup" else 0),
    )

    climax_pool = [
        beat for beat in beats
        if position(beat) >= 0.35 and beat["id"] != setup["id"]
        and beat.get("role") in {"escalation", "reaction", "payoff"}
    ] or [beat for beat in beats if beat["id"] != setup["id"]] or [setup]
    climax = max(
        climax_pool,
        key=lambda beat: float(beat.get("payoffScore") or 0) * 0.42
        + float(beat.get("hookScore") or 0) * 0.2
        + float(beat.get("score") or 0) * 0.28
        + min(0.1, position(beat) * 0.1),
    )

    between = [
        beat for beat in beats
        if float(setup["end"]) <= float(beat["start"]) < float(climax["start"])
    ]
    rising_pool = [beat for beat in between if beat.get("role") in {"development", "escalation", "callback"}] or between
    rising = sorted(
        rising_pool,
        key=lambda beat: float(beat.get("score") or 0) * 0.5
        + float(beat.get("briefRelevance") or 0) * 0.3
        + float(beat.get("hookScore") or 0) * 0.2,
        reverse=True,
    )[:3]
    rising.sort(key=lambda beat: float(beat["start"]))

    tension_pool = [beat for beat in between if beat.get("role") in {"escalation", "reaction"}] or rising_pool
    tension = max(
        tension_pool,
        key=lambda beat: float(beat.get("hookScore") or 0) * 0.45
        + float(beat.get("score") or 0) * 0.35
        + (0.2 if beat.get("role") == "escalation" else 0),
        default=None,
    )

    after = [beat for beat in beats if float(beat["start"]) >= float(climax["end"])]
    resolution_pool = [beat for beat in after if beat.get("role") in {"payoff", "callback", "development", "reaction"}] or after
    resolution = max(
        resolution_pool,
        key=lambda beat: float(beat.get("payoffScore") or 0) * 0.45
        + float(beat.get("score") or 0) * 0.35
        + position(beat) * 0.2,
        default=None,
    )

    stages: list[tuple[str, str, list[dict[str, Any]], str]] = [
        ("setup", "Setup", [setup], "Establishes the premise, rules, or central question."),
        ("rising_action", "Rising action", rising, "Adds meaningful developments between the premise and peak."),
        ("tension", "Tension", [tension] if tension else [], "Raises uncertainty, difficulty, or emotional pressure."),
        ("climax", "Climax", [climax], "Carries the strongest late payoff, reaction, or decisive turn."),
        ("resolution", "Resolution", [resolution] if resolution else [], "Shows the outcome, aftermath, or callback after the peak."),
    ]
    result = []
    for stage, label, stage_beats, why in stages:
        stage_beats = [beat for beat in stage_beats if beat]
        evidence = sorted({signal for beat in stage_beats for signal in beat.get("signals", [])})
        confidence = (
            sum(float(beat.get("confidence") or 0) for beat in stage_beats) / len(stage_beats)
            if stage_beats else 0.0
        )
        result.append({
            "stage": stage,
            "label": label,
            "beatIds": [beat["id"] for beat in stage_beats],
            "sourceStart": round(min((float(beat["start"]) for beat in stage_beats), default=0.0), 3),
            "sourceEnd": round(max((float(beat["end"]) for beat in stage_beats), default=0.0), 3),
            "confidence": round(confidence, 4),
            "evidence": evidence,
            "why": why,
        })
    return result


def analyze_story(transcript: dict[str, Any], brief: str = "") -> dict[str, Any]:
    """Turn timestamped transcript segments into explainable narrative beats."""
    segments = _normalise_segments(transcript)
    if not segments:
        return {"version": STORY_GRAPH_VERSION, "duration": 0.0, "brief": brief, "beats": []}
    groups = _group_segments(segments)
    duration = max(segment["end"] for segment in segments)
    brief_tokens = _content_tokens(brief)
    beats: list[dict[str, Any]] = []

    for index, group in enumerate(groups):
        start = group[0]["start"]
        end = group[-1]["end"]
        text = " ".join(segment["text"] for segment in group)
        tokens = _content_tokens(text)
        words = _words(text)
        phrase_text = " ".join(words)
        position = start / max(1.0, duration)
        term_hits = {role: sorted(tokens & terms) for role, terms in _ROLE_TERMS.items()}
        payoff_phrase = any(phrase in phrase_text for phrase in ("did it", "made it", "there we go", "finish the challenge", "finished the challenge"))
        reaction_phrase = any(phrase in phrase_text for phrase in ("are you serious", "no way", "oh my god", "what the fuck", "what is happening"))
        role_scores = {
            "setup": (len(term_hits["setup"]) * 0.22 + (0.32 if position < 0.2 else 0)) * (0.35 if position > 0.55 else 1),
            "escalation": len(term_hits["escalation"]) * 0.20 + (0.12 if 0.15 <= position <= 0.8 else 0),
            "payoff": len(term_hits["payoff"]) * 0.28 + (0.3 if payoff_phrase else 0) + (0.16 if position > 0.65 and term_hits["payoff"] else 0),
            "reaction": len(term_hits["reaction"]) * 0.28 + (0.35 if reaction_phrase else 0),
            "callback": len(term_hits["callback"]) * 0.28,
        }
        role, role_score = max(role_scores.items(), key=lambda item: item[1])
        if role_score < 0.28:
            role = "development"

        relevance = (
            len(tokens & brief_tokens) / max(1, len(brief_tokens))
            if brief_tokens else 0.35
        )
        question_signal = 1.0 if "?" in text or any(phrase in phrase_text for phrase in ("how did", "what happened", "what is happening", "why did")) else 0.0
        reaction_signal = _clamp(len(term_hits["reaction"]) / 2)
        if reaction_phrase:
            reaction_signal = _clamp(reaction_signal + 0.5)
        payoff_signal = _clamp(len(term_hits["payoff"]) / 2 + (0.45 if payoff_phrase else 0))
        hook_signal = _clamp(question_signal * 0.35 + reaction_signal * 0.45 + relevance * 0.35)
        density = _clamp(len(words) / max(1.0, end - start) / 2.5)
        role_value = {
            "setup": 0.62, "escalation": 0.72, "development": 0.48,
            "reaction": 0.78, "callback": 0.7, "payoff": 1.0,
        }[role]
        score = _clamp(
            relevance * 0.30 + hook_signal * 0.16 + payoff_signal * 0.25
            + density * 0.10 + role_value * 0.19
        )
        evidence = sorted({hit for hits in term_hits.values() for hit in hits})
        if brief_tokens & tokens:
            evidence.extend(sorted(brief_tokens & tokens))
        confidence = _clamp(0.42 + min(0.28, len(evidence) * 0.04) + abs(role_score - 0.28) * 0.18, 0.35, 0.95)
        beats.append({
            "id": f"beat_{index + 1:03d}",
            "index": index,
            "role": role,
            "title": _best_title_line(group, role, brief_tokens, index),
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "score": round(score, 4),
            "confidence": round(confidence, 4),
            "hookScore": round(hook_signal, 4),
            "payoffScore": round(payoff_signal, 4),
            "briefRelevance": round(relevance, 4),
            "visualDependency": "unknown",
            "signals": evidence,
            "text": text,
            "boundaryEvidence": {
                "firstSegment": group[0]["text"],
                "lastSegment": group[-1]["text"],
                "segmentStartIndex": group[0]["index"],
                "segmentEndIndex": group[-1]["index"],
            },
        })
    narrative_arc = _narrative_arc(beats, duration)
    stage_by_beat = {
        beat_id: stage["stage"]
        for stage in narrative_arc
        for beat_id in stage["beatIds"]
    }
    for beat in beats:
        beat["narrativeStage"] = stage_by_beat.get(beat["id"], "development")
    return {
        "version": STORY_GRAPH_VERSION,
        "duration": round(duration, 3),
        "brief": brief,
        "beats": beats,
        "narrativeArc": narrative_arc,
    }


def _merge_selected(beats: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for beat in sorted(beats, key=lambda item: item["start"]):
        if (
            sections
            and beat["start"] - sections[-1]["end"] <= 1
            and beat["role"] == sections[-1]["role"]
            and beat["end"] - sections[-1]["start"] <= 90
        ):
            section = sections[-1]
            section["end"] = beat["end"]
            section["duration"] = round(section["end"] - section["start"], 3)
            section["score"] = round(max(section["score"], beat["score"]), 4)
            section["beatIds"].append(beat["id"])
            section["roles"].append(beat["role"])
            section["requiredEvents"].extend(
                event for event in beat.get("requiredEvents", [])
                if event not in section["requiredEvents"]
            )
            section["text"] = f"{section['text']} {beat['text']}"
            section["why"] = f"{section['why']}; {beat['role']}: {beat['title']}"
            continue
        sections.append({
            "start": beat["start"],
            "end": beat["end"],
            "duration": beat["duration"],
            "score": beat["score"],
            "title": beat["title"],
            "role": beat["role"],
            "roles": [beat["role"]],
            "beatIds": [beat["id"]],
            "why": f"{beat['role']}: {beat['title']}",
            "text": beat["text"],
            "requiredEvents": list(beat.get("requiredEvents", [])),
        })
    return sections


def select_story_sections(
    story_graph: dict[str, Any], *, target_seconds: float, max_sections: int,
) -> list[dict[str, Any]]:
    """Choose a coherent setup-to-payoff sequence, then return source ranges."""
    beats = list(story_graph.get("beats", []))
    if not beats:
        return []
    max_sections = max(2, min(30, int(max_sections)))
    target_seconds = max(60.0, float(target_seconds))
    selected: dict[str, dict[str, Any]] = {}
    beat_by_id = {beat["id"]: beat for beat in beats}

    def add_best(candidates: list[dict[str, Any]], key) -> None:
        if candidates:
            beat = max(candidates, key=key)
            selected[beat["id"]] = beat

    early_limit = max(1, len(beats) // 3)
    add_best(
        [beat for beat in beats[:early_limit] if beat["role"] == "setup"] or beats[:early_limit],
        lambda beat: beat["score"] + beat["hookScore"] * 0.10 + beat["briefRelevance"] * 1.20,
    )
    add_best(
        [beat for beat in beats[max(0, len(beats) * 2 // 3):] if beat["role"] == "payoff"]
        or [beat for beat in beats if beat["role"] == "payoff"]
        or beats[-max(1, len(beats) // 3):],
        lambda beat: beat["score"] + beat["payoffScore"] * 0.4,
    )
    relevant_hooks = [beat for beat in beats if beat["briefRelevance"] > 0]
    add_best(relevant_hooks or beats, lambda beat: beat["hookScore"] + beat["score"] * 0.35 + beat["briefRelevance"] * 0.5)

    # Narrative coherence wins before generic score ranking. Keep one strong
    # representative of every available dramatic stage in source order.
    for stage in story_graph.get("narrativeArc", []):
        stage_beats = [beat_by_id[beat_id] for beat_id in stage.get("beatIds", []) if beat_id in beat_by_id]
        add_best(
            stage_beats,
            lambda beat: float(beat.get("score") or 0)
            + float(beat.get("hookScore") or 0) * 0.2
            + float(beat.get("payoffScore") or 0) * 0.25,
        )

    for event in story_graph.get("requiredEvents", []):
        for beat_id in event.get("beatIds", []):
            if beat_id in beat_by_id:
                selected[beat_id] = beat_by_id[beat_id]

    stream_context = story_graph.get("streamContext", {})
    if stream_context.get("selectedType") in {"challenge", "irl_event", "dating_social", "gaming", "sports_watchalong"}:
        coverage_candidates = [
            beat_by_id[segment["anchorBeatId"]]
            for segment in stream_context.get("sourceSegments", [])
            if segment.get("anchorBeatId") in beat_by_id and segment["anchorBeatId"] not in selected
        ]
        duration = max(1.0, float(story_graph.get("duration") or 0))
        while coverage_candidates and len(selected) < max_sections:
            existing_positions = [float(beat.get("start") or 0) / duration for beat in selected.values()]
            beat = max(
                coverage_candidates,
                key=lambda item: min(
                    (abs(float(item.get("start") or 0) / duration - position) for position in existing_positions),
                    default=1.0,
                ) + float(item.get("score") or 0) * 0.08,
            )
            selected[beat["id"]] = beat
            coverage_candidates.remove(beat)

    total = sum(beat["duration"] for beat in selected.values())
    ranked = sorted(
        [beat for beat in beats if beat["duration"] >= 5 or beat["role"] == "payoff"],
        key=lambda beat: (
            beat["score"]
            + (0.12 if beat["role"] in {"escalation", "reaction", "callback"} else 0)
            + beat["briefRelevance"] * 0.16
            + float(beat.get("mediaSignals", {}).get("visualActivity", 0)) * 0.06
        ),
        reverse=True,
    )
    for beat in ranked:
        if len(selected) >= max_sections:
            break
        if total >= target_seconds and len(selected) >= 3:
            break
        if beat["id"] in selected:
            continue
        if story_graph.get("brief") and beat["briefRelevance"] <= 0 and beat["role"] != "payoff":
            continue
        selected[beat["id"]] = beat
        total += beat["duration"]
    return _merge_selected(selected.values())


def build_chapters(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = 0.0
    chapters = []
    for index, section in enumerate(sections):
        duration = float(section["duration"])
        chapters.append({
            "id": f"chapter_{index + 1:02d}",
            "title": section.get("title") or f"Part {index + 1}",
            "timelineStart": round(cursor, 3),
            "timelineEnd": round(cursor + duration, 3),
            "sourceStart": section["start"],
            "sourceEnd": section["end"],
            "beatIds": list(section.get("beatIds", [])),
            "role": section.get("role", "development"),
        })
        cursor += duration
    return chapters


def build_quality_report(
    sections: list[dict[str, Any]], story_graph: dict[str, Any], *, target_seconds: float,
) -> dict[str, Any]:
    """Report narrative risks without pretending an automatic cut is editorially final."""
    duration = float(story_graph.get("duration") or 0)
    selected_seconds = sum(float(section.get("duration") or 0) for section in sections)
    roles = {role for section in sections for role in section.get("roles", [section.get("role")]) if role}
    selected_beat_ids = {beat_id for section in sections for beat_id in section.get("beatIds", [])}
    warnings: list[dict[str, str]] = []
    if sections:
        opening = float(sections[0].get("start") or 0)
        if opening > max(60.0, duration * 0.08):
            warnings.append({
                "code": "late_opening",
                "severity": "review",
                "message": f"The cut starts {opening / 60:.1f} minutes into the source. Confirm the challenge setup is still understandable.",
            })
        gaps = [
            float(current.get("start") or 0) - float(previous.get("end") or 0)
            for previous, current in zip(sections, sections[1:])
        ]
        if gaps and max(gaps) > 90:
            warnings.append({
                "code": "large_source_jump",
                "severity": "review",
                "message": f"The rough cut skips up to {max(gaps) / 60:.1f} source minutes between sections. Review the hard-cut continuity.",
            })
    if "setup" not in roles:
        warnings.append({"code": "missing_setup", "severity": "blocker", "message": "No setup beat was selected."})
    if "payoff" not in roles:
        warnings.append({"code": "missing_payoff", "severity": "blocker", "message": "No payoff beat was selected."})
    for stage in story_graph.get("narrativeArc", []):
        beat_ids = set(stage.get("beatIds", []))
        if not beat_ids:
            warnings.append({
                "code": f"missing_{stage['stage']}",
                "severity": "review" if stage["stage"] in {"rising_action", "resolution"} else "blocker",
                "message": f"The story graph could not identify a supported {stage['label'].lower()} beat.",
            })
        elif not (beat_ids & selected_beat_ids):
            warnings.append({
                "code": f"unselected_{stage['stage']}",
                "severity": "review",
                "message": f"The {stage['label'].lower()} evidence was not included in the rough cut.",
            })
    required_event_coverage = []
    for event in story_graph.get("requiredEvents", []):
        matched_ids = set(event.get("beatIds", []))
        included = bool(matched_ids & selected_beat_ids)
        required_event_coverage.append({
            **event,
            "included": included,
        })
        if not event.get("matched"):
            warnings.append({
                "code": f"required_event_unmatched_{len(required_event_coverage)}",
                "severity": "blocker",
                "message": f"Required moment could not be located: {event.get('query', 'unknown moment')}.",
            })
        elif not included:
            warnings.append({
                "code": f"required_event_missing_{len(required_event_coverage)}",
                "severity": "blocker",
                "message": f"Required moment was located but omitted: {event.get('query', 'unknown moment')}.",
            })
    if duration > target_seconds and selected_seconds < target_seconds * 0.7:
        warnings.append({
            "code": "target_shortfall",
            "severity": "review",
            "message": f"The selected story is {selected_seconds / 60:.1f} minutes versus a {target_seconds / 60:.1f}-minute target.",
        })
    grade = "blocked" if any(item["severity"] == "blocker" for item in warnings) else "review" if warnings else "ready"
    return {
        "grade": grade,
        "warnings": warnings,
        "metrics": {
            "selectedSeconds": round(selected_seconds, 3),
            "sourceCoverage": round(selected_seconds / duration, 4) if duration else 0,
            "targetSeconds": round(target_seconds, 3),
            "roleCoverage": sorted(roles),
            "arcCoverage": [
                stage["stage"] for stage in story_graph.get("narrativeArc", [])
                if set(stage.get("beatIds", [])) & selected_beat_ids
            ],
            "requiredEventCoverage": required_event_coverage,
        },
    }


def suggest_flashbacks(story_graph: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    """Suggest later high-energy/payoff excerpts for an opening cold-open montage."""
    duration = float(story_graph.get("duration") or 0)
    eligible = [
        beat for beat in story_graph.get("beats", [])
        if float(beat.get("start") or 0) >= min(30.0, duration * 0.12)
        and beat.get("role") in {"escalation", "reaction", "callback", "payoff"}
    ]
    ranked = sorted(
        eligible,
        key=lambda beat: beat.get("hookScore", 0) * 0.42
        + beat.get("payoffScore", 0) * 0.42
        + beat.get("score", 0) * 0.16,
        reverse=True,
    )[:max(0, min(5, int(limit)))]
    suggestions = []
    for beat in ranked:
        end = float(beat["end"])
        stage = str(beat.get("narrativeStage") or "development")
        # A cold open should tease the pressure, not reveal the final answer.
        start = float(beat["start"])
        if stage not in {"tension", "climax"}:
            start = max(start, end - 12.0)
        teaser_end = min(end, start + (8.0 if stage == "climax" else 12.0))
        suggestions.append({
            "beatId": beat["id"],
            "title": beat["title"],
            "role": beat["role"],
            "sourceStart": round(start, 3),
            "sourceEnd": round(teaser_end, 3),
            "narrativeStage": stage,
            "score": round(
                beat.get("hookScore", 0) * 0.42
                + beat.get("payoffScore", 0) * 0.42
                + beat.get("score", 0) * 0.16,
                4,
            ),
            "why": f"{beat['role']} beat with hook {beat['hookScore']:.0%} and payoff {beat['payoffScore']:.0%}",
        })
    return suggestions


__all__ = [
    "STORY_GRAPH_VERSION", "analyze_story", "build_chapters", "build_quality_report",
    "infer_stream_type", "match_required_events", "select_story_sections", "stream_story_contract", "suggest_flashbacks",
]
