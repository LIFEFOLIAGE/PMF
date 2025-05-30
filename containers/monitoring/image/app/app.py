import os
import sys
import traceback

from flask import Flask, request, session, jsonify
from datetime import datetime
from waitress import serve

import mon
import logging

logger = None

VERSION = 201
app = Flask(__name__)

# TODO x versione 3, da discutere con Almaviva: inserire nei requisiti la maschera bosco?


def create_logger(mon_input, level=logging.INFO):
    data_rif = mon_input['data_rif']
    date_start = mon_input['data_ini_mon']
    date_end = mon_input['data_fin_mon']
    code_region = int(mon_input['id_regione'])
    log_path = f'../data/{data_rif}_MON_{code_region}_{date_start}_{date_end}_LOG.txt'
    log_format = f"%(asctime)s [MON][{code_region}] %(levelname)s - %(message)s"
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter(log_format))

    bin_logger = logging.getLogger('mon_logger')
    bin_logger.setLevel(level)
    bin_logger.addHandler(handler)

    return bin_logger



@app.route('/ping', methods=['GET'])
def ping():
    result = {
            'api_version': VERSION,
            'isOK': True,
            'error': {
                'coderr': 0,
                'deserr': ""
                }
            }
    return jsonify(result)


@app.route('/monitor', methods=['GET', 'POST'])
def monitor():
    status = 1
    path_err_log = '../data/mon_error_backtrace.txt'
    if os.path.exists(path_err_log):
        os.remove(path_err_log)

    err_desc = ""
    content = request.json
    if not content:
        raise Exception("No JSON content received")

    # -- define monitoring parameters --------------------------------------------
    mon_input = dict(content)
    global logger
    logger = create_logger(mon_input)
    if not logger:
        raise Exception("Error creating logger")

    result = {
            'api_version': VERSION,
            'isOK': False,
            'data': dict(),
            'error': dict()
            }

    try:
        mon_input['path_mask'] = '../data'

        # -- define response defaults ------------------------------------------------
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        result['data']['start_date'] = timestamp

        # -- lauch monitoring app & update response ----------------------------------
        status = mon.main(mon_input, logger)

    except Exception as e:
        print('Error in monitor')
        logger.error(repr(e))
        exc_type, exc_value, exc_traceback = sys.exc_info()
        desc = repr(traceback.extract_tb(exc_traceback))
        err_desc = repr(e) + '\n' + desc
        with open(path_err_log, 'w') as err_log:
            traceback.print_exc(file=err_log)

    if not status:
        result['isOK'] = True
        result['error']['coderr'] = 0
        result['error']['deserr'] = ""
    else:
        result['error']['coderr'] = 1
        result['error']['deserr'] = err_desc

        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        result['data']['end_date'] = timestamp
    return jsonify(result)


if __name__ == '__main__':
    serve(app, host="0.0.0.0", port=8000)






