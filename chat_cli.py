"""Terminal CLI chat client for testing Sahayak without a browser.

Usage:
  python chat_cli.py                     # Interactive REPL
  python chat_cli.py --demo              # Automated Unnao farmer scenario
  python chat_cli.py "Your message"      # Single message turn
"""

from __future__ import annotations

import io
import sys
import uuid

# Ensure Windows terminal prints unicode cleanly
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def print_trace(trace: list[dict]):
    if not trace:
        return
    print("\n   [Agents Trace]")
    for item in trace:
        agent = item.get("agent", "unknown")
        action = item.get("action", "")
        ms = item.get("ms", 0)
        print(f"   • {agent.upper():<12} ({ms:>3}ms): {action}")
    print()


def send_chat(session_id: str, message: str, lang: str = "en") -> dict:
    payload = {
        "session_id": session_id,
        "message": message,
        "lang": lang,
    }
    response = client.post("/chat", json=payload)
    if response.status_code != 200:
        print(f"[Error {response.status_code}]: {response.text}")
        return {}
    return response.json()


def run_demo():
    print("=" * 65)
    print("Running Unnao Farmer Demo Scenario (2 Turns)")
    print("=" * 65)

    session_id = f"cli-demo-{uuid.uuid4().hex[:8]}"

    # Turn 1
    msg1 = "I am a farmer in Unnao with two acres."
    print(f"\n[Citizen]: {msg1}")
    res1 = send_chat(session_id, msg1, lang="en")

    print_trace(res1.get("trace", []))
    print(f"[Sahayak]: {res1.get('reply')}")
    print(f"[State]:   {res1.get('state')}")

    # Turn 2: Follow-up response
    msg2 = "My annual family income is around 80,000 rupees."
    print(f"\n[Citizen]: {msg2}")
    res2 = send_chat(session_id, msg2, lang="en")

    print_trace(res2.get("trace", []))
    print(f"[Sahayak]:\n{res2.get('reply')}")
    print(f"\n[State]:   {res2.get('state')}")

    print("\n" + "=" * 65)
    print("✔ Demo Completed: Agent asked 1 follow-up, then matched schemes with reasons & links.")
    print("=" * 65)


def run_repl():
    print("=" * 65)
    print("Sahayak Terminal Chat (Type 'exit' to quit, 'start over' to reset)")
    print("=" * 65)

    session_id = f"cli-{uuid.uuid4().hex[:8]}"
    current_lang = "en"

    while True:
        try:
            user_msg = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not user_msg:
            continue
        if user_msg.lower() in {"exit", "quit", "q"}:
            print("Goodbye!")
            break

        res = send_chat(session_id, user_msg, lang=current_lang)
        if not res:
            continue

        print_trace(res.get("trace", []))
        print(f"Sahayak: {res.get('reply')}")
        print(f"(State: {res.get('state')})")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--demo":
            run_demo()
        else:
            # Run Turn 1 with provided string
            session_id = f"cli-single-{uuid.uuid4().hex[:8]}"
            print(f"[Citizen]: {arg}")
            res = send_chat(session_id, arg, lang="en")
            print_trace(res.get("trace", []))
            print(f"[Sahayak]:\n{res.get('reply')}")
            print(f"[State]: {res.get('state')}")
    else:
        # Default to running the Unnao farmer demo scenario
        run_demo()
