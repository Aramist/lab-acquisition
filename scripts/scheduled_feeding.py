import datetime
import sched
import time

from scripts import feeder


def hourly_datetime_generator(interval=3600, on_the_hour=True, stop_dt=None):
    start_time = datetime.datetime.now()
    # The nearest hour prior to the current time
    # The first dt returned by the generator will be this + 1 hour
    if on_the_hour:
        next_feeding = start_time.replace(
                minute=0,
                second=0,
                microsecond=0)
    else:
        next_feeding = start_time
    increment = datetime.timedelta(seconds=interval)
    while stop_dt is None or next_feeding < stop_dt:
        next_feeding = next_feeding + increment
        yield next_feeding


def dispense_food(scheduler, feeder_list, time_generator):
    for feeder in feeder_list:
        feeder.dispense_once()
    try:
        next_time = next(time_generator)
        scheduler.enterabs(next_time.timestamp(), 1, dispense_food, (scheduler, feeder_list, time_generator))
    except StopIteration:
        return


def feed_regularly(dio_ports, interval=3600, on_the_hour=True, stop_dt=None):
    feeders = [feeder.Feeder(port, 'feeder_{}'.format(n)) for n, port in enumerate(dio_ports)]
    time_gen = hourly_datetime_generator(interval, on_the_hour, stop_dt)
    scheduler = sched.scheduler(time.time, time.sleep)
    scheduler.enterabs(next(time_gen).timestamp(), 1, dispense_food, (scheduler, feeders, time_gen))
    scheduler.run()


if __name__ == '__main__':
    # Run a demo
    feed_regularly((u'Dev1/port0/line7',), interval=3600, on_the_hour=True, stop_dt=None)

