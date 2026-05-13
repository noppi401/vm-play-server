"""Command-line interface for AIvenv."""

import click


@click.command()
@click.version_option()
def main() -> None:
    """Run the AIvenv command-line interface."""
    click.echo("AIvenv scaffold is installed.")
