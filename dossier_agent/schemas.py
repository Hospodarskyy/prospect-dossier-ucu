from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Judge (LLM output)
# --------------------------------------------------------------------------
class JudgeFeedback(BaseModel):
    status: Literal["pass", "fail"] = Field(
        description="'pass' if the research is sufficient to write the dossier, "
        "otherwise 'fail'."
    )
    missing_sections: list[str] = Field(
        default_factory=list,
        description="Dossier sections that have no data and are not marked [Pending].",
    )
    unsourced_claims: list[str] = Field(
        default_factory=list,
        description="Claims in the research that have no source URL.",
    )
    stale_news: list[str] = Field(
        default_factory=list,
        description="News items older than 90 days.",
    )
    summary: str = Field(
        description="One or two sentences telling the researcher what to improve; "
        "a brief confirmation if status is 'pass'."
    )


# --------------------------------------------------------------------------
# result.json (validated before writing; spec section 0 "Спільний формат")
# Every field is filled by script (outbox.py), no LLM formatter.
# --------------------------------------------------------------------------
class NewsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Optional[str] = None
    title: str
    url: str


class PainItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis: str
    evidence_url: Optional[str] = None


class PendingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question: str
    source_ref: str = ""


class RunError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    message: str


class CaseRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None
    title: Optional[str] = None
    url: str


class DossierData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str
    domain: str
    iterations: int
    judge_status: Literal["pass", "fail"]
    facts_count: int
    unsourced_count: Optional[int]       # None: verification could not count
    news: list[NewsItem]
    pains: list[PainItem]
    seller: str                          # whose case studies the angle section uses
    seller_cases: list[CaseRef]
    previous_dossier_date: Optional[str]


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: str
    run_id: str
    status: Literal["ok", "partial", "failed"]
    trigger: Literal["inbox", "manual"]
    started_at: str
    items_processed: int
    pending_human: list[PendingItem]
    errors: list[RunError]
    usage: Optional[dict]                # filled by the hard stops (item 9)
    data: Optional[DossierData]          # None when the run failed
