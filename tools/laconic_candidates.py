#!/usr/bin/env python3
"""Review strong observations that have not yet been distilled into capabilities."""

import argparse
import os
import shlex
from pathlib import Path

from laconic_index import load_concepts, select_capability_candidates, select_knowledge_candidates


def main():
    parser = argparse.ArgumentParser(
        description="show relevant strong evidence awaiting capability distillation"
    )
    parser.add_argument("--cwd", default=os.getcwd(), help="project used for relevance")
    parser.add_argument("--knowledge", action="store_true",
                        help="show strong evidence not cited by semantic knowledge")
    args = parser.parse_args()

    selector = select_knowledge_candidates if args.knowledge else select_capability_candidates
    candidates = selector(load_concepts(), str(Path(args.cwd).resolve()))
    if not candidates:
        print("No undistilled strong evidence is relevant to this project.")
        return 0

    if args.knowledge:
        print("Semantic candidates (evidence is not yet a knowledge claim):")
    else:
        print("Capability candidates (evidence is not a capability claim):")
    for item in candidates:
        concept = shlex.quote(item["id"])
        print(f"\n{item['id']} evidence #{item['index']} "
              f"[{item['kind']}, {item.get('basis', 'direct')}, {item['date']}]")
        print(f"  {item['text']}")
        if args.knowledge:
            print("  distil: ~/.laconic/bin/laconic-record "
                  f"{concept} --claim-from {item['index']} "
                  '--claim-kind <kind> --claim "<narrow proposition supported>"')
        else:
            print("  distil: ~/.laconic/bin/laconic-record "
                  f"{concept} --capability-from {item['index']} "
                  '--capability "<narrow reusable ability demonstrated by this evidence>"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
