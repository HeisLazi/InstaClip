"""Profile view/edit + LLM tuner endpoints."""

from fastapi import APIRouter, HTTPException

from backend.job_manager import jobs
from backend.schemas import ProfileAddRequest, ProfilePatchApply, ProfileRemoveRequest

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
def get_profile():
    from utils.profile_editor import EDITABLE_DICT_LISTS, EDITABLE_LISTS, load_profile

    return {
        "profile": load_profile(),
        "schema": {
            "lists":      {k: v for k, v in EDITABLE_LISTS.items()},
            "dict_lists": {k: v for k, v in EDITABLE_DICT_LISTS.items()},
        },
    }


@router.put("")
def save_profile(body: dict):
    """Body is the full profile dict (use sparingly — prefer add/remove/apply)."""
    from utils.profile_editor import save_profile as do_save
    do_save(body)
    return {"ok": True}


@router.post("/add")
def add(req: ProfileAddRequest):
    from utils.profile_editor import add_to_list, load_profile, save_profile
    profile = load_profile()
    added = add_to_list(profile, req.key, req.value)
    if added:
        save_profile(profile)
    return {"added": added, "profile": profile}


@router.post("/remove")
def remove(req: ProfileRemoveRequest):
    from utils.profile_editor import load_profile, remove_from_list, save_profile
    profile = load_profile()
    removed = remove_from_list(profile, req.key, req.value)
    if removed:
        save_profile(profile)
    return {"removed": removed, "profile": profile}


@router.post("/suggest")
def suggest():
    """Kick off the LLM tuner. Returns the patch synchronously (it's fast)
    but uses the job manager so the frontend can also poll if it wants."""

    def _do(handle):
        from modules.profile_tuner.profile_tuner import suggest_changes
        handle.progress(stage="thinking")
        return suggest_changes()

    job = jobs.submit("profile_suggest", _do)
    return {"job_id": job.id}


@router.post("/suggest-from-reviews")
def suggest_from_reviews():
    """
    Review-driven tuner: the LLM reads recent review notes and emits both
    structured profile patches AND free-form context_rules (rules that the
    flat profile cannot express, e.g. "silent horror running is clippable").
    The user previews the result and applies via /profile/apply, which will
    also persist context_rules to data/user_notes.md.
    """

    def _do(handle):
        from modules.profile_tuner.profile_tuner import suggest_changes_from_reviews
        handle.progress(stage="reading_reviews")
        return suggest_changes_from_reviews()

    job = jobs.submit("profile_suggest_from_reviews", _do)
    return {"job_id": job.id}


@router.post("/apply")
def apply_patch(patch: ProfilePatchApply):
    """Apply the user-curated patch from the LLM diff view."""
    from modules.clip_memory import (
        append_avoid_patterns,
        append_context_rules,
        append_learned_slang,
    )
    from utils.profile_editor import apply_patch, load_profile, save_profile

    profile = load_profile()
    if not profile:
        raise HTTPException(400, "no profile to patch")

    stats = apply_patch(profile, {"add": patch.add, "remove": patch.remove})
    if patch.save:
        save_profile(profile)

    # Persist the free-form review-tuner outputs to clip_memory.md so the
    # chat engine and future tuner runs see them across sessions.
    memory_writes: dict[str, int] = {}
    if patch.context_rules:
        try:
            memory_writes["context_rules_added"] = append_context_rules(patch.context_rules)
        except Exception as e:
            memory_writes["context_rules_error"] = str(e)
    if patch.slang_glossary:
        try:
            memory_writes["slang_entries_added"] = append_learned_slang(patch.slang_glossary)
        except Exception as e:
            memory_writes["slang_error"] = str(e)
    if patch.avoid_patterns:
        try:
            memory_writes["avoid_patterns_added"] = append_avoid_patterns(patch.avoid_patterns)
        except Exception as e:
            memory_writes["avoid_error"] = str(e)

    stats = {**stats, **memory_writes}
    return {"stats": stats, "profile": profile}


@router.get("/memory")
def get_memory():
    """Return the AI clip memory file + section stats. Used by the UI badge."""
    from modules.clip_memory import memory_stats, read_memory_for_llm
    return {
        "stats": memory_stats(),
        "content": read_memory_for_llm(),
    }


@router.post("/memory/refresh-twitch")
def refresh_twitch_memory_section():
    """Rebuild the 'Twitch-validated moments' section of clip_memory.md from
    the latest twitch_clip_notes.json sidecar."""
    from modules.clip_memory import refresh_twitch_summary
    count = refresh_twitch_summary()
    return {"twitch_clips_summarized": count}
