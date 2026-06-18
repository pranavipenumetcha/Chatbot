"""A command-line channel for the assistant.

Its entire job is to prove the point that "channel doesn't matter": it imports
the exact same ``Agent`` and ``Session`` the web server uses. No business logic
lives here — only reading stdin and printing stdout.

Run:  python -m app.channels.cli
"""
from __future__ import annotations

from app.agent.core import get_agent
from app.services.sessions import store

BANNER = """
========================================================
  Nestara Assistant — CLI channel
  Type your message and press Enter. Ctrl-C or 'quit' to exit.
========================================================
"""


def main() -> None:
    print(BANNER)
    session = store.get_or_create(None)
    agent = get_agent()
    try:
        while True:
            user = input("\nyou > ").strip()
            if user.lower() in {"quit", "exit"}:
                break
            if not user:
                continue
            reply = agent.handle(session, user)
            print(f"\nnestara > {reply}")
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
