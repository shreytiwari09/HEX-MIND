"""The Mission Control live stream: `GET /ws/missions/{id}?after_seq=N` (PRD §12.4).

Protocol (JSON text frames):

1. client -> `{"type": "auth", "token": "<bearer token>"}` as the first frame, within
   `AUTH_TIMEOUT_S`. (A browser WebSocket cannot send an Authorization header, and a token in the
   URL would end up in logs.) Failure closes with code 4401; an unknown mission with 4404.
2. server -> `{"type": "snapshot", "mission": <MissionOut>, "last_seq": N}`: the mission as it is
   now, and the newest event it includes.
3. server -> `{"type": "event", "event": <EventOut>}` for every event of the mission's run with
   `seq > after_seq`, in order, then live as they happen. Without `after_seq` the stream starts
   after `last_seq` (history is `GET /api/runs/{run_id}/events`). A client that reconnects passes
   the last contiguous `seq` it saw, and `seq` has no gaps, so it can detect any it missed.
"""

import asyncio
import contextlib
import secrets
import uuid

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.api.missions import _mission_out
from app.api.schemas import EventOut
from app.db.models import Mission, Run
from app.events.log import list_events

router = APIRouter(tags=["stream"])

AUTH_TIMEOUT_S = 5.0
SAFETY_POLL_S = 5.0  # re-check even without a wake-up, in case the hub lost its connection
BATCH = 500

UNAUTHORIZED = 4401
NOT_FOUND = 4404


async def _authenticate(websocket: WebSocket) -> bool:
    try:
        frame = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT_S)
    except (TimeoutError, WebSocketDisconnect, ValueError, KeyError, RuntimeError):
        return False
    token = frame.get("token") if isinstance(frame, dict) else None
    expected: str = websocket.app.state.settings.api_token
    return (
        isinstance(frame, dict)
        and frame.get("type") == "auth"
        and isinstance(token, str)
        and secrets.compare_digest(token.encode(), expected.encode())
    )


@router.websocket("/ws/missions/{mission_id}")
async def mission_stream(
    websocket: WebSocket, mission_id: uuid.UUID, after_seq: int | None = None
) -> None:
    await websocket.accept()
    if not await _authenticate(websocket):
        await websocket.close(code=UNAUTHORIZED)
        return

    sessionmaker = websocket.app.state.sessionmaker
    hub = websocket.app.state.event_hub
    await hub.ensure_started()
    async with sessionmaker() as session:
        mission = await session.get(Mission, mission_id)
        run_id = mission.run_id if mission else None
    if run_id is None:
        await websocket.close(code=NOT_FOUND)
        return

    # Subscribe before reading anything, so no event slips between snapshot and stream. The
    # database connection is released before the (long) stream starts.
    with hub.subscribe(run_id) as wake:
        async with sessionmaker() as session:
            mission = await session.get(Mission, mission_id)
            run = await session.get(Run, run_id)
            assert mission is not None and run is not None
            snapshot = await _mission_out(session, mission)
            last_seq = run.last_event_seq
        cursor = last_seq if after_seq is None else max(after_seq, 0)
        await websocket.send_json(
            {"type": "snapshot", "mission": snapshot.model_dump(mode="json"), "last_seq": last_seq}
        )
        await _stream(websocket, sessionmaker, run_id, cursor, wake)


async def _stream(websocket, sessionmaker, run_id, cursor, wake) -> None:  # type: ignore[no-untyped-def]
    closed = asyncio.create_task(_until_disconnect(websocket))
    try:
        while not closed.done():
            wake.clear()  # clear, then read: a wake-up after this point is kept
            async with sessionmaker() as session:
                events = await list_events(session, run_id, after_seq=cursor, limit=BATCH)
            for event in events:
                await websocket.send_json(
                    {
                        "type": "event",
                        "event": EventOut.model_validate(event).model_dump(mode="json"),
                    }
                )
                cursor = event.seq
            if len(events) == BATCH:
                continue  # there may be more waiting
            waiter = asyncio.create_task(wake.wait())
            await asyncio.wait(
                {waiter, closed}, timeout=SAFETY_POLL_S, return_when=asyncio.FIRST_COMPLETED
            )
            waiter.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass  # the client went away mid-send
    finally:
        closed.cancel()
        if websocket.application_state == WebSocketState.CONNECTED:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close()


async def _until_disconnect(websocket: WebSocket) -> None:
    """Returns when the client disconnects; anything the client sends is ignored."""
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
