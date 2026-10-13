"""DataPulse conceptual model: axioms, dimensions, scales and enforcement rules.

Platform-agnostic by design. Nothing in this module assumes a particular data
platform; platform-specific guidance lives only in lever implementation notes.
"""

FRAMEWORK_VERSION = "2.0.0"

AXIOMS = [
    {"id": "A1", "name": "Purpose", "text": "Data exists to reduce uncertainty in decisions."},
    {"id": "A2", "name": "Realization", "text": "Value is created at the point of consumption, not collection."},
    {"id": "A3", "name": "Enforcement", "text": "Governance is architecture, not bureaucracy. A policy that is not enforced by a system is a suggestion."},
    {"id": "A4", "name": "Ownership", "text": "Domains own data; platforms reduce the cognitive load of ownership."},
    {"id": "A5", "name": "Upper Bound", "text": "AI outcomes are bounded by data readiness: no AI system outperforms its weakest data dimension."},
    {"id": "A6", "name": "Funding", "text": "Modernization must pay for itself in waves. Every wave ships measurable value."},
    {"id": "A7", "name": "Consumers", "text": "AI agents are consumers of data, not exceptions to governance."},
]

LEVELS = {
    1: {"name": "Ad Hoc", "summary": "Depends on individuals; not repeatable; not measured."},
    2: {"name": "Standardized", "summary": "Documented and repeatable in places; enforced by people, not systems."},
    3: {"name": "Platform-Enabled", "summary": "Built into the platform for critical scope; owned and measured."},
    4: {"name": "AI-Assisted", "summary": "Measured end-to-end, enforced as code, and accelerated by AI with human review."},
    5: {"name": "Agentic", "summary": "Self-maintaining within policy; humans supervise exceptions and set policy."},
}

WEIGHTS = {"Critical": 3.0, "High": 2.0, "Standard": 1.0, "Trajectory": 0.5}

TIERS = {
    "T1": {
        "name": "Data for AI Readiness",
        "question": "Is the data ready to be consumed by people, models and agents?",
        "aggregation": "Readiness ceiling = min(R1..R6). R7 is reported as a trajectory and can never exceed its foundations.",
    },
    "T2": {
        "name": "AI for Data Capability",
        "question": "Is AI being used to make the data estate better, faster than people alone could?",
        "aggregation": "Weighted average (D2 25%, D3 20%, D4 20%, D1 15%, D5 10%, D6 10%). Emits flywheel status.",
    },
    "T3": {
        "name": "Execution Principles",
        "question": "Is the program run so that gains compound instead of dissipating?",
        "aggregation": "Simple average with a critical flag on any principle below 1.5.",
    },
}

