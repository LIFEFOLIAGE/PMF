import os
import time
import logging
import glob
import numpy as np
from math import floor
from datetime import datetime, date
from typing import Tuple
from osgeo import gdal
from .medoid import saveEmptyMedoidAndMedian

gdal.UseExceptions()

def maskImages(inputDir:str, outputDir:str, tile:str, subTile:str, iteration:int, nImages:int, \
    nBands:int, compositDir:str, startDateRef:str) -> Tuple[list, int, int]:
    """Mask NoData, cloud-shadow, cloud-medium-probability, cloud-high-probability, thin-cirrus, snow-ice and water in S2 images

    Args:
        inputDir (str): path to directory with resampled subtiles (must be created with the resampleAndSubset function)
        outputDir (str): path to output directory (output in numpy array of shape HxWxD) # NOTE: overwritten for every subtile to save diskspace
        tile (str): tilenumber to process
        subTile (str): sub-tilenumber to process
        iteration (int): the number of the current iteration (for logging purposes)
        nImages (int): number of images to process
        nBands (int): number of bands to process
        compositDir (str): path to the directory where the medoids are saved
        startDateRef (str): start time for logging purposes
        
    Returns:
        list: single band arrays # B2, B3, B4, B8, B8A, B9, B11, B12
        int: width of subTile
        int: height of subTile
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    os.makedirs(outputDir, exist_ok=True)
    logger.info('#### Masking tile {} - subTile {} started ####'.format(tile, subTile)) 
    firstFile = glob.glob(os.path.join(inputDir,'*_{}_10m_{}_0.vrt'.format(tile, subTile)))[0] # _0 for first image of subset
    ds = gdal.Open(firstFile) 
    width = ds.RasterXSize
    height = ds.RasterYSize
    ds = None
    # Init arrays
    B2, B3, B4, B8, B8A, B9, B11, B12, scl = initSingleBandArrays(
        h=height,w=width,nImages=nImages, startDateRef=startDateRef, dtype=np.float32)
    watermasks = np.zeros((height,width,nImages), dtype=np.float16)
    imageSpecificMasks = np.zeros((height,width,nImages), dtype=bool)
    
    startTime = time.time()
    for i in np.arange(nImages):  
        B2[:,:,i], B3[:,:,i], B4[:,:,i], B8[:,:,i], B8A[:,:,i], B9[:,:,i], B11[:,:,i], B12[:,:,i], scl[:,:,i] = \
            createSingleBandImages(inputDir=inputDir, tile=tile, subTile=subTile, B2=B2[:,:,i], B3=B3[:,:,i], \
                B4=B4[:,:,i], B8=B8[:,:,i], B8A=B8A[:,:,i], B9=B9[:,:,i], B11=B11[:,:,i], B12=B12[:,:,i], \
                scl=scl[:,:,i], iteration=i, startDateRef=startDateRef)
        watermasks[:,:,i], imageSpecificMasks[:,:,i] = createMasks(scl=scl[:,:,i], watermasks=watermasks[:,:,i], \
            imageSpecificMasks=imageSpecificMasks[:,:,i], startDateRef=startDateRef)
    timeDelta = time.time() - startTime
    logger.info('[{}-A] Masking subtile {} completed in {:.2f} seconds.'.format(iteration, subTile, timeDelta))
    
    B2, B3, B4, B8, B8A, B9, B11, B12 = applyMasks(B2, B3, B4, B8, B8A, B9, B11, B12, imageSpecificMasks, \
        watermasks,startDateRef)
    
    # check if valid pixels remain:
    if np.all(imageSpecificMasks):
        logger.info('subtile {} had no valid pixels'.format(subTile))
        saveEmptyMedoidAndMedian(
            height, 
            width, 
            nBands, 
            outputDir=compositDir, 
            subTilesDir=inputDir, 
            tile=tile, 
            subTile=subTile, 
            startDateRef=startDateRef)
        scl = watermasks = imageSpecificMasks = B2 = B3 = B4 = B8 = B8A = B9 = B11 = B12 = None # Free some memory
        return [], width, height

    # save masked images as numpy array
    for i in np.arange(nImages):
        files = glob.glob(inputDir+'/*_{}_10m_{}_{}.vrt'.format(tile, subTile, i))
        date = os.path.basename(files[0]).split('_')[0]
        saveAsNumpy(width, height, nBands, B2[:,:,i], B3[:,:,i], B4[:,:,i], B8[:,:,i], \
            B8A[:,:,i], B9[:,:,i], B11[:,:,i], B12[:,:,i], '{}_{}_{}.npy'.format(date, tile, i), \
                outputDir, startDateRef=startDateRef, dtype=np.float32)

    bandList = [B2, B3, B4, B8, B8A, B9, B11, B12]
    return bandList, width, height

def createSingleBandImages(inputDir:str, tile:str, subTile:str, B2:np.ndarray, B3:np.ndarray, \
    B4:np.ndarray, B8:np.ndarray, B8A:np.ndarray, B9:np.ndarray, B11:np.ndarray, B12:np.ndarray, \
    scl:np.ndarray, iteration:int, startDateRef:str) -> Tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray,np.ndarray,\
        np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
    """Add bands from image on disk to single band arrays

    Args:
        inputDir (str): path to directory with resampled subtiles (must be created with the resampleAndSubset function)
        tile (str): tilenumber to process
        subTile (str): sub-tilenumber to process
        B2 (np.ndarray): B2 array indexed at current iteration
        B3 (np.ndarray): B3 array indexed at current iteration
        B4 (np.ndarray): B4 array indexed at current iteration
        B8 (np.ndarray): B8 array indexed at current iteration
        B8A (np.ndarray): B8A array indexed at current iteration
        B9 (np.ndarray): B9 array indexed at current iteration
        B11 (np.ndarray): B11 array indexed at current iteration
        B12 (np.ndarray): B12 array indexed at current iteration
        scl (np.ndarray): scl array indexed at current iteration
        iteration (int): extra identifier file
        startDateRef (str): start time for logging purposes

    Returns:
        np.ndarray: B2 array indexed at current iteration
        np.ndarray: B3 array indexed at current iteration
        np.ndarray: B4 array indexed at current iteration
        np.ndarray: B8 array indexed at current iteration
        np.ndarray: B8A array indexed at current iteration
        np.ndarray: B9 array indexed at current iteration
        np.ndarray: B11 array indexed at current iteration
        np.ndarray: B12 array indexed at current iteration
        np.ndarray: scl array indexed at current iteration
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    file10m = glob.glob(os.path.join(inputDir,'*_{}_10m_{}_{}.vrt'.format(tile, subTile, iteration)))[0]
    baseline = gdal.Info(file10m, format="json")["metadata"][""]["PROCESSING_BASELINE"]
    product_date = os.path.basename(file10m).split('_')[0]     
    ds = gdal.Open(file10m)
    B4 = ds.GetRasterBand(1).ReadAsArray()
    B3 = ds.GetRasterBand(2).ReadAsArray()
    B2 = ds.GetRasterBand(3).ReadAsArray()
    B8 = ds.GetRasterBand(4).ReadAsArray()
    
    file20m = glob.glob(os.path.join(inputDir,'*_{}_20m_{}_{}.vrt'.format(tile, subTile, iteration)))[0]
    ds = gdal.Open(file20m)
    B8A = ds.GetRasterBand(4).ReadAsArray()
    B11 = ds.GetRasterBand(5).ReadAsArray()
    B12 = ds.GetRasterBand(6).ReadAsArray()
    scl = ds.GetRasterBand(9).ReadAsArray()
    
    file60m = glob.glob(os.path.join(inputDir,'*_{}_60m_{}_{}.vrt'.format(tile, subTile, iteration)))[0]
    ds = gdal.Open(file60m)
    B9 = ds.GetRasterBand(2).ReadAsArray()
    ds = None

    B2, B3, B4, B8, B8A, B9, B11, B12 = harmonize_baselines(
        baseline=float(baseline), 
        product_date=product_date, 
        B2=B2, 
        B3=B3, 
        B4=B4, 
        B8=B8, 
        B8A=B8A, 
        B9=B9, 
        B11=B11, 
        B12=B12, 
        startDateRef=startDateRef)
    
    return B2, B3, B4, B8, B8A, B9, B11, B12, scl

