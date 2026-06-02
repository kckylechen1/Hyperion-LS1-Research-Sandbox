# Architecture (Public Sandbox)

```text
Synthetic fixture snapshot (JSON)
        │
        ├─► ls1_contract/validator   ── required LS1 paths present?
        ├─► ls1_contract/projection  ── flat LS1 fact dict for reviewers
        │
        ▼
alpha_tensor/builder  (read-only projection, no Warpcore)
        │
        ├─► AlphaTensor  ── Observer / provenance input
        │
        ├─► decision_provenance/binder  ◄── redacted chat atom
        │         └─► validator → alpha | scoring | beta diagnosis
        │
        └─► pattern_memory/evidence  ── similar cases (demo store)
```

**Authority:** Warpcore/LS1 in production computes physics; this repo only documents **outputs** and **projection**.