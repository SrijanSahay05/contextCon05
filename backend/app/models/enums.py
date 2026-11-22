"""Status and kind enums shared by the ORM models and the API schemas.

Both layers import from here so the stored values and the API contract can't drift.
"""

from enum import StrEnum


class SourceKind(StrEnum):
    crustdata = "crustdata"
    web = "web"
    news = "news"
    email = "email"
    upload = "upload"
    llm = "llm"


class ReliabilityTier(StrEnum):
    a = "A"
    b = "B"
    c = "C"


class SubjectType(StrEnum):
    company = "company"
    person = "person"
    fund = "fund"
    investor = "investor"


class ExtractedBy(StrEnum):
    rule = "rule"
    llm = "llm"


class ReviewStatus(StrEnum):
    """Lifecycle of a thesis or scoring profile."""

    draft = "draft"
    confirmed = "confirmed"


class ProfileOrigin(StrEnum):
    derived = "derived"
    edited = "edited"
    generic = "generic"


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class SearchStatus(StrEnum):
    draft = "draft"
    confirmed = "confirmed"
    running = "running"
    done = "done"
    failed = "failed"


class RunKind(StrEnum):
    onboarding = "onboarding"
    search = "search"
    dd = "dd"
    recheck = "recheck"
    memo = "memo"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    held = "held"


class StepStatus(StrEnum):
    running = "running"
    done = "done"
    failed = "failed"


class Provider(StrEnum):
    crustdata = "crustdata"
    web = "web"
    llm = "llm"
    gmail = "gmail"


class UnitType(StrEnum):
    credits = "credits"
    input_tokens = "input_tokens"
    output_tokens = "output_tokens"


class CandidateStatus(StrEnum):
    new = "new"
    shortlist = "shortlist"
    in_dd = "in_dd"
    invest = "invest"
    watch = "watch"
    pass_ = "pass"


class DDStage(StrEnum):
    gaps_identified = "gaps_identified"
    request_drafted = "request_drafted"
    awaiting_founder = "awaiting_founder"
    ingesting = "ingesting"
    verifying = "verifying"
    ready_for_decision = "ready_for_decision"


class SuggestedAction(StrEnum):
    reach_out = "reach_out"
    request_data = "request_data"
    watch = "watch"
    pass_ = "pass"
    invest = "invest"


class SignalKind(StrEnum):
    strong = "strong"
    red_flag = "red_flag"
    gap = "gap"


class QuestionStatus(StrEnum):
    draft = "draft"
    approved = "approved"
    sent = "sent"
    answered = "answered"


class OutreachChannel(StrEnum):
    email = "email"
    linkedin = "linkedin"


class OutreachStatus(StrEnum):
    draft = "draft"
    approved = "approved"
    sending = "sending"
    sent = "sent"
    replied = "replied"


class SnapshotTrigger(StrEnum):
    initial = "initial"
    dd_ingest = "dd_ingest"
    watch_event = "watch_event"
    profile_change = "profile_change"
    override = "override"


class WatchReason(StrEnum):
    watch = "watch"
    pass_ = "pass"


class WatchEventStatus(StrEnum):
    open = "open"
    acted = "acted"
    dismissed = "dismissed"


class DDItemKind(StrEnum):
    deck = "deck"
    data_room = "data_room"
    financials = "financials"
    cap_table = "cap_table"
    grant_letter = "grant_letter"
    customer_refs = "customer_refs"
    answer = "answer"


class DDItemStatus(StrEnum):
    requested = "requested"
    received = "received"
    received_needs_access = "received_needs_access"
    verified = "verified"
    contradicted = "contradicted"
    unverifiable = "unverifiable"


class DocumentOrigin(StrEnum):
    email = "email"
    vc_upload = "vc_upload"
    founder_upload = "founder_upload"
    public = "public"


class ParseStatus(StrEnum):
    pending = "pending"
    parsed = "parsed"
    failed = "failed"


class VerificationResult(StrEnum):
    verified = "verified"
    contradicted = "contradicted"
    unverifiable = "unverifiable"
    self_reported = "self_reported"


class MailDirection(StrEnum):
    outbound = "outbound"
    inbound = "inbound"
