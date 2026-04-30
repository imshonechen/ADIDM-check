import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)
_scheduler = None


def _run_scrape(app):
    with app.app_context():
        from app.scraper import scrape
        config = app.config
        result = scrape(
            config['DATABASE_PATH'],
            config['SCRAPE_URL'],
            config['SCRAPE_USER_AGENT'],
            config['REQUEST_TIMEOUT']
        )
        if result:
            logger.info(
                f"Scrape result: status={result.get('status')}, "
                f"version={result.get('version')}, is_new={result.get('is_new')}"
            )
        else:
            logger.warning('Scrape returned no result')


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _run_scrape,
        'cron',
        hour=app.config['SCRAPE_HOUR'],
        minute=app.config['SCRAPE_MINUTE'],
        args=[app],
        id='daily_scrape'
    )
    _scheduler.start()
    logger.info(f"Scheduler started: daily scrape at {app.config['SCRAPE_HOUR']:02d}:{app.config['SCRAPE_MINUTE']:02d}")