DIMENSIONS = [
    # Tier 1 - Data for AI readiness
    {"id": "R1", "tier": "T1", "name": "Discoverable", "north_star": False,
     "definition": "People and machines can find the data that exists, who owns it and whether it is fit for purpose, without asking someone.",
     "failure_mode": "Teams rebuild datasets that already exist; AI projects stall on 'where is the data?'"},
    {"id": "R2", "tier": "T1", "name": "Understood", "north_star": False,
     "definition": "Meaning, lineage and caveats are explicit and machine-readable, so the same number means the same thing everywhere.",
     "failure_mode": "Meetings argue about whose number is right; models learn from fields nobody can explain."},
    {"id": "R3", "tier": "T1", "name": "Trusted", "north_star": False,
     "definition": "Quality expectations are published, measured and met; issues are caught before consumers see them.",
     "failure_mode": "Shadow spreadsheets re-check official numbers; AI outputs inherit silent data defects."},
    {"id": "R4", "tier": "T1", "name": "Governed", "north_star": False,
     "definition": "Access, classification, retention and audit are enforced by the platform, consistently across every engine and consumer.",
     "failure_mode": "Access takes weeks or is far too broad; nobody can prove who used what, for what purpose."},
    {"id": "R5", "tier": "T1", "name": "Integrated", "north_star": False,
     "definition": "New sources are onboarded quickly through standard patterns, and core entities resolve to one trusted view.",
     "failure_mode": "Every project reconciles customers and products again; onboarding a source takes a quarter."},
    {"id": "R6", "tier": "T1", "name": "Performant", "north_star": False,
     "definition": "Freshness, latency and cost meet what the decision or model actually needs, predictably and measurably.",
     "failure_mode": "Stale or slow data forces workarounds; costs grow with no unit economics."},
    {"id": "R7", "tier": "T1", "name": "Agent-Addressable", "north_star": True,
     "definition": "Agents can discover, understand and act on governed data through programmatic interfaces under the same policies as humans, with full traceability.",
     "failure_mode": "Agents run on shared credentials and copied data, outside governance, with no audit trail."},
    # Tier 2 - AI for data
    {"id": "D1", "tier": "T2", "name": "AI Discovery", "weight": 0.15, "north_star": False,
     "definition": "AI generates and maintains metadata and lets people find data in natural language.",
     "failure_mode": "Catalog coverage never catches up with the estate because curation is manual."},
    {"id": "D2", "tier": "T2", "name": "AI Quality", "weight": 0.25, "north_star": False,
     "definition": "AI infers quality rules, detects anomalies and accelerates root cause and remediation.",
     "failure_mode": "Hand-written rules cover a fraction of data; issues are found by consumers."},
    {"id": "D3", "tier": "T2", "name": "AI Governance", "weight": 0.20, "north_star": False,
     "definition": "AI systems are inventoried, risk-tiered and gated; AI is also used to enforce governance at scale.",
     "failure_mode": "Models and GenAI apps ship without inventory, evaluation or guardrails."},
    {"id": "D4", "tier": "T2", "name": "AI DataOps", "weight": 0.20, "north_star": False,
     "definition": "Pipelines are code, tested and deployed automatically, with AI accelerating build, test and operations.",
     "failure_mode": "Engineering capacity is consumed keeping fragile pipelines alive."},
    {"id": "D5", "tier": "T2", "name": "AI Semantics", "weight": 0.10, "north_star": False,
     "definition": "Business meaning is captured in a machine-readable semantic model that AI can reason over accurately.",
     "failure_mode": "AI assistants answer data questions confidently and incorrectly."},
    {"id": "D6", "tier": "T2", "name": "AI Stewardship", "weight": 0.10, "north_star": True,
     "definition": "Agents perform routine stewardship under human supervision, and readiness compounds measurably.",
     "failure_mode": "Stewardship is an unfunded side job; readiness decays as the estate grows."},
    # Tier 3 - Execution principles
    {"id": "P1", "tier": "T3", "name": "Domain Pain Sequencing", "north_star": False,
     "definition": "Work is sequenced by quantified business pain and data readiness, not by technology preference.",
     "failure_mode": "Platform-first programs build capability nobody consumes."},
    {"id": "P2", "tier": "T3", "name": "Funded Waves", "north_star": False,
     "definition": "Funding is released in waves gated on measured value from the previous wave.",
     "failure_mode": "Multi-year programs promise value at the end and lose sponsorship in the middle."},
    {"id": "P3", "tier": "T3", "name": "Platform Governance", "north_star": False,
     "definition": "Governance is enforced, logged and recoverable in the platform: guardrails, not review boards.",
     "failure_mode": "Policies live in documents; compliance depends on memory and goodwill."},
    {"id": "P4", "tier": "T3", "name": "Cognitive Load Reduction", "north_star": False,
     "definition": "Golden paths and self-service let domain teams deliver without becoming platform experts.",
     "failure_mode": "Every delivery queues behind a central team that knows the tools."},
    {"id": "P5", "tier": "T3", "name": "AI Accelerant", "north_star": False,
     "definition": "AI is applied, safely and measurably, to accelerate the data program itself.",
     "failure_mode": "AI is either banned and used anyway, or used without any measurement of benefit."},
    {"id": "P6", "tier": "T3", "name": "Consumer-First Design", "north_star": False,
     "definition": "Data products are specified by their consumers, including agents, and retired when unused.",
     "failure_mode": "Producers publish what they have; most published data is never used."},
    {"id": "P7", "tier": "T3", "name": "Velocity Measurement", "north_star": False,
     "definition": "Time from signal to decision to action is baselined and drives investment decisions.",
     "failure_mode": "Programs report activity (tables migrated) instead of outcomes (decisions accelerated)."},
]

DIM_INDEX = {d["id"]: d for d in DIMENSIONS}

VELOCITY = [
    {"id": "Discovery", "span": "'I have a question' to 'I found the right data'"},
    {"id": "Integration", "span": "'The data exists' to 'it is usable in my context'"},
    {"id": "Quality", "span": "'An issue exists' to 'the issue is resolved'"},
    {"id": "Insight", "span": "'Trusted data' to 'decision-ready insight or model'"},
    {"id": "Action", "span": "'Insight delivered' to 'action taken, with trust intact'"},
]

