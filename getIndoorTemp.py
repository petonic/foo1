#!/usr/bin/python
#Based off the tutorial by adafruit here:
# http://learn.adafruit.com/adafruits-raspberry-pi-lesson-11-ds18b20-temperature-sensing/software

import Adafruit_DHT
import ConfigParser
import sys


# Sensor should be set to Adafruit_DHT.DHT11,
# Adafruit_DHT.DHT22, or Adafruit_DHT.AM2302.
sensor = Adafruit_DHT.DHT22

# Example using a Beaglebone Black with DHT sensor
# connected to pin P8_11.
#pin = 'P8_11'

# Example using a Raspberry Pi with DHT sensor
# connected to GPIO23.
#pin = 23
# Purple from the LCD GPIO pins



pin = 27        # This is where the DHT22 pin is connected

def getIndoorTemp():
    config = ConfigParser.ConfigParser()
    config.read("config.txt")
    TH_FILE = config.get('main',"TEMP_HUM_FILE").strip('"')
    if TH_FILE:
        # print >> sys.stderr, "GIT: Look likes we'll read from a file"
        try:
            with open(TH_FILE, "r") as file:
                ttemp = float(file.readline())
                thumid = float(file.readline())
                return [ttemp, thumid]
            file.closed
            # print >> sys.stderr, "GIT: Yup, temp = {}, humid = {}".format(ttemp, thumid)
        except IOError: 
            # Ignore this
            print >> sys.stderr, "GIT: Error actually reading the file"
    humidity, temperature = Adafruit_DHT.read_retry(sensor, pin)
    if humidity is not None and temperature is not None:
        tempf = temperature * 9.0 / 5.0 + 32.0
        retval = [ tempf, humidity ]
        return retval
    else:
        return []
    


        
if __name__ == "__main__":
    returnVal = getIndoorTemp()
    # print(returnVal)
    if (len (returnVal) == 2):
        temp = returnVal[0]
        humid = returnVal[1]
        print ("Temperature is %f" % temp)
        print ("Humidity is %f" % humid)
    else:
        print ("Error reading temperature")
        exit(-1)
    exit(0)
