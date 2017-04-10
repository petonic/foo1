#!/usr/bin/env python3
#
#
import os
import subprocess
import re
import configparser as ConfigParser
import wiringpi
import datetime
from datetime import datetime, timedelta
from tzlocal import get_localzone
from getTemp import getTemp
from flask import Flask, request, session, g, redirect, url_for, \
     abort, render_template, flash, jsonify



# import remote_pdb
# def bp():
#   remote_pdb.set_trace('0.0.0.0',4444)
from pdb import set_trace as bp

# Global DEBUG variable declaration so that functions can see it.
debug=False

app = Flask(__name__)
#hard to be secret in open source... >.>
app.secret_key = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'

abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)

config = ConfigParser.ConfigParser()
config.read("config.txt")
ZIP = config.get('weather','ZIP')
HEATER_PIN = int(config.get('main','HEATER_PIN'))
FAN_PIN = int(config.get('main','FAN_PIN'))
weatherEnabled = config.getboolean('weather','enabled')

#
# Set up logging for WEBSRVd
#
import logging
log = logging.getLogger()
# Make it skip printing to stderr
log.propagate = False
websvrd_DEBUG = config.getboolean('websrvd', 'DEBUG')

DEBUG=websvrd_DEBUG
# create file handler which logs even debug messages
fh = logging.FileHandler('log.websrvd.dbg')
fh.setLevel(logging.DEBUG)
log.addHandler(fh)
# create file handler which logs Info and real errors
fh = logging.FileHandler('log.websrvd')
fh.setLevel(logging.INFO)
log.addHandler(fh)


if (websvrd_DEBUG):
  log.setLevel("DEBUG")
else:
  log.setLevel("INFO")

log.debug("websvrd_DEBUG=<{}>, debug=<{}>".format(websvrd_DEBUG, debug))

#start the daemon in the background, ignore errors
# subprocess.Popen("/usr/bin/python daemon.py start", shell=True)

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
  # in "status"
  #
  wiringpi.pinMode(HEATER_PIN, 1)       # Output mode
  wiringpi.digitalWrite(HEATER_PIN, 1)  # Pins are activeHI, so turn off.
  wiringpi.pinMode(FAN_PIN, 1)      # Output mode
  wiringpi.digitalWrite(FAN_PIN, 1)  # Pins are activeHI, so turn off.


def getWhatsOn():
    # Must flip them because the relays are active LOW, and inactive HIGH
    #
    heatStatus = 1 - wiringpi.digitalRead(HEATER_PIN)
    fanStatus = 1 - wiringpi.digitalRead(FAN_PIN)

    dprint ( '======== getWhatsOnL Heat Status ({}) is {}, and fanStatus({}) is {}'.format(HEATER_PIN, heatStatus, FAN_PIN, fanStatus))

    headerStr = "<table>"

    heatString = "<tr><td>Heat:</td><td>{}</td></tr>".format("<font color='red'>ON" if heatStatus == 1 else "<font color='blue'>Off")
    fanString = "<tr><td>Fan:</td><td>{}</td></tr>".format("<font color='blue'>ON" if fanStatus == 1 else "<font color='black'>Off")
    return '<table>' + heatString + fanString + '</table>'


def getDaemonStatus():
    # print "rwi: getDaemonStatus() called"
    try:
        with open('.thermod.pid') as infile:
            pid = int(infile.readline().rstrip('\n'))
            try:
                os.kill(pid, 0)
                return "<p id=\"daemonRunning\"> Daemon is running. </p>"
            except OSError:
                return "<p id=\"daemonNotRunning\"> DAEMON IS NOT RUNNING. </p>"
    except IOError:
        return "<p id=\"daemonNotRunning\"> (no pidfile) DAEMON IS NOT RUNNING. </p>"

@app.route('/')
def my_form():
    f = open("status", "r")
    targetTemp = f.readline().strip()
    targetTemp = int(targetTemp)
    mode = f.readline().rstrip('\n')
    f.close()
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

    rv =render_template("form.html", targetTemp = targetTemp, \
                                        weatherString = weatherString, \
                                        checked = checked, \
                                        daemonStatus = daemonStatus, \
                                        whatsOn = whatsOn)

    return rv


@app.route("/", methods=['POST'])
def my_form_post():

    text = request.form['target']
    mode = "off"
    dprint( "****************** Top of form_post")

    with open("status","r") as f:
      targetTemp = f.readline().strip()
      targetTemp = int(targetTemp)
      # targetTemp = int("12")
      mode = f.readline().rstrip('\n')



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
        f = open("status", "w")
        f.write(newTargetTemp + "\n" + mode)
        f.close()
        flash("New temperature of " + newTargetTemp + " set!")
        return redirect(url_for('my_form'))
    else:
        flash("That is not a two digit number! Try again!")
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
    # print 'app.debug is {}'.format(app.debug)
    return getWhatsOn()

@app.route('/_toggleChanged_<switchVal>', methods= ['GET'])
def toggleChanged(switchVal):

  #
  # Rewrite the STATUS file so that the toggle change is reflected.
  # Must read the file, and then re-write the file.
  #

  with open("status","r") as f:
    targetTemp = f.readline().strip()
    targetTemp = int(targetTemp)
    # targetTemp = int("12")

  # Javascript boolean is lower-case True and False
  mode = "heat" if switchVal == "true" else "off"

  dprint ("toggleChanged:  target temp is {:d}, mode is <{:s}>".
          format(targetTemp, mode))

  with open("status", "w") as f:
    f.write(str(targetTemp) + "\n" + mode)


  return ""


@app.route('/_liveDaemonStatus', methods= ['GET'])
def updateDaemonStatus():

    return getDaemonStatus()


if __name__ == "__main__":
    log.info("***\n*** Restarting websrvd at {}, debug is {}\n***".
            format(lnow(), websvrd_DEBUG))




    # app.config['DEBUG'] = True
    # DEBUG=True
    app.run("0.0.0.0", port=7000, debug=False)
