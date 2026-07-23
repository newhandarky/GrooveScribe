<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **GrooveScribe** (8648 symbols, 14368 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/GrooveScribe/context` | Codebase overview, check index freshness |
| `gitnexus://repo/GrooveScribe/clusters` | All functional areas |
| `gitnexus://repo/GrooveScribe/processes` | All execution flows |
| `gitnexus://repo/GrooveScribe/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

<!-- groovescribe-workflow:start -->
## GrooveScribe workflow modes

`STANDARD` is the only default mode for this repository. Use it for ordinary
features, bug fixes, benchmark corrections, pipeline/API/frontend/worker
changes, and test reinforcement.

Select a mode in this order:

1. A mode explicitly requested by the user.
2. `REFACTOR` only when the user explicitly requests a behavior-preserving
   refactor, or a matching `docs/refactoring/work-items/<work-item>.md` exists.
3. `STANDARD` for every other current task.
4. Never select `SPEC_DRIVEN` automatically. It is disabled until the user
   explicitly enables it with a bound spec, plan, tasks file, and concrete task.

Existing product, architecture, engineering-task, and release documents are
not SpecKit tasks by themselves.

### STANDARD

Follow: request → repository/branch/worktree check → GitNexus index check →
available GitNexus or CodeGraph architecture exploration → the repository's
existing impact-analysis rule before editing symbols → implementation →
targeted tests → broader relevant tests → post-change impact review.

### REFACTOR

This is optional, not the default. Record the refactoring goal and preserved
external behavior, then use architecture/impact evidence, small implementation
batches, tests, and post-change impact review. The governing work item must be
reported when one exists.

### Evidence boundaries and fallback

- GitNexus is evidence for code structure, dependencies, execution flows, and
  impact only; it is never the source of product requirements.
- CodeGraph is supplementary structural evidence for code it has indexed.
- Missing graph relationships do not prove that no dependency exists.
- When either graph is stale, insufficient, or unavailable, report that fact
  and use repository files, `rg`, tests, and runtime evidence instead.

Before future implementation work, print a short summary containing:

- Workflow mode
- Mode evidence
- Repository
- Branch
- Worktree status
- GitNexus index status
- CodeGraph index status
- Governing refactoring work item (`none` when absent)
- Next action
<!-- groovescribe-workflow:end -->
