#! /usr/bin/env python3
"""thermod.py

Usage:
  thermod [releaseGPIO]
  thermod
  thermod (-h | --help)

  Options:
    -h --help     Show this screen.
"""
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
import calendar
from datetime import datetime, timedelta
import pytz
from tzlocal import get_localzone
import logging

import wiringpi

# ----------------------------------
# - Read config                    -
# ----------------------------------
from configparser import SafeConfigParser
config = SafeConfigParser(os.environ)

config.read("config.txt")

print('XYZZY: THERMOD: STARTING NOW!!!!  CWD = {}: {}'.format(
        os.getcwd(),datetime.now().isoformat()), file=sys.stderr)


active_hysteresis = float(config.get('main', 'active_hysteresis'))
inactive_hysteresis = float(config.get('main', 'inactive_hysteresis'))

fan_idle_time = int(config.get('main', 'FAN_IDLE_TIME'))
compressor_save_time = int(config.get('main', 'COMPRESSOR_SAVE_TIME'))

HEATER_PIN = int(config.get('main', 'HEATER_PIN'))
AC_PIN = int(config.get('main', 'AC_PIN'))
FAN_PIN = int(config.get('main', 'FAN_PIN'))

TH_FILE = config.get('temp sensor', "TEMP_HUM_FILE").strip('"')
PID_FILE = config.get('thermod', 'PIDFILE').strip('"')
LOG_FILE = config.get('thermod', "LOGFILE").strip('"')
STATUS_FILE = config.get('thermod', "STATUSFILE").strip('"')
TEMPHUMID_DB = config.get('thermod', "TEMPHUMID_DB").strip('"')

# ----------------------------------
# - Set up logging                 -
# ----------------------------------

import logging.config
logging.config.fileConfig('config.logger')

log = logging.getLogger('com.petonic.pithy.thermod')

print('loglevel == {}, logDEBUG = {}'.format(log.level, logging.DEBUG))

# ----------------------------------
# - Fix up timezone stuff          -
# ----------------------------------

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
    return (ts.format(str))


def pgpio(pins, state):
    log.debug('-----GPIO-OUTPUT({},{})'.format(pins, state))
    # Convert to list if it's a single pin number
    if not (isinstance(pins, list)):
        pins = [pins]
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

#
# mail config
#

mailEnabled = config.getboolean('mail', 'enabled')
if mailEnabled == True:
    import smtplib
    # Holds last time
    mailBackoffTimes = [ 1, 2, 4, 8, 60, 2*60, 6*60, 12*60 ]  # in mins
    mailBackoffCount = 0        # Our index into the Backoff times array
    mailLastSentTime = 0.0      # Holds last time
    mailLastSubject = ""        # Last subject line sent
    mailNumRepeats = 0

config.read("mailconf.txt")
SMTP_SERVER = config.get('mailconf', 'SMTP_SERVER')
SMTP_PORT = int(config.get('mailconf', 'SMTP_PORT'))
username = config.get('mailconf', 'username')
password = config.get('mailconf', 'password')
sender = config.get('mailconf', 'sender')
recipient = config.get('mailconf', 'recipient')
subject = config.get('mailconf', 'subject')
email_body_prefix = config.get('mailconf', 'email_body_prefix')
error_threshold = float(config.get('mail', 'error_threshold'))

#
# Globals for Thermod
#
lastTemp = 0.0
lastHumid = 0.0


def configureGPIO():
    wiringpi.wiringPiSetupSys()
    # gpio export 4 high
    # gpio export 17 high
    subprocess.call(["gpio", "export", str(HEATER_PIN), "high"])
    subprocess.call(["gpio", "export", str(FAN_PIN), "high"])

    wiringpi.pinMode(HEATER_PIN, 1)  # Output mode
    wiringpi.digitalWrite(HEATER_PIN, 1)  # Pins are activeHI, so turn off.
    wiringpi.pinMode(FAN_PIN, 1)  # Output mode
    wiringpi.digitalWrite(FAN_PIN, 1)  # Pins are activeHI, so turn off.


def getHVACState():
    """This function returns the state of the HVAC pins: idle, fan, heat."""
    # Must flip them because the relays are active LOW, and inactive HIGH
    heat_status = 1 - wiringpi.digitalRead(HEATER_PIN)
    fan_status = 1 - wiringpi.digitalRead(FAN_PIN)

    if fan_status == 1:
        if heat_status == 1:
            return 'heat'
        else:
            return 'fan'
    else:
        if heat_status == 1:
            err_str = 'DANGER: Invalid HVAC State, heat_status = {}, fan_status = {}'.format(
                heat_status, fan_status)
            log_error(err_str)
            sendErrorMail(err_str, fatalError=True)
        else:
            return 'off'      # Both FAN and HEAT are off
    return 'invalid'