# Dimension precedence: a capability cannot run more than `slack` levels ahead
# of what it depends on. Evaluated in this order against already-enforced scores.
# "min" means the dependent is capped at min(upstreams) + slack.
DEPENDENCIES = [
    {"dim": "R2", "upon": ["R1"], "slack": 1.0, "why": "You cannot consistently define what you cannot find."},
    {"dim": "R3", "upon": ["R2"], "slack": 1.0, "why": "You cannot measure the quality of data whose meaning is not agreed."},
    {"dim": "R7", "upon": ["R1", "R2", "R3", "R4"], "slack": 0.0, "why": "Agent-addressability cannot exceed the foundations agents consume (A5, A7)."},
    {"dim": "D1", "upon": ["R1"], "slack": 1.0, "why": "AI cataloging amplifies an existing inventory; it cannot replace one."},
    {"dim": "D2", "upon": ["R3"], "slack": 1.0, "why": "AI quality needs defined expectations to learn from and enforce."},
    {"dim": "D3", "upon": ["R4"], "slack": 1.0, "why": "AI governance is built on data governance; models inherit data policies."},
    {"dim": "D4", "upon": ["P3"], "slack": 1.0, "why": "AI-accelerated delivery without platform guardrails accelerates risk."},
    {"dim": "D5", "upon": ["R2"], "slack": 1.0, "why": "A semantic model for AI needs governed definitions to encode."},
    {"dim": "D6", "upon": ["D1", "D2", "D3"], "slack": 0.0, "why": "Agentic stewardship is bounded by the AI capabilities it orchestrates."},
    {"dim": "P5", "upon": ["P3"], "slack": 1.0, "why": "AI acceleration of delivery requires enforced platform policy for AI usage."},
]

# AI job types and the readiness dimensions on their critical path (Scoping protocol, step 5).
JOBS = {
    "Inference": {"path": ["R1", "R2", "R3", "R4"], "desc": "Answers questions (BI copilots, RAG, text-to-SQL)."},
    "Training": {"path": ["R3", "R5", "R4", "R6"], "desc": "Learns patterns (predictive models, fine-tuning)."},
    "Agent": {"path": ["R7", "R4", "R1", "R2"], "desc": "Acts autonomously (tool-using agents, automated decisions, write-back)."},
}

# Levers that must be ENFORCED (not merely planned) before a job type can be marked Go.
JOB_LEVER_GATES = {
    "Agent": ["L-20", "L-21", "L-22"],
    "Training": ["L-11"],
    "Inference": [],
}

FLYWHEEL = [
    {"status": "Not Engaged", "rule": "Tier 2 below 2.0"},
    {"status": "Emerging", "rule": "Tier 2 from 2.0 to below 3.0"},
    {"status": "Active", "rule": "Tier 2 at 3.0 or above"},
    {"status": "Compounding", "rule": "Tier 2 at 4.0 or above and readiness ceiling at 4.0 or above"},
]

EVIDENCE_TYPES = [
    {"id": "attestation", "name": "Verbal attestation", "strength": 0,
     "desc": "Stated in interview. Useful for discovery; never sufficient on its own above level 2."},
    {"id": "document", "name": "Document / policy", "strength": 1,
     "desc": "Written standard, policy, runbook or design. Proves intent, not operation."},
    {"id": "artifact", "name": "Artifact / screenshot", "strength": 1,
     "desc": "An example output: a catalog page, a contract file, a dashboard. Proves existence."},
    {"id": "metric", "name": "System metric / log", "strength": 2,
     "desc": "Telemetry exported from a system: coverage %, MTTR, audit log query. Proves operation at scale."},
    {"id": "inspection", "name": "Platform inspection", "strength": 2,
     "desc": "Assessor observed it live in the platform, or ran the check themselves."},
]

LEVER_STATUSES = ["Proposed", "Committed", "Enforced", "Verified", "Retired"]

LEVER_TRANSITIONS = {
    "Proposed": ["Committed", "Retired"],
    "Committed": ["Enforced", "Proposed", "Retired"],
    "Enforced": ["Verified", "Committed", "Retired"],
    "Verified": ["Enforced", "Retired"],
    "Retired": ["Proposed"],
}

ENFORCEMENT_MODES = {
    "preventive": "Blocks the non-compliant action before it happens (gate, policy, failing check).",
    "detective": "Detects non-compliance quickly and routes it to an owner with an SLA.",
    "corrective": "Automatically remediates or rolls back non-compliance.",
    "directive": "Defines the standard and accountability; must be paired with a detective or preventive lever to count as enforced.",
}

