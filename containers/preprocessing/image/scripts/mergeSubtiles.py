import glob
import os
import logging
import time
import shutil
import numpy as np
from osgeo import gdal

gdal.UseExceptions()

def mergeSubTiles(inputDir:str, outputDir:str, tile:str, startDateRef:str) -> None:
    """Merge sub-tiles back together

    Args:
        inputDir (str): path to directory with intput images (tif format)
        outputDir (str): path to output directory (output in vrt)
        tile (str): tile to process
        startDateRef (str): start time for logging purposes
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    startTime = time.time()
    os.makedirs(outputDir, exist_ok=True)
    for method in ['medoid', 'median']:
        subTiles = glob.glob(inputDir+'/{}_{}_*.tif'.format(method, tile))
        gdal.BuildVRT(os.path.join(outputDir,"{}_{}.vrt".format(method, tile)), subTiles, bandList=[1,2,3,4,5,6,7,8], srcNodata=np.nan, VRTNodata=np.nan)
        gdal.Translate(os.path.join(outputDir,"{}_{}.tif".format(method, tile)),os.path.join(outputDir,"{}_{}.vrt".format(method,tile)), noData=np.nan)

    # delete subtile medoid files and directory
    shutil.rmtree(inputDir)

    timeDelta = time.time() - startTime
    logger.info('Merging subtiles completed in {:.2f} seconds. Output files: "medoid_{}.tif" and "median_{}.tif"'.format(timeDelta, tile, tile))

def mergeTilesToEPSGCode(inputDir: str, outputDir:str, startDateRef:str) -> None:
    """Merge tiles to create an image of the complete region in specified EPSG:4326

    Args:
        inputDir (str): path to directory with intput images (tif format)
        outputDir (str): path to output directory (output in tif)
        startDateRef (str): start time for logging purposes
        epsgCode (str): coordinate system reference. Defaults to EPSG:4326
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    startTime = time.time()
    os.makedirs(outputDir, exist_ok=True)
    for method in ['medoid', 'median']:
        methodTiles=glob.glob(inputDir+'/{}*.tif'.format(method))
        gdal.Warp(os.path.join(outputDir,"{}.tif".format(method)), methodTiles, dstSRS='EPSG:4326',dstNodata=np.nan)
        #gdal.Warp(os.path.join(outputDir,"{}.tif".format(method)), methodTiles, dstSRS=epsgCode,dstNodata=np.nan)

    # delete tile medoid files and directory
    #shutil.rmtree(inputDir)

    timeDelta = time.time() - startTime
    logger.info('Merging tiles completed successfully in {:.2f} seconds. Output files: "medoid.tif", "median.tif"'.format(timeDelta))