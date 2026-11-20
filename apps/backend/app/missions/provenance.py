"""Provenance (PRD §14.2): where a changed file came from.

    file -> feature -> handoff -> agent instance -> model calls
         -> persona version + skill versions + plugins + model -> plan -> user approval

Everything here is read from what was recorded while the mission ran (handoffs, the event log,
`llm_calls`, validator reports), never from an agent's own account. The handoff's list of changed
files comes from git; the model calls are those the persona made during the attempt; the events
carry their audit-chain hashes, so each link can be checked against `GET /api/audit/verify`.

Granularity is the feature: a file is traced to the features whose commits changed it, in order.
It cannot say which line came from which tool call (hunk-level provenance is a stretch goal in
the PRD).
`to_prov` renders the same facts as W3C PROV-JSON for export.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentEvent,
    Checkpoint,
    FeatureRow,
    HandoffRow,
    LLMCall,
    Milestone,
    Mission,
    ValidatorReportRow,
)
from app.events import chain

EVENT_TYPES = (
    "mission_status_changed",
    "need_answered",
    "feature_status_changed",
    "handoff_recorded",
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _ref(event: AgentEvent | None) -> dict[str, Any] | None:
    """Where an event sits in the audit chain."""
    if event is None:
        return None
    return {"seq": event.seq, "ts": _iso(event.ts), "hash": event.hash}


async def build(session: AsyncSession, mission: Mission) -> dict[str, Any]:
    features = list(
        await session.scalars(
            select(FeatureRow)
            .where(FeatureRow.mission_id == mission.id)
            .order_by(FeatureRow.position)
        )
    )
    milestones = {
        m.id: m
        for m in await session.scalars(select(Milestone).where(Milestone.mission_id == mission.id))
    }
    by_id = {f.id: f for f in features}
    handoffs = list(
        await session.scalars(
            select(HandoffRow)
            .where(HandoffRow.mission_id == mission.id)
            .order_by(HandoffRow.created_at)
        )
    )
    checkpoints = {
        c.feature_id: c
        for c in await session.scalars(
            select(Checkpoint).where(Checkpoint.mission_id == mission.id)
        )
        if c.feature_id is not None and not c.label.startswith("Acceptance tests")
    }
    events = list(
        await session.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == mission.run_id, AgentEvent.type.in_(EVENT_TYPES))
            .order_by(AgentEvent.seq)
        )
    )
    calls = list(
        await session.scalars(
            select(LLMCall).where(LLMCall.run_id == mission.run_id).order_by(LLMCall.created_at)
        )
    )
    reports = list(
        await session.scalars(
            select(ValidatorReportRow)
            .where(ValidatorReportRow.mission_id == mission.id)
            .order_by(ValidatorReportRow.created_at)
        )
    )

    approval = next(
        (
            e
            for e in events
            if e.type == "mission_status_changed"
            and e.payload.get("previous") == "awaiting_approval"
            and e.payload.get("status") == "running"
        ),
        None,
    )
    decisions = [
        {"kind": "need_answered", "action": e.payload.get("action"), **(_ref(e) or {})}
        for e in events
        if e.type == "need_answered"
    ]

    changes: dict[str, list[dict[str, Any]]] = {}
    for handoff in handoffs:
        feature = by_id.get(handoff.feature_id)
        if feature is None:
            continue
        data = handoff.data
        # The attempt that was accepted began at the last "in progress" before its handoff
        # (retries and outages start new ones, so the attempt counter is not what to match).
        started = max(
            (
                e
                for e in events
                if e.type == "feature_status_changed"
                and e.payload.get("feature_id") == feature.key
                and e.payload.get("status") == "in_progress"
                and e.ts <= handoff.created_at
            ),
            key=lambda e: e.seq,
            default=None,
        )
        began = started.ts if started else None
        recorded = next(
            (
                e
                for e in events
                if e.type == "handoff_recorded"
                and e.payload.get("feature_id") == feature.key
                and e.ts >= handoff.created_at
            ),
            None,
        )
        made = [
            {
                "at": _iso(c.created_at),
                "purpose": c.purpose,
                "provider": c.provider,
                "model": c.model,
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cost_usd": float(c.est_cost_usd) if c.est_cost_usd is not None else None,
                "key_label": c.key_label,
                "request_sha256": c.request_sha256,
                "response_sha256": c.response_sha256,
                "error": c.error,
            }
            for c in calls
            if c.persona_id == feature.persona_id
            and c.created_at <= handoff.created_at
            and (began is None or c.created_at >= began)
        ]
        milestone = milestones.get(feature.milestone_id)
        verdicts = [
            {"validator": r.validator, "round": r.round, "verdict": r.verdict}
            for r in reports
            if milestone is not None and r.data.get("milestone_id") == milestone.key
        ]
        record = {
            "feature": {
                "id": feature.key,
                "title": feature.title,
                "milestone": milestone.key if milestone else None,
            },
            "persona": {"id": handoff.persona_id, "version": data.get("persona_version", 1)},
            "agent_id": f"{handoff.persona_id}_{handoff.attempt:02d}",
            "attempt": handoff.attempt,
            "model_used": data.get("model_used"),
            "variant_id": data.get("variant_id"),
            "skills": data.get("skills", []),
            "plugins": data.get("plugins", []),
            "commands": [
                {"command": c.get("command"), "exit_code": c.get("exit_code")}
                for c in data.get("commands", [])
            ],
            "commit": checkpoints[feature.id].commit if feature.id in checkpoints else None,
            "recorded_at": _iso(handoff.created_at),
            "handoff_event": _ref(recorded),
            "model_calls": made,
            "validated_by": verdicts,
        }
        for path in data.get("files_changed", []):
            changes.setdefault(path, []).append(record)

    audit = await chain.verify_run(session, mission.run_id)
    return {
        "mission": {
            "id": str(mission.id),
            "title": mission.title,
            "idea": mission.idea,
            "branch": mission.branch,
            "variant_id": mission.variant_id,
            "created_at": _iso(mission.created_at),
        },
        "plan": [
            {
                "id": f.key,
                "title": f.title,
                "persona": f.persona_id,
                "milestone": milestones[f.milestone_id].key
                if f.milestone_id in milestones
                else None,
                "expected_behavior": f.spec.get("expected_behavior", []),
            }
            for f in features
        ],
        "validation_contract": mission.validation_contract or [],
        "approval": _ref(approval),
        "decisions": decisions,
        "files": [{"path": path, "changes": entries} for path, entries in sorted(changes.items())],
        "audit": {
            "run_id": str(mission.run_id),
            "ok": audit.ok,
            "events": audit.events,
            "head": audit.head,
            "broken": None if audit.broken is None else audit.broken.reason,
        },
    }


def to_prov(doc: dict[str, Any]) -> dict[str, Any]:
    """The same facts as W3C PROV-JSON: files are entities generated by feature activities,
    performed by persona agents on the user's behalf, using the approved plan."""
    mission = doc["mission"]["id"]
    prefix = {"hex": "https://hexmind.local/prov#", "prov": "http://www.w3.org/ns/prov#"}
    entity: dict[str, Any] = {
        f"hex:plan-{mission}": {"prov:type": "hex:Plan", "hex:idea": doc["mission"]["idea"]},
    }
    activity: dict[str, Any] = {}
    agent: dict[str, Any] = {"hex:user": {"prov:type": "prov:Person"}}
    generated: dict[str, Any] = {}
    used: dict[str, Any] = {}
    associated: dict[str, Any] = {}
    delegated: dict[str, Any] = {}
    derived: dict[str, Any] = {}
    n = 0

    def key(prefix_: str) -> str:
        nonlocal n
        n += 1
        return f"_:{prefix_}{n}"

    if doc["approval"]:
        activity["hex:approval"] = {
            "prov:startTime": doc["approval"]["ts"],
            "hex:audit_hash": doc["approval"]["hash"],
        }
        associated[key("a")] = {"prov:activity": "hex:approval", "prov:agent": "hex:user"}
        used[key("u")] = {"prov:activity": "hex:approval", "prov:entity": f"hex:plan-{mission}"}
    for file in doc["files"]:
        file_id = f"hex:file-{file['path']}"
        entity[file_id] = {"prov:type": "hex:File", "hex:path": file["path"]}
        for change in file["changes"]:
            act = f"hex:work-{change['feature']['id']}-{change['attempt']}"
            persona = f"hex:persona-{change['persona']['id']}-v{change['persona']['version']}"
            instance = f"hex:agent-{change['agent_id']}"
            activity[act] = {
                "prov:endTime": change["recorded_at"],
                "hex:feature": change["feature"]["id"],
                "hex:model": change["model_used"],
                "hex:commit": change["commit"],
                "hex:skills": [s["version"] for s in change["skills"]],
                "hex:audit_hash": (change["handoff_event"] or {}).get("hash"),
            }
            agent[persona] = {
                "prov:type": "prov:SoftwareAgent",
                "hex:persona": change["persona"]["id"],
                "hex:version": change["persona"]["version"],
            }
            agent[instance] = {"prov:type": "prov:SoftwareAgent", "hex:attempt": change["attempt"]}
            generated[key("g")] = {"prov:entity": file_id, "prov:activity": act}
            used[key("u")] = {"prov:activity": act, "prov:entity": f"hex:plan-{mission}"}
            associated[key("a")] = {"prov:activity": act, "prov:agent": instance}
            delegated[key("d")] = {
                "prov:delegate": instance,
                "prov:responsible": "hex:user",
                "prov:activity": act,
            }
            derived[key("v")] = {
                "prov:generatedEntity": file_id,
                "prov:usedEntity": f"hex:plan-{mission}",
            }
            for index, call in enumerate(change["model_calls"]):
                call_id = f"hex:call-{act}-{index}"
                activity[call_id] = {
                    "prov:startTime": call["at"],
                    "hex:model": f"{call['provider']}:{call['model']}",
                    "hex:request_sha256": call["request_sha256"],
                    "hex:response_sha256": call["response_sha256"],
                }
                used[key("u")] = {"prov:activity": act, "prov:entity": call_id}
    return {
        "prefix": prefix,
        "entity": entity,
        "activity": activity,
        "agent": agent,
        "wasGeneratedBy": generated,
        "used": used,
        "wasAssociatedWith": associated,
        "actedOnBehalfOf": delegated,
        "wasDerivedFrom": derived,
    }
