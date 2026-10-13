"""Command-line entry point: python -m casa_agent.cli "what you want" """
from __future__ import annotations

import asyncio
import sys

from .agent import chat_turn


def main() -> None:
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        print('Usage: python -m casa_agent.cli "We are 3, renting in Chamberí, max 1800, need elevator"')
        sys.exit(1)
    result = asyncio.run(chat_turn([{"role": "user", "content": text}]))
    print(f"Params: {result.params.summary()}")
    print(f"{result.total_found} found → {result.after_dedup} unique → {result.matching} match\n")
    print(result.survey)


if __name__ == "__main__":
    main()
