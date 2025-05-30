from osgeo import gdal
import glob
import os
import time
import logging
from typing import Tuple
from math import floor

gdal.UseExceptions()

def resampleAndSubset(inputDir:str, resampleDir:str, subTilesDir:str, tile:str, cropFile:str, startDateRef:str) -> int:
    """Resample input bands to 10m, crop to cutline and create sub-tiles for processing

    Args:
        inputDir (str): path to source data (must be zipfiles)
        resampleDir (str): path to output directory for resampled source data (output in vrt (10m) and tif (20 and 60m))
        subTilesDir (str): path to output directory for splitted tiles (output in vrt)
        tile (str): tilenumber to process
        cropFile (str): path to file to use as cutline for cropping
        startDateRef (str): start time for logging purposes

    Returns:
        int: number of source files processed
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    os.makedirs(resampleDir, exist_ok=True)
    os.makedirs(subTilesDir, exist_ok=True)

    files = glob.glob(inputDir + '/*.zip')
    nImages = len(files)
    assert nImages > 0, '{} does not contain any source products (note: products must be original zip files)'.format(inputDir)
    logger.info('#### Resampling and Subsetting tile {} started ####\nNumber of files: {}'.format(tile, nImages))
    width = height = xMin = yMin = xMax = yMax = xSizes = ySizes = xCoords = yCoords = None #Init
    for i, file in enumerate(files):
        startTime = time.time()
        sensingDate, width, height, xMin, yMin, xMax, yMax, xSizes, ySizes, xCoords, yCoords = \
            resample(resampleDir, tile, file, cropFile, width, height, xMin, yMin, xMax, yMax, \
            xSizes, ySizes, xCoords, yCoords, iteration=i, startDateRef=startDateRef)
        timeDelta = time.time() - startTime
        logger.info('[{}-A] Resampling and cropping file {} completed in {:.2f} seconds.'.format(i, os.path.basename(file),timeDelta))

        #gdal warp for smaller tiles
        startTime = time.time()
        createSubTiles(inputDir=resampleDir, outputDir=subTilesDir, tile=tile, date=sensingDate, \
            xSizes=xSizes, ySizes=ySizes,xCoords=xCoords, yCoords=yCoords, iteration=i, \
            startDateRef=startDateRef)
            
        timeDelta = time.time() - startTime
        logger.info('[{}-B] Subsetting file {} completed in {:.2f} seconds.'.format(i, os.path.basename(file),timeDelta))

    
    return nImages

def resample(outputDir:str, tile:str, file:str, cropFile:str, width:int or None, height:int or None, \
    xMin:float or None, yMin:float or None, xMax:float or None, yMax:float or None, \
    xSizes:list or None, ySizes:list or None, xCoords:list or None, yCoords:list or None, \
    iteration:int,startDateRef:str) -> Tuple[str, int, int, float, float, float, float, list, list, list, list]:
    """Resample input bands to 10m

    Args:
        outputDir (str): path to output directory for resampled source data (output in vrt (10m) and tif (20 and 60m))
        tile (str): tilenumber to process
        file (str): path to inputfile (*.zip format)
        cropFile (str): path to file to use as cutline for cropping
        width (int | None): width of inputfile in pixels, None on first itertion
        height (int | None): height of inputfile in pixels, None on first itertion
        xMin (float | None): x-coordinate upper left corner of inputfile, None on first iteration
        yMin (float | None): y-coordinate lower right corner of inputfile, None on first iteration
        xMax (float | None): x-coordinate lower right corner of inputfile, None on first iteration
        yMax (float | None): y-coordinate upper left corner of inputfile, None on first iteration
        xSizes (list | None): width of subTiles to create in pixels, None on first interation 
        ySizes (list | None): height of subTiles to create in pixels, None on first interation 
        xCoords (list | None): x-coords of subTiles to create, None on first interation 
        yCoords (list | None): y-coords of subTiles to create, None on first interation 
        iteration (int): current iteration to avoid overwriting files
        startDateRef (str): start time for logging purposes

    Returns:
        str: sensing date of source image 
        int: width 
        int: height 
        float: xMin 
        float: yMin
        float: xMax 
        float: yMax 
        list: xSizes
        list: ySizes
        list: xCoords
        list: yCoords
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    info = gdal.Info(file, format="json")
    m10_file = info['metadata']['SUBDATASETS']['SUBDATASET_1_NAME']
    m20_file = info['metadata']['SUBDATASETS']['SUBDATASET_2_NAME']
    m60_file = info['metadata']['SUBDATASETS']['SUBDATASET_3_NAME']
    sensingDate = info['metadata']['']['DATATAKE_1_DATATAKE_SENSING_START'].split('T')[0]
    ds10 = gdal.Open(m10_file)
    ds20 = gdal.Open(m20_file)
    ds60 = gdal.Open(m60_file)
    gdal.Warp(os.path.join(outputDir,'{}_{}_10m_{}.vrt'.format(sensingDate, tile, iteration)), \
        ds10, cropToCutline=True, cutlineDSName=cropFile, dstNodata=0)
    if width == None:
        width, height, xMin, yMin, xMax, yMax, xSizes, ySizes, xCoords, yCoords = \
            getOutputBounds(outputDir, tile=tile, date=sensingDate, \
            iteration=iteration, startDateRef=startDateRef)
    gdal.Warp(os.path.join(outputDir,'{}_{}_20m_{}.tif'.format(sensingDate, tile, iteration)), \
        ds20, cropToCutline=True, cutlineDSName=cropFile, dstNodata=0, resampleAlg='near', \
        outputBounds=(xMin, yMin, xMax, yMax), width=width, height=height)
    gdal.Warp(os.path.join(outputDir,'{}_{}_60m_{}.tif'.format(sensingDate, tile, iteration)), \
        ds60, cropToCutline=True, cutlineDSName=cropFile, dstNodata=0, resampleAlg='near', \
        outputBounds=(xMin, yMin, xMax, yMax), width=width, height=height)
    ds10 = ds20 = ds60 = None
    return sensingDate, width, height, xMin, yMin, xMax, yMax, xSizes, ySizes, xCoords, yCoords

