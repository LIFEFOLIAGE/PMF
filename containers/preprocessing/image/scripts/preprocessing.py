from .netcdf import tif2netcdf
import numpy as np
import glob
import os
import logging
import shutil
from .resampleAndSubset import resampleAndSubset
from .masking import maskImages
from .medoid import calculateMedoid
from .mergeSubtiles import mergeSubTiles, mergeTilesToEPSGCode
from .regionMapping import regionMapping
from .createMetaData import createMetadataFile



def executePreprocessing(region: str, config, startDateRef: str, startDate: str, endDate:str, apiVersion:str):
    """Preprocess Sentinel-2 images to create median and medoid composits for the given year and region

    Args:
        region (str): id of region to process
        config (configparser.ConfigParser): config file with directories
        startDateRef (str): pipline start time
        startDate (str): processing starting date. format: yyyymmdd
        endDate (str): processing end date. format: yyyymmdd
        apiVersion (str): api version.
    """
    # create logger
    year = startDate[:4]
    logger = logging.getLogger('{}'.format(startDateRef))
    logger.info('#### Life Foliage: composit generation started for region {} ({}) with Sentinel-2 images collected in {} ####'.format(
        region, regionMapping(region).capitalize(), year))
    # Define folderstructure
    geojsonDir = config['project']['GEOJSONDIR']
    outDir = config['project']['OUTPUTDIR']
    dataDir = os.path.join(config['project']['OUTPUTDIR'],'input', year)
    workDir = os.path.join(config['project']['OUTPUTDIR'], 'work','{}_{}_{}'.format(startDateRef,region, year))
    tiles = config[region]['TILES'].split(',')
    resampleDir = os.path.join(workDir, '0_resample')
    subTilesDir = os.path.join(workDir, '1_subTiles')
    maskedDir = os.path.join(workDir, '2_masked')
    compositDir = os.path.join(workDir, '3_composit')
    mergedCompositDir = os.path.join(workDir, '4_mergedComposits')
    regionDir = os.path.join(workDir, '5_mergedCompositsRegion')
    metaDataTemplate = os.path.join(config['project']['TEMPLATEDIR'], 'metadata_template.xml')

    os.makedirs(workDir, exist_ok=True)
    os.makedirs(outDir, exist_ok=True)

    NBANDS = 8  # (B2, B3, B4, B8, B8A, B9, B11, B12)

    for tile in tiles:
        assert os.path.exists(os.path.join(geojsonDir, '{}_{}.geojson'.format(tile, region))), \
            'geojson for tile {} and region {} does not exist in region {}. \nPlease create with getClippedRegion.py'.format(
                tile, region, geojsonDir)
        assert os.path.exists(os.path.join(
            dataDir, tile)), 'Input directory {} does not exists'.format(os.path.join(dataDir, tile))
        assert len(glob.glob(dataDir+'/{}/*'.format(tile))
                   ) > 0, 'Input directory {} is empty'.format(os.path.join(dataDir, tile))
    for tile in tiles:
        cropFile = os.path.join(
            geojsonDir, '{}_{}.geojson'.format(tile, region))
        nImages = resampleAndSubset(inputDir=os.path.join(dataDir, tile), resampleDir=resampleDir, subTilesDir=subTilesDir,
                                    tile=tile, cropFile=cropFile, startDateRef=startDateRef)
        resampledFiles = glob.glob(subTilesDir+'/*_{}_*'.format(tile))
        subTiles = np.array([os.path.basename(file).split(
            '_')[3].split('.')[0] for file in resampledFiles])
        uniqueSubTiles = set(subTiles)
        for i_subTile, subTile in enumerate(uniqueSubTiles):
            bandList, width, height = maskImages(inputDir=subTilesDir, outputDir=maskedDir, tile=tile, subTile=subTile,
                                                 iteration=i_subTile, nImages=nImages, nBands=NBANDS, compositDir=compositDir, startDateRef=startDateRef)
            if len(bandList) > 0:
                calculateMedoid(inputDir=maskedDir, outputDir=compositDir, subTilesDir=subTilesDir, tile=tile,
                                bandList=bandList, width=width, height=height, nImages=nImages, iteration=i_subTile,
                                subTile=subTile, startDateRef=startDateRef)
        mergeSubTiles(inputDir=compositDir, outputDir=mergedCompositDir,
                      tile=tile, startDateRef=startDateRef)
        # Delete temporary files (and folder) of intermediate steps
        #shutil.rmtree(subTilesDir)
        #shutil.rmtree(maskedDir) 
        #shutil.rmtree(resampleDir)
    mergeTilesToEPSGCode(inputDir=mergedCompositDir,
                    outputDir=regionDir, startDateRef=startDateRef)
    tif2netcdf(
        outputFile=os.path.join(outDir, '{}_PRE_{}_{}_{}_0_{}_R.nc'.format(
            startDateRef, region, startDate, endDate, apiVersion)),
        inputFile=os.path.join(regionDir, 'medoid.tif'),
        startDateRef=startDateRef)
    tif2netcdf(
        outputFile=os.path.join(outDir, '{}_PRE_{}_{}_{}_1_{}_R.nc'.format(
            startDateRef, region, startDate, endDate, apiVersion)),
        inputFile=os.path.join(regionDir, 'median.tif'),
        startDateRef=startDateRef,
        method='median')
    # uncomment to save metadata
    # createMetadataFile(
    #     outputFile=os.path.join(outDir, '{}_PRE_{}_{}_{}_0_{}_R_meta.xml'.format(
    #         startDateRef, region, startDate, endDate, apiVersion)), 
    #     metadataTemplate=metaDataTemplate, 
    #     tifImage=os.path.join(regionDir, 'medoid.tif'),
    #     region=regionMapping(region).capitalize(),
    #     startDate=startDate,
    #     endDate=endDate,
    #     startDateRef=startDateRef,
    #     method='medoid')
    # createMetadataFile(
    #     outputFile=os.path.join(outDir, '{}_PRE_{}_{}_{}_1_{}_R_meta.xml'.format(
    #         startDateRef, region, startDate, endDate, apiVersion)), 
    #     metadataTemplate=metaDataTemplate, 
    #     tifImage=os.path.join(regionDir, 'median.tif'),
    #     region=regionMapping(region).capitalize(),
    #     startDate=startDate,
    #     endDate=endDate,
    #     startDateRef=startDateRef, 
    #     method='median')
    # Delete temporary files and folders
    #shutil.rmtree(dataDir)
    #shutil.rmtree(regionDir)
    #shutil.rmtree(workDir, ignore_errors=True)
