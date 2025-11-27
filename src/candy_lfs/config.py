import json
import os
from pathlib import Path
from typing import Any, Optional

import keyring
import yaml

CONFIG_DIR = Path.home() / ".candy-lfs"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
KEYRING_SERVICE = "candy-lfs"


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
                "api_endpoint": os.getenv("CANDY_LFS_API_ENDPOINT", ""),
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
    def current_tenant(self) -> Optional[str]:
        return self._config.get("current_tenant")

    @current_tenant.setter
    def current_tenant(self, value: Optional[str]) -> None:
        self._config["current_tenant"] = value
        self._save_config()

    def get_token(self, tenant_id: str) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, f"token:{tenant_id}")
        except Exception:
            return None

    def set_token(self, tenant_id: str, token: str) -> None:
        keyring.set_password(KEYRING_SERVICE, f"token:{tenant_id}", token)

    def delete_token(self, tenant_id: str) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, f"token:{tenant_id}")
        except keyring.errors.PasswordDeleteError:
            pass

    def get_github_token(self, tenant_id: str) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, f"github:{tenant_id}")
        except Exception:
            return None

    def set_github_token(self, tenant_id: str, token: str) -> None:
        keyring.set_password(KEYRING_SERVICE, f"github:{tenant_id}", token)

    def delete_github_token(self, tenant_id: str) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, f"github:{tenant_id}")
        except keyring.errors.PasswordDeleteError:
            pass

    def get_tenant_list(self) -> list[dict[str, Any]]:
        return self._config.get("tenants", [])

    def add_tenant(self, tenant_id: str, name: str, role: str) -> None:
        tenants = self._config.get("tenants", [])
        for tenant in tenants:
            if tenant["tenant_id"] == tenant_id:
                tenant["name"] = name
                tenant["role"] = role
                break
        else:
            tenants.append({"tenant_id": tenant_id, "name": name, "role": role})
        self._config["tenants"] = tenants
        self._save_config()

    def remove_tenant(self, tenant_id: str) -> None:
        tenants = self._config.get("tenants", [])
        self._config["tenants"] = [t for t in tenants if t["tenant_id"] != tenant_id]
        self._save_config()
        self.delete_token(tenant_id)
        self.delete_github_token(tenant_id)