def harmonize_baselines(baseline:float, product_date:str, B2:np.ndarray, B3:np.ndarray, \
    B4:np.ndarray, B8:np.ndarray, B8A:np.ndarray, B9:np.ndarray, B11:np.ndarray, \
    B12:np.ndarray, startDateRef:str) -> Tuple[np.ndarray,np.ndarray,np.ndarray,np.ndarray,\
    np.ndarray,np.ndarray,np.ndarray,np.ndarray]:
    """Harmonize Sentinel products with baseline > 4.00 with older products

    Args:
        baseline (str): processing baseline of Sentinel-2 image
        product_date (str): datestring of product sensing date format: '%Y-%m-%d'
        B2 (np.ndarray): B2 array indexed at current iteration
        B3 (np.ndarray): B3 array indexed at current iteration
        B4 (np.ndarray): B4 array indexed at current iteration
        B8 (np.ndarray): B8 array indexed at current iteration
        B8A (np.ndarray): B8A array indexed at current iteration
        B9 (np.ndarray): B9 array indexed at current iteration
        B11 (np.ndarray): B11 array indexed at current iteration
        B12 (np.ndarray): B12 array indexed at current iteration
        startDateRef (str): start time for logging purposes

    Returns:
        np.ndarray: B2 array indexed at current iteration
        np.ndarray: B3 array indexed at current iteration
        np.ndarray: B4 array indexed at current iteration
        np.ndarray: B8 array indexed at current iteration
        np.ndarray: B8A array indexed at current iteration
        np.ndarray: B9 array indexed at current iteration
        np.ndarray: B11 array indexed at current iteration
        np.ndarray: B12 array indexed at current iteration
    """
    logger = logging.getLogger('{}'.format(startDateRef))

    processing_baseline = float(baseline)
    ADD_OFFSET = 0
    QUANTIFICATION_VALUE = 10000 # NOTE: didn't divide by 10000 --> to keep integer datatype
    if floor(processing_baseline) == 99:      
        d = datetime.strptime(product_date, '%Y-%m-%d') 
        if d.date() > date(2022, 1, 24):
            ADD_OFFSET = -1000
    elif floor(processing_baseline) > 4:     
        ADD_OFFSET = -1000    
    B2 = (B2 + ADD_OFFSET) 
    B3 = (B3 + ADD_OFFSET) 
    B4 = (B4 + ADD_OFFSET) 
    B8 = (B8 + ADD_OFFSET) 
    B8A = (B8A + ADD_OFFSET) 
    B9 = (B9 + ADD_OFFSET) 
    B11 = (B11 + ADD_OFFSET) 
    B12 = (B12 + ADD_OFFSET) 

    return B2, B3, B4, B8, B8A, B9, B11, B12

