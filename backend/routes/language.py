"""Creator Language Pack endpoints (commercial-intelligence phase, contract #1).

The creator's slang/multilingual glossary that makes the AI understand how they
talk and biases transcription toward their vocabulary. Visible/editable/exportable
(shareable `.lekprofile`), declarative and secret-free.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/language", tags=["language"])


class TermBody(BaseModel):
    term: str
    meaning: str
    lang: str = ""
    aliases: Optional[list[str]] = None


class ImportBody(BaseModel):
    terms: list[dict]
    mode: str = "merge"          # merge | replace


@router.get("/terms")
def list_terms():
    from modules.language_pack import list_terms
    return {"terms": list_terms()}


@router.post("/terms")
def add_term(body: TermBody):
    from modules.language_pack import add_term
    entry = add_term(body.term, body.meaning, lang=body.lang, aliases=body.aliases)
    if entry is None:
        raise HTTPException(status_code=400, detail="term and meaning are required")
    return {"term": entry}


@router.delete("/terms/{term}")
def delete_term(term: str):
    from modules.language_pack import delete_term
    return {"deleted": delete_term(term)}


@router.post("/seed-from-reviews")
def seed_from_reviews():
    """Mine review notes for slang the creator already explained."""
    from modules.language_pack import seed_from_reviews
    return seed_from_reviews()


@router.get("/hotwords")
def hotwords():
    """Transcription bias words (for the Whisper initial prompt)."""
    from modules.language_pack import whisper_hotwords
    return {"hotwords": whisper_hotwords()}


@router.get("/export")
def export_pack():
    from modules.language_pack import export_pack
    return export_pack()


@router.post("/import")
def import_pack(body: ImportBody):
    from modules.language_pack import import_pack
    try:
        return import_pack({"terms": body.terms}, mode=body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
