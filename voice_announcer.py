import queue
import threading

import pyttsx3

_speech_queue = queue.Queue()
_worker_started = False


def _worker():
    engine = pyttsx3.init()
    engine.setProperty("rate", 165)
    while True:
        text = _speech_queue.get()
        if text is None:
            break
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            print(f"Voice announcement failed: {exc}")


def _ensure_worker_started():
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def speak(text: str) -> None:
    """Queues a short phrase to be spoken aloud, without blocking the caller."""
    _ensure_worker_started()
    _speech_queue.put(text)
