import json
import queue
import threading
from typing import Dict, Iterator, List


class RealtimeBroker:
    """In-process thread-safe event bus for Server-Sent Events (SSE)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: List[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event_type: str, data: Dict) -> int:
        message = {"event": event_type, "data": data}
        with self._lock:
            subscribers = list(self._subscribers)
        delivered = 0
        for q in subscribers:
            try:
                q.put_nowait(message)
                delivered += 1
            except queue.Full:
                pass
        return delivered

    def stream(self, heartbeat_seconds: int = 15) -> Iterator[str]:
        q = self.subscribe()
        try:
            yield "event: connected\ndata: {\"status\": \"ok\"}\n\n"
            while True:
                try:
                    msg = q.get(timeout=heartbeat_seconds)
                    payload = json.dumps(msg["data"])
                    yield f"event: {msg['event']}\ndata: {payload}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            self.unsubscribe(q)


realtime_broker = RealtimeBroker()
