"""In-process flight table for cancel/stop of the provider socket.

The per-chat lock lives in sessions (API layer). This table only tracks the
open provider connection for a request_id so /api/stop can close it.
"""

from __future__ import annotations

import threading
import time

FLIGHT_LOCK = threading.Lock()
FLIGHTS: dict[str, dict] = {}
FLIGHTS_BY_SUBMISSION: dict[str, dict] = {}


def begin_flight(request_id: str, submission_id: str | None = None) -> dict:
    flight = {
        "request_id": request_id,
        "submission_id": submission_id if isinstance(submission_id, str) and submission_id else None,
        "cancel": threading.Event(),
        "conn": None,
        "sock": None,
        "turn": 0,
        "started": time.monotonic(),
    }
    with FLIGHT_LOCK:
        FLIGHTS[request_id] = flight
        if flight["submission_id"]:
            FLIGHTS_BY_SUBMISSION[flight["submission_id"]] = flight
    return flight


def end_flight(request_id: str) -> None:
    with FLIGHT_LOCK:
        flight = FLIGHTS.pop(request_id, None)
        if not flight:
            return
        submission_id = flight.get("submission_id")
        if submission_id and FLIGHTS_BY_SUBMISSION.get(submission_id) is flight:
            FLIGHTS_BY_SUBMISSION.pop(submission_id, None)
        held = flight.get("sock")
        flight["sock"] = None
    if held is not None:
        closer = getattr(held, "close", None)
        if closer:
            try:
                closer()
            except OSError:
                pass


def note_turn(request_id: str, turn: int) -> None:
    with FLIGHT_LOCK:
        flight = FLIGHTS.get(request_id)
        if flight is not None:
            flight["turn"] = turn


def flight_turn(request_id: str) -> int:
    with FLIGHT_LOCK:
        flight = FLIGHTS.get(request_id)
        return flight["turn"] if flight else 0


def provider_cancelled(request_id: str) -> bool:
    with FLIGHT_LOCK:
        flight = FLIGHTS.get(request_id)
        return bool(flight and flight["cancel"].is_set())


def attach_provider(request_id: str, connection, sock=None) -> None:
    with FLIGHT_LOCK:
        flight = FLIGHTS.get(request_id)
        if flight is None:
            return
        flight["conn"] = connection
        if sock is not None:
            previous = flight.get("sock")
            flight["sock"] = sock
            if previous is not None and previous is not sock:
                closer = getattr(previous, "close", None)
                if closer:
                    try:
                        closer()
                    except OSError:
                        pass


def stop_request(*, request_id: str | None = None, submission_id: str | None = None) -> dict:
    """Cancel the in-flight provider call. Returns {ok, stopped, settled}."""
    if not isinstance(request_id, str) or not request_id:
        request_id = None
    if not isinstance(submission_id, str) or not submission_id:
        submission_id = None
    with FLIGHT_LOCK:
        flight = FLIGHTS.get(request_id) if request_id else None
        if flight is None and submission_id:
            flight = FLIGHTS_BY_SUBMISSION.get(submission_id)
        if flight is None:
            return {"ok": True, "stopped": False, "settled": True}
        flight["cancel"].set()
        held = flight.get("sock")
        flight["sock"] = None
        request_id = flight["request_id"]
    if held is not None:
        closer = getattr(held, "close", None)
        if closer:
            try:
                closer()
            except OSError:
                pass
    # Brief wait for the turn to notice cancel.
    for _ in range(50):
        with FLIGHT_LOCK:
            if request_id not in FLIGHTS:
                return {"ok": True, "stopped": True, "settled": True}
        time.sleep(0.02)
    return {"ok": True, "stopped": True, "settled": request_id not in FLIGHTS}


def clear_flights() -> None:
    """Tests only."""
    with FLIGHT_LOCK:
        FLIGHTS.clear()
        FLIGHTS_BY_SUBMISSION.clear()