def createMasks(scl:np.ndarray, watermasks:np.ndarray, imageSpecificMasks:np.ndarray, startDateRef:str, \
    waterValue:int = 6, maskValueArray:list = [0,1,3,8,9,10,11],) -> Tuple[np.ndarray, np.ndarray]: 
    """Create image specific masks for water and other undesired features (e.g. clouds)

    Args:
        scl (np.ndarray): scl array from all images in stack
        watermasks (np.ndarray): zero initialized array  
        imageSpecificMasks (np.ndarray): zero initialized array
        startDateRef (str): start time for logging purposes
        waterValue (int, optional): value representing water in scl array. Defaults to 6.
        maskValueArray (list, optional): list of values in scl array to mask (except watermask). 
            Defaults to [0,3,8,9,10,11]. #0: NoData, 3: cloud-shadow, 8: cloud-medium-probability 
            9: cloud-high-probability, 10: thin-cirrus, 11: snow-ice

    Returns:
        np.ndarray: watermasks (1 for each image in the stack)
        np.ndarray: mask for each image in the stack
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    watermask = scl == waterValue
    watermasks[watermask] = 1 
    nans = scl == 0
    watermasks[nans] = np.nan
    imageSpecificMasks = np.isin(scl,maskValueArray) 
    return watermasks, imageSpecificMasks

def applyMasks(B2:np.ndarray, B3:np.ndarray, B4:np.ndarray, B8:np.ndarray, B8A:np.ndarray, \
    B9:np.ndarray, B11:np.ndarray, B12:np.ndarray, imageSpecificMasks:np.ndarray, \
    watermasks:np.ndarray, startDateRef:str):
    """Apply masks

    Args:
        B2 (np.ndarray): B2 array containing band from all images in stack
        B3 (np.ndarray): B3 array containing band from all images in stack
        B4 (np.ndarray): B4 array containing band from all images in stack
        B8 (np.ndarray): B8 array containing band from all images in stack
        B8A (np.ndarray): B8A array containing band from all images in stack
        B11 (np.ndarray): B11 array containing band from all images in stack
        B12 (np.ndarray): B12 array containing band from all images in stack
        imageSpecificMasks (np.ndarray): mask array for all images in stack
        watermasks (np.ndarray): watermask array for all images in stack
        startDateRef (str): start time for logging purposes

    Returns:
        np.ndarray: masked B2 array
        np.ndarray: masked B3 array
        np.ndarray: masked B4 array
        np.ndarray: masked B8 array
        np.ndarray: masked B8A array
        np.ndarray: masked B9 array
        np.ndarray: masked B11 array
        np.ndarray: masked B12 array
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    B4[imageSpecificMasks] = np.nan
    B3[imageSpecificMasks] = np.nan
    B2[imageSpecificMasks] = np.nan
    B8[imageSpecificMasks] = np.nan
    B8A[imageSpecificMasks] = np.nan
    B11[imageSpecificMasks] = np.nan
    B12[imageSpecificMasks] = np.nan
    B9[imageSpecificMasks] = np.nan

    # create single watermask and apply
    watermask = np.nanmedian(watermasks, axis=2) >= 0.5
    B4[watermask] = np.nan
    B3[watermask] = np.nan
    B2[watermask] = np.nan
    B8[watermask] = np.nan
    B8A[watermask] = np.nan
    B11[watermask] = np.nan
    B12[watermask] = np.nan
    B9[watermask] = np.nan
    
    return B2, B3, B4, B8, B8A, B9, B11, B12

