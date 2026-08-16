# Contributing

Contributions should make an engineering decision clearer, correct a technical error, or add a failure mode that practitioners are likely to encounter.

## Before writing

1. Search for the concept before adding a new file. Extend an existing chapter when the topic does not need independent navigation.
2. State the problem and the guarantee before introducing a library or pattern.
3. Separate facts from recommendations. A protocol rule needs a source; a design recommendation needs assumptions and tradeoffs.
4. Prefer an official specification or project documentation over a secondary tutorial.

## Writing standard

- Use direct technical language and complete sentences.
- Define an unfamiliar term at first use or link to the glossary.
- Keep examples typed and small enough to explain.
- Use `async def` only when the path awaits non-blocking I/O.
- Name failure cases, operational signals, and relevant security boundaries.
- Do not use emoji, marketing copy, placeholder sections, or Unicode dash characters.
- Do not describe one architecture as universally correct.

Use `database layer`, `repository`, and `persistence adapter` deliberately. They are not interchangeable: a repository exposes domain-oriented persistence operations, while a database layer may only manage engines, sessions, and mappings.

## Source format

Use descriptive Markdown links near the claim they support:

```markdown
FastAPI delegates its web behavior to Starlette and data handling to Pydantic, as described in the [FastAPI features documentation](https://fastapi.tiangolo.com/features/).
```

Do not cite a search page. Check the destination before submitting. For stable background material, add the canonical source to `resources/sources.md` and cite the specific page from the chapter.

## Code examples

Examples should follow the currently documented FastAPI, Pydantic v2, and SQLAlchemy 2.x interfaces. Include imports. When a fragment intentionally omits setup, say what provides it. Never include a real credential.

For runnable examples:

- keep dependency groups reproducible;
- provide startup and test commands;
- isolate external services behind interfaces or fixtures;
- test authorization failures, not only successful requests;
- make migration behavior explicit.

## Local checks

```bash
python tools/check_docs.py
python -m pip install -r requirements-docs.txt
python tools/prepare_mkdocs.py
mkdocs build --strict
python -m compileall examples
(cd examples/basic-crud && pytest)
(cd examples/production-api && pytest)
(cd examples/ai-api && pytest)
```

If you change a dependency declaration, install that example in a clean environment before opening a pull request.

## Review checklist

- Internal links resolve with the exact filename casing.
- The example and its explanation agree.
- Security advice is fail-closed.
- Retry examples have bounds and use idempotency where required.
- Transactions have a clear owner.
- Metrics avoid unbounded labels.
- No section exists solely to repeat the preceding section.

By contributing, you agree that your work is licensed under the repository's MIT License.
