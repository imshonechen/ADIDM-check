import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.settings import get_scrape_settings

logger = logging.getLogger(__name__)
_scheduler = None


def _run_scrape(app):
    with app.app_context():
        from app.scraper import scrape
        config = app.config
        settings = get_scrape_settings(config['DATABASE_PATH'], config)
        result = scrape(
            config['DATABASE_PATH'],
            settings['scrape_url'],
            settings['scrape_user_agent'],
            settings['request_timeout']
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
    settings = get_scrape_settings(app.config['DATABASE_PATH'], app.config)
    _scheduler.add_job(
        _run_scrape,
        CronTrigger(hour=settings['scrape_hour'], minute=settings['scrape_minute']),
        args=[app],
        id='daily_scrape'
    )
    _scheduler.start()
    logger.info(
        f"Scheduler started: daily scrape at "
        f"{settings['scrape_hour']:02d}:{settings['scrape_minute']:02d}"
    )


def reschedule_daily_scrape(app):
    if _scheduler is None:
        return

    settings = get_scrape_settings(app.config['DATABASE_PATH'], app.config)
    _scheduler.reschedule_job(
        'daily_scrape',
        trigger=CronTrigger(hour=settings['scrape_hour'], minute=settings['scrape_minute'])
    )
    logger.info(
        f"Scheduler rescheduled: daily scrape at "
        f"{settings['scrape_hour']:02d}:{settings['scrape_minute']:02d}"
    )
