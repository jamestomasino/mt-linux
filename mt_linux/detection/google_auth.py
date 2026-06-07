from __future__ import annotations

import time
from pathlib import Path
import webbrowser

AUTH_PROMPT_MESSAGE = "Please visit this URL to authorize this application: {url}"
AUTH_SUCCESS_MESSAGE = "The authentication flow has completed. You may close this window."


def run_google_auth(credentials_path: Path, token_path: Path) -> Path:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google_auth_oauthlib.flow import WSGITimeoutError
        import google_auth_oauthlib.flow as flow_module
        import wsgiref.simple_server
    except ImportError as exc:
        raise RuntimeError(
            "google-auth-oauthlib is not installed. Install the calendar extras to enable Google auth."
        ) from exc

    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path),
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    try:
        creds = _run_resilient_local_server_flow(
            flow,
            flow_module=flow_module,
            simple_server=wsgiref.simple_server,
            timeout_seconds=300,
        )
    except WSGITimeoutError as exc:
        raise RuntimeError(
            "Google auth timed out waiting for the browser callback. Run `mt-ctl auth google` again and complete the consent flow in your browser."
        ) from exc
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return token_path


def _run_resilient_local_server_flow(flow, flow_module, simple_server, timeout_seconds: int):
    wsgi_app = flow_module._RedirectWSGIApp(AUTH_SUCCESS_MESSAGE)
    simple_server.WSGIServer.allow_reuse_address = False
    local_server = simple_server.make_server(
        "localhost",
        0,
        wsgi_app,
        handler_class=flow_module._WSGIRequestHandler,
    )
    try:
        flow.redirect_uri = f"http://localhost:{local_server.server_port}/"
        auth_url, _state = flow.authorization_url(access_type="offline")
        try:
            webbrowser.open(auth_url, new=1, autoraise=True)
        except Exception:
            pass
        print(AUTH_PROMPT_MESSAGE.format(url=auth_url))

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and wsgi_app.last_request_uri is None:
            local_server.timeout = min(5, max(deadline - time.monotonic(), 0.1))
            local_server.handle_request()

        if wsgi_app.last_request_uri is None:
            raise flow_module.WSGITimeoutError(
                "Timed out waiting for response from authorization server"
            )

        authorization_response = wsgi_app.last_request_uri.replace("http", "https")
        flow.fetch_token(authorization_response=authorization_response)
        return flow.credentials
    finally:
        local_server.server_close()
