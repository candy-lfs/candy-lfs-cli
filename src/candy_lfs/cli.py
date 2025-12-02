import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .api import APIClient, APIError
from .config import Config, __BUILD_API_ENDPOINT__, __BUILD_LFS_ENDPOINT__

console = Console()
config = Config()


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
        table.add_column("Token")
        for tenant in tenants:
            has_token = "✓" if config.get_github_token(tenant["tenant_id"]) else "✗"
            table.add_row(tenant["tenant_id"], tenant["name"], has_token)
        console.print(table)


@main.command()
def apiconfig() -> None:
    console.print(f"[bold]CANDY_LFS_API_ENDPOINT:[/bold] {__BUILD_API_ENDPOINT__ or '[dim]not set[/dim]'}")
    console.print(f"[bold]CANDY_LFS_LFS_ENDPOINT:[/bold] {__BUILD_LFS_ENDPOINT__ or '[dim]not set[/dim]'}")


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
        repo_names = token_response.get("repo_names", [])
        for rn in repo_names:
            config.set_github_token(tenant_id, token, rn)
        config.add_tenant(tenant_id, tenant_id)
        if not config.current_tenant:
            config.current_tenant = tenant_id
        console.print(f"[green]✓[/green] Logged in as [bold]{github_user}[/bold] ({permission})")
        console.print(f"[green]✓[/green] Token stored for {len(repo_names)} repositories in tenant: {tenant_id}")
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
    if config.current_tenant == tenant_id:
        config.current_tenant = None
    console.print(f"[green]✓[/green] Logged out from tenant: {tenant_id}")


@main.group()
def tenant() -> None:
    pass


@tenant.command("select")
@click.argument("tenant_id")
def select_tenant(tenant_id: str) -> None:
    tenants = config.get_tenant_list()
    if not any(t["tenant_id"] == tenant_id for t in tenants):
        raise click.ClickException(f"Tenant '{tenant_id}' not found. Use 'candy-lfs login' first.")
    config.current_tenant = tenant_id
    console.print(f"[green]✓[/green] Switched to tenant: {tenant_id}")


main.add_command(config_cmd, name="config")


if __name__ == "__main__":
    main()
