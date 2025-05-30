import os
import sys
import logging
import configparser
import time
from functools import reduce
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, Response, status
from pydantic import BaseModel
from sentinelsat.exceptions import ServerError

from .download import executeDownload
from .preprocessing import executePreprocessing
from .regionMapping import regionMapping

# Launch with: uvicorn service:app --host localhost --port 3000

configfile = "app/config/service.conf" 

# Getting configuration variables from configfile
config = configparser.ConfigParser()
config.read(configfile)

app = FastAPI()

#TODO
def _getApiVersion():
    return('1')

def _getDateString(format:str="%Y-%m-%d %H:%M:%S") -> str:
    """Get now date and time in specified format

    Args:
        format (str, optional): format string composed of format codes. Defaults to "%Y-%m-%d %H:%M:%S".

    Returns:
        str: date string in specified format. Default: YYYY-MM-DD HH:MM:SS
    """
    now = datetime.now()
    return now.strftime(format)

class ErrorModel(BaseModel):
    coderr: int = 0
    deserr: str = ''

class DateModel(BaseModel):
    start_date: str 
    end_date: str

class ResultsModel(BaseModel):
    api_version: float = _getApiVersion()
    isOk: bool = True
    error: ErrorModel = ErrorModel()
    data: DateModel | None = None  

def setupLogger(region: str, year: str, startDate:str, endDate:str, startDateRef: str) -> logging.Logger:
    """create logger for current process

    Args:
        region (str): region ID of current process
        year (str): year of current process
        startDate (str): download images starting at startDate, format: yyyymmdd
        endDate (str): download images until endDate, format: yyyymmdd
        startDateRef (str): reference date of current process (input to the api call)

    Returns:
        logging.Logger: logger for current process
    """
    # outDir = config['project']['OUTPUTDIR']
    outDir = config.get("project", "OUTPUTDIR")
    os.makedirs(outDir, exist_ok=True)
    outlog = os.path.join(outDir, '{}_PRE_{}_{}_{}_LOG.txt'.format(startDateRef,region, startDate, endDate))

    logger = logging.getLogger('{}'.format(startDateRef))
    formatter = logging.Formatter("[%(asctime)s][PRE][{}][{}] %(levelname)s %(message)s".format(region, year),datefmt='%Y-%m-%d %H:%M:%S')
    handler = logging.FileHandler(outlog)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    # let logger handle also uncaught exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.error("ERROR", exc_info=(exc_type, exc_value, exc_traceback))
    sys.excepthook = handle_exception    
    return logger

def releaseLogfile(logger: logging.Logger):
    """ Release log file.
    If file isn't released it remains attached to the service,
    leading to esauration of resources and unability to move/delete logfile

    Args:
        logger (logging.Logger): logger to release
    """
    for handler in logger.handlers:
        logger.removeHandler(handler)
        handler.close()

def handleErrorResult(errorMessage: str, errorCode:int, startDatetime:str, logger: logging.Logger=None) -> ResultsModel:
    """_summary_

    Args:
        errorMessage (str): message to add to ResultsModel
        errorCode (int):  error code to add to ResultsModel
        startDatetime (str): start date and time of current process
        logger (logging.Logger, optional): logger of current process. Defaults to None.

    Returns:
        ResultsModel: results with error
    """
    results: ResultsModel = ResultsModel(
        isOk=False, 
        error=ErrorModel(coderr=errorCode, deserr=errorMessage),
        data=DateModel(start_date=startDatetime, end_date=_getDateString()))
    if logger != None:
        logger.error(errorMessage)
        releaseLogfile(logger)
    return results

  

@app.get("/")
def root():
    return {"message":"Life Foliage Preprocess service up and running"}

@app.get("/ping", response_model=ResultsModel)
async def ping():
    return ResultsModel()

