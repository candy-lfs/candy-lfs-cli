import sys
import subprocess
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm

from . import __version__
from .api import APIClient, APIError
from .config import Config

console = Console()
config = Config()


def get_client(tenant_id: Optional[str] = None) -> APIClient:
    if not config.api_endpoint:
        raise click.ClickException(
            "API endpoint not configured. Set with: candy-lfs config set-endpoint <url>"
        )
    if tenant_id is None:
        tenant_id = config.current_tenant
        if not tenant_id:
            raise click.ClickException(
                "No tenant selected. Use: candy-lfs tenant select <tenant-id>"
            )
    token = config.get_token(tenant_id)
    if not token:
        raise click.ClickException(
            f"No authentication token for tenant '{tenant_id}'. Use: candy-lfs login"
        )
    return APIClient(config.api_endpoint, token)


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    pass


@main.group()
def config_cmd() -> None:
    pass


@config_cmd.command("set-endpoint")
@click.argument("url")
def set_endpoint(url: str) -> None:
    config.api_endpoint = url
    console.print(f"[green]✓[/green] API endpoint set to: {url}")


@config_cmd.command("show")
def show_config() -> None:
    console.print(f"[bold]API Endpoint:[/bold] {config.api_endpoint or '[dim]not set[/dim]'}")
    console.print(f"[bold]Current Tenant:[/bold] {config.current_tenant or '[dim]none[/dim]'}")
    tenants = config.get_tenant_list()
    if tenants:
        console.print("\n[bold]Known Tenants:[/bold]")
        table = Table()
        table.add_column("Tenant ID")
        table.add_column("Name")
        table.add_column("Role")
        table.add_column("Token")
        for tenant in tenants:
            has_token = "✓" if config.get_github_token(tenant["tenant_id"]) else "✗"
            table.add_row(tenant["tenant_id"], tenant["name"], tenant["role"], has_token)
        console.print(table)


@main.command()
@click.argument("tenant_id")
def login(tenant_id: str) -> None:
    if not config.api_endpoint:
        raise click.ClickException(
            "API endpoint not configured. Set with: candy-lfs config set-endpoint <url>"
        )
    try:
        client = APIClient(config.api_endpoint)
        console.print(f"[bold]Logging in to tenant:[/bold] {tenant_id}")
        device_response = client.github_device_code(tenant_id)
        user_code = device_response["user_code"]
        verification_uri = device_response["verification_uri"]
        console.print(f"\n[bold yellow]→ Open this URL in your browser:[/bold yellow]")
        console.print(f"  {verification_uri}")
        console.print(f"\n[bold yellow]→ Enter this code:[/bold yellow]")
        console.print(f"  [bold cyan]{user_code}[/bold cyan]\n")
        token_response = client.wait_for_github_auth(
            tenant_id, device_response["device_code"], device_response["interval"]
        )
        token = token_response["token"]
        github_user = token_response["github_user"]
        permission = token_response["permission"]
        config.set_github_token(tenant_id, token)
        config.set_lfs_token(tenant_id, token)
        config.add_tenant(tenant_id, tenant_id, "member")  # Default role
        if not config.current_tenant:
            config.current_tenant = tenant_id
        console.print(f"[green]✓[/green] Logged in as [bold]{github_user}[/bold] ({permission})")
        console.print(f"[green]✓[/green] Token stored for tenant: {tenant_id}")
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        if e.status_code:
            console.print(f"[dim]Status code: {e.status_code}[/dim]")
        if e.details:
            console.print(f"[dim]Details: {e.details}[/dim]")
        sys.exit(1)


@main.command()
@click.argument("tenant_id", required=False)
def logout(tenant_id: Optional[str]) -> None:
    if not tenant_id:
        tenant_id = config.current_tenant
        if not tenant_id:
            raise click.ClickException("No tenant specified and no current tenant selected")
    config.delete_github_token(tenant_id)
    config.delete_lfs_token(tenant_id)
    config.delete_token(tenant_id)
    if config.current_tenant == tenant_id:
        config.current_tenant = None
    console.print(f"[green]✓[/green] Logged out from tenant: {tenant_id}")


@main.group()
def tenant() -> None:
    pass


@tenant.command("list")
def list_tenants() -> None:
    tenants = config.get_tenant_list()
    if not tenants:
        console.print("[dim]No tenants configured. Use 'candy-lfs login' to authenticate.[/dim]")
        return
    table = Table(title="Your Tenants")
    table.add_column("Tenant ID")
    table.add_column("Name")
    table.add_column("Role")
    table.add_column("Current")
    for tenant in tenants:
        is_current = "✓" if tenant["tenant_id"] == config.current_tenant else ""
        table.add_row(tenant["tenant_id"], tenant["name"], tenant["role"], is_current)
    console.print(table)


@tenant.command("select")
@click.argument("tenant_id")
def select_tenant(tenant_id: str) -> None:
    tenants = config.get_tenant_list()
    if not any(t["tenant_id"] == tenant_id for t in tenants):
        raise click.ClickException(f"Tenant '{tenant_id}' not found. Use 'candy-lfs login' first.")
    config.current_tenant = tenant_id
    console.print(f"[green]✓[/green] Switched to tenant: {tenant_id}")


