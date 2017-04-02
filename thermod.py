#! /usr/bin/env python3


"""
This is the THERMOD daemon that is part of the Pithy thermostat.

It is always designed to be running when the RPI is powered on.  It actually
controls the HEATER and FAN pins of the thermostat, and is the only
program that does.  It takes its direction from one file called STATUS_FILE
that holds "status\ntargTemp", where status = {heat, off} and targTemp
is in degF

This daemon controls the GPIO pins directly using the WiringPI library.
As mentioned, it's the only process that controls the GPIO pin, so

Other daemons that are involved are:
  * websvrd.py      -- Web Server Daemon.  Runs when GUI is up.

  * getTemp.py - (getTemp.py) Python script to read the temp/humid from
        the GPIO sensors.  Can configure it to read that info from
        a static file, as debug.  See sourcefile.  Configured through
        config.txt

  * Setui           -- Modifies the STATUS_FILE file only, which is what gives
        direction to pithyd.py.  It simulates driving the UI.

  * Settemp         -- When getTemp.py is in debug mode, then this script
        sets the apparent temp&humid.

  * Chromium        -- accesses localhost:7000 for GUI

"""


import sys
import subprocess
import os
import time
import datetime
import dateutil.parser
import configparser as ConfigParser
import calendar
from datetime import datetime, timedelta
import pytz
from tzlocal import get_localzone
import logging

import wiringpi


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
# Create logger
fh = logging.StreamHandler()
fh.setLevel(loglevel)
# create formatter and add it to the handlers
formatterF = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s')
fh.setFormatter(formatterF)
# add the handlers to the log
log.addHandler(fh)


print('loglevel == {}, logDEBUG = {}'.format(
    loglevel, logging.DEBUG))





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


from getTemp import getTemp

# set working directory to where "thermod.py" is
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


lastTemp = 0.0
lastHumid = 0.0

def configureGPIO():
  wiringpi.wiringPiSetupSys()
  # gpio export 4 high
  # gpio export 17 high
  subprocess.call(["gpio", "export", str(HEATER_PIN), "high" ])
  subprocess.call(["gpio", "export", str(FAN_PIN), "high" ])

  wiringpi.pinMode(HEATER_PIN, 1)       # Output mode
  wiringpi.digitalWrite(HEATER_PIN, 1)  # Pins are activeHI, so turn off.
  wiringpi.pinMode(FAN_PIN, 1)      # Output mode
  wiringpi.digitalWrite(FAN_PIN, 1)  # Pins are activeHI, so turn off.

def getHVACState():
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

def heat():
  pgpio(HEATER_PIN, wiringpi.LOW)
  pgpio(FAN_PIN, wiringpi.LOW)
  return 1

def fan_to_idle():
  # to blow the rest of the heated / cooled air out of the system
  pgpio(HEATER_PIN, wiringpi.HIGH)
  pgpio(FAN_PIN, wiringpi.LOW)
  time.sleep(30)


def idle():
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


def run():
  # Line below makes us log immediately upon running the first time.
  lastLog = datetime.now() - timedelta(minutes=6)
  lastMail = datetime.now()
  log.info("Daemon starting, pid is %d", os.getpid())
  configureGPIO()
  while True:
    # change cwd to wherever websrvrd is
    abspath = os.path.abspath(__file__)
    dname = os.path.dirname(abspath)
    os.chdir(dname)

    tempHumid = getTemp()
    if len(tempHumid) < 2:
      log.warning("thermod:{}: error reading tempHumid value".format(
          lnow()))
      indoorTemp = lastTemp
      humidity = lastHumid
    else:
      indoorTemp = float(tempHumid[0])
      humidity = float(tempHumid[1])

    hvacState = int(getHVACState())

    try:
      file = open(STATUS_FILE, "r")
      targetTemp = float(file.readline().rstrip('\n'))
      switchMode = file.readline().rstrip('\n')
      file.close()
    except Exception as e:
      # Set default operation modes if the statusfile isn't found.
      targetTemp = 70.0
      switchMode = 'off'

    # Log values so far
    log.debug('Target Temp = %f, Switch = %s'%(targetTemp, switchMode))


    now = datetime.now()
    logElapsed = now - lastLog
    mailElapsed = now - lastMail

    # heat_mode -- check if beyond tolerance
    # it's 72, we want it to be 78, and the error threshold is 5 = this
    # triggers
    if mailEnabled == True and (mailElapsed > timedelta(minutes=20)) and (float(targetTemp) - indoorTemp) > errorThreshold:
      sendErrorMail('Heat beyond threshold ({} - {} > {} = {}'.format(
          targetTemp, indoorTemp, errorThreshold,
          float(targetTemp) - indoorTemp))
      lastMail = datetime.now()
      log.info("MAIL: Sent mail to " + recipient + " at " + now)

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
          log.info("STATE: Switching to heat at " +
                  lnow() + ", hvacState = %d" % hvacState)
          hvacState = heat()

      elif hvacState == 1:  # heating
        if indoorTemp > targetTemp + active_hysteresis:
          log.info("STATE: Switching to fan idle at " +
                    lnow() + ", hvacState = %d" % hvacState)
          fan_to_idle()
          log.info("STATE: Switching to idle at " +
                  lnow() + ", hvacState = %d" % hvacState)
          hvacState = idle()
    else:
      #
      # The switchMode is "off", so we have to check if the hvacState is actually
      # off as well.  If not, then we have to turn it off.
      #
      if not(switchMode == "off"):
         log.fatal("Invalid switchMode <{}>".format(switchMode))
         assert(switchMode == "off")
      if (hvacState == 1):  # Heating is on, turn it off
        log.info("STATE: switch is off, turning off heat and fan");
        log.info("STATE: Switching to fan idle at " +
                  lnow() + ", hvacState = %d" % hvacState)
        fan_to_idle()
        log.info("STATE: Switching to idle at " +
                lnow() + ", hvacState = %d" % hvacState)
        hvacState = idle()

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

  log.info("***\n*** Starting thermod at {}, debug is {}\n***".
          format(lnow(), thermo_DEBUG))



  if sqliteEnabled == True:
    conn = sqlite3.connect("temperatureLogs.db")
    c = conn.cursor()
    # Time, temp, targTemp, humid, switch, heater
    c.execute(
        'CREATE TABLE IF NOT EXISTS logging (datetime TIMESTAMP, \
        actualTemp FLOAT, targetTemp INT, humid FLOAT, switch INT, \
        hvacState INT)')


  try:
    run()
  except KeyboardInterrupt:
    log.debug('Keyboard interrupt, stopping')
    sys.exit(9)
  finally:
    log.info('*** Finally, turning off all relays')
    wiringpi.pinMode(HEATER_PIN, 1)       # Output mode
    wiringpi.digitalWrite(HEATER_PIN, 1)  # Pins are activeHI, so turn off.
    wiringpi.pinMode(FAN_PIN, 1)      # Output mode
    wiringpi.digitalWrite(FAN_PIN, 1)  # Pins are activeHI, so turn off.
