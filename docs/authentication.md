# Dataset authentication

iristool uses the source SDKs' authentication mechanisms. Public datasets often
work without credentials. Follow the relevant section below only if your
dataset requires login, consent, or access approval.

Install the relevant iristool extra first; see the [installation instructions](../README.md#install-optional-support).
The `uv run` commands below assume you installed iristool in your own uv project.
In the iristool source checkout, use `uv run --all-extras` instead. With pip,
activate your virtual environment and omit the `uv run` prefix.

## Store tokens in `.env`

Follow the README's [`.env` setup](../README.md#configure-and-load-env) to create
your connection configuration. After obtaining a token using the provider's
instructions below, uncomment and fill in the corresponding line in `.env`:

```dotenv
KAGGLE_API_TOKEN='your-kaggle-token'
HF_TOKEN='your-hugging-face-read-token'
```

Only set the tokens your datasets need. Load the file in the same terminal
before running Python or the CLI (bash/zsh):

```bash
set -a
source .env
set +a
```

The SDKs read these exported variables; iristool does not load `.env` itself.
Reload the file after changing a token. Cached login credentials are an
alternative to setting tokens in `.env`. Do not commit the file.

## Kaggle

Most public datasets, including `uciml/iris`, need no account or API key.

For private or consent-required datasets:

1. Create or sign in to a [Kaggle account](https://www.kaggle.com/).
2. Open [Settings → API](https://www.kaggle.com/settings/api), click
  **Generate New Token**, and copy the token.
3. Run `uv run python -c "import kagglehub; kagglehub.login()"`
  and enter it at the prompt. With pip, omit `uv run`.
4. If the dataset requires consent, visit its page and accept the terms first.
  Your account must have permission to read private datasets.

For automation, provide `KAGGLE_API_TOKEN` through your secret manager.
KaggleHub also reads `~/.kaggle/access_token`. Existing legacy credentials work
from `~/.kaggle/kaggle.json`: choose **Create Legacy API Key** in the same settings
page, move the downloaded file there, and restrict permissions (`chmod 600` on
macOS/Linux). Use one authentication method; do not commit credentials.
See the [KaggleHub authentication guide](https://github.com/Kaggle/kagglehub#authenticate).

## Hugging Face

Public, ungated datasets such as `scikit-learn/iris` work without a token.
For private or gated datasets:

1. Create or sign in to a [Hugging Face account](https://huggingface.co/join).
2. Open [Access Tokens](https://huggingface.co/settings/tokens) and create a token
  with read access to the intended dataset.
3. Run `uv run hf auth login` and paste the token at the prompt.
  With pip, use `hf auth login` directly.
4. For a gated dataset, request access or accept its terms on its page and wait
  for approval where required. A token does not grant access by itself.

For scripts/CI, provide `HF_TOKEN` through your environment or secret manager.
Credentials and files use Hugging Face's cache under `~/.cache/huggingface`;
set `HF_HOME` to relocate it. See the
[authentication guide](https://huggingface.co/docs/huggingface_hub/en/quick-start#authentication)
and [download guide](https://huggingface.co/docs/hub/en/datasets-downloading).

## When browser approval is required

A token authenticates your account; it does not accept a dataset's conditions
or grant access by itself. For [gated Hugging Face datasets](https://huggingface.co/docs/hub/en/datasets-gated),
request access on the dataset page in your browser. Approval can be immediate
or require the owner's review. [KaggleHub](https://github.com/Kaggle/kagglehub#authenticate)
also requires credentials for private or consent-required datasets; open the
specific dataset page and complete any consent step first.

When a download raises HTTP 401/403, a gated-repository error, or a Kaggle
unauthenticated error, iristool stops processing before importing any tables.
The CLI exits with status **1** and displays an actionable error like:

```text
Import failed: Dataset processing failed: access denied. Open <dataset URL>
in your browser, sign in and confirm the terms or request access. Wait for
approval if required. Then set HF_TOKEN (or log in with the source SDK) using
the approved account and repeat the same command. No dataset tables were imported.
```

For Kaggle, the message names `KAGGLE_API_TOKEN` instead. This also applies with
`--replace`: no existing target table is deleted when the download is denied.
Python callers receive a `PermissionError` with the same instructions and the
original source exception as its cause. Unrelated network or parsing failures
retain their original errors.

After accepting terms or receiving approval:

1. Use a token belonging to the **same account** that received access.
2. Save it in `.env`, then reload the file (`set -a; source .env; set +a`).
3. Repeat the exact import command you ran before.

iristool does not open a browser or accept terms automatically. A 401/403 can
also indicate an invalid token or missing private-dataset permission, so check
those if confirming access does not resolve the error. Kaggle competition-rule
acceptance is a separate flow: competition URLs are not supported by this
dataset adapter. Access approval does not change format support; nested/media
Hugging Face datasets still need flattening before import.

A manual anonymous check against [LMSYS-Chat-1M](https://huggingface.co/datasets/lmsys/lmsys-chat-1m)
verified this browser-confirmation error without importing any tables. This is
an access-denial check, not an import example: that dataset contains nested
conversation values and needs preprocessing after access is granted.

The access-error tests simulate the SDKs' 401/403 and wrapped gated errors;
they require no account or browser approval. An end-to-end approval test
requires an account you control and a dataset for which you can accept the
terms; it is not part of unattended CI.

## Credentials and troubleshooting

- Keep tokens out of source code, Git, notebooks, and command output. Use your
  environment or a secret manager for automated runs.
- HTTP 401 usually indicates missing or invalid credentials. HTTP 403 can mean
  the account lacks permission or has not accepted the dataset's terms.
- A successful login does not grant access to private or gated datasets. Use
  the same account that has been granted access on the provider's website.
- To change accounts or revoke access, use the source SDK's authentication tools
  and revoke the corresponding token in the provider's account settings.

Return to [dataset imports](../README.md#dataset-integrations) for download and
IRIS import examples.
