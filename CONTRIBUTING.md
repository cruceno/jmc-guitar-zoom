# Contributing

Thanks for your interest. Please read the notes below before opening a pull request.

## Run the tests

```sh
uv sync
QT_QPA_PLATFORM=offscreen uv run pytest
```

The suite runs offscreen and without a pedal. To also run the tests that compare the synthetic fixtures with Zoom's
real files, download them once with `uv run python scripts/fetch_test_fixtures.py` (they are skipped otherwise).

## Build the packages

```sh
uv sync --group build
bash packaging/linux/build_appimage.sh          # Linux: dist/JMC_Guitar_Zoom-<version>-x86_64.AppImage
QT_QPA_PLATFORM=offscreen ./dist/JMC_Guitar_Zoom-*-x86_64.AppImage --self-check
```

On Windows, `uv run pyinstaller --noconfirm packaging/jmc-guitar-zoom.spec` builds `dist\jmc-guitar-zoom\`, and
Inno Setup 6 (`ISCC /DAppVersion=<version> packaging\windows\jmc-guitar-zoom.iss`) turns it into the installer.
The hidden `--self-check [PATH]` option prints (and writes to PATH) the version, the data folder, the fonts, the MIDI
ports and the Guitar Lab folder, and exits non-zero when Qt or the MIDI backend did not load.

## Make a release

1. Set the new version in `pyproject.toml` and `jmc_guitar_zoom/__init__.py` (a test checks they match).
2. Commit, then tag and push the tag: `git tag v0.2.0 && git push origin v0.2.0`.
3. The `release` workflow runs the tests on Linux and Windows, checks the tag against the version, builds the
   AppImage and the installer, and publishes a GitHub Release with both. The tag must be `v` plus the exact version
   string, so a prerelease spells its version with a `-` too: version `0.2.0-rc1`, tag `v0.2.0-rc1` (a tag with a
   `-` is published as a prerelease). Pushes to `main`, pull requests and manual runs build the same packages as
   workflow artifacts only.

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