RULES = [
    {"id": "ENF-01", "name": "Evidence gate: level 3", "applies": "question",
     "text": "A level of 3 or above needs at least one piece of evidence stronger than verbal attestation (document, artifact, metric or inspection).",
     "effect": "Validated mode: the question is capped at 2. Attested mode: a warning, and the evidence-backed score shows the cap."},
    {"id": "ENF-02", "name": "Evidence gate: level 4+", "applies": "question",
     "text": "A level of 4 or 5 needs operating evidence: a system metric/log or a platform inspection. Level 5 needs two independent pieces of evidence.",
     "effect": "Validated mode: capped at 3 (or 4 for level 5 with only one item). Attested mode: a warning."},
    {"id": "ENF-03", "name": "Metric triangulation", "applies": "dimension",
     "text": "Where a measured metric maps to a dimension, the dimension cannot exceed the metric-implied level by more than one.",
     "effect": "Dimension is capped at metric level + 1 and an inflation finding is raised."},
    {"id": "ENF-04", "name": "Weakest critical control", "applies": "dimension",
     "text": "If any Critical question in a dimension is at level 1, the dimension cannot score above 2.",
     "effect": "Dimension capped at 2.0; a blocker finding is raised."},
    {"id": "ENF-05", "name": "Dimension precedence", "applies": "dimension",
     "text": "A dimension cannot run more than its allowed slack ahead of the dimensions it depends on (see dependency table).",
     "effect": "Dimension capped at min(upstream) + slack."},
    {"id": "ENF-06", "name": "Readiness ceiling (A5)", "applies": "tier",
     "text": "Tier 1 readiness is the minimum of R1-R6, not the average. The binding constraint is named.",
     "effect": "Ceiling reported with its binding dimension(s); levers on the binding dimension are prioritised."},
    {"id": "ENF-07", "name": "Execution critical flag", "applies": "tier",
     "text": "Any execution principle below 1.5 is a critical flag regardless of the Tier 3 average.",
     "effect": "Critical finding; the roadmap must include a lever on that principle in Wave 0."},
    {"id": "ENF-08", "name": "Use-case gate", "applies": "use_case",
     "text": "A use case is Go only if every dimension on its job's critical path is at least 3, Conditional from 2, otherwise Blocked. Agent use cases are also Blocked until levers L-20, L-21 and L-22 are Enforced; Training use cases need L-11 Enforced.",
     "effect": "Use case status and the exact levers that unblock it."},
    {"id": "ENF-09", "name": "Lever lifecycle", "applies": "lever",
     "text": "Committed needs an owner, a wave and a KPI target. Enforced needs enforcement evidence, a KPI baseline, its prerequisite levers Enforced and its precondition levels met. Verified needs the KPI current value to meet its target. Directive-only levers must be paired with an enforced detective or preventive lever.",
     "effect": "The transition is rejected with the unmet conditions listed. An exception (with an approver, a justification and an expiry of 180 days or less) can override precondition levels only."},
    {"id": "ENF-10", "name": "Wave pays for itself (A6)", "applies": "roadmap",
     "text": "Every wave must contain at least one lever with time-to-value of 90 days or less, and must respect wave capacity.",
     "effect": "The roadmap generator enforces it; manual plans that violate it raise findings."},
    {"id": "ENF-11", "name": "Coverage", "applies": "dimension",
     "text": "A dimension with less than half its questions answered is provisional and is excluded from tier aggregation.",
     "effect": "Marked provisional; tier scores note the gap."},
    {"id": "ENF-12", "name": "Confidence", "applies": "question",
     "text": "A level of 4 or 5 recorded with low confidence is flagged for validation.",
     "effect": "Warning finding."},
    {"id": "ENF-13", "name": "Verification decay", "applies": "lever",
     "text": "A Verified lever must be re-verified every 90 days; an exception expires on its expiry date.",
     "effect": "Stale verifications and expired exceptions are reported; expired exceptions no longer override."},
]

ASSESSMENT_MODES = {
    "attested": "Phase 0 discovery. Evidence gates warn rather than cap; every other rule is enforced.",
    "validated": "Evidence-backed assessment. All rules, including evidence gates, cap scores.",
}

WAVES = [
    {"id": 0, "name": "Wave 0", "window": "0-90 days", "purpose": "Unblock the binding constraint and prove value fast."},
    {"id": 1, "name": "Wave 1", "window": "3-9 months", "purpose": "Industrialise the foundations the first use cases depend on."},
    {"id": 2, "name": "Wave 2", "window": "9-18 months", "purpose": "Turn on the flywheel: AI for data, agent readiness."},
]
