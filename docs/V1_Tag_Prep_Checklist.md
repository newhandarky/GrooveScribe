# GrooveScribe V1 Tag Prep Checklist

This checklist prepares the repository for an annotated V1 release candidate tag. It documents the final checks only; this work pack must not create the tag automatically.

## Suggested Tag

```text
v1.0.0-rc1
```

## Final Checks

Run from repo root:

```bash
git status --short --branch
git diff --check
.venv-ai/bin/python scripts/run_v1_rc_pilot.py --output-dir /tmp/groovescribe-v1-rc-pilot
.venv-ai/bin/python scripts/check_v1_rc_handoff.py /tmp/groovescribe-v1-rc-pilot/rc_manifest.json
rg -n "/Users/|/tmp/|/private/tmp/|/var/folders/|Traceback|stdout|stderr|raw command|command_template|output_tail|diagnostic_tail" /tmp/groovescribe-v1-rc-pilot
git status --short --branch
git diff --check
```

Expected result:

- RC pilot prints `status=passed`.
- RC handoff validator prints `status=passed` and `issues=[]`.
- The RC handoff redaction scan has no matches.
- Git status does not include generated artifacts.
- `git diff --check` has no output.

## Suggested Annotated Tag Command

Only run this after the final checks pass:

```bash
git tag -a v1.0.0-rc1 -m "GrooveScribe V1.0.0 RC1

Local-first V1 release candidate.

Validated with RC pilot handoff:
- rc_manifest.json
- rc_handoff.md
- release_gate_report.json
- release_evidence/evidence.json
- release_evidence/evidence.md

true-AI remains opt-in.
PDF renderer remains optional.
Generated storage, DB, dist, tmp, Playwright reports, evidence, review packets, and RC handoff outputs are not committed."
```

## Before Pushing A Tag

- Confirm the tag points at the intended `main` commit.
- Confirm `docs/V1_Release_Notes.md` matches the release candidate scope.
- Confirm `docs/V1_Release_Artifact_Index.md` lists the repo-external generated artifacts.
- Do not create a tag from a dirty worktree.
- Do not include generated RC/evidence/review packet files in git.
