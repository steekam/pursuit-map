# PursuitMap operating contract

Read this file before changing the repository. Keep changes within the current phase unless the user explicitly expands scope.

## Communication style

Use plain, direct English. Follow these rules:

- Use active voice and concrete nouns.
- Put the result first.
- Use short sentences. Keep one instruction or claim per sentence.
- Use one term for one concept. Follow the glossary.
- Remove needless words, filler, and repeated conclusions.
- Prefer familiar words over abstract or technical words.
- Explain a technical term at first use.
- State measurements with units, denominators, time windows, and source references.
- Separate measured facts, assumptions, limitations, and interpretations.
- Use headings and lists when they improve scanning.
- Revise each paragraph until its subject, action, and consequence are clear.

Use ASD-STE100 Simplified Technical English principles for procedures and technical notes:

- Use approved, familiar meanings for words.
- Avoid idioms, slang, metaphors, humour, and cultural references.
- Avoid vague verbs such as `handle`, `manage`, `support`, and `address` when a specific verb is available.
- Avoid nominalizations. Use `verify the manifest`, not `perform verification of the manifest`.
- Use the same name for the same object in code, docs, tests, and reports.
- Use explicit references. Replace `this`, `that`, or `it` with the object name when the reference is unclear.
- Write procedures as ordered actions. Give one action per step.

Use William Zinsser's editing principles:

- Omit needless words.
- Write for a human reader.
- Prefer clarity and simplicity over display.
- Keep the writer's natural voice.
- Cut introductions that delay the subject.
- Do a final tightening pass before delivery.

Avoid common AI-ism patterns:

- Do not use contrast frames such as `not X, but Y` or `this, not that`.
- Do not use empty openings such as `In today's world`, `It is important to note`, or `As an AI`.
- Do not use inflated verbs such as `leverage`, `utilize`, `delve`, `unlock`, or `operationalize` when a plain verb works.
- Do not use unsupported claims such as `robust`, `seamless`, `powerful`, or `comprehensive` without evidence.
- Do not repeat the conclusion in several forms.

## Source and truth rules

- Treat the hashed OCP South Africa bulk snapshot as the Phase 1 baseline source.
- Preserve raw source artifacts and raw JSON. Never replace raw values with parsed or normalized values.
- Keep missing, invalid, sentinel, zero, negative, and placeholder values distinct.
- Every canonical or derived output must retain source snapshot hash, run ID, and the relevant source keys.
- Use deterministic transformations. Scores are retrieval or rule scores, never probabilities or predictions.
- Do not add fuzzy matching, embeddings, LLM extraction, document downloading, lead scoring, API services, or browser UI in Phase 1–1.5.

## Data and run rules

- Canonical Parquet and DuckDB outputs belong under a unique normalization run directory.
- Derived marts and reports belong under their operation run directory.
- Compatibility files may point to the latest run; they must not be the only copy.
- Do not commit raw or generated data. Record hashes and row counts in manifests.
- Before changing a schema, update `config/pipeline-contract.json`, canonical schema documentation, and tests together.
- When a phase or milestone changes, update `docs/roadmap/phase-tracker.md` and add a build-log entry with measurements.

## Development loop

1. Read the relevant ADR and contract entry.
2. Make one cohesive change.
3. Run `uv run pytest -q`, `uv run python -m compileall -q pipeline/src tests`, and `git diff --check`.
4. Run the affected CLI command against a fixture, then the current snapshot when practical.
5. Commit one logical change with an imperative message. Do not use checkpoint commits.

## Useful commands

```bash
uv run pursuitmap ingest za
uv run pursuitmap normalize za
uv run pursuitmap verify za
uv run pursuitmap profile za
uv run pursuitmap materialize za
uv run pursuitmap search za --query "network modernization" --vertical ict --format json
```

The contract is machine-readable in `config/pipeline-contract.json`. The canonical schema and decision history live under `docs/`.