########################
#
# These functions use GPIO functions, and both pins are active == LOW.
# Switching these pins to a HIGH state will turn off the associated realy.
########################
def hvac_heat():
    pgpio(HEATER_PIN, wiringpi.LOW)
    pgpio(FAN_PIN, wiringpi.LOW)
    return 'heat'

def hvac_fan():
    pgpio(HEATER_PIN, wiringpi.HIGH)
    pgpio(FAN_PIN, wiringpi.LOW)
    return 'fan'

def hvac_idle_fan():
    # to blow the rest of the heated / cooled air out of the system
    pgpio(HEATER_PIN, wiringpi.HIGH)
    pgpio(FAN_PIN, wiringpi.LOW)
    log.debug(".....\tfan_to_idle: going to sleep for {} seconds".format(
        fan_idle_time))
    time.sleep(fan_idle_time)

def hvac_all_off():
    pgpio(HEATER_PIN, wiringpi.HIGH)
    pgpio(FAN_PIN, wiringpi.HIGH)
    # delay to preserve compressor
    log.debug(".....\tidle: Going to sleep for {} seconds".format(
        compressor_save_time))
    time.sleep(compressor_save_time)
    return 'off'

########################
#
# Mail and other error logging.
#
########################


if mailEnabled == True:
    def sendErrorMail(mystr, fatalError=False):
        global mailBackoffCount, mailBackoffCount, mailLastSentTime
        global mailLastSubject, mailNumRepeats

        nbody = email_body_prefix
        log.info('Repeating last message, Rep Cnt = {}, BOCnt = {}'.format(
            mailNumRepeats, mailBackoffCount))
                # Check to see if we're repeating the message too quickly.
        if mystr == mailLastSubject:
            currTime = time.time()
            if (currTime - mailLastSentTime) < (60 * 60):
                mailNumRepeats += 1
                log.info('... sendErrorMail(skipping)')
                # Enough time has not passed, don't send it.
                return
        else:
            # Different subject line, so reset things
            mailLastSubject = mystr
            if mailNumRepeats:
                # Give the user an indication of the numbrer of repts.
                mystr = "(Prev rptd * {} times) ".format(mailBackoffCount)
            mailLastSentTime = time.time()
            mailNumRepeats = 0

        headers = [
            "From: " + sender, "Subject: " + subject + ": " + mystr,
            "To: " + recipient, "MIME-Version: 1.0", "Content-Type: text/plain"
        ]
        headers = "\r\n".join(headers)
        try:
            heat_status = 1 - wiringpi.digitalRead(HEATER_PIN)
            fan_status = 1 - wiringpi.digitalRead(FAN_PIN)
            nbody = nbody + "\r\nPithy shut down!!!\r\n" if fatalError else "" + \
              "\r\n\r\nThermod V1 Status at  " + lnow() + ":\r\n"
            try:
                temp_status = subprocess.check_output(
                    ['/bin/cat', STATUS_FILE])
                # Prepend a tab to each line
                nbody = nbody + "\tContents of Status File = {}\r\n".format(
                    repr(temp_status))
            except Exception as e:
                nbody = nbody + '\tCannot get Status File ({}): {}\r\n'.format(
                    STATUS_FILE, repr(e))
            hvac_state = getHVACState()
            tempHumid = getTemp()
            nbody = nbody + "\thvacState = " + str(hvac_state) + "\r\n"
            nbody = nbody + "\temp+humid = " + repr(tempHumid) + "\r\n"
            nbody = nbody + "\theatStatus = " + str(heat_status) + "\r\n"
            nbody = nbody + "\tfanStatus = " + str(fan_status) + "\r\n"
            if fatalError:
                nbody = nbody + "\r\nPithy received fatal error, exiting program\r\n"
            session = smtplib.SMTP_SSL("{}:{}".format(SMTP_SERVER, SMTP_PORT))
            session.login(username, password)
            session.sendmail(sender, recipient, headers + "\r\n\r\n" + nbody)
            session.quit()
        except Exception as e:
            log.error("Error trying to send email warning:{}".format(repr(e)))

    def log_error(*args):
        log.error(args)
        sendErrorMail('Error from Pithy. Thermod: %s' % args)

    def log_fatal(*args):
        log.fatal(args)
        sendErrorMail(
            'Fatal error from Pithy! Thermod: %s' % args, fatalError=True)
        sys.exit(9)
