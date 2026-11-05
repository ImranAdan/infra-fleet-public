"""Read a recording's accepted evidence back through an engine, as recorded
and with its capture proof made incomplete. Run from an engine root:
python3 -B proof.py <recording.json>"""
import json
import sys

sys.path.insert(0, "mandate/src")
from mandate import evidence as e  # noqa: E402

rec = json.load(open(sys.argv[1]))
changes = {"as recorded": {}, "compared merge removed": {"compared_sha": None},
           "capture declared unproven": {"unproven": "capture did not prove a base"}, "base removed": {"base_sha": None}}
for accepted in rec["decision"]["accepted"]:
    for raw in accepted["records"]:
        for name, change in changes.items():
            try:
                got = e.EvidenceRecord.from_dict({**raw, **change})
                said = f"read back: base {got.base_sha}, compared {got.compared_sha}, unproven {got.unproven}"
            except ValueError as exc:
                said = f"refused: {exc}"
            print(f"{accepted['requirement']} check run {raw['check_run_id']}, {name}: {said}")
