"""Fetch the disposable qg-admin token from the local Keycloak port-forward."""

import json
import os
import urllib.parse
import urllib.request


def get_token() -> str:
    url = os.environ.get("QG_KEYCLOAK_URL", "http://127.0.0.1:8081")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("QG_KEYCLOAK_URL must be a local HTTP port-forward")
    url = url.rstrip("/") + "/realms/qg/protocol/openid-connect/token"
    payload = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "krameriusClient",
            "client_secret": "qg-local-only",
            "username": "qg-admin",
            "password": "qg-local-only",
        }
    ).encode()
    request = urllib.request.Request(url, data=payload, headers={"Host": "qg-keycloak:8080"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return str(json.load(response)["access_token"])


if __name__ == "__main__":
    print(get_token())
