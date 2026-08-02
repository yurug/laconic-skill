#!/usr/bin/env python3
"""Export/import a local blinded review of frozen theory A/B outputs.

The HTML is self-contained and makes no network requests. It contains real work material and
must stay under eval/runs/, which is gitignored. Arm identity is resolved only when importing
the downloaded JSON against outputs.jsonl.
"""

import argparse
import html
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))
from theory_ab import blind_pair, report  # noqa: E402


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def render(outputs):
    cards = []
    for number, row in enumerate(outputs, 1):
        _, arm_a, arm_b = blind_pair(row)
        evidence = "".join(
            f"<li><code>{html.escape(item['kind'])}</code> "
            f"{html.escape(item['observation'])}</li>"
            for item in row["profile"]
        )
        cards.append(f"""
<article data-key="{html.escape(row['key'])}">
  <h2>Pair {number}</h2>
  <h3>Request</h3><pre>{html.escape(row['prompt'])}</pre>
  <details><summary>Demonstrated understanding</summary><ul>{evidence}</ul></details>
  <div class="answers"><section><h3>Answer A</h3><pre>{html.escape(row[f'{arm_a}_output'])}</pre></section>
  <section><h3>Answer B</h3><pre>{html.escape(row[f'{arm_b}_output'])}</pre></section></div>
  <fieldset><legend>Winner</legend>
    <label><input type="radio" name="winner-{number}" value="A"> A</label>
    <label><input type="radio" name="winner-{number}" value="B"> B</label>
    <label><input type="radio" name="winner-{number}" value="tie"> tie</label>
  </fieldset>
  <label>Material loss <select class="loss"><option value="">none</option><option>A</option><option>B</option><option value="A,B">both</option></select></label>
  <label>Unsupported assumption <select class="unsupported"><option value="">none</option><option>A</option><option>B</option><option value="A,B">both</option></select></label>
  <label>Why <input class="why" maxlength="160"></label>
</article>""")
    return """<!doctype html><meta charset="utf-8"><title>Blinded Laconic A/B review</title>
<style>body{font:16px system-ui;max-width:1400px;margin:auto;padding:24px}article{border-top:2px solid #555;padding:24px 0}.answers{display:grid;grid-template-columns:1fr 1fr;gap:24px}pre{white-space:pre-wrap;background:#f4f4f4;padding:12px}label{margin:8px;display:inline-block}@media(max-width:900px){.answers{grid-template-columns:1fr}}</style>
<h1>Blinded response review</h1><p>Judge preservation, calibration, unsupported assumptions, directness, and usefulness. Do not reward repetition of the evidence.</p>
""" + "".join(cards) + """
<button id="export">Export completed judgments</button><script>
document.querySelector('#export').onclick=()=>{const rows=[...document.querySelectorAll('article')].map((card,i)=>{const selected=card.querySelector(`input[name="winner-${i+1}"]:checked`);return {key:card.dataset.key,winner:selected?.value||null,material_loss:card.querySelector('.loss').value.split(',').filter(Boolean),unsupported_assumption:card.querySelector('.unsupported').value.split(',').filter(Boolean),why:card.querySelector('.why').value}});if(rows.some(r=>!r.winner)){alert('Choose a winner for every pair');return}const blob=new Blob([rows.map(JSON.stringify).join('\n')+'\n'],{type:'application/jsonl'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='human-judgments.jsonl';a.click()};
</script>"""


def import_results(outputs, judgments):
    by_key = {row["key"]: row for row in outputs}
    if len(judgments) != len(outputs) or {row.get("key") for row in judgments} != set(by_key):
        raise ValueError("judgments must cover every output key exactly once")
    rulings = []
    for judgment in judgments:
        source = by_key[judgment["key"]]
        labels, _, _ = blind_pair(source)
        winner = judgment.get("winner")
        if winner not in {"A", "B", "tie"}:
            raise ValueError(f"invalid winner for {judgment['key'][:12]}")
        mapped = "tie" if winner == "tie" else labels[winner]
        loss = [labels[label] for label in judgment.get("material_loss", [])]
        unsupported = [labels[label] for label in judgment.get("unsupported_assumption", [])]
        if mapped == "theory" and ("theory" in loss or "theory" in unsupported):
            mapped = "policy"
        rulings.append({
            "key": judgment["key"], "winner": mapped, "material_loss": loss,
            "unsupported_assumption": unsupported, "why": judgment.get("why", ""),
        })
    return rulings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=str(EVAL / "runs" / "theory-ab"))
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--import-results")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    outputs_path = run_dir / "outputs.jsonl"
    if not outputs_path.exists():
        print(f"missing {outputs_path}", file=sys.stderr)
        return 1
    outputs = load_jsonl(outputs_path)
    if args.export:
        destination = run_dir / "human-review.html"
        destination.write_text(render(outputs), encoding="utf-8")
        print(f"wrote local blinded bundle: {destination}")
    if args.import_results:
        rulings = import_results(outputs, load_jsonl(Path(args.import_results)))
        report(rulings, [
            {"theory": row["profile"]} for row in outputs
        ], diagnostic=True)
    if not args.export and not args.import_results:
        print("pass --export or --import-results <jsonl>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