else:
    # mailEnable is not true, so stub out those other functions
    def log_error(*args):
        log.error(args)

    def log_fatal(*args):
        log.fatal(args)


def run():
    # Line below makes us log immediately upon running the first time.
    lastLog = datetime.now() - timedelta(minutes=6)
    lastMail = datetime.now()
    configureGPIO()

    # Write our PID to PID_FILE
    try:
      with open(PID_FILE, "w") as outfile:
        print('{}'.format(os.getpid()), file=outfile)
    except IOError:
        pass

    # change cwd to wherever websrvrd is
    abspath = os.path.abspath(__file__)
    dname = os.path.dirname(abspath)
    os.chdir(dname)


    # d888888b d8b   db d88888b d888888b d8b   db d888888b d888888b d88888b
    #   `88'   888o  88 88'       `88'   888o  88   `88'   `~~88~~' 88'
    #    88    88V8o 88 88ooo      88    88V8o 88    88       88    88ooooo
    #    88    88 V8o88 88~~~      88    88 V8o88    88       88    88~~~~~
    #   .88.   88  V888 88        .88.   88  V888   .88.      88    88.
    # Y888888P VP   V8P YP      Y888888P VP   V8P Y888888P    YP    Y88888P
    #
    # db       .d88b.   .d88b.  d8888b.
    # 88      .8P  Y8. .8P  Y8. 88  `8D
    # 88      88    88 88    88 88oodD'
    # 88      88    88 88    88 88~~~
    # 88booo. `8b  d8' `8b  d8' 88
    # Y88888P  `Y88P'   `Y88P'  88

    switch_mode = 'off'

    while True:
        tempHumid = getTemp()
        if len(tempHumid) < 2:
            log.warning(
                "thermod:{}: error reading tempHumid value".format(lnow()))
            indoor_temp = lastTemp
            humidity = lastHumid
        else:
            indoor_temp = float(tempHumid[0])
            humidity = float(tempHumid[1])

        hvac_state = getHVACState()

        # Save this value in case we have to change state of the
        # GPIO
        old_switch_mode = switch_mode

        try:
            file = open(STATUS_FILE, "r")
            target_temp = float(file.readline().rstrip('\n'))
            switch_mode = file.readline().rstrip('\n')
            file.close()
        except Exception as e:
            defStatus = 'off'
            # Set default operation modes if the statusfile isn't found.
            target_temp = 70.0
            switch_mode = defStatus
            log.info('no_alarm: Can\'t read STATUS_FILE {}, so writing'
             ' ( {} / {} )to it\nReason: {}'.
             format(STATUS_FILE, target_temp, defStatus, repr(e)))
            # Rewrite the STATUS_FILE so that we aren't in this error
            # state and we don't keep on spewing messages.
            try:
              with open(STATUS_FILE, "w") as ofile:
                print('{:f}\n{}\n'.format(target_temp, switch_mode),file=ofile)
            except IOError:
                log.fatal('Cannot re-write missing STATUS_FILE {}'.format(
                 STATUS_FILE))
                sys.exit(144)

        # Log values so far

        now = datetime.now()
        logElapsed = now - lastLog
        mailElapsed = now - lastMail

        # heat_mode -- check if beyond tolerance
        # it's 72, we want it to be 78, and the error threshold is 5 = this
        # triggers
        if mailEnabled == True and (mailElapsed > timedelta(minutes=20)) and \
            (float(target_temp) - indoor_temp) > error_threshold:
            sendErrorMail('Heat beyond threshold ({} - {} = {} > {}'.format(
                target_temp, indoor_temp,
                float(target_temp) - indoor_temp, error_threshold))
            lastMail = datetime.now()
            log.info("MAIL: Sent mail to " + recipient + \
                     " at " + now.strftime('%F %T'))

        # logging actual temp and indoor temp to sqlite database.
        # you can do fun things with this data, like make charts!
        if logElapsed > timedelta(minutes=6) and sqliteEnabled:
            sqlCursor.execute('INSERT INTO logging VALUES(?, ?, ?, ?, ?, ?)',
                      (now, trimFloat(indoor_temp), target_temp,
                       trimFloat(humidity), switch_mode, hvac_state))
            conn.commit()
            lastLog = datetime.now()

        # $hvac_state has the following values:
        #   'idle', 'fan', 'heat'
        # $switch_mode has the following:
        #   'off', 'fan', 'heat'
        if switch_mode == 'heat':
            if hvac_state != 'heat':  # Fan  or Idle
                if indoor_temp < target_temp - inactive_hysteresis:
                    log.info('STATE: Switching to heat at {}, '
                             'hvac_state = {}'.format(lnow(), hvac_state))
                    hvac_state = hvac_heat()
            # If we've reached temp to get to, shut the heat and fan down.
            elif hvac_state == 1:  # heating
                if indoor_temp > target_temp + active_hysteresis:
                    log.info('STATE: Switching to fan idle at {}, '
                             'hvac_state = {}'.format(lnow(), hvac_state))
                    hvac_idle_fan()
                    log.info('STATE: Switching to ALL_OFF at {}, '
                             'hvac_state = {}'.format(lnow(), hvac_state))
                    hvac_state = hvac_all_off()
        elif switch_mode == 'fan':
            hvac_state = hvac_fan()
        else:
            #
            # The switch_mode is "off", so we have to check if the hvac_state is actually
            # off as well.  If not, then we have to turn it off.
            #
            if not (switch_mode == "off"):
                log_fatal("Invalid switch_mode <{}>".format(switch_mode))
                assert (switch_mode == "off")

            log.debug('Turning system off, previous hvac_state = {}'.format(
                        hvac_state))

            if hvac_state == 'heat':  # Heating is on, turn it off
                log.info("STATE: switch is off, turning off heat and fan")
                log.info('STATE: Switching to fan idle at {}, '
                       'hvac_state = {}'.format(lnow(), hvac_state))
                hvac_idle_fan()
                log.info('STATE: Switching to ALL_OFF at {}, '
                       'hvac_state = {}'.format(lnow(), hvac_state))
            if hvac_state != 'off':
                hvac_state = hvac_all_off()

        # logging stuff
        heat_status = 1 - wiringpi.digitalRead(HEATER_PIN)
        fan_status = 1 - wiringpi.digitalRead(FAN_PIN)

      #   "DBG:********"; from pdb import set_trace as bp; bp()

        def dpv(exp):
            caller = sys._getframe(1)
            return('\n\t\t{} = {}'.format(exp, caller.f_locals[exp.strip()]))

        log.info("**** Debug Status ****" +
            dpv("target_temp") +
            dpv("switch_mode") +
            dpv("hvac_state ") +
            dpv("indoor_temp") +
            dpv("heat_status") +
            dpv("fan_status "))


        time.sleep(5)


