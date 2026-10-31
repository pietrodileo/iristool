"""Download with workspace credentials without changing the parent SDK login."""

import contextlib
import json
import sys


def main():
    request = json.load(sys.stdin)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import kagglehub
            from kagglehub.config import set_kaggle_api_token
            set_kaggle_api_token(request["token"])
            path = kagglehub.dataset_download(
                request["dataset"], **({"path": request["file"]} if request["file"] else {}))
        print(json.dumps(str(path)))
    except Exception:
        # Provider exceptions may contain credentials; return no SDK diagnostics.
        sys.exit(1)


if __name__ == "__main__":
    main()
