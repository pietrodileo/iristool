# Publish to PyPI

Once the project is ready to share, build and upload it so anyone can install it with `pip install iristool` or `uv pip install iristool`. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first, run the tests described in the [README](../README.md#development-and-testing), and execute these commands from the repository root.

## Current release: 0.3.1

Version **0.3.1** is published on PyPI. This is a patch release with no major
API changes. The package includes optional `kaggle`, `huggingface`, and
`integrations` extras, plus the `kaggle-iris` and `hf-iris` commands.
`pyproject.toml` and the iristool entry in `uv.lock` should both say `0.3.1`.

To verify this release independently of the source checkout:

```bash
uv venv .venv-pypi
source .venv-pypi/bin/activate
uv pip install 'iristool[integrations]==0.3.1'
uv pip show iristool
kaggle-iris --help
hf-iris --help
```

Use the README's `.env` setup and public dataset examples to test against IRIS.
Verify a base install without extras in another fresh environment as well:
`uv pip install 'iristool==0.3.1'`. It must not require either source SDK.

Do not republish changed files as 0.3.1. The steps below are for the next release.
Before releasing, run the suite with `uv run --all-extras`, including the source
integration flags described in the README. Inspect the built wheel: it must
include `iristool/integrations/`, both CLI entry points, and optional extras.
Publishing is a separate explicit action; installation and testing do not upload
anything to PyPI.

## 1. Bump the version

Every new release needs a new version. Choose **one** command; these examples start from `0.3.1`:

```bash
uv version --bump patch    # 0.3.1 -> 0.3.2
uv version --bump minor    # 0.3.1 -> 0.4.0
uv version --bump major    # 0.3.1 -> 1.0.0
uv version 1.2.3          # set an explicit version
uv version                # just print the current version
```

`uv version` updates `pyproject.toml` and, by default, locks and syncs the project, creating or updating `uv.lock`. Already uploaded files cannot be replaced with changed contents under the same filenames.

## 2. Build distributable artifacts

```bash
uv build                  # writes the source archive and wheel into dist/
```

Remove older release artifacts from `dist/` before building, or use `uv build --clear` to clear the output directory first. This keeps the next upload limited to the intended release.

## 3. Get a PyPI token

Log in to [PyPI](https://pypi.org/manage/account/token/) and create an API token. Use a project-scoped token once `iristool` exists; use an account-wide token for the first upload. The token starts with `pypi-`.

## 4. Publish with the token

Export the token as `UV_PUBLISH_TOKEN`; `uv publish` reads it automatically. Keep the token private and avoid saving it in source control or shared shell history.

Linux / macOS / Git Bash, with Python available:

```bash
# Linux / macOS / Git Bash
export UV_PUBLISH_TOKEN=pypi-<your-token>
uv publish
```

PowerShell:

```powershell
# PowerShell
$env:UV_PUBLISH_TOKEN = "pypi-<your-token>"
uv publish
```

## 5. Verify the public install

Install the published package from PyPI and display its installed version:

```bash
uv pip install --upgrade iristool
uv pip show iristool
```

Run this in a fresh virtual environment to avoid using an existing local or editable installation. Check the `Version` field against the release you uploaded. This checks package metadata, not an IRIS connection.

See the [uv publishing guide](https://docs.astral.sh/uv/guides/package/) for build, token authentication, and public-install verification details.