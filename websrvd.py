#!/usr/bin/env python3
#
#
import os
import subprocess
import sys
import re
import configparser as ConfigParser
import wiringpi
import datetime
from datetime import datetime, timedelta
from tzlocal import get_localzone
from getTemp import getTemp
from flask import Flask, request, session, g, redirect, url_for, \
     abort, render_template, flash, jsonify




# Global debug variable declaration so that functions can see it.
debug=False
lastFlash = datetime(1970, 1, 1, 0, 0)
flashCleared = True

app = Flask(__name__)
#hard to be secret in open source... >.>
app.secret_key = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'

abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)

from configparser import SafeConfigParser
config = SafeConfigParser(os.environ)

config.read("config.txt")

ZIP = config.get('weather','ZIP')
HEATER_PIN = int(config.get('main','HEATER_PIN'))
FAN_PIN = int(config.get('main','FAN_PIN'))
STATUS_FILE = config.get('thermod', "STATUSFILE").strip('"')
PID_FILE = config.get('thermod', "PIDFILE").strip('"')
FLASH_DUR = int(config.get('websrvd', 'FLASH_DUR'))
weatherEnabled = config.getboolean('weather','enabled')


# ----------------------------------
# - Set up logging                 -
# ----------------------------------

import logging.config
logging.config.fileConfig('config.logger')

log = logging.getLogger('com.petonic.pithy.websrvd')

print('loglevel == {}, logDEBUG = {}'.format(log.level, logging.DEBUG))


if weatherEnabled == True:
    import pywapi
    def getWeather():
        result = pywapi.get_weather_from_yahoo( str(ZIP), units = 'imperial' )
        string = result['html_description']
        string = string.replace("\n", "")

        #You will likely have to change these strings, unless you don't mind the additional garbage at the end.
        string = string.replace("(provided by <a href=\"http://www.weather.com\" >The Weather Channel</a>)<br/>", "")
        string = string.replace("<br /><a href=\"http://us.rd.yahoo.com/dailynews/rss/weather/Nashville__TN/*http://weather.yahoo.com/forecast/USTN0357_f.html\">Full Forecast at Yahoo! Weather</a><BR/><BR/>", "")
        return string



def dprint(str):
    if (debug):
        log.debug(str)

def lnow():
  utc_time = datetime.now()
  tzone = get_localzone()
  ltime = tzone.localize(utc_time)

  rts = utc_time.strftime("%Y-%m-%d %H:%M:%S")
  return rts


def gpioInitSetup():
  wiringpi.wiringPiSetupSys()
  subprocess.call(["gpio", "export", str(HEATER_PIN), "high" ])
  subprocess.call(["gpio", "export", str(FAN_PIN), "high" ])
  #
  # By default, we turn off the heater and the FAN when
  # we first startup.  No harm done because THERMOD will
  # put them back on if that's the state that's config'd
  # in STATUS_FILE
  #
  wiringpi.pinMode(HEATER_PIN, 1)       # Output mode
  wiringpi.digitalWrite(HEATER_PIN, 1)  # Pins are activeHI, so turn off.
  wiringpi.pinMode(FAN_PIN, 1)      # Output mode
  wiringpi.digitalWrite(FAN_PIN, 1)  # Pins are activeHI, so turn off.

def gpioRead(pinNum):
    """int gpioRead(int pinNum)
    Reads the specified GPIO pin using the

    /sys/class/gpio/gpioN/value filesystem scheme."""
    devFile = '/sys/class/gpio/gpio{}/value'.format(pinNum)
    try:
      with open(devFile, "r") as infile:
        retVal = int(infile.readline())
    except Exception as e:
        log.fatal('Cannot read the file ({}).  Is thermod '
            'running?  Major error: {}'.format(
            devFile, repr(e)))
        sys.exit(200)
    return retVal

def tempFlash(msg):
    """ void tempFlash(str)

    Prints a flash message on the web page for default duration (see config).
    """

    global flashCleared, lastFlash

    lastFlash = datetime.now()
    log.debug('*** Setting tempFlash to {}: {}'.format(
      lastFlash.strftime("%Y-%m-%d %H:%M:%S"), msg))

    flashCleared = False
    flash(msg)


def getWhatsOn():
    global flashCleared, lastFlash
    #
    # Use /sys/class/gpio/gpio{HEATER,FAN}/value to read the
    # status because wiringPI always returns 0 for some reason, or
    # worse, you have to be root to access them.  That's bad for
    # a web server.... :-(
    # This is not time critical.  That much.
    #
    # Must flip them because the relays are active LOW, and inactive HIGH
    #
    heatStatus = 1 - gpioRead(HEATER_PIN)
    fanStatus = 1 - gpioRead(FAN_PIN)

    # log.debug('WhatsOn: Heat = {}, Fan = {}'.format(heatStatus, fanStatus))

    #
    # Reset the flash() message if it's been up long enough.
    #
    now = datetime.now()
    # log.debug('Now is set to {}'.format(now))
    flashElapsed = now - lastFlash
    # log.none('flashElapsed is set to {}'.format(flashElapsed))
    # log.debug('flashCleared is set to {}'.format(flashCleared))
    # log.debug('FLASH_DUR is set to {}'.format(FLASH_DUR))

    if ((not flashCleared) and
      (flashElapsed > timedelta(seconds=FLASH_DUR))):
        log.debug('**** Cleared the flash message')
        flashCleared = True
        flash(" ")


    headerStr = "<table>"

    heatString = "<tr><td>Heat:</td><td>{}</td></tr>".format("<font color='red'>ON" if heatStatus == 1 else "<font color='black'>Off")
    fanString = "<tr><td>Fan:</td><td>{}</td></tr>".format("<font color='blue'>ON" if fanStatus == 1 else "<font color='black'>Off")
    return '<table>' + heatString + fanString + '</table>'


