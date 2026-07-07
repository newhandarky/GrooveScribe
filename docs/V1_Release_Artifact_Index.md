# GrooveScribe V1 Release Artifact Index

V1 release artifacts are generated evidence files for reviewer handoff. They are not source files and must not be committed.

Current RC1 candidate handoff artifacts are expected to be regenerated under `/tmp/groovescribe-v1-rc-pilot` and validated with `scripts/check_v1_rc_handoff.py`. They remain repo-external even when the validation passes.

## RC Handoff Bundle

Default generated location:

```text
/tmp/groovescribe-v1-rc-pilot
```

Generated files:

- `rc_manifest.json`: summary manifest for the release candidate handoff.
- `rc_handoff.md`: reviewer-readable handoff summary.
- `release_gate_report.json`: summary-only release gate report without command output tails.
- `release_evidence/evidence.json`: release evidence JSON.
- `release_evidence/evidence.md`: release evidence Markdown.

Validation expectation:

- `rc_manifest.json` reports `status=passed`.
- `scripts/check_v1_rc_handoff.py` reports `status=passed` and `issues=[]`.
- Redaction scans over the bundle have no matches for local paths, tracebacks, raw command details, stdout/stderr tails, or command templates.

## Review Packet Artifacts

When a completed job is supplied to the RC pilot with `--review-job-id`, review packet files may be generated under the RC output directory:

- `review_packet/review_packet.json`
- `review_packet/review_notes.md`
- `review_packet/review_packet.zip`

Review packet export is optional for final tag prep. Missing or non-completed jobs must not block deterministic RC sign-off.

## Storage Policy

Generated artifacts stay outside git. Do not commit:

- RC handoff bundles
- release evidence
- review packets
- frontend build output
- local storage directories
- SQLite/DB files
- tmp artifacts
- Playwright reports
