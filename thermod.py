#! /usr/bin/env python2


"""
This is the THERMOD daemon that is part of the Pithy thermostat.

It is always designed to be running when the RPI is powered on.  It actually
controls the HEATER and FAN pins of the thermostat, and is the only
program that does.  It takes its direction from one file called STATUS_FILE
that holds "status\ntargTemp", where status = {heat, off} and targTemp
is in degF

This daemon controls the GPIO pins directly using the WiringPI library.

Other daemons that are involved are:
  * websvrd.py      -- Web Server Daemon.  Runs when GUI is up.

  * getTemp.py - (GIT.py) Python script to read the temp/humid from
        the GPIO sensors.  Can configure it to read that info from
        a static file, too.  See sourcefile.  Configured through
        config.txt
  * Setui           -- Modifies the STATUS_FILE file only, which is what gives
        direction to pithyd.py.  It simulates driving the UI.
  * Settemp         -- When GIT.py is in debug mode, then this script
        sets the apparent temp&humid.
  * daemon.py       -- Part of a stock library to allow Python programs
        to become long-running daemons.
  * Chromium        -- accesses localhost:7000 for GUI

"""


import sys
import subprocess
import os
import time
import datetime
import dateutil.parser
import ConfigParser
import calendar
from datetime import datetime, timedelta
import pytz
import pdb
import remote_pdb
from tzlocal import get_localzone
import logging

import wiringpi


def bp():
  remote_pdb.set_trace('0.0.0.0',4444)
# ----------------------------------
# - Read config and set up logging -
# ----------------------------------
config = ConfigParser.ConfigParser()
config.read("config.txt")
log = logging.getLogger()

# Make it skip printing to stderr
log.propagate = False


DEBUGLEVEL = logging.error
loglevel = logging.INFO
thermo_DEBUG = config.getboolean('thermod', 'DEBUG')
if config.getboolean('thermod', "DEBUG"):
  loglevel = logging.DEBUG
  DEBUG=thermo_DEBUG



active_hysteresis = float(config.get('main', 'active_hysteresis'))
inactive_hysteresis = float(config.get('main', 'inactive_hysteresis'))

HEATER_PIN = int(config.get('main', 'HEATER_PIN'))
AC_PIN = int(config.get('main', 'AC_PIN'))
FAN_PIN = int(config.get('main', 'FAN_PIN'))

TH_FILE = config.get('temp sensor', "TEMP_HUM_FILE").strip('"')
PID_FILE = config.get('thermod', 'PIDFILE').strip('"')
LOG_FILE = config.get('thermod', "LOGFILE").strip('"')
STATUS_FILE = config.get('thermod', "STATUSFILE").strip('"')


# create log
log = logging.getLogger()
log.setLevel(loglevel)
# create file handler which logs even debug messages
fh = logging.FileHandler(LOG_FILE)
fh.setLevel(loglevel)
# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)
# create formatter and add it to the handlers
formatterF = logging.Formatter('%(asctime)s:%(processName)s:%(levelname)s:%(message)s')
formatterC = logging.Formatter('%(filename)s: %(message)s')
fh.setFormatter(formatterF)
ch.setFormatter(formatterC)
# add the handlers to the log
log.addHandler(fh)
log.addHandler(ch)





local_tz = pytz.timezone('US/Pacific-New')  # use your local timezone name here
# AuthNOTE: pytz.reference.LocalTimezone() would produce wrong result here

# You could use `tzlocal` module to get local timezone on Unix and Win32
# from tzlocal import get_localzone # $ pip install tzlocal

# # get local timezone
# local_tz = get_localzone()


def utc_to_local(utc_dt):
  local_dt = utc_dt.replace(tzinfo=pytz.utc).astimezone(local_tz)
  return local_tz.normalize(local_dt)  # .normalize might be unnecessary


def repeat_to_length(string_to_expand, length):
  return (string_to_expand * ((length / len(string_to_expand)) + 1))[:length]


def errhdr(outch, inch, str):
  ts = repeat_to_length(outch, 40) + "\n"
  ts += repeat_to_length(inch, 40) + "\n"
  ts += repeat_to_length(inch, 40) + "\n"
  ts += repeat_to_length(inch, 10) + ' Message: ' + str + "\n"
  ts += repeat_to_length(inch, 40) + "\n"
  ts += repeat_to_length(inch, 40) + "\n"
  ts += repeat_to_length(outch, 40) + "\n"
  return(ts.format(str))


def pgpio(pins, state):
  log.debug('-----GPIO-OUTPUT({},{})'.format(pins, state))
  # Convert to list if it's a single pin number
  if not(isinstance(pins, list)):
    pins = [ pins ]
  for i in pins:
    wiringpi.digitalWrite(i, state)