def getDaemonStatus():
    try:
        with open(PID_FILE) as infile:
            pid = int(infile.readline().rstrip('\n'))
            try:
                os.kill(pid, 0)
                return "<p id=\"daemonRunning\">Daemon is running</p>"
            except OSError:
                return "<p id=\"daemonNotRunning\" class=\"blink_me\">DAEMON IS NOT RUNNING</p>"
    except IOError:
        return "<p id=\"daemonNotRunning\"> (no pidfile) DAEMON IS NOT RUNNING. </p>"

@app.route('/')
def my_form():
    try:
      with open(STATUS_FILE, "r") as file:
          targetTemp = float(file.readline().strip())
          mode = file.readline().rstrip('\n')
    except IOError:
        log.fatal("Error getting status from {}. Is thermod running?".
            format(STATUS_FILE))
        sys.exit(121)
    log.debug("MY_FORM: target temp is {}, mode is <{}>".
              format(targetTemp, mode))

    weatherString = ""
    if weatherEnabled == True:
        try:
            weatherString = getWeather()
        except:
            weatherString = "Couldn't get remote weather info! <br><br>"

    whatsOn = getWhatsOn()

    #find out what mode the system is in, and set the switch accordingly
    #the switch is in the "cool" position when the checkbox is checked

    daemonStatus=getDaemonStatus()

    if mode == "heat":
      checked = "checked=\"checked\""
    elif mode == "off":
      checked = ""
    else:
        checked = "Something broke"

    log.debug("*** Right before Rendering template, checked = <{}>".
           format(checked))

    log.debug('Rendering template')
    rv =render_template("form.html", targetTemp = int(targetTemp), \
                                        weatherString = weatherString, \
                                        checked = checked, \
                                        daemonStatus = daemonStatus, \
                                        whatsOn = whatsOn)

    return rv


@app.route("/", methods=['POST'])
def my_form_post():
    global lastFlash, flashCleared

    text = request.form['target']
    mode = "off"
    dprint( "****************** Top of form_post")

    try:
        with open(STATUS_FILE,"r") as f:
            targetTemp = float(f.readline().strip())
            # targetTemp = int("12")
            mode = f.readline().rstrip('\n')
    except Exception as e:
        log.fatal('my_form_post: Cannot read status file ({}): {}'.format(
            STATUS_FILE, repr(e)))




    # Eliminated the toggle of status -- done dynamically
    #
    # #default mode to off
    # #heat if the checkbox is returned, it is checked
    # #and cool mode has been selected
    # #
    # #This is a toggle.  When the post is made, if the switch is off, then
    # #turn it to heat. If it's on HEAT, then turn it off.
    #
    # if 'onoffswitch' in request.form:
    #     mode = "off"
    # else:
    #     mode = "heat"
    #
    # dprint("Current OnOffSwitch = {}".format(request.form['onoffswitch']))

    newTargetTemp = text.upper()
    match = re.search(r'^\d{2}$',newTargetTemp)
    if match:
        f = open(STATUS_FILE, "w")
        f.write(newTargetTemp + "\n" + mode)
        f.close()
        tempFlash('New temperature of {} set!'.format(newTargetTemp))
        return redirect(url_for('my_form'))
    else:
        tempFlash("That is not a two digit number! Try again!")
        return redirect(url_for('my_form'))


#the flask views for the incredible and probably
#not at all standards compliant live data

@app.route("/toggleMe", methods=['POST'])
def toggleSwitch():
  passedval = request.get_data()

  # import json
  log.info("{}: Got to toggle of switch, value = {}".format(lnow(), passedval))

  return("OK");


@app.route('/_liveTemp', methods= ['GET'])
def updateTemp():
    rv = getTemp();
    if len(rv) != 2:
      # Must've had an error, log it and use the last known value
      log.warning("websrvd:{}: error reading tempHumid value".format(
          lnow()))
      temp = updateTemp.lastTemp
      humidity = updateTemp.lastHumid
    else:
      temp=rv[0];
    rv = (str(round(temp,1)))
    return (rv)

# Static variables for updateTemp()
updateTemp.lastTemp = 0
updateTemp.lastHumid = 0

@app.route('/_liveWhatsOn', methods= ['GET'])
def updateWhatsOn():
    return getWhatsOn()

@app.route('/_toggleChanged_<switchVal>', methods= ['GET'])
def toggleChanged(switchVal):

  #
  # Rewrite the STATUS file so that the toggle change is reflected.
  # Must read the file, and then re-write the file.
  #

  with open(STATUS_FILE,"r") as f:
    targetTemp = f.readline().strip()
    targetTemp = int(targetTemp)
    # targetTemp = int("12")

  # Javascript boolean is lower-case True and False
  mode = "heat" if switchVal == "true" else "off"

  dprint ("toggleChanged:  target temp is {:d}, mode is <{:s}>".
          format(targetTemp, mode))

  with open(STATUS_FILE, "w") as f:
    f.write(str(targetTemp) + "\n" + mode)


  return ""


@app.route('/_liveDaemonStatus', methods= ['GET'])
def updateDaemonStatus():

    return getDaemonStatus()


if __name__ == "__main__":
    print('Starting the web server')
    log.info("***\n*** Restarting websrvd at {}, debug is {},"
        "Level set to {}\n***".
            format(lnow(), logging.DEBUG, log.level))




    # app.config['DEBUG'] = True
    # DEBUG=True
    app.run("0.0.0.0", port=7000, debug=True)