def createSubTiles(inputDir:str, outputDir:str, tile:str, date:str, xSizes:list, \
    ySizes:list, xCoords:list, yCoords:list, iteration:int,startDateRef:str) -> None:
    """Divide tile in subtiles for processing

    Args:
        inputDir (str): path to directory with resampled tiles (must be created with the resample function)
        outputDir (str): path to output directory for sub-tiles (output in vrt)
        tile (str): tilenumber to process
        date (str): generation date of image (only for saving purposes) 
        xSizes (list): width of subTiles to create in pixels
        ySizes (list): height of subTiles to create in pixels
        xCoords (list): x-coords of subTiles to create
        yCoords (list): y-coords of subTiles to create
        iteraton (int): extra identifier for file to avoid overwriting
        startDateRef (str): start time for logging purposes
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    for j, xSize in enumerate(xSizes):
        for k, ySize in enumerate(ySizes): 
            gdal.Warp(os.path.join(outputDir,'{}_{}_10m_{}-{}_{}.vrt'.format(date, tile, j,k,iteration)),\
                os.path.join(inputDir,'{}_{}_10m_{}.vrt'.format(date, tile,iteration)), dstNodata=0, \
                outputBounds=(xCoords[j], yCoords[k+1], xCoords[j+1], yCoords[k]), width=xSize, height=ySize)
            gdal.Warp(os.path.join(outputDir,'{}_{}_20m_{}-{}_{}.vrt'.format(date, tile, j,k,iteration)),\
                os.path.join(inputDir,'{}_{}_20m_{}.tif'.format(date, tile,iteration)), dstNodata=0, \
                outputBounds=(xCoords[j], yCoords[k+1], xCoords[j+1], yCoords[k]), width=xSize, height=ySize)
            gdal.Warp(os.path.join(outputDir,'{}_{}_60m_{}-{}_{}.vrt'.format(date, tile, j,k,iteration)),\
                os.path.join(inputDir,'{}_{}_60m_{}.tif'.format(date, tile,iteration)), dstNodata=0, \
                outputBounds=(xCoords[j], yCoords[k+1], xCoords[j+1], yCoords[k]), width=xSize, height=ySize)

def deleteTemporaryResampledFiles(inputDir:str, date:str, tile:str, iteration:int, startDateRef:str):
    """Delete files that are not needed anymore to free disk space

    Args:
        inputDir (str): path to directory with resampled tiles (must be created with the resample function)
        date (str): generation date of image 
        tile (str): tilenumber to process
        iteration (int): extra identifier for file to avoid overwriting
        startDateRef (str): start time for logging purposes
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    os.remove(os.path.join(inputDir,'{}_{}_10m_{}.vrt'.format(date, tile,iteration)))
    os.remove(os.path.join(inputDir,'{}_{}_20m_{}.tif'.format(date, tile,iteration)))
    os.remove(os.path.join(inputDir,'{}_{}_60m_{}.tif'.format(date, tile,iteration)))

def getOutputBounds(inputDir:str, tile:str, date:str, startDateRef:str, nTilesX:int=3, nTilesY:int=3,\
        iteration:int=0) -> Tuple[int, int, float, float, float, float, list, list, list, list]:
    """_summary_

    Args:
        inputDir (str): path to directory with resampled tiles (must be created with the resample function)
        tile (str): tilenumber to process
        date (str): generation date of image (only for saving purposes) 
        startDateRef (str): start time for logging purposes
        nTilesX (int, optional): number of subtiles to create in the x-direction. Defaults to 3.
        nTilesY (int, optional): number of subtiles to create in the y-direction. Defaults to 3.
        iteration (int, optional): iteration used as extra identiefier file. Defaults to 0.
    Returns:
        int: width 
        int: height 
        float: xMin 
        float: yMin
        float: xMax 
        float: yMax 
        list: xSizes
        list: ySizes
        list: xCoords
        list: yCoords
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    ds = gdal.Open(os.path.join(inputDir,'{}_{}_10m_{}.vrt'.format(date, tile, iteration)))
    width = ds.RasterXSize
    height = ds.RasterYSize
    geoTransform = ds.GetGeoTransform()
    ds = None
    xMin = geoTransform[0]
    yMax = geoTransform[3]
    xMax = xMin + geoTransform[1]*width
    yMin = yMax + geoTransform[5]*height 
    res = geoTransform[1]

    tileWidth = floor(width / nTilesX)
    tileHeight = floor(height / nTilesY)
    lastWidth = (width % nTilesX) + tileWidth
    lastHeight = (height % nTilesY) + tileHeight

    xCoords = [xMin + tileWidth*j*res for j in range(nTilesX)]
    yCoords = [yMax - tileHeight*j*res for j in range(nTilesY)]
    xCoords.append(xMax)
    yCoords.append(yMin)
    xSizes = [tileWidth]*(nTilesX-1)
    xSizes.append(lastWidth)
    ySizes = [tileHeight]*(nTilesY-1)
    ySizes.append(lastHeight)
    return width, height, xMin, yMin, xMax, yMax, xSizes, ySizes, xCoords, yCoords