def trimFloat(fnum):
  """ Trims a floating point input to 2 digits and returns the string."""
  return "{:.2f}".format(fnum)



from daemon import Daemon
from getTemp import getTemp

# set working directory to where "rubustat_daemon.py" is
abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)

# Set local timezone
local_tz = pytz.timezone('US/Pacific-New')


def lnow():
  utc_time = datetime.now()
  tzone = get_localzone()
  ltime = tzone.localize(utc_time)

  rts = utc_time.strftime("%Y-%m-%d %H:%M:%S")
  return rts


sqliteEnabled = config.getboolean('sqlite', 'enabled')
if sqliteEnabled == True:
  import sqlite3

# mail config
mailEnabled = config.getboolean('mail', 'enabled')
if mailEnabled == True:
  import smtplib

config.read("mailconf.txt")
SMTP_SERVER = config.get('mailconf', 'SMTP_SERVER')
SMTP_PORT = int(config.get('mailconf', 'SMTP_PORT'))
username = config.get('mailconf', 'username')
password = config.get('mailconf', 'password')
sender = config.get('mailconf', 'sender')
recipient = config.get('mailconf', 'recipient')
subject = config.get('mailconf', 'subject')
body = config.get('mailconf', 'body')
errorThreshold = float(config.get('mail', 'errorThreshold'))


