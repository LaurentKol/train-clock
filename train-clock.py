#!/usr/bin/python
"""Train Clock

Description: Display next trains departure time for an itinerary within Japan (using Jorudan website).

Ingredients:
  1x Raspberry Pi with internet connectivity
  1x 4 digit 7segment LED using TM1637

Script is provided "as -is", without any warranty nor responsability.

TODO: Adapt to use more common tm1637 module, such as https://github.com/intel-iot-devkit/upm/blob/master/examples/python/tm1637.py

"""
__author__ = "Laurent Kolakofsky (laurent.kol@gmail.com)"
__license__ = "GPLv2"

import sys, pycurl, re, threading

from tm1637 import *
from HTMLParser import HTMLParser
from StringIO import StringIO
from urllib import urlencode
from time import sleep
from datetime import date, datetime, time, timedelta

DEBUG = True

DISPLAY_REFRESH_DELAY  = 2
SCHEDULE_REFRESH_DELAY = 60

STATION_FROM = 'Tameikesan-No'
STATION_TO   = 'Shibuya'
# Only get schedule from this train line
TRAIN_LINE_REGEXP = 'Ginza Line'
# Time to walk to station
MINUTE_TO_STATION = 6

# Only run during this schedule
SCHEDULE = {
  'weekday' : [range(700,830),range(1845,2345)],
  'weekend' : [range(1000,2345)]
}

# Returns True if now is in SCHEDULE
def isItTimeToRun():
  now = datetime.today()
  weekday_i = int(now.strftime('%w'))
  time_i = int(now.strftime('%H%M'))

  def isInRange(time,time_range):
    for time_range in SCHEDULE['weekday']:
      if time_i in time_range:
        return True
    return False

  if weekday_i in range(1,5):
    return isInRange(time_i,SCHEDULE['weekday'])
  else:
    return isInRange(time_i,SCHEDULE['weekend'])

# HTMLParser subclass overriding handler methods
class JorudanHTMLParser(HTMLParser):
    departure = None
    line = 'unknown'
    tags = []
    state = 0 # before-body

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):

        # Find main's page body
        if self.state in range(0,3) and len(self.tags) >= 2 and self.tags[-2:] == ['b','font']:
          if data.strip() == STATION_FROM:
            self.state = 1 # in-body
          elif data.strip() == STATION_TO:
            self.state = 4 # after-body

        # Get 'Train Info'
        if self.state in range(1,3) and self.tags[-12:] == ['tr','td','img','td','img','td','img','td','img','td','b','font'] and len(data) > 4:
          self.line = data

        # Get next train's time
        if self.state in range(1,3) and self.tags[-1] == 'font':
          line_m = re.match('.*'+TRAIN_LINE_REGEXP+'.*',self.line)
          time_m = re.match('([0-9]+:[0-9]+[a-z]+).*',data)
          if line_m and time_m:
            self.departure = time_m.group(0)

class ScheduleFinder:
    def __init__(self):
            self.c = pycurl.Curl()

    def GetSchedule(self, dt):

        if not isinstance(dt,datetime):
          print "GetSchedule only take datetime arg, not ", dt
          return None

        post_data = {
            'from_in': STATION_FROM,
            'to_in': STATION_TO,
            'Dyyyymm': "%04d%02d" % (dt.year,dt.month),
            'Ddd': "%02d" % dt.day,
            'Dhh': "%02d" % dt.hour,
            'Dmn': "%02d" % dt.minute,
            'Sfromto':'from',
            'Sseat':'0',
            'Bsearch':'Search',
            'Knorikae':'Knorikae',
            'proc_mode':'K',
            'proc_sw':'11',
            'proc_sw_sub':'0',
            'from_nm':'',
            'to_nm':'',
            'Sfrom_sw':'1'}

        # Form data must provide already urlencoded.
        postfields = urlencode(post_data)

        c = pycurl.Curl()
        c.setopt(c.URL, 'http://world.jorudan.co.jp/norikae/cgi-bin/engkeyin.cgi')

        c.setopt(c.POSTFIELDS, postfields)
        buffer = StringIO()
        c.setopt(c.WRITEFUNCTION, buffer.write)

        c.perform()
        c.close()

        # Fed parser's some HTML
        parser = JorudanHTMLParser()
        parser.feed(buffer.getvalue())

        # Check whether departure time was found
        if not parser.departure:
          print 'Failed to find schedule. Either Station or Line name is wrong or parser is broken'

        # Transform into 24h format
        try:
          t = datetime.strptime(parser.departure, '%I:%M%p')
        except TypeError:
          t = None
        return t


class ScheduleFinderThread(threading.Thread):
  next_train_1_s = '0000'
  next_train_2_s = '0000'

  def __init__(self):
    threading.Thread.__init__(self)
    self.sf = ScheduleFinder()

  def run(self):
    while True:
      if isItTimeToRun():
        now = datetime.now()
        now_plus_time_to_stn = datetime.combine(date.today(), time(now.hour,now.minute)) + timedelta(minutes=MINUTE_TO_STATION)
        next_train_1 = self.sf.GetSchedule(now_plus_time_to_stn)

        if next_train_1:
          next_train_1_plus_one_min = datetime.combine(date.today(),time(next_train_1.hour,next_train_1.minute)) + timedelta(minutes=1)
          next_train_2 = self.sf.GetSchedule(next_train_1_plus_one_min)

        if next_train_1 and next_train_2:
          self.next_train_1_s = "%02d%02d" % (next_train_1.hour,next_train_1.minute)
          self.next_train_2_s = "%02d%02d" % (next_train_2.hour,next_train_2.minute)
          if DEBUG : print 'ScheduleFinderThread:',self.next_train_1_s
          if DEBUG : print 'ScheduleFinderThread:',self.next_train_2_s

      sleep(SCHEDULE_REFRESH_DELAY)

class DisplayThread(threading.Thread):
  def __init__(self):
    threading.Thread.__init__(self)
    self.Display = TM1637(20,21,BRIGHT_TYPICAL)
    self.Display.ShowDoublepoint(True)
    self.Display.Clear()

  def formatToDisplay(self,four_digit_s):
    a = []
    for char in four_digit_s:
      a.append(int(char))
    return a

  def run(self):
    while True:
      if isItTimeToRun():
        if DEBUG : print "DisplayThread:",schedule_finder_t.next_train_1_s,schedule_finder_t.next_train_2_s
        self.Display.Show(self.formatToDisplay(schedule_finder_t.next_train_1_s))
        sleep(DISPLAY_REFRESH_DELAY)
        self.Display.Show(self.formatToDisplay(schedule_finder_t.next_train_2_s))
        sleep(DISPLAY_REFRESH_DELAY)
      else:
        if DEBUG : print "Off running schedule, sleeping..."
        self.Display.Clear()
        sleep(60)

# Use different threads for train schedule lookup and display so that there's no lag when loading new train departure time.
schedule_finder_t = ScheduleFinderThread()
schedule_finder_t.daemon = True
schedule_finder_t.start()
display_t = DisplayThread()
display_t.daemon = True
display_t.start()

# Required when running threads in daemon mode, which is needed to catch Ctrl-C
while True:
  sleep(60)

