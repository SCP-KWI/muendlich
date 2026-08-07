"""Live check of the Anthropic structurer. Requires ANTHROPIC_API_KEY.

Run from backend/:  AI_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-... python -m scripts.smoke_anthropic

Calls the real cloud model on a sample German dictation and prints the parsed
per-student observations. Does NOT touch the database.
"""
import os
import sys

from app.ai.structurer_anthropic import AnthropicStructurer

SAMPLE = (
    "Anna war heute super und hat Beatrice geholfen. Colin ging mir auf die "
    "Nerven. Darian war unaufmerksam. Felicia hatte ihre Hausaufgaben nicht dabei."
)


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — skipping live Anthropic test.")
        sys.exit(0)

    structurer = AnthropicStructurer()
    observations = structurer.structure(SAMPLE, language="de")

    print(f"input: {SAMPLE}\n")
    print(f"parsed {len(observations)} observations:")
    for o in observations:
        print(f"  {o['mention']:12} [{o['sentiment']:8}] {o['text']}")

    assert observations, "expected at least one observation"
    print("\nANTHROPIC SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
