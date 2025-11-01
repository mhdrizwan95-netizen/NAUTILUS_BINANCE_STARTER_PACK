from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from .config import settings
from .trainer import train_once


def main():
    logger.info("scheduler starting")
    sched = BlockingScheduler(timezone="UTC")

    def _job():
        try:
            res = train_once(n_states=settings.HMM_STATES, promote=True)
            logger.info(f"retrain -> {res}")
        except Exception as e:
            logger.exception(f"retrain failed: {e}")

    sched.add_job(
        _job,
        CronTrigger.from_crontab(settings.RETRAIN_CRON),
        name="periodic_retrain",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