@tenant.command("info")
@click.argument("tenant_id", required=False)
def tenant_info(tenant_id: Optional[str]) -> None:
    try:
        client = get_client(tenant_id)
        tid = tenant_id or config.current_tenant
        info = client.get_tenant(tid)
        console.print(f"[bold]Tenant ID:[/bold] {info['tenant_id']}")
        console.print(f"[bold]Name:[/bold] {info['name']}")
        console.print(f"[bold]Plan:[/bold] {info['plan']}")
        console.print(f"[bold]Your Role:[/bold] {info['role']}")
        console.print(f"[bold]Created:[/bold] {info['created_at']}")
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        sys.exit(1)


@main.group()
def repo() -> None:
    pass


@repo.command("list")
@click.option("--tenant", "-t", help="Tenant ID")
def list_repos(tenant: Optional[str]) -> None:
    try:
        client = get_client(tenant)
        tid = tenant or config.current_tenant
        repos = client.list_repos(tid)
        if not repos:
            console.print("[dim]No repositories found.[/dim]")
            return
        table = Table(title=f"Repositories in {tid}")
        table.add_column("Repository")
        table.add_column("Created")
        for repo_item in repos:
            table.add_row(repo_item["repo_name"], repo_item["created_at"])
        console.print(table)
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        sys.exit(1)


@repo.command("create")
@click.argument("repo_name")
@click.option("--tenant", "-t", help="Tenant ID")
def create_repo(repo_name: str, tenant: Optional[str]) -> None:
    try:
        client = get_client(tenant)
        tid = tenant or config.current_tenant
        result = client.create_repo(tid, repo_name)
        console.print(f"[green]✓[/green] Repository created: {result['repo_name']}")
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        sys.exit(1)


@repo.command("delete")
@click.argument("repo_name")
@click.option("--tenant", "-t", help="Tenant ID")
@click.confirmation_option(prompt="Are you sure?")
def delete_repo(repo_name: str, tenant: Optional[str]) -> None:
    try:
        client = get_client(tenant)
        tid = tenant or config.current_tenant
        client.delete_repo(tid, repo_name)
        console.print(f"[green]✓[/green] Repository deleted: {repo_name}")
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        sys.exit(1)


@main.group()
def token() -> None:
    pass


@token.command("list")
@click.option("--tenant", "-t", help="Tenant ID")
def list_tokens(tenant: Optional[str]) -> None:
    try:
        client = get_client(tenant)
        tid = tenant or config.current_tenant
        tokens = client.list_tokens(tid)
        if not tokens:
            console.print("[dim]No tokens found.[/dim]")
            return
        table = Table(title=f"Tokens in {tid}")
        table.add_column("Token ID")
        table.add_column("Name")
        table.add_column("Scope")
        table.add_column("Repo")
        table.add_column("Permission")
        table.add_column("Expires")
        for token_item in tokens:
            table.add_row(
                token_item["token_id"],
                token_item["name"],
                token_item["scope"],
                token_item.get("repo_name", "-"),
                token_item["permission"],
                token_item.get("expires_at", "never")[:10] if token_item.get("expires_at") else "never"
            )
        console.print(table)
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        sys.exit(1)


@token.command("create")
@click.argument("name")
@click.option("--scope", type=click.Choice(["tenant", "repo"]), default="tenant")
@click.option("--repo")
@click.option("--permission", type=click.Choice(["rw", "ro"]), default="rw")
@click.option("--expires", type=int)
@click.option("--tenant", "-t", help="Tenant ID")
def create_token(
    name: str, scope: str, repo: Optional[str], permission: str, expires: Optional[int], tenant: Optional[str]
) -> None:
    if scope == "repo" and not repo:
        raise click.ClickException("--repo is required when scope is 'repo'")
    try:
        client = get_client(tenant)
        tid = tenant or config.current_tenant
        result = client.create_token(tid, name, scope, permission, repo, expires)
        console.print(f"[green]✓[/green] Token created: {result['token_id']}")
        console.print(f"\n[bold yellow]⚠  Save this token:[/bold yellow]")
        console.print(f"[bold cyan]{result['token']}[/bold cyan]\n")
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        sys.exit(1)


@token.command("revoke")
@click.argument("token_id")
@click.option("--tenant", "-t", help="Tenant ID")
@click.confirmation_option(prompt="Are you sure?")
def revoke_token(token_id: str, tenant: Optional[str]) -> None:
    try:
        client = get_client(tenant)
        tid = tenant or config.current_tenant
        client.delete_token(tid, token_id)
        console.print(f"[green]✓[/green] Token revoked: {token_id}")
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        sys.exit(1)


@main.command()
@click.option("--tenant", "-t", help="Tenant ID")
def usage(tenant: Optional[str]) -> None:
    try:
        client = get_client(tenant)
        tid = tenant or config.current_tenant
        usage_data = client.get_usage(tid)
        total_bytes = usage_data["total"]["storage_bytes"]
        total_mb = total_bytes / (1024 * 1024)
        total_gb = total_bytes / (1024 * 1024 * 1024)
        console.print(f"\n[bold]Storage Usage for {tid}:[/bold]")
        console.print(f"Total: {total_gb:.2f} GB ({total_mb:.1f} MB, {usage_data['object_count']} objects)\n")
        if usage_data.get("repos"):
            table = Table(title="Per-Repository Usage")
            table.add_column("Repository")
            table.add_column("Storage", justify="right")
            for repo_usage in usage_data["repos"]:
                repo_mb = repo_usage["storage_bytes"] / (1024 * 1024)
                table.add_row(repo_usage["repo_name"], f"{repo_mb:.2f} MB")
            console.print(table)
    except APIError as e:
        console.print(f"[red]✗[/red] {e.message}", style="bold red")
        sys.exit(1)


main.add_command(config_cmd, name="config")


if __name__ == "__main__":
    main()