class rubustatDaemon(Daemon):

  lastTemp = 0.0
  lastHumid = 0.0

  def configureGPIO(self):
    wiringpi.wiringPiSetupSys()
    # gpio export 4 high
    # gpio export 17 high
    subprocess.call(["gpio", "export", str(HEATER_PIN), "high" ])
    subprocess.call(["gpio", "export", str(FAN_PIN), "high" ])

    wiringpi.pinMode(HEATER_PIN, 1)       # Output mode
    wiringpi.digitalWrite(HEATER_PIN, 1)  # Pins are activeHI, so turn off.
    wiringpi.pinMode(FAN_PIN, 1)      # Output mode
    wiringpi.digitalWrite(FAN_PIN, 1)  # Pins are activeHI, so turn off.

  def getHVACState(self):
    # Must flip them because the relays are active LOW, and inactive HIGH
    heatStatus = 1 - wiringpi.digitalRead(HEATER_PIN)
    fanStatus = 1 - wiringpi.digitalRead(FAN_PIN)

    if heatStatus == 1 and fanStatus == 1:
      # heating
      return 1
    elif heatStatus == 0 and fanStatus == 0:
      # idle
      return 0
    else:
      # broken
      return 2

  def heat(self):
    pgpio(HEATER_PIN, wiringpi.LOW)
    pgpio(FAN_PIN, wiringpi.LOW)
    return 1

  def fan_to_idle(self):
    # to blow the rest of the heated / cooled air out of the system
    pgpio(HEATER_PIN, wiringpi.HIGH)
    pgpio(FAN_PIN, wiringpi.LOW)
    time.sleep(30)


  def idle(self):
    pgpio(HEATER_PIN, wiringpi.HIGH)
    pgpio(FAN_PIN, wiringpi.HIGH)
    # delay to preserve compressor
    log.debug(".....\tGoing to sleep for 45 seconds")
    time.sleep(45)
    return 0

  if mailEnabled == True:
    def sendErrorMail(mystr):
      headers = ["From: " + sender,
                 "Subject: " + subject + mystr,
                 "To: " + recipient,
                 "MIME-Version: 1.0",
                 "Content-Type: text/html"]
      headers = "\r\n".join(headers)
      try:
        session = smtplib.SMTP_SSL("{}:{}".format(SMTP_SERVER, SMTP_PORT))
        session.login(username, password)
        session.sendmail(sender, recipient, headers + "\r\n\r\n" + body)
        session.quit()
      except:
        log.error("Error trying to send email warning")


  def run(self):
    # Line below makes us log immediately upon running the first time.
    lastLog = datetime.now() - timedelta(minutes=6)
    lastMail = datetime.now()
    log.info("Daemon starting, pid is %d", os.getpid())
    self.configureGPIO()
    while True:

      # change cwd to wherever rubustat_daemon is
      abspath = os.path.abspath(__file__)
      dname = os.path.dirname(abspath)
      os.chdir(dname)

      tempHumid = getTemp()
      if len(tempHumid) < 2:
        log.warning("thermod:{}: error reading tempHumid value".format(
            lnow()))
        indoorTemp = rubustatDaemon.lastTemp
        humidity = rubustatDaemon.lastHumid
      else:
        indoorTemp = float(tempHumid[0])
        humidity = float(tempHumid[1])

      hvacState = int(self.getHVACState())

      file = open(STATUS_FILE, "r")
      targetTemp = float(file.readline().rstrip('\n'))
      switchMode = file.readline().rstrip('\n')
      file.close()

      now = datetime.now()
      logElapsed = now - lastLog
      mailElapsed = now - lastMail

      # heat -- check if beyond tolerance
      # it's 72, we want it to be 78, and the error threshold is 5 = this
      # triggers
      if mailEnabled == True and (mailElapsed > timedelta(minutes=20)) and (float(targetTemp) - indoorTemp) > errorThreshold:
        self.sendErrorMail()
        lastMail = datetime.now()
        if DEBUG == 1:
          log.INFO("MAIL: Sent mail to " + recipient + " at " + now)

      # logging actual temp and indoor temp to sqlite database.
      # you can do fun things with this data, like make charts!
      if logElapsed > timedelta(minutes=6) and sqliteEnabled:
        c.execute('INSERT INTO logging VALUES(?, ?, ?, ?, ?, ?)',
                  (now, trimFloat(indoorTemp), targetTemp,
                   trimFloat(humidity), switchMode, hvacState))
        conn.commit()
        lastLog = datetime.now()

      # $hvacState has two values: 0=idle, 1=heating
      # log.debug('Top of Ifs in main loop: mode = <{}>, hvacState = {}'.format(
      #     switchMode, hvacState))
      if switchMode == "heat":
        if hvacState == 0:  # idle
          if indoorTemp < targetTemp - inactive_hysteresis:
            log.debug("STATE: Switching to heat at " +
                    lnow() + ", hvacState = %d" % hvacState)
            hvacState = self.heat()

        elif hvacState == 1:  # heating
          if indoorTemp > targetTemp + active_hysteresis:
            log.debug("STATE: Switching to fan idle at " +
                      lnow() + ", hvacState = %d" % hvacState)
            self.fan_to_idle()
            log.debug("STATE: Switching to idle at " +
                    lnow() + ", hvacState = %d" % hvacState)
            hvacState = self.idle()
      else:
        #
        # The switchMode is "off", so we have to check if the hvacState is actually
        # off as well.  If not, then we have to turn it off.
        #
        if not(switchMode == "off"):
           log.error("Invalid switchMode <{}>".format(switchMode))
           assert(switchMode == "off")
        if (hvacState == 1):  # Heating is on, turn it off
          log.debug("STATE: switch is off, turning off heat and fan");
          log.debug("STATE: Switching to fan idle at " +
                    lnow() + ", hvacState = %d" % hvacState)
          self.fan_to_idle()
          log.debug("STATE: Switching to idle at " +
                  lnow() + ", hvacState = %d" % hvacState)
          hvacState = self.idle()

      # logging stuff
      heatStatus = 1 - wiringpi.digitalRead(HEATER_PIN)
      fanStatus = 1 - wiringpi.digitalRead(FAN_PIN)
      log.debug("Report at " + lnow())
      log.debug("\tswitchMode = " + str(switchMode)+ "")
      log.debug("\thvacState = " + str(hvacState)+ "")
      log.debug("\tindoorTemp = " + str(indoorTemp)+ "")
      log.debug("\ttargetTemp = " + str(targetTemp)+ "")
      log.debug("\theatStatus = " + str(heatStatus) + "")
      log.debug("\tfanStatus = " + str(fanStatus)+ "")
      # log.close()

      time.sleep(5)


if __name__ == "__main__":
  daemon = rubustatDaemon(PID_FILE)


  log.info("***\n*** Restarting thermod at {}, debug is {}\n***".
          format(lnow(), thermo_DEBUG))

  if sqliteEnabled == True:
    conn = sqlite3.connect("temperatureLogs.db")
    c = conn.cursor()
    # Time, temp, targTemp, humid, switch, heater
    c.execute(
        'CREATE TABLE IF NOT EXISTS logging (datetime TIMESTAMP, \
        actualTemp FLOAT, targetTemp INT, humid FLOAT, switch INT, \
        hvacState INT)')

  if len(sys.argv) == 2:
    if 'start' == sys.argv[1]:
      daemon.start()
    elif 'stop' == sys.argv[1]:
      # stop all HVAC activity when daemon stops
      wiringpi.pinMode(HEATER_PIN, 0)
      wiringpi.pinMode(FAN_PIN, 0)

      daemon.stop()
    elif 'restart' == sys.argv[1]:
      daemon.restart()
    else:
      log.error("Unknown command")
      sys.exit(2)
    sys.exit(0)
  else:
    print >>sys.stderr, ("usage: %s start|stop|restart\nExiting..." %
                         sys.argv[0])
    sys.exit(2)
