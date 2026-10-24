# Publish to PyPI

Once the project is ready to share, build and upload it so anyone can install it with `pip install iristool` or `uv pip install iristool`. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first, run the tests described in the [README](../README.md#development-and-testing), and execute these commands from the repository root.

## Integration release (0.2.0)

The working tree is prepared as **0.2.0** with optional `kaggle`, `huggingface`,
and `integrations` extras. This does not mean it has been uploaded to PyPI.
Before releasing, run the full suite with `uv run --all-extras`, including the
source integration flags described in the README. Build and inspect the wheel:
it must include `iristool/integrations/`, both CLI entry points, and optional
extra metadata. A base install must not require either source SDK.

After publishing, verify in a fresh environment using
`python -m pip install 'iristool[integrations]==0.2.0'`, then test
`kaggle-iris --help`, `hf-iris --help`, and the public dataset examples against
IRIS. Also verify `pip install iristool==0.2.0` without extras. Do not bump again
if 0.2.0 is the intended unpublished version. Publishing is a separate explicit
release action, not part of running the tests or installing from source.

## 1. Bump the version

Every new release needs a new version. Choose **one** command; the comments below assume the current version is `0.1.0`:

```bash
uv version --bump patch    # 0.1.0 -> 0.1.1
uv version --bump minor    # 0.1.0 -> 0.2.0
uv version --bump major    # 0.1.0 -> 1.0.0
uv version 1.2.3          # set an explicit version
uv version                # just print the current version
```

`uv version` updates `pyproject.toml` and, by default, locks and syncs the project, creating or updating `uv.lock`. For the first release, keep `0.1.0` if it has not been published. Already uploaded files cannot be replaced with changed contents under the same filenames.

## 2. Build distributable artifacts

```bash
uv build                  # writes the source archive and wheel into dist/
```

Remove older release artifacts from `dist/` before building, or use `uv build --clear` to clear the output directory first. This keeps the next upload limited to the intended release.

## 3. Get a PyPI token

Log in to [PyPI](https://pypi.org/manage/account/token/) and create an API token. Use a project-scoped token once `iristool` exists; use an account-wide token for the first upload. The token starts with `pypi-`.

## 4. Publish with the token

Export the token as `UV_PUBLISH_TOKEN`; `uv publish` reads it automatically. These examples prompt for it so the token itself is not saved in shell history.

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