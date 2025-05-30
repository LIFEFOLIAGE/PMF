import sys
import logging
import time
import os
from uuid import uuid4
from datetime import datetime
from osgeo import gdal
from .regionMapping import regionMapping

def createMetadataFile(outputFile:str, metadataTemplate:str, tifImage:str, region:str, year:str, startMonth:str, startDay:str, endMonth:str, endDay:str, startDateRef:str, method:str):
    logger = logging.getLogger('{}'.format(startDateRef))
    startTime = time.time()

    now = datetime.now().replace(microsecond=0).isoformat()
    startDate = '{}-{}-{}'.format(year, startMonth, startDay)
    endDate = '{}-{}-{}'.format(year, endMonth, endDay)

    ds = gdal.Open(tifImage)
    width = ds.RasterXSize
    height = ds.RasterYSize
    geoTransform = ds.GetGeoTransform()
    ds = None
    xMin = geoTransform[0]
    yMax = geoTransform[3]
    xMax = xMin + geoTransform[1]*width
    yMin = yMax + geoTransform[5]*height 

    with open(metadataTemplate, 'r', encoding="utf8") as file:
        filedata = file.read()
    # Replace the target string
    filedata = filedata.replace('0_FILE_IDENTIFIER', str(uuid4()))
    filedata = filedata.replace('1_LAST_UPDATE', now)
    filedata = filedata.replace('2_REGION', region)
    filedata = filedata.replace('3_STARTDATE', startDate)
    filedata = filedata.replace('4_ENDDATE', endDate)
    filedata = filedata.replace('5_CREATIONDATE', now)
    filedata = filedata.replace('6_LON_MIN', str(xMin))
    filedata = filedata.replace('7_LON_MAX', str(xMax))
    filedata = filedata.replace('8_LAT_MIN', str(yMin))
    filedata = filedata.replace('9_LAT_MAX', str(yMax))
    filedata = filedata.replace('10_METHOD', method)
    # filedata = filedata.replace('11_RESOURCE_LOCATOR')

    # Write the file out again
    with open(outputFile, 'w') as file:
        file.write(filedata)

    timeDelta = time.time() - startTime
    logger.info('Writing metadata completed in {:.2f} seconds. Output file: "{}" \
        '.format(timeDelta, os.path.basename(outputFile)))

if __name__ == '__main__':
    """
    args: metadataTemplate, outputDir, shadowFile, region, year, startDatRef, method.
    example: python createMedaData.py G:/LifeFoliage/life-foliage/output G:/LifeFolaige/life-foliage/templates/metadata_template.xml G:/LifeFoliage/life-foliage/work/20220725101500_19_2021/5_mergedMedoidRegion/medoid.tif 01 2021 20220729070000 medoid
    """
    outputDir = sys.argv[1]
    metadataTemplate = sys.argv[2]
    tifImage = sys.argv[3]
    region = regionMapping(sys.argv[4]).capitalize()
    year = sys.argv[5]
    startDateRef = sys.argv[6]
    method = sys.arv[7]
    outputFile = os.path.join(
        outputDir, 
        '{}_{}_{}_PRE_R_meta.xml'.format(startDateRef, region, year)) 

    createMetadataFile(outputFile, metadataTemplate, tifImage, region, year, startDateRef, method)