# /usr/bin/env python2


from __future__ import print_function

import wiringpi

from time import sleep
import sys
import fileinput
from pdb import set_trace as bp
def bp(arg):
  pass

Relay_channel = [4]
# Relay_channel = [17, 04]


def setup():
  wiringpi.wiringPiSetupSys() # For GPIO pin numbering accessible by user.
  for i in Relay_channel:
    wiringpi.pinMode(i,1)   # Output mode


  print("|=====================================================|")
  print("|         2-Channel High trigger Relay Sample         |")
  print("|-----------------------------------------------------|")
  print("|                                                     |")
  print("|          Turn {} channels on off in orders           |".format(
      len(Relay_channel)))
  print("ffoo")
  for i in Relay_channel:
    print("|  Pin #{}                                           |".format(
        i, ))
  print("|                                                     |")
  print("|                                                     |")
  print("|=====================================================|")


def main():
  while True:
    for i in range(0, len(Relay_channel)):
      print("Press Key to turn on {}({})".format(i + 1, Relay_channel[i]))
      line = sys.stdin.readline()

      print('...Relay channel {}({}) on'.format(i + 1, Relay_channel[i]))
      wiringpi.digitalWrite(Relay_channel[i],1) # Write 1 ( HIGH ) to pin i

      print("Press Key to turn off {}({})".format(i + 1, Relay_channel[i]))
      line = sys.stdin.readline()

      print('...Relay channel {}({}) off'.format(i + 1, Relay_channel[i]))
      wiringpi.digitalWrite(Relay_channel[i],0) # Write 0 ( LOW ) to pin i

def destroy():
  pass

for i in Relay_channel:
  print("i is {}".format(i))

  if __name__ == '__main__':
    setup()
    try:
      main()
    except KeyboardInterrupt:
      destroy()