@app.get("/preprocess/{data_rif}/{id_regione}/{data_ini_mon}/{data_fin_mon}", response_model=ResultsModel)
async def preprocess(id_regione:str, data_ini_mon:str, data_fin_mon:str, data_rif:str, response: Response):
    """start preprocessing pipeline

    Args:
        id_regione (str): region to process
        data_ini_mon (str): start date for processing in format yyyymmdd
        data_fin_mon (str): end date for processing in format yyyymmdd
        data_rif (str): reference starttime (time in DB to start process)
        response (Response): response used to change response codes

    Returns:
        ResultsModel: response to caller as speciefied by the ResultsModel
    """
    # time the preprocessing starts = now()
    startDatetime = _getDateString()
    
    startDateDate = datetime.strptime(data_ini_mon, "%Y%m%d")
    endDateDate = datetime.strptime(data_fin_mon, "%Y%m%d")
        
    region = str(id_regione)
    startDate = str(data_ini_mon)
    endDate = str(data_fin_mon)
    startDateRef = str(data_rif)

    if startDateRef.split('-') != -1:
        startDateRef = reduce(lambda a, b: a+b, startDateRef.split('-'))

    # check user input
    months = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']
    days = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10',
            '11', '12', '13', '14', '15', '16', '17', '18', '19', '20',
            '22', '22', '23', '24', '25', '26', '27', '28', '29', '30', '31']
    if len(startDate) != 8:
        errorMessage = "startDate must be specified in format: yyyymmdd"
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    startYear = startDate[:4]
    startMonth = startDate[4:6]
    startDay = startDate[6:8] 
    if len(endDate) != 8:
        errorMessage = "endDate must be specified in format: yyyymmdd"
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    endYear = endDate[:4]
    endMonth = endDate[4:6]
    endDay = endDate[6:8] 
    if startYear != endYear:
        errorMessage = "start and end date must be within one year"
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    year = startYear
    if int(year) < 2016 or int(year) > int(date.today().year):
        errorMessage = "There is no Sentinel-2 data for year {}".format(year)
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    if startMonth not in months:
        errorMessage = "start month incorrect. startDate must specified in format: yyyymmdd"
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    if endMonth not in months:
        errorMessage = "end month incorrect. endDate must specified in format: yyyymmdd"
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    if startDay not in days:
        errorMessage = "start day incorrect. startDate must specified in format: yyyymmdd"
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    if endDay not in days:
        errorMessage = "end day incorrect. endDate must specified in format: yyyymmdd"
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    if int(region) not in range(1,21):
        errorMessage = "region id does not exist. RegionMapping: {}".format(regionMapping())
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results
    if not config.has_section(region):
        errorMessage = "region id does not exist in configuration file"
        errorCode = 400
        results = handleErrorResult(errorMessage, errorCode, startDatetime)
        response.status_code = status.HTTP_400_BAD_REQUEST
        return results

    # start and end array to process 3 consecuitive years (-1, 0, +1 years)
    startDateArray = [(startDateDate+relativedelta(years=-1)).strftime('%Y%m%d'), startDate,(startDateDate+relativedelta(years=1)).strftime('%Y%m%d')]
    endDateArray = [(endDateDate+relativedelta(years=-1)).strftime('%Y%m%d'), endDate,(endDateDate+relativedelta(years=1)).strftime('%Y%m%d')]

    # setup logger
    logger = setupLogger(region, year, startDate, endDate, startDateRef)

    for startDate, endDate in list(zip(startDateArray, endDateArray)):
        # init 
        nProducts = 9999
        nDownloaded = 0
        
        try:                                        
            nDownloaded, nProducts = executeDownload(region=region, config=config, startDateRef=startDateRef, startDate=startDate, endDate=endDate)
            print('#################### Downloaded:', nDownloaded, '/', nProducts, '####################') 
        except ServerError:
            logger.error('')
            # wait 15 minutes before retrying to download (to resolve sentinel server error)
            time.sleep(15*60) 
        except Exception as error:
            logger.exception('')
            releaseLogfile(logger)
            errorMessage = str(error)
            errorCode = 1
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            results = handleErrorResult(errorMessage, errorCode, startDatetime)
            return results

        try:
            executePreprocessing(region=region, config=config, startDateRef=startDateRef, startDate=startDate, endDate=endDate, apiVersion=_getApiVersion())
        except Exception as error:
            logger.exception('')
            releaseLogfile(logger)
            errorMessage = str(error)
            errorCode = 3
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            results = handleErrorResult(errorMessage, errorCode, startDatetime)
            return results


    releaseLogfile(logger)
    results: ResultsModel = ResultsModel(data=DateModel(start_date=startDatetime, end_date=_getDateString()))
    return results