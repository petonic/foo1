#!/usr/bin/env python3
"""getTemp - AM2302 Temp/Humidity Sensor Reader

Usage:
  getTemp.py [-v] [-l] [-s] [-r retries] [-c cachefile] [-m]

Options:
  -v,--verbose    Verbose output.
  -m,--metric     Metric output (Celcius).  Def=Fahrenheit.
  -s,--sensor     Sensor data only, do not use EnvCache (does not read or write
                  from/to the cache.  Will return error value if cannot read
                  device.  Still does retries (unless '-r 0').
  -l,--loop       Loop indefinitely.
  -c,--cache cachefile    Specifies the cachefile to use. D=/tmp/getTemp_cache.
                          unless specified in CONFIG file.
  -r,--retries retries      Specifies number of retries, default = 5.

"""

from docopt import docopt



# Based off the tutorial by adafruit here:
# http://learn.adafruit.com/adafruits-raspberry-pi-lesson-11-ds18b20-temperature-sensing/software
#
# v2
#
import Adafruit_DHT
import configparser as ConfigParser
import sys
import time
import datetime
from datetime import datetime, timedelta
import pytz
import logging
import dateutil.parser
from time import sleep

opt = {
  "--cache": False,
  "--loop": False,
  "--metric": False,
  "--retries": 3,
  "--sensor": False,
  "--verbose": False,
}


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
thfLockfile = config.get('temp sensor',"THF_LOCKFILE").strip('"')
readInterval = config.getint('temp sensor', "GPIO_READ_INTERVAL")
maxFailsSecs = config.getint('temp sensor', "MAX_FAILS_SECS")
maxRetries = config.getint('temp sensor', "MAX_RETRIES")
logfile = config.get('temp sensor', "LOGFILE").strip('"')
loglevel = logging.WARNING
if config.getboolean('temp sensor', "DEBUG"):
  loglevel = logging.DEBUG

print('Debug is {}'.format(loglevel))

# This is to prevent warning spam while using the debugTempFile
notify_if_file_not_found = True;
notify_if_file_found = True;

# ----------------------------------
# - Set up logging                 -
# ----------------------------------

import logging.config
logging.config.fileConfig('config.logger')

log = logging.getLogger('com.petonic.pithy.getTemp')

print('loglevel == {}, logDEBUG = {}'.format(log.level, logging.DEBUG))


#
# Writes the temp&humid to the EnvCacheFile.  Any error is fatal.
#
def writeCacheFile(temp, humidity):
  log.debug("Writing cache back to disk with [{:f}, {:f}]".
            format(temp, humidity))
  now = datetime.now()
  try:
    with open(envCacheFile, "w") as file:
      print("{:-2.2f}\n{:-2.2f}\n{}".format(temp, humidity, now.ctime()),
            file=file)
  except IOError as e:
    log.fatal("Some error writing back to Env Cache File ({}), e = {}".
              format(envCacheFile, e))
    return []


def getTemp():
  global pin, envCacheFile, dbgTempFile, readInterval, maxFailsSecs,\
        logfile, loglevel, opt, maxRetries
  global notify_if_file_found, notify_if_file_not_found

  # ----------------------------------------------
  # If we are configured to read the temp&humid from a file instead of
  # the GPIO, go ahead and do that and then return those values
  # ----------------------------------------------

  if dbgTempFile:
    def readFloat(infile, filename):
      try:
        tstr = infile.readline().strip()
        rval = float(tstr)
      except Exception as e:
        log.warn('Error reading float from file {}, '
         'tstr=<{}>\nReason: {}, using sensor data'.
         format(filename, tstr, repr(e)))
        raise ValueError
      return(rval)

    import filelock
    thfLock = filelock.FileLock(thfLockfile)

    with thfLock.acquire(timeout=10):
      try:
        with open(dbgTempFile, "r") as infile:
          ttemp = readFloat(infile, dbgTempFile)
          thumid = readFloat(infile, dbgTempFile)
        if notify_if_file_found:
          log.info("*** Found dbtTempFile: {}".
           format(dbgTempFile))
          log.info('*** Using Debug Mode, temp={:-2.2f} '
           'humid={:-2.2f}'.format(ttemp, thumid))

          notify_if_file_found = False
        return [ttemp, thumid]
      except filelock.Timeout as e:
        # This is fatal because getTemp should be able to acquire
        # a lock after 10 seconds under any normal circumstance.
        log.fatal('Cannot acquire TH Debug file ({})'
         ' lock ({}) for 10 secs:'
         ' {}'.format(dbgTempFile, thfLockfile, repr(e)))
        sys.exit(121)
      except Exception as e:
        # Ignore this
        if notify_if_file_not_found:
          log.info('*** Normal mode -- Using sensor, '
           'no dbgTempFile:{} or error: {}'.format(dbgTempFile,
           repr(e)))
          notify_if_file_not_found = False

  # Continue execution and use the Sensor's data
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


  # Loop for retries.  Do the retries, and if we reach the max, then we can
  # use the EnvCache file.
  #
  for i in range(maxRetries):
    # Read values from GPIO sensors
    humidity, temperature = Adafruit_DHT.read(sensor, pin)
    if humidity and temperature:
      break
    log.info('... Local timeout on sensor, retrying {} more times'.format(
        maxRetries - i))
    sleep(2)


  if humidity is not None and temperature is not None:
      # No errors, so let's just return those values after we write it to
      # the env_cache file
      #
      # Defaults to Farenheiht, so convert unless --metric is specified
      if not opt['--metric']:
        tempf = temperature * 9.0 / 5.0 + 32.0
      retval = [ tempf, humidity ]
      writeCacheFile(tempf, humidity)
      return retval
  else:
    #
    # Got an error, so we have to use the cached value.
    #
    if opt['--sensor']: # No cache option
      log.error('Error reading sensor and -s specified')
      return []

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
      sys.exit(44)
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
    log.debug("Error reading GPIO, using valid cache: age = {}".format(
              now - cLastTime))
    retval = [cTemp, cHumid]
    return retval



if __name__ == "__main__":

  opt = docopt(__doc__, options_first=True, version='1.0.0')

  if opt['--verbose']:
    log.loglevel = logging.DEBUG
    log.setLevel(logging.DEBUG)


  if opt['--cache']:
    envCacheFile = opt['--cache']



  # print('*********** Calling MAIN()',file=sys.stderr)

  log.propagate = True        # Make logging appear on STDERR/OUT

  # Wrap an infinite loop around this, and break out if the user
  # didn't specify a repeat.
  while True:
    log.debug("Callng getTemp()")
    returnVal = getTemp()
    # print(returnVal)
    if (len (returnVal) == 2):
      temp = returnVal[0]
      humid = returnVal[1]
      print ("Temperature is %f %s" % (temp, 'degC'
           if opt['--metric'] else 'degF'))
      print ("Humidity is %f" % humid)
    else:
      log.fatal("Error from getTemp()!")
      sys.exit(43)
    if not opt['--loop']:
      sys.exit(0)
    sleep(2)
