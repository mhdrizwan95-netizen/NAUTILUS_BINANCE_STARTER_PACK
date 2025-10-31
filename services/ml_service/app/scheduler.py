from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from .config import settings
from .trainer import train_once


def main():
    logger.info("Launching ML retrain scheduler...")
    sched = BlockingScheduler(timezone="UTC")

    def _job():
        try:
            logger.info("Scheduled retrain starting...")
            res = train_once(n_states=settings.HMM_STATES, promote=True)
            logger.info(f"Retrain done -> {res}")
        except Exception as e:
            logger.exception(f"Scheduled retrain failed: {e}")

    cron = CronTrigger.from_crontab(settings.RETRAIN_CRON)
    sched.add_job(_job, cron, name="periodic_retrain", max_instances=1, coalesce=True, misfire_grace_time=600)

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
