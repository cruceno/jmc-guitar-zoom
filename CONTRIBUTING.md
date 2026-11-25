# Contributing

Thanks for your interest. Please read the notes below before opening a pull request.

## Run the tests

```sh
uv sync
QT_QPA_PLATFORM=offscreen uv run pytest
```

The suite runs offscreen and without a pedal. To also run the tests that compare the synthetic fixtures with Zoom's
real files, download them once with `uv run python scripts/fetch_test_fixtures.py` (they are skipped otherwise).

## Safety rules

- **Tests never write to a pedal and never open a MIDI port.** Use `FakeTransport` and the in-memory pedal file
  stores of the existing tests. A test that needs hardware does not belong in the suite.
- Any new code that writes to the pedal must go through the existing guarded path: the model gate
  (`write_block_reason`), a backup first, the write, a read-back comparison. See `docs/architecture.md`.
- Do not add files that belong to Zoom (effect binaries, patches or lists dumped from a pedal, Guitar Lab artwork,
  firmware). Extend the factories in `tests/support/` instead.
- Keep personal data (paths, emails, serial numbers) out of the code, the tests and the docs.

## Style

- Behaviour changes come with a test that fails without the change (red, then green).
- User-visible text is Spanish and lives in `jmc_guitar_zoom/ui/strings.py`; code, comments and docs are English.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).

## Upstream

This is an independent derivative of mungewell/zoom-zt2. The upstream author does not accept AI-generated
contributions, so changes here are not sent upstream.
