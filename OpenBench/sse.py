import json
import queue
import threading
import uuid

_lock = threading.Lock()
_clients = {}  # {client_id: queue.Queue}


def subscribe():
    client_id = str(uuid.uuid4())
    q = queue.Queue(maxsize=64)
    with _lock:
        _clients[client_id] = q
    return client_id, q


def unsubscribe(client_id):
    with _lock:
        _clients.pop(client_id, None)


def broadcast(data):
    payload = json.dumps(data)
    with _lock:
        clients = list(_clients.values())
    for q in clients:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass
