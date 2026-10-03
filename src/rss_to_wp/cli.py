"""CLI for evidence-based RSS to WordPress publishing."""

from pathlib import Path
from typing import Optional

import typer

from rss_to_wp import __version__
from rss_to_wp.config import get_app_settings, load_feeds_config
from rss_to_wp.pipeline import run_pipeline
from rss_to_wp.rewriter import OpenAIRewriter
from rss_to_wp.storage import DedupeStore
from rss_to_wp.utils import build_summary_email, send_email_notification, setup_logging
from rss_to_wp.wordpress import WordPressClient

app = typer.Typer(
    help="Publish useful, verified local news from RSS sources.", add_completion=False
)


@app.callback()
def main(version: bool = typer.Option(False, "--version", "-v")):
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def run(
    config: Path = typer.Option(Path("feeds.yaml"), "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n"),
    single_feed: Optional[str] = typer.Option(None, "--single-feed", "-f"),
    hours: int = typer.Option(72, "--hours", "-h", min=1, max=168),
    replay: bool = typer.Option(
        False, "--replay", help="Assess recent sources again; requires --dry-run."
    ),
):
    if replay and not dry_run:
        raise typer.BadParameter("--replay requires --dry-run")
    try:
        settings = get_app_settings()
        cfg = load_feeds_config(config)
    except Exception as error:
        # Pydantic error repr can expose secret field values. Keep CI logs clean.
        typer.echo(
            f"Configuration error ({type(error).__name__}); check required settings and feeds.yaml.",
            err=True,
        )
        raise typer.Exit(1) from error
    setup_logging(level=settings.log_level, log_file=settings.log_file)
    if single_feed:
        cfg.feeds = [f for f in cfg.feeds if f.name.casefold() == single_feed.casefold()]
        if not cfg.feeds:
            raise typer.BadParameter("Unknown feed name")
    store = DedupeStore()
    editor = OpenAIRewriter(api_key=settings.openai_api_key, model=settings.openai_model)
    wp = (
        None
        if dry_run
        else WordPressClient(
            settings.wordpress_base_url,
            settings.wordpress_username,
            settings.wordpress_app_password,
            settings.wordpress_post_status,
        )
    )
    report = run_pipeline(cfg, settings, store, editor, wp, dry_run, hours, replay)
    published = [row for row in report["stories"] if row.get("outcome") == "published"]
    if published and settings.smtp_email and settings.smtp_password and settings.notification_email:
        subject, body = build_summary_email(
            processed_articles=[
                {
                    "title": row["article"]["headline"],
                    "url": row["post_url"],
                    "feed_name": "Pontotoc News",
                }
                for row in published
            ],
            skipped_count=report["held"] + report["duplicates"],
            error_count=report["errors"],
            site_name="Pontotoc News",
        )
        send_email_notification(
            smtp_email=settings.smtp_email,
            smtp_password=settings.smtp_password,
            to_email=settings.notification_email,
            subject=subject,
            html_body=body,
        )
    typer.echo(
        f"Eligible: {report['eligible']}; published/saved: {report['published']}; held: {report['held']}; errors: {report['errors']}"
    )
    if report["errors"]:
        raise typer.Exit(1)


@app.command()
def status():
    store = DedupeStore()
    typer.echo(f"Tracked entries: {store.get_processed_count()}")
    for entry in store.get_recent_entries(limit=10):
        typer.echo(f"{entry['entry_title']} — {entry['wp_post_url']}")


@app.command()
def clear_db(confirm: bool = typer.Option(False, "--yes", "-y")):
    if confirm or typer.confirm("Clear local history? WordPress duplicate checks will still run."):
        typer.echo(f"Cleared {DedupeStore().clear_all()} entries")
