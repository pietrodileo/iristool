# Build and publish to PyPI

The latest published release is **0.3.1**. New exports, CLI names, and access-error
instructions in this branch are for the next release. Keep the current version
until you prepare that release; never upload changed files as 0.3.1 again.

## Automatic releases from Git tags

[`.github/workflows/publish.yml`](../.github/workflows/publish.yml) runs unit tests
with all extras, builds the wheel/source archive, and checks that the wheel's
base install exposes the new CLI commands. Pull requests and manual runs build
and test only. Pushing a `vVERSION` tag also publishes the resulting artifacts
to PyPI, provided the tag matches `pyproject.toml` exactly.

### One-time setup

1. In the GitHub repository settings for `pietrodileo/iristool`, create an
   environment named **`pypi`**. You can restrict its deployment tags to `v*`.
   Required reviewers are optional; adding them pauses publishing for approval.
2. Open [iristool's PyPI publishing settings](https://pypi.org/manage/project/iristool/settings/publishing/)
   and add a **GitHub Trusted Publisher** with these exact values:

   | Field | Value |
   | --- | --- |
   | Owner | `pietrodileo` |
   | Repository | `iristool` |
   | Workflow filename | `publish.yml` |
   | Environment | `pypi` |

The publish job requests a short-lived identity token (`id-token: write`).
No `PYPI_API_TOKEN` secret is needed. This setup is required before a tag can
publish successfully. See [PyPI's setup guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
and [publishing workflow guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

### Release the next version

Run from this repository after the changes have been reviewed and merged into
the branch you release from. For the next feature release, starting at 0.3.1:

```bash
uv version --bump minor   # 0.3.1 -> 0.4.0; also updates uv.lock
uv run --locked --all-extras python -m unittest discover -s tests -v -b
```

Run the opt-in IRIS/source checks in the
[README](../README.md#development-and-testing) before releasing too. The GitHub
workflow runs offline unit tests; it does not start IRIS or use source tokens.
Update the README release notice to 0.4.0 and remove the unreleased-feature
qualifications, then commit `pyproject.toml`, `uv.lock`, and those docs:

```bash
git add pyproject.toml uv.lock README.md docs/publish.md
git commit -m "Release 0.4.0"
git push
# This tag push starts the PyPI upload automatically:
git tag -a v0.4.0 -m "iristool 0.4.0"
git push origin v0.4.0
```

Use your actual version in every command. A mismatched tag fails before
publishing. Watch the **Build and publish to PyPI** workflow in GitHub Actions.
Published versions cannot be overwritten; fix an uploaded release with a new
version and new tag. Do not move an already published tag to different code.

### Verify the published package

Use a fresh environment, separate from local source development:

```bash
uv venv .venv-pypi
source .venv-pypi/bin/activate
uv pip install 'iristool[integrations,excel]==0.4.0'
uv pip show iristool
iristool-kaggle --help
iristool-hf --help
```

Replace 0.4.0 with the version you actually published. Load `.env` as described
in the README to test imports/exports against IRIS. Also test a fresh base-only
install: it must not install KaggleHub, datasets, or openpyxl.

## Local builds and manual publishing

To inspect artifacts without publishing:

```bash
uv build --clear
```

The wheel must include `iristool/integrations/`, the new CLI entry points and
legacy aliases, the `excel` extra, and `IRIStool.export_table`. Only the source
archive and wheel belong in `dist/` when uploading.

If you choose manual publishing instead of the tag workflow, obtain a
project-scoped [PyPI API token](https://pypi.org/manage/account/token/), supply it
as `UV_PUBLISH_TOKEN` through your environment, and run `uv publish`.
Keep the token out of Git and shared shell history. Do not use both publishing
paths for the same version. See the [uv publishing guide](https://docs.astral.sh/uv/guides/package/).
