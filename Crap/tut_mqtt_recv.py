#! /usr/bin/env python3
#
# Tutorial for MQTT Subscriptions. I'll plug this right into
# the thermod daemon.

MQTT_CLIENT = 'pithy_thermod'
MQTT_TOPIC = 'dht'
MQTT_SERVERIP = 'localhost'      # i.e, pithy

global_temp = None
global_humid = None
global_id = None
global_time = None

import paho.mqtt.client as mqtt
import threading
import datetime
from datetime import datetime

def print_values():
    print('*** PRINT_VALUES: {} / {} from {} at {}'.format(
            global_temp, global_humid, global_id, datetime.now().isoformat()))


    threading.Timer(10, print_values).start()

def main():
    mclient = mqtt.Client(MQTT_CLIENT)

    print('Connecting to server', MQTT_SERVERIP)
    mclient.connect(MQTT_SERVERIP)

    print('Subscribing to topic', MQTT_TOPIC)
    mclient.subscribe(MQTT_TOPIC)

if __name__ == '__main__':
    main()
