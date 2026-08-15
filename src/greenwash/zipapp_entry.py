"""Process entry point used by the generated single-file zipapp."""

from greenwash.cli import main as cli_main


def run() -> None:
    """Propagate the CLI's pass/block/error status through zipapp."""
    raise SystemExit(cli_main())
