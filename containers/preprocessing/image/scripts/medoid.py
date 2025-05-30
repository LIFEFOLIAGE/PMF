from osgeo import gdal
import os
import time
import glob
import logging
import numpy as np

gdal.UseExceptions()

def calculateMedoid(inputDir:str, outputDir:str, subTilesDir:str, tile:str, bandList:list, \
    width:int, height:int, nImages:int, iteration:int, subTile:str, startDateRef:str) -> None:
    """Calculate and save median and medoid

    Args:
        inputDir (str): path to directory with masked subtiles (must be created with the maskImages function)
        outputDir (str): path to output directory (output in tif)
        subTilesDir (str): path to directory with resampled subtiles (must be created with the resampleAndSubset function)
        tile (str): tilenumber to process
        bandList (list): single band arrays # B2, B3, B4, B8, B8A, B9, B11, B12
        width (int): width of subTile
        height (int): height of subTile
        nImages (int): number of images in stack
        iteration (int): the number of the current iteration (for logging purposes)
        subTile (str): sub-tilenumber to process
        startDateRef (str): start time for logging purposes
    """
    os.makedirs(outputDir, exist_ok=True)
    logger = logging.getLogger('{}'.format(startDateRef))
    startTime = time.time()
    nBands = len(bandList)
    # init arrays
    medians = np.zeros((height,width,nBands), dtype=np.uint16)
    medoid = np.zeros((height,width,nBands), dtype=np.uint16) 
    summedSquaredDiff = np.zeros((height,width,nImages), dtype=np.uint64)
    
    for i, band in enumerate(bandList):
        if np.all(np.isnan(band)):
            logger.debug('All nans in band {}, iteration {}'.format(band, i))      
        medians[:,:,i] = np.nanmedian(band, axis=2)

    if np.all(np.isnan(medians)):  
        logger.debug('All nans in median for tile {} - sub-tile {}'.format(tile, subTile))     
        saveEmptyMedoidAndMedian(height=height, width=width, nBands=nBands, outputDir=outputDir, \
            subTilesDir=subTilesDir, tile=tile, subTile=subTile,startDateRef=startDateRef)
        return

    bandList = None #Free some memory
    numpyArrays = glob.glob1(inputDir,"*{}*.npy".format(tile)) 
    for i, numpyArray in enumerate(numpyArrays):
        summedSquaredDiff[:,:,i] = calculateSummedSquaredDiff(os.path.join(inputDir, numpyArray), medians, startDateRef)
    #np.save(os.path.join(outputDir,'summedSquaredDiff_{}_{}.npy'.format(tile, subTile)), summedSquaredDiff)
    
    summedSquaredDiff[np.isnan(summedSquaredDiff)] = 99999999999999 if np.all(np.isnan(summedSquaredDiff)) else np.nanmax(summedSquaredDiff)+1 
    # try:
    indexMin = np.nanargmin(summedSquaredDiff, axis=2)
    # except Exception:
    #     logger.exception('')

    for i, numpyArray in enumerate(numpyArrays):
        medoid = getPixelsForMedoid(indexMin, i, medoid, os.path.join(inputDir,numpyArray),startDateRef)

    shadowImage = glob.glob1(subTilesDir,"*{}_10m_{}_0.vrt".format(tile, subTile))
    saveAsGTiff(
        medoid, 
        outputFile=os.path.join(outputDir, 'medoid_{}_{}.tif'.format(tile, subTile)), 
        shadowFile=os.path.join(subTilesDir, shadowImage[0]),
        startDateRef=startDateRef)
    saveAsGTiff(
        medians, 
        outputFile=os.path.join(outputDir, 'median_{}_{}.tif'.format(tile, subTile)), 
        shadowFile=os.path.join(subTilesDir, shadowImage[0]),
        startDateRef=startDateRef)
    
    # logging
    timeDelta = time.time() - startTime
    logger.info('[{}-B] Calculating medoid for subtile {} completed in {:.2f} seconds. Output files: {}'.format(iteration, subTile,timeDelta, 'medoid_{}_{}.tif and median_{}_{}.tif'.format(tile, subTile, tile, subTile)))
    summedSquaredDiff = medians = numpyArray = medoid = None #Free some memory

