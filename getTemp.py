#!/usr/bin/env python2
#
# Based off the tutorial by adafruit here:
# http://learn.adafruit.com/adafruits-raspberry-pi-lesson-11-ds18b20-temperature-sensing/software
#
# v2
#
import Adafruit_DHT
import ConfigParser
import sys
import time
import datetime
from datetime import datetime, timedelta
import pytz
import logging
from pdb import set_trace as bp
import dateutil.parser


# Sensor should be set to Adafruit_DHT.DHT11,
# Adafruit_DHT.DHT22, or Adafruit_DHT.AM2302.
#
sensor = Adafruit_DHT.AM2302

#
# Read the config parameters
#

config = ConfigParser.ConfigParser()
config.read("config.txt")

pin = config.getint('temp sensor', "GPIO_PIN")
envCacheFile = config.get('temp sensor', 'ENVCACHE').strip('"')
dbgTempFile = config.get('temp sensor',"TEMP_HUM_FILE").strip('"')
readInterval = config.getint('temp sensor', "GPIO_READ_INTERVAL")
maxFailsSecs = config.getint('temp sensor', "MAX_FAILS_SECS")
logfile = config.get('temp sensor', "LOGFILE").strip('"')
loglevel = logging.INFO
if config.getboolean('temp sensor', "DEBUG"):
  loglevel = logging.DEBUG


# create log
log = logging.getLogger()
log.setLevel(loglevel)
# create file handler which logs even debug messages
fh = logging.FileHandler(logfile)
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



#
# Writes the temp&humid to the EnvCacheFile.  Any error is fatal.
#
def writeCacheFile(temp, humidity):
  log.debug("Writing cache back to disk with [{:f}, {:f}]".
            format(temp, humidity))
  now = datetime.now()
  try:
    with open(envCacheFile, "w") as file:
      print >> file, "{:-2.2f}\n{:-2.2f}\n{}".format(temp, humidity, now.ctime() )
  except IOError as e:
    log.fatal("Some error writing back to Env Cache File ({}), e = {}".
              format(envCacheFile, e))
    return []


def getTemp():
  global pin, envCacheFile, dbgTempFile, readInterval, maxFailsSecs,\
        logfile, loglevel

  # ----------------------------------------------
  # If we are configured to read the temp&humid from a file instead of
  # the GPIO, go ahead and do that and then return those values
  # ----------------------------------------------

  if dbgTempFile:
      # print >> sys.stderr, "GIT: Look likes we'll read from a file"
      try:
          with open(dbgTempFile, "r") as file:
              ttemp = float(file.readline())
              thumid = float(file.readline())
              log.debug("Using Debug Mode, temp={:-2.2f} humid={:-2.2f}"
                        .format(ttemp, thumid))
              return [ttemp, thumid]
      except IOError as e:
          # Ignore this
          log.error("Error reading debug input file <{}>".format
                    (dbgTempFile))
          log.error(e)
          return []

  # ----------------------------------------------
  # Read the temp values
  # if Successful:
  #   write the vals to the cache file
  # if error:
  #   read the cache file
  #   if time is within tolerance:
  #     return cache values
  #   else:
  #     Fatal Error
  # ----------------------------------------------

  # Read values from GPIO sensors
  humidity, temperature = Adafruit_DHT.read(sensor, pin)

  if humidity is not None and temperature is not None:
      # No errors, so let's just return those values after we write it to
      # the env_cache file
      tempf = temperature * 9.0 / 5.0 + 32.0
      retval = [ tempf, humidity ]
      writeCacheFile(tempf, humidity)
      return retval
  else:
    #
    # Got an error, so we have to use the cached value.
    #
    log.debug("Using the cache")
    try:
      with open(envCacheFile) as file:
        cTemp = float(file.readline().rstrip('\n'))
        cHumid = float(file.readline().rstrip('\n'))
        cLastTimeString = file.readline().rstrip('\n')
        cLastTime = dateutil.parser.parse(cLastTimeString)
    except IOError as e:
      # IO error, this is fatal.
      log.fatal("Error reading / parsing Env Cache File ({}), error = {}"
                .format(envCacheFile, e))
    #
    # Check to see if the time delta isn't too long
    # If it is, then log it and terminate
    #
    now = datetime.now()
    if (now - cLastTime) > timedelta(seconds=maxFailsSecs):
      # The cache is too stale, fatal error
      log.fatal("Cache is stale: last = %s, now = %s, exiting",
                cLastTimeString, now.ctime())
      return []
    #
    # Got a valid set from the cache, log it and return those values
    #
    log.info("Error reading GPIO, using valid cache: last = %s, now = %s",
              cLastTimeString, now.ctime())
    retval = [ cTemp, cHumid]
    return retval



if __name__ == "__main__":
    returnVal = getTemp()
    log.propagate = True        # Make logging appear on STDERR/OUT
    log.info("Running getTemp now from command line")
    # print(returnVal)
    if (len (returnVal) == 2):
        temp = returnVal[0]
        humid = returnVal[1]
        print ("Temperature is %f" % temp)
        print ("Humidity is %f" % humid)
    else:
      log.fatal("Error from getTemp()!")
      sys.exit(43)
    exit(0)
