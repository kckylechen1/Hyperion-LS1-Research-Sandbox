# Decision Provenance (Sandbox)

## Atoms

| Atom | Role |
|------|------|
| `watch_idea` | Redacted user intent summary |
| `decision_rationale` | Redacted agent stance + human action |
| `outcome_validation` | Fixture outcome label + forward returns |
| `lesson_candidate` | Distilled axiom only — **no raw chat** |

## Bind flow

```text
chat.jsonl event + snapshot fixture
    → bind_chat_to_snapshot()
    → AlphaTensor + ProvenanceBundle + diagnosis dict
```

Promotion to semantic memory must use `lesson_candidate.core_axiom`, never full transcripts.