def calculateSummedSquaredDiff(file:str, medians:np.ndarray, startDateRef:str) -> np.ndarray:
    """Calculate the summed squared difference between image and band medians

    Args:
        file (str): path to image array
        medians (np.ndarray): array containing median for each band
        startDateRef (str): start time for logging purposes

    Returns:
        np.ndarray: per pixel sum of the squared difference between image and band medians
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    im = np.load(file)
    try:
        squaredDiff = np.power(np.subtract(im, medians), 2)
    except Exception:
        logger.exception('Error in file: {}'.format(file))
        squaredDiff[:] = np.nan
    return np.sum(squaredDiff,axis=2)

def getPixelsForMedoid(indexMin:np.ndarray, fileIndex:int, medoid:np.ndarray, file:str, startDateRef:str) -> np.ndarray:
    """Add medoid pixels from specified image to medoid array

    Args:
        indexMin (np.ndarray): index of image with lowest summed squared difference (per pixel)
        fileIndex (int): index of current image
        medoid (np.ndarray): medoid array to complement with pixels of current image
        file (str): path to image array
        startDateRef (str): start time for logging purposes

    Returns:
        np.ndarray: medoid array
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    im = np.load(file)
    maskIndex = (indexMin == fileIndex)
    medoid[maskIndex] = im[maskIndex]
    return medoid

def saveAsGTiff(arr, outputFile, shadowFile,startDateRef:str):
    logger = logging.getLogger('{}'.format(startDateRef))
    shadow = gdal.Open(shadowFile, gdal.GA_ReadOnly)
    geoTransform = shadow.GetGeoTransform()
    projection = shadow.GetProjection()
    xSize = shadow.RasterXSize
    ySize = shadow.RasterYSize
    nBands = arr.shape[2]

    driver = gdal.GetDriverByName('GTiff')
    outRaster = driver.Create(outputFile, xSize, ySize,nBands,gdal.GDT_UInt16)
    outRaster.SetGeoTransform(geoTransform)
    outRaster.SetProjection(projection)
    for i in range(nBands):
        outBand = outRaster.GetRasterBand(i+1)
        outBand.WriteArray(arr[:,:,i])
        outBand.FlushCache()

def saveEmptyMedoidAndMedian(height:int, width:int, nBands:int, outputDir:str, \
    subTilesDir:str, tile:str, subTile:str, startDateRef:str) -> None:
    """save array of nans (if subtile is completely outside of (region) cropping bounds )

    Args:
        height (int): height of subtile
        width (int): width of subtile
        nBands (int): number of bands in the output image
        outputDir (str): path to medoid directory
        tile (str): tile to process
        subTile (str): subtile to process
        startDateRef (str): start time for logging purposes
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    os.makedirs(outputDir, exist_ok=True)
    medoid = np.zeros((height,width,nBands), dtype=np.float32)
    medoid[:] = np.nan
    np.save(os.path.join(outputDir,'medoid_{}_{}.npy'.format(tile, subTile)), medoid)
    shadowImage = glob.glob1(subTilesDir,"*{}_10m_{}_0.vrt".format(tile, subTile))
    saveAsGTiff(
        medoid, 
        outputFile=os.path.join(outputDir, 'medoid_{}_{}.tif'.format(tile, subTile)), 
        shadowFile=os.path.join(subTilesDir, shadowImage[0]), 
        startDateRef=startDateRef)
    saveAsGTiff(
        medoid, 
        outputFile=os.path.join(outputDir, 'median_{}_{}.tif'.format(tile, subTile)), 
        shadowFile=os.path.join(subTilesDir, shadowImage[0]), 
        startDateRef=startDateRef)