import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import yaml

CONFIG_DIR = Path.home() / ".candy-lfs"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

__BUILD_API_ENDPOINT__ = ""
__BUILD_LFS_ENDPOINT__ = ""

DEFAULT_API_ENDPOINT = __BUILD_API_ENDPOINT__ or os.getenv("CANDY_LFS_API_ENDPOINT", "")
DEFAULT_LFS_ENDPOINT = __BUILD_LFS_ENDPOINT__ or os.getenv("CANDY_LFS_LFS_ENDPOINT", "")


class Config:
    def __init__(self) -> None:
        self.config_dir = CONFIG_DIR
        self.config_file = CONFIG_FILE
        self._config: dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        if self.config_file.exists():
            with open(self.config_file, "r") as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {
                "api_endpoint": DEFAULT_API_ENDPOINT,
                "current_tenant": None,
            }

    def _save_config(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            yaml.dump(self._config, f, default_flow_style=False)

    @property
    def api_endpoint(self) -> str:
        return self._config.get("api_endpoint", "")

    @api_endpoint.setter
    def api_endpoint(self, value: str) -> None:
        self._config["api_endpoint"] = value
        self._save_config()

    @property
    def lfs_endpoint(self) -> str:
        return self._config.get("lfs_endpoint", DEFAULT_LFS_ENDPOINT)

    @lfs_endpoint.setter
    def lfs_endpoint(self, value: str) -> None:
        self._config["lfs_endpoint"] = value
        self._save_config()

    @property
    def current_tenant(self) -> Optional[str]:
        return self._config.get("current_tenant")

    @current_tenant.setter
    def current_tenant(self, value: Optional[str]) -> None:
        self._config["current_tenant"] = value
        self._save_config()

    def _get_git_credential_info(self, tenant_id: str, repo_name: Optional[str] = None) -> tuple[str, str]:
        """Returns (host, path) for git credential (LFS API)"""
        if self.lfs_endpoint:
            parsed = urlparse(self.lfs_endpoint)
            if repo_name:
                path = f"{tenant_id}/{repo_name}"
            else:
                path = tenant_id
            return (parsed.netloc, path)
        if repo_name:
            return ("candy-lfs.local", f"{tenant_id}/{repo_name}")
        return ("candy-lfs.local", tenant_id)

    def _git_credential_get(self, host: str, path: str, username: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "credential", "fill"],
                input=f"protocol=https\nhost={host}\npath={path}\nusername={username}\n\n",
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("password="):
                        return line.split("=", 1)[1]
        except Exception:
            pass
        return None

    def _git_credential_store(self, host: str, path: str, username: str, password: str) -> None:
        try:
            subprocess.run(
                ["git", "credential", "approve"],
                input=f"protocol=https\nhost={host}\npath={path}\nusername={username}\npassword={password}\n\n",
                capture_output=True,
                text=True,
                timeout=5
            )
        except Exception:
            pass

    def _git_credential_erase(self, host: str, path: str, username: str) -> None:
        try:
            subprocess.run(
                ["git", "credential", "reject"],
                input=f"protocol=https\nhost={host}\npath={path}\nusername={username}\n\n",
                capture_output=True,
                text=True,
                timeout=5
            )
        except Exception:
            pass

    def _ensure_use_http_path(self, host: str) -> None:
        """Ensure useHttpPath is enabled for the LFS host to support multi-tenant credentials."""
        config_key = f"credential.https://{host}.useHttpPath"
        try:
            result = subprocess.run(
                ["git", "config", "--global", "--get", config_key],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0 or result.stdout.strip() != "true":
                subprocess.run(
                    ["git", "config", "--global", config_key, "true"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
        except Exception:
            pass

    def get_github_token(self, tenant_id: str, repo_name: Optional[str] = None) -> Optional[str]:
        host, path = self._get_git_credential_info(tenant_id, repo_name)
        return self._git_credential_get(host, path, tenant_id)

    def set_github_token(self, tenant_id: str, token: str, repo_name: Optional[str] = None) -> None:
        host, path = self._get_git_credential_info(tenant_id, repo_name)
        self._ensure_use_http_path(host)
        self._git_credential_store(host, path, tenant_id, token)

    def delete_github_token(self, tenant_id: str, repo_name: Optional[str] = None) -> None:
        host, path = self._get_git_credential_info(tenant_id, repo_name)
        self._git_credential_erase(host, path, tenant_id)

    def delete_all_tenant_credentials(self, tenant_id: str) -> None:
        """Delete all credentials for a tenant (all repositories)."""
        repo_names = self.get_tenant_repos(tenant_id)
        for repo_name in repo_names:
            self.delete_github_token(tenant_id, repo_name)
        self._clear_tenant_repos(tenant_id)

    def get_tenant_repos(self, tenant_id: str) -> list[str]:
        """Get list of repository names for a tenant."""
        tenant_repos = self._config.get("tenant_repos", {})
        return tenant_repos.get(tenant_id, [])

    def set_tenant_repos(self, tenant_id: str, repo_names: list[str]) -> None:
        """Set the list of repository names for a tenant."""
        if "tenant_repos" not in self._config:
            self._config["tenant_repos"] = {}
        self._config["tenant_repos"][tenant_id] = repo_names
        self._save_config()

    def _clear_tenant_repos(self, tenant_id: str) -> None:
        """Clear the repository list for a tenant."""
        tenant_repos = self._config.get("tenant_repos", {})
        if tenant_id in tenant_repos:
            del tenant_repos[tenant_id]
            self._config["tenant_repos"] = tenant_repos
            self._save_config()

    def get_tenant_list(self) -> list[dict[str, Any]]:
        return self._config.get("tenants", [])

    def add_tenant(self, tenant_id: str, name: str) -> None:
        tenants = self._config.get("tenants", [])
        for tenant in tenants:
            if tenant["tenant_id"] == tenant_id:
                tenant["name"] = name
                break
        else:
            tenants.append({"tenant_id": tenant_id, "name": name})
        self._config["tenants"] = tenants
        self._save_config()

    def remove_tenant(self, tenant_id: str) -> None:
        tenants = self._config.get("tenants", [])
        self._config["tenants"] = [t for t in tenants if t["tenant_id"] != tenant_id]
        self._save_config()
        self.delete_github_token(tenant_id)
