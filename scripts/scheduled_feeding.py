import datetime
import sched

import feeder


def hourly_datetime_generator(interval=3600, on_the_hour=True):
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
    while True:
        next_feeding = next_feeding + increment
        yield next_feeding


def dispense_food(scheduler, feeder_list, time_generator):
    for feeder in feeder_list:
        feeder.dispense_once()
    scheduler.enterabs(next(time_generator), 1, dispense_food, (scheduler, feeders, time_gen))


def feed_hourly(dio_ports, interval=3600, on_the_hour=True):
    feeders = [feeder.Feeder(port, 'feeder_{}'.format(n)) for port,n in enumerate(dio_ports)]
    time_gen = hourly_datetime_generator(interval, on_the_hour)
    scheduler = sched.scheduler()
    scheduler.enterabs(next(time_gen), 1, dispense_food, (scheduler, feeders, time_gen))


if __name__ == '__main__':
    # Run a demo with shorter feed delays
    feed_regularly(('Dev1/port0/line7',), interval=5, on_the_hour=False)

