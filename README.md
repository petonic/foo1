# High level organization

There are three main components that need to be run to get an operational thermostat program and its associated web GUI.  These are listed in the order to run them in, generally

## 1. ```thermod.py```

This is the daemon that should always be running that monitors the temp sensor and controls the FAN and the HEAT gpio pins.

Normally, this is a simple daemon process that hasn't been Daemonized.  We're using supervisord to do that and monitor its execution.
## 2. ```websrvd.py```

This is the flask server that provides the application/web interface for browsers to latch on to.

The directories below contain important files for the web server:

* ```templates```
    Holds the HTML file, including the embedded javascript functions.

* ```static```
    Holds the ```CSS``` style file, as well as imported ```.js``` javascript files.  The javascript here are just canned imported js.d


## 3. ```runBrowser```
