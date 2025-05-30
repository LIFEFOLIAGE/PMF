
import logging
import time
import rioxarray as rxr
import os

def tif2netcdf(outputFile:str, inputFile:str, startDateRef:str, epsgCode:str="EPSG:4326", method='medoid') -> None:
    """Convert geotiff to netCDF file

    Args:
        outputFile (str): full path to outputfile (outputformat: .nc)
        inputFile (str): full path to file to convert
        startDateRef (str): start time for logging purposes
        epsgCode (str): CRS definition in EPSG code. Defaults to "EPSG:4326" (WGS84).
    """
    logger = logging.getLogger('{}'.format(startDateRef))
    logger.info('#### Converting to netCDF4 format ####')
    startTime = time.time()

    dsIn = rxr.open_rasterio(inputFile, band_as_variable=True)
    dsIn = dsIn.rename_vars({
        "band_1": "B2",
        "band_2": "B3",
        "band_3": "B4",
        "band_4": "B8",
        "band_5": "B8A",
        "band_6": "B9",
        "band_7": "B11",
        "band_8": "B12"
    })

    dsIn["B2"] = dsIn["B2"].assign_attrs({"long_name": f"Sentinel-2, {method} band 2, blue"})
    dsIn["B3"] = dsIn["B3"].assign_attrs({"long_name": f"Sentinel-2, {method} band 3, green"})
    dsIn["B4"] = dsIn["B4"].assign_attrs({"long_name": f"Sentinel-2, {method} band 4, red"})
    dsIn["B8"] = dsIn["B8"].assign_attrs({"long_name": f"Sentinel-2, {method} band 8, NIR"})
    dsIn["B8A"] = dsIn["B8A"].assign_attrs({"long_name": f"Sentinel-2, {method} band 8A, vegetation Red Edge"})
    dsIn["B9"] = dsIn["B9"].assign_attrs({"long_name": f"Sentinel-2, {method} band 9, water vapour"})
    dsIn["B11"] = dsIn["B11"].assign_attrs({"long_name": f"Sentinel-2, {method} band 11, SWIR"})
    dsIn["B12"] = dsIn["B12"].assign_attrs({"long_name": f"Sentinel-2, {method} band 12, SWIR"})

    for v in dsIn.data_vars:
        dsIn[v].encoding.update(dict(zlib=True))
    dsIn.to_netcdf(path=outputFile)

    dsIn = None

    timeDelta = time.time() - startTime
    logger.info('Processing completed successfully in {:.2f} seconds. Output file: "{}" \
        '.format(timeDelta, os.path.basename(outputFile)))