def saveAsNumpy(w:int, h:int, nBands:int, B2:np.ndarray, B3:np.ndarray, B4:np.ndarray, B8:np.ndarray, \
    B8A:np.ndarray, B9:np.ndarray, B11:np.ndarray, B12:np.ndarray, file:str, outputdir:str, \
    startDateRef:str, dtype:np.dtype=np.float32) -> None:
    """Save input (subtile) to numpy array (bands are merged again)

    Args:
        w (int): width of output array
        h (int): height of output array
        nBands (int): number of bands (dimensions) in output array
        B2 (np.ndarray): B2 array indexed at current iteration
        B3 (np.ndarray): B3 array indexed at current iteration
        B4 (np.ndarray): B4 array indexed at current iteration
        B8 (np.ndarray): B8 array indexed at current iteration
        B8A (np.ndarray): B8A array indexed at current iteration
        B9 (np.ndarray): B9 array indexed at current iteration
        B11 (np.ndarray): B11 array indexed at current iteration
        B12 (np.ndarray): B12 array indexed at current iteration
        file (str): output file name
        outputdir (str): path to output directory
        startDateRef (str): start time for logging purposes
        dtype (np.dtype, optional): data type of output array. Defaults to np.float32.
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    arr = np.zeros((h,w,nBands), dtype=dtype)
    arr[:,:,0] = B2
    arr[:,:,1] = B3
    arr[:,:,2] = B4
    arr[:,:,3] = B8
    arr[:,:,4] = B8A
    arr[:,:,5] = B9
    arr[:,:,6] = B11
    arr[:,:,7] = B12
    np.save(outputdir+'/'+file, arr)

def initSingleBandArrays(w:int,h:int,nImages:int,startDateRef:str,dtype:np.dtype=np.float32) :
    """Initialize numpy arrays to store specific bands from all images

    Args:
        w (int): width of image (of arrays to create)
        h (int): height of image (of arrays to create)
        nImages (int): number of images
        startDateRef (str): start time for logging purposes
        dtype (np.dtype, optional): data type of arrays. Defaults to np.float32.

    Returns:
        np.ndarray: nan initalized array for B2 bands
        np.ndarray: nan initalized array for B3 bands
        np.ndarray: nan initalized array for B4 bands
        np.ndarray: nan initalized array for B8 bands
        np.ndarray: nan initalized array for B8A bands
        np.ndarray: nan initalized array for B9 bands
        np.ndarray: nan initalized array for B11 bands
        np.ndarray: nan initalized array for B12 bands
        np.ndarray: nan initalized array for scl bands
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    B2 = np.zeros((h,w,nImages), dtype=dtype) 
    B3 = np.zeros((h,w,nImages), dtype=dtype)  
    B4 = np.zeros((h,w,nImages), dtype=dtype)  
    B8 = np.zeros((h,w,nImages), dtype=dtype)  
    B8A = np.zeros((h,w,nImages), dtype=dtype)  
    B9 = np.zeros((h,w,nImages), dtype=dtype)  
    B11 = np.zeros((h,w,nImages), dtype=dtype) 
    B12 = np.zeros((h,w,nImages), dtype=dtype) 
    scl = np.zeros((h,w,nImages), dtype=dtype) 
    B2[:] = np.nan
    B3[:] = np.nan
    B4[:] = np.nan
    B8[:] = np.nan
    B8A[:] = np.nan
    B9[:] = np.nan
    B11[:] = np.nan
    B12[:] = np.nan
    scl[:] = np.nan
    return B2, B3, B4, B8, B8A, B9, B11, B12, scl