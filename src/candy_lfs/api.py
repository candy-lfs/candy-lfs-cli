import time
from typing import Any, Optional

import requests
from rich.console import Console

console = Console()


class APIError(Exception):
    def __init__(self, status_code: int, message: str, details: Optional[dict[str, Any]] = None):
        self.status_code = status_code
        self.message = message
        self.details = details or {}
        super().__init__(f"API Error {status_code}: {message}")


class APIClient:
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.request(method, url, json=json, params=params, timeout=30)
            if response.status_code == 204:
                return None
            if response.status_code >= 400:
                try:
                    error_data = response.json()
                    # OAuth format: {error, error_description}
                    if "error" in error_data and "error_description" in error_data:
                        message = error_data.get("error_description", error_data.get("error", "unknown_error"))
                    elif "error" in error_data:
                        message = error_data.get("error", "unknown_error")
                    # Management API format: {error, details, request_id}
                    else:
                        message = error_data.get("error", error_data.get("message", response.text))
                        # Append validation details if present
                        if "details" in error_data and error_data["details"]:
                            details_str = ", ".join(str(d) for d in error_data["details"] if d)
                            if details_str:
                                message = f"{message}: {details_str}"
                except Exception:
                    message = response.text
                raise APIError(response.status_code, message, error_data if 'error_data' in locals() else None)
            return response.json()
        except requests.RequestException as e:
            raise APIError(0, f"Network error: {str(e)}")

    def github_device_code(self, tenant_id: str) -> dict[str, Any]:
        return self._request("POST", "/auth/github/device", json={"tenant_id": tenant_id})

    def github_poll_token(self, tenant_id: str, device_code: str) -> dict[str, Any]:
        return self._request("POST", "/auth/github/token", json={"tenant_id": tenant_id, "device_code": device_code})

    def wait_for_github_auth(self, tenant_id: str, device_code: str, interval: int = 5) -> dict[str, Any]:
        with console.status("[bold green]Waiting for authorization..."):
            while True:
                try:
                    return self.github_poll_token(tenant_id, device_code)
                except APIError as e:
                    if e.status_code == 400:
                        error = e.details.get("error", "")
                        if error == "authorization_pending":
                            time.sleep(interval)
                            continue
                        elif error == "slow_down":
                            interval += 5
                            time.sleep(interval)
                            continue
                    raise

    def list_tenants(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/tenants")
        return result.get("tenants", [])

    def create_tenant(self, tenant_id: str, name: str) -> dict[str, Any]:
        return self._request("POST", "/tenants", json={"tenant_id": tenant_id, "name": name})

    def get_tenant(self, tenant_id: str) -> dict[str, Any]:
        return self._request("GET", f"/tenants/{tenant_id}")

    def delete_tenant(self, tenant_id: str) -> None:
        self._request("DELETE", f"/tenants/{tenant_id}")

    def list_repos(self, tenant_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/tenants/{tenant_id}/repos")
        return result.get("repos", [])

    def create_repo(self, tenant_id: str, repo_name: str) -> dict[str, Any]:
        return self._request("POST", f"/tenants/{tenant_id}/repos", json={"repo_name": repo_name})

    def delete_repo(self, tenant_id: str, repo_name: str) -> None:
        self._request("DELETE", f"/tenants/{tenant_id}/repos/{repo_name}")

    def list_tokens(self, tenant_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/tenants/{tenant_id}/tokens")
        return result.get("tokens", [])

    def create_token(
        self,
        tenant_id: str,
        name: str,
        scope: str,
        permission: str,
        repo_name: Optional[str] = None,
        expires_in_days: Optional[int] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "scope": scope,
            "permission": permission,
        }
        if repo_name:
            body["repo_name"] = repo_name
        if expires_in_days:
            body["expires_in_days"] = expires_in_days
        return self._request("POST", f"/tenants/{tenant_id}/tokens", json=body)

    def delete_token(self, tenant_id: str, token_id: str) -> None:
        self._request("DELETE", f"/tenants/{tenant_id}/tokens/{token_id}")

    def get_usage(self, tenant_id: str) -> dict[str, Any]:
        return self._request("GET", f"/tenants/{tenant_id}/usage")
