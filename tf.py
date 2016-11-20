from flask import Flask, url_for
app = Flask(__name__)

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


@app.route('/')
def hello_world():
    app.logger.debug('A value for debugging')
    return 'Hello, World!'


if __name__ == "__main__":
    print '************* RUNNING AS MAIN ****************'
    print '************* RUNNING AS MAIN ****************'
    print '************* RUNNING AS MAIN ****************'
    print '************* RUNNING AS MAIN ****************'
    print '************* RUNNING AS MAIN ****************'
    app.run("0.0.0.0", port=7000, debug=False)
