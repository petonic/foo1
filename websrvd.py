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
     abort, render_template, flash, jsonify, make_response

PROJ_DIR='/home/pi/pithy'
PYTHON2_PATH='/usr/bin/python2'
PROXY_PROCESS=[ PYTHON2_PATH, 'proxy_solo.py2' ]



# Global debug variable declaration so that functions can see it.
debug=True
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

print(('loglevel == {}, logDEBUG = {}'.format(log.level, logging.DEBUG)))


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

@app.route('/indigo', methods=['GET'])
def go_to_indigo():
  redirURL='/p/macreyes.local:8176/controlpage?name=CR&useJS=True'
  return redirect(redirURL)


  # d8888b. d8888b.  .d88b.  db    db db    db
  # 88  `8D 88  `8D .8P  Y8. `8b  d8' `8b  d8'
  # 88oodD' 88oobY' 88    88  `8bd8'   `8bd8'
  # 88~~~   88`8b   88    88  .dPYb.     88
  # 88      88 `88. `8b  d8' .8P  Y8.    88
  # 88      88   YD  `Y88P'  YP    YP    YP

  # .d8888. d88888b d8888b. db    db d88888b d8888b.
  # 88'  YP 88'     88  `8D 88    88 88'     88  `8D
  # `8bo.   88ooooo 88oobY' Y8    8P 88ooooo 88oobY'
  #   `Y8b. 88~~~~~ 88`8b   `8b  d8' 88~~~~~ 88`8b
  # db   8D 88.     88 `88.  `8bd8'  88.     88 `88.
  # `8888Y' Y88888P 88   YD    YP    Y88888P 88   YD

import http.client
import re
import urllib.request, urllib.parse, urllib.error
import urllib.parse
import json

from flask import Flask, Blueprint, request, Response, url_for
from werkzeug.datastructures import Headers
from werkzeug.exceptions import NotFound


proxy = app

# You can insert Authentication here.
#proxy.before_request(check_login)

# Filters.
HTML_REGEX = re.compile(r'((?:src|action|href)=["\'])/')
JQUERY_REGEX = re.compile(r'(\$\.(?:get|post)\(["\'])/')
JS_LOCATION_REGEX = re.compile(r'((?:window|document)\.location.*=.*["\'])/')
CSS_REGEX = re.compile(r'(url\(["\']?)/')

REGEXES = [HTML_REGEX, JQUERY_REGEX, JS_LOCATION_REGEX, CSS_REGEX]


def iterform(multidict):
    for key in list(multidict.keys()):
        for value in multidict.getlist(key):
            yield (key.encode("utf8"), value.encode("utf8"))

def parse_host_port(h):
    """Parses strings in the form host[:port]"""
    host_port = h.split(":", 1)
    if len(host_port) == 1:
        return (h, 80)
    else:
        host_port[1] = int(host_port[1])
        return host_port


# For RESTful Service
@proxy.route('/proxy/<host>/', methods=["GET", "POST", "PUT", "DELETE"])
@proxy.route('/proxy/<host>/<path:file>', methods=["GET", "POST", "PUT", "DELETE"])
def proxy_request(host, file=""):
    hostname, port = parse_host_port(host)
    import sys

    log.debug('Hostname : Port is {} : {}'.format(hostname, port))

    log.debug("H: '{}' P: '{}'".format(hostname, port))
    log.debug("F: '{}'".format(file))
    # Whitelist a few headers to pass on
    request_headers = {}
    for h in ["Cookie", "Referer", "X-Csrf-Token"]:
        if h in request.headers:
            request_headers[h] = request.headers[h]

    if request.query_string:
        path = "/%s?%s" % (file, request.query_string)
    else:
        path = "/" + file

    if request.method == "POST" or request.method == "PUT":
        form_data = list(iterform(request.form))
        form_data = urllib.parse.urlencode(form_data)
        request_headers["Content-Length"] = len(form_data)
    else:
        form_data = None

    conn = http.client.HTTPConnection(hostname, port)
    conn.request(request.method, path, body=form_data, headers=request_headers)
    resp = conn.getresponse()

    # Clean up response headers for forwarding
    d = {}
    response_headers = Headers()
    for key, value in resp.getheaders():
        log.debug("HEADER: '{}':'{}'".format(key, value))
        d[key.lower()] = value
        if key in ["content-length", "connection", "content-type"]:
            continue

        if key == "set-cookie":
            cookies = value.split(",")
            [response_headers.add(key, c) for c in cookies]
        else:
            response_headers.add(key, value)

    # If this is a redirect, munge the Location URL
    if "location" in response_headers:
        redirect = response_headers["location"]
        parsed = urllib.parse.urlparse(request.url)
        redirect_parsed = urllib.parse.urlparse(redirect)

        redirect_host = redirect_parsed.netloc
        if not redirect_host:
            redirect_host = "%s:%d" % (hostname, port)

        redirect_path = redirect_parsed.path
        if redirect_parsed.query:
            redirect_path += "?" + redirect_parsed.query

        munged_path = url_for(".proxy_request",
                              host=redirect_host,
                              file=redirect_path[1:])

        url = "%s://%s%s" % (parsed.scheme, parsed.netloc, munged_path)
        response_headers["location"] = url

    # Rewrite URLs in the content to point to our URL schemt.method == " instead.
    # Ugly, but seems to mostly work.
    root = url_for(".proxy_request", host=host)
    contents = resp.read().decode('utf-8')

    # Restructing Contents.
    if d["content-type"].find("application/json") >= 0:
        # JSON format conentens will be modified here.
        jc = json.loads(contents)
        if "nodes" in jc:
            del jc["nodes"]
        contents = json.dumps(jc)

    else:
        # Generic HTTP.
        for regex in REGEXES:
           contents = regex.sub(r'\1%s' % root, contents)
        #    "DBG:********"; from pdb import set_trace as bp; bp()

    flask_response = Response(response=contents,
                              status=resp.status,
                              headers=response_headers,
                              content_type=resp.getheader('content-type'))
    return flask_response


    # d88888b d8b   db d8888b.
    # 88'     888o  88 88  `8D
    # 88ooooo 88V8o 88 88   88
    # 88~~~~~ 88 V8o88 88   88
    # 88.     88  V888 88  .8D
    # Y88888P VP   V8P Y8888D'

    # d8888b. d8888b.  .d88b.  db    db db    db
    # 88  `8D 88  `8D .8P  Y8. `8b  d8' `8b  d8'
    # 88oodD' 88oobY' 88    88  `8bd8'   `8bd8'
    # 88~~~   88`8b   88    88  .dPYb.     88
    # 88      88 `88. `8b  d8' .8P  Y8.    88
    # 88      88   YD  `Y88P'  YP    YP    YP






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

    # Our proxy that we spawn will die when we get killed.
    # As per:
    #  https://pymotw.com/3/subprocess/#process-groups-sessions
    os.setpgrp()
    # Start the proxy server
    proxy_pid = subprocess.Popen(PROXY_PROCESS, stderr=subprocess.STDOUT).pid
    log.debug('Started proxy server -- PID = {}'.format(proxy_pid))
    # p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, shell=True)


    # app.config['DEBUG'] = True
    # DEBUG=True
    app.run("0.0.0.0", port=7000, debug=True)