def releaseGPIO():
    log.info('Releasing all GPIO Connections')
    wiringpi.pinMode(HEATER_PIN, 1)  # Output mode
    wiringpi.digitalWrite(HEATER_PIN, 1)  # Pins are activeHI, so turn off.
    wiringpi.pinMode(FAN_PIN, 1)  # Output mode
    wiringpi.digitalWrite(FAN_PIN, 1)  # Pins are activeHI, so turn off.


if __name__ == "__main__":


    from docopt import docopt
    args = docopt(__doc__)


    if args['releaseGPIO']:
        print('Releasing GPIO pins heat ({}) and fan ({})'.format(
            HEATER_PIN, FAN_PIN))
        sys.exit(0)

    log.info("\n***\n*** Starting thermod at {}, debug is {},"
        "LogLevel = {}\n***".format(
        lnow(), logging.DEBUG, log.level    ))

    if sqliteEnabled == True:
        try:
            conn = sqlite3.connect(TEMPHUMID_DB)
        except Exception as e:
            log.fatal('SQLite3L: Error sqlite3.connect with {}: {}'.format(
                    TEMPHUMID_DB, e))
            sys.exit(32)
        sqlCursor = conn.cursor()
        # Time, temp, targTemp, humid, switch, heater
        sqlCursor.execute('CREATE TABLE IF NOT EXISTS logging '
         '(datetime TIMESTAMP, actualTemp FLOAT, target_temp INT, '
         'humid FLOAT, switch INT, hvac_state VARCHAR)')

    try:
        run()
    except KeyboardInterrupt:
        log.debug('Keyboard interrupt, stopping')
        sys.exit(9)
    finally:
        log.info('*** Finally_Clause, turning off all relays')
        releaseGPIO()
