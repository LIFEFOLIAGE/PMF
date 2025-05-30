# TODO:

# -- LIBRARIES ---------------------------------------------------------------
# main libraries
import os

import numpy as np
import rasterio as rio
import xarray as xr
import rioxarray
import geopandas as gpd

#import h5py
import netCDF4
import h5netcdf

# import string
from datetime import datetime
import rao_q_lin
import alert


# polygonize
import fiona
import rasterio.features
from shapely.geometry import shape, mapping
from shapely.geometry.polygon import Polygon
import pickle

# connected pixel filtering
import cv2

TESTING = 1

# web

logger = None
# debug



# -- HELPER CLASSES AND FUNCTION ---------------------------------------------
class DD(dict):  # @@2
    """dot.notation access to dictionary attributes (pickable) """
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__
    def __getstate__(self): return self.__dict__
    def __setstate__(self, d): self.__dict__.update(d)


class FormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


# -- INPUT/OUTPUT FUNCTIONS --------------------------------------------------
def f_get_mask(path):
    with rio.open(path) as f:
        return np.squeeze(f.read()).astype(np.uint8)


def f_get_dataset_nc_xarray(path3, mask=0):
    '''
    requires files named pre.nc, now.nc, post.nc in folder
    '''
    # rename bands
    #bandnames = ['B2'   , 'B3'    , 'B4'  , 'B8'  , 'B9', 'B8A'   , 'B11'   , 'B12']
    #new_names = ['blue' , 'green' , 'red' , 'nir' , 'B9', 'redE4' , 'swir1' , 'swir2']
    bandnames = ['B8'  , 'B11'   , 'B12']
    new_names = ['nir' , 'swir1' , 'swir2']
    band_dict = dict(zip(bandnames, new_names))

    # build raster collection
    p3 = path3
    d3 = DD()
    first_loop = True
    for ix in p3:
        d3[ix] = DD()
        path = p3[ix]
        with rioxarray.open_rasterio(path) as f:
            for band in band_dict.keys():
                data = f[band].data.astype(np.float32)
                #data[data==9.969209968386869e+36] = np.nan #TODO: risolvere con Almaviva
                band_new = band_dict[band]
                if type(mask) == int:
                    d3[ix][band_new] = data[0][:][:]
                else:
                    d3[ix][band_new] = data[0][:][:] * np.squeeze(mask)
    return d3, path3['pre']


def f_write_nc(reference, out_path, group, data_dict, crs=4326, metadata_dict=None):
    '''write netcdf data
    ref: <str> path to netcdf data used as reference
    out_path: <str> output path for writing netcdf
    group: <str> result use. One between: /tagli_boschivi, /incendi, /natura_2000
    crs: <int> crs epsg code
    metadata_dict: dictionary containing metadata. The dict is nested using var_name
    '''
    with rioxarray.open_rasterio(reference) as ref:
    # manage dimensions
        arr_x = ref.x.data
        arr_x = xr.DataArray(arr_x, dims=['longitude'])

        arr_y = ref.y.data
        arr_y = xr.DataArray(arr_y, dims=['latitude'])

        if metadata_dict:
            arr_x = f_set_attrs(arr_x, 'x', metadata_dict)
            arr_y = f_set_attrs(arr_y, 'y', metadata_dict)

        # manage data
        xd = xr.Dataset()
        for key in data_dict:
            data =  data_dict[key]
            xa = xr.DataArray(
                data,
                dims=('latitude', 'longitude'),
                coords={'latitude': arr_y, 'longitude': arr_x}
            )
            if metadata_dict:
                xa = f_set_attrs(xa, key, metadata_dict)
            xa.encoding = dict(zlib=True, complevel=5)
            rio_crs = rio.crs.CRS.from_user_input(crs)
            xa = xa.rio.write_crs(rio_crs)
            key = str(key)
            xd[key] = xa
    xd.to_netcdf(out_path, format='NETCDF4', engine='netcdf4', mode='a')
    #xd.to_netcdf(out_path, engine="h5netcdf", mode='a')
    xd.close()


def f_set_attrs(var, var_name, metadata_dict):
    '''set attributes of netcdf data
    xa: <xarray dataset>
    var_name: <str> netcdf layer name
    metadata_dict: dictionary containing metadata. The dict is nested using var_name
    '''
    for key in metadata_dict[var_name]:
        var.attrs[key] = metadata_dict[var_name][key]
    return var





# -- 3I3D algorithm ----------------------------------------------------------
def f_ndif(image1, image2):
    "get normalized difference"

    image1 = np.where(image1==0, 0.0001, image1)
    image2 = np.where(image2==0, 0.0001, image2)
    return (image1 - image2) / (image1 + image2)


def f_magnitude(x, y, z):
    "get magnitude"
    return (x**2 + y**2 + z**2)**0.5


def f_con(x, v1, v2):
    "function implemented in 3i3d"
    return np.abs((v2 - np.abs(x - v1))/v2)


def f_3i3d(
        ds: DD,
        th: int,             # threshold
        debug: bool = True
         ) -> (np.array, np.array):
    '''
    dataset: image dataset<DD>
    image names = 'pre', 'now', 'post'
    returns (magnitude, change_map)
        magnitude: 8 bit image (probability of forest anomaly)
        change_map: 1 bit image (forest anomaly mask)
    '''
    req2 = ['pre', 'now', 'post']
    band2 = ['swir1', 'swir2', 'nir']
    for req1 in req2:
        if not req1 in ds:
            raise LookupError('image {} not found'.format(req1))
        for band1 in band2:
            # Testing input
            #f_write_image(ds[req1][band1], profile, 'testing/{a}_{b}.tif'.format(a=req1, b=band1), dtype=rio.float32)

            if not band1 in ds[req1]:
                raise LookupError('band {a} not found in {b} image'.format(a=band1, b=req1))


    # logger.info("step 1 ok")
    c_todegree = 180 / np.pi
    #c_todegree = 180 / 3.1416

    #image_name2 = 'pre', 'now', 'post'
    for image in ds:
        ds[image].ndmi = f_ndif(ds[image].nir, ds[image].swir1)
        ds[image].nbr  = f_ndif(ds[image].nir, ds[image].swir2)
        ds[image].msi  = ds[image].swir1 / ds[image].nir

    # cleanup memory
    for image in ds:
        ds[image].nir   = None
        ds[image].swir1 = None
        ds[image].swir2 = None

    d1 = DD()
    d2 = DD()
    # logger.info("step 1.5 ok")

    d1.x = ds.now.ndmi  - ds.pre.ndmi
    d1.y = ds.now.nbr   - ds.pre.nbr
    d1.z = ds.now.msi   - ds.pre.msi

    d2.x = ds.post.ndmi - ds.now.ndmi
    d2.y = ds.post.nbr  - ds.now.nbr
    d2.z = ds.post.msi  - ds.now.msi

    # cleanup memory
    for image in ds:
        ds[image].ndmi = None
        ds[image].nbr  = None
        ds[image].msi  = None

    # logger.info("step 2 ok")
    modulo_a = f_magnitude(d1.x, d1.y, d1.z)
    modulo_b = f_magnitude(d2.x, d2.y, d2.z)

    d1.x = np.where(d1.x == 0, 0.0001, d1.x)
    d2.x = np.where(d2.x == 0, 0.0001, d2.x)
    phi_a = np.arctan(d1.y / d1.x) * c_todegree  # maxdif 0.03
    phi_b = np.arctan(d2.y / d2.x) * c_todegree


    phi_a_con = np.where(d1.x<0, phi_a + 180, phi_a)
    phi_b_con = np.where(d2.x<0, phi_b + 180, phi_b)

    theta_a = np.arccos(d1.z / modulo_a) * c_todegree  # maxdif 0.03
    theta_b = np.arccos(d2.z / modulo_b) * c_todegree

    dE = (d1.x - d2.x)**2 + (d1.y - d2.y)**2 + (d1.z - d2.z)**2

    # cleanup memory
    d1 = None
    d2 = None

    # logger.info("step 3 ok")
    p_theta_a = f_con(theta_a, 45, 135)
    p_theta_b = f_con(theta_b, 135, 135)

    p_phi_a_con = f_con(phi_a_con, 225, 315)
    p_phi_b_con = f_con(phi_b_con, 45, 225)

    magnitude = 255 * (p_theta_a + p_theta_b + p_phi_a_con + p_phi_b_con + dE) / 5
    magnitude_8bit = np.where(magnitude > 255, 255, magnitude).astype(np.uint8)
    change_map = magnitude_8bit > th
    #if DEBUG:
    #    print('debug: modulo_a')
    #    return(modulo_a, modulo_b, theta_a, theta_b, dE, p_theta_a, magnitude, change_map)
    #else:
    logger.info("3i3d mapping complete")
    return(magnitude_8bit, change_map)

# -- POSTPROCESSING ----------------------------------------------------------
def f_get_mask_pixel_filtering(raster_bool, band_name, par3):
    if type(raster_bool) == str:
        with rioxarray.open_rasterio(raster_bool) as f:
            data = f[band_name].data
            data = np.squeeze(data)
    elif type(raster_bool) == np.ndarray:
        data = raster_bool.astype(np.uint8)
        data = np.squeeze(data)
    else:
        raise NotImplementedError

    output = cv2.connectedComponentsWithStats(
        data)
    (numLabels, labels, stats, centroids) = output
    mask = np.zeros(data.shape, dtype="uint8") # empty mask

    counter = 0
    # label zero is the background
    for i in range(1, numLabels):
        counter += 1
        area = stats[i, cv2.CC_STAT_AREA]   #
        keepArea = area > par3['area_min_th'] and area < par3['area_max_th']
        if keepArea:
            mask[labels == i] = 1
        print("progress: {} / 100%".format(int((counter/numLabels) * 100), 2), end=" \r")
    return mask


def f_apply_raster_filter(par, region):
    path3 = par.path_data[region].sentinel2
    meta3 = par.n2000[region].meta3

    print("filtering forest anomalies")
    par3 = {
            'area_min_th': 10,   # pixel. Area: 100 (pixel) * 100 (m2 pixel) = 10000 (1 ha)
            'area_max_th': 5000,  # pixel. Area: 5000 (pixel) * 100 (m2 pixel) = 500000 (50 ha)
            }
    mask = f_get_mask_pixel_filtering(par.path_out[region].n2000, 'change_map', par3)

    # remove holes in forest anomalies by area
    print("filtering holes in forest anomalies")
    mask = mask.astype(np.int8)
    mask_inv = (mask * -1) + 1
    par3 = {
            'area_min_th': 0,   # Area: 100 (pixel) * 100 (m2 pixel) = 0 (0 ha)
            'area_max_th': 5000,  # pixel. Area: 50 (pixel) * 100 (m2 pixel) = 5000 (0.5 ha)
            }
    mask_hole   = f_get_mask_pixel_filtering(mask_inv, 'change_map', par3)
    change_mask = np.maximum(mask, mask_hole)

    # write output
    print("writing output to nc")
    reference = path3.pre
    path      = par.path_out[region].n2000
    group     = '/3i3d'
    data_dict = {'change_map_filtered': change_mask}
    f_write_nc(reference, path, group, data_dict, crs='epsg:4326', metadata_dict=meta3)


def polygonize(raster_path, band_name, out_path):
    # Read input band with Rasterio

    path_band = 'netcdf:' + raster_path + ':{}'.format(band_name)
    with rio.open(path_band) as src:
        crs = src.crs.to_wkt()
        src_band = src.read().astype(np.uint8)
        # Keep track of unique pixel values in the input band
        #unique_values = np.unique(src_band)
        # Polygonize with Rasterio. `shapes()` returns an iterable
        # of (geom, value) as tuples
        shapes = list(rasterio.features.shapes(src_band, transform=src.transform))


    shp_schema = {
        'geometry': 'Polygon',
        'properties': {}
    }

    # Get a list of all polygons for a given pixel value
    # and create a MultiPolygon geometry with shapely.
    # Then write the record to an output shapefile with fiona.
    # We make use of the `shape()` and `mapping()` functions from
    # shapely to translate between the GeoJSON-like dict format
    # and the shapely geometry type.
    #output_driver = 'ESRI Shapefile'
    output_driver = "GeoJSON"
    with fiona.open(out_path, 'w', output_driver, shp_schema, crs) as shp:
        polygons = [shape(geom) for geom, value in shapes
                    if value == 1]
        for pol in polygons:
            pol1 = Polygon(pol)
            if not pol1.is_valid:
                clean = pol1.buffer(0.0)
                if clean.is_valid and clean.geom_type == 'Polygon':
                    pol1 = clean
                else:
                    continue
            shp.write({
                'geometry': mapping(pol1),
                'properties': {}
            })




# -- PARAMETERIZATION --------------------------------------------------------
def f_get_parameters(mon_in):
    dir_data = '../data/'
    dir_parent = '../'
    data_rif = mon_in['data_rif']
    date_start = mon_in['data_ini_mon']
    date_end = mon_in['data_fin_mon']

    par = DD()
    par.region3 = { # unused. used for check purposes
            10: 'Umbria',
            12: 'Lazio'
            }
    code_region = int(mon_in['id_regione'])


    if not code_region in par.region3:
        raise NotImplementedError(f'Region with code {code_region} is not managed')

    # -- file check ------------------------
    # check if files exist
    in_name2 = mon_in['path_file_preprocessing'] # from post
    fname2 = os.listdir(dir_data)
    for x in in_name2:
        if x not in fname2:
            raise FileNotFoundError(f'{x} not found in data directory')

    # forest mask
    forest_mask_name = f'dati_aggiuntivi/STC_forest_mask_{code_region}.tif'
    path_forest_mask = os.path.join(dir_parent, forest_mask_name)

    # n2000 sites
    name_n2000_sites = f'dati_aggiuntivi/STC_N2000_sites_{code_region}.shp'
    path_n2000_sites = os.path.join(dir_parent, name_n2000_sites)

    # PMF export
    name_fmp = mon_in['path_file_fmp']  # from json request
    path_fmp = os.path.join(dir_data, name_fmp)

    for x in (path_fmp, path_n2000_sites, path_forest_mask):
        if not os.path.exists(x):
            raise FileNotFoundError(f'{x} not found')

    # --- sentinel2 -----------------------------
    fname2 = os.listdir(dir_data)
    years = []
    in_name2 = mon_in['path_file_preprocessing']
    for fn in in_name2:
        f1 = fn.split('_')
        if int(f1[2]) == code_region and f1[1] == 'PRE' and int(f1[5]) == 0 and fn.endswith('.nc'):
            years.append(int(f1[3][:4]))
    years = sorted(years)
    if len(years) != 3:
        raise Exception("Sentinel2 composites: found files (and years) != 3")
    par.last_year = years[-1]




    # ---------------------------------------
    # build path dictionary (input and output)
    region = code_region
    dir_tmp = dir_data + 'tmp/'
    dir_output = dir_data + 'output/'
    os.makedirs(dir_tmp, exist_ok=True)
    os.makedirs(dir_output, exist_ok=True)

    # OUTPUT PATHS
    par.path_out = DD()
    par.path_out[region] = DD()

    path_n2000  = dir_output + '{data_rif}_MON_{code_region}_{date_start}_{date_end}_0_1_ecological_disturbances.nc'
    path_alert  = dir_output + '{data_rif}_MON_{code_region}_{date_start}_{date_end}_0_1_alert.geojson'
    path_biodiv = dir_output + '{data_rif}_MON_{code_region}_{date_start}_{date_end}_0_1_nat2000.geojson'
    path_n2000  = path_n2000.format(data_rif  = data_rif, code_region = region, date_start = date_start, date_end = date_end)
    path_alert  = path_alert.format(data_rif  = data_rif, code_region = region, date_start = date_start, date_end = date_end)
    path_biodiv = path_biodiv.format(data_rif = data_rif, code_region = region, date_start = date_start, date_end = date_end)

    par.path_out[region].n2000  = path_n2000
    par.path_out[region].alert  = path_alert
    par.path_out[region].biodiv = path_biodiv

    # TEMPORARY FILE PATHS
    par.dir_tmp = dir_tmp
    par.path_tmp = DD()
    par.path_tmp[region] = DD()
    # forest disturbances
    par.path_tmp[region].n2000_geojson_epsg4326 = dir_tmp  + 'disturbances_epsg4326.geojson'  # not required
    par.path_tmp[region].n2000_geojson =  dir_tmp  + 'disturbances.geojson'


    # INPUT PATHS
    par.path_data = DD()
    par.path_data[region] = DD()
    par.path_data[region].fmp = path_fmp
    par.path_data[region].forest_mask = path_forest_mask
    par.path_data[region].n2000_sites = path_n2000_sites

    # sentinel2
    par.path_data[region].sentinel2 = DD()
    for fn in in_name2:
        f1 = fn.split('_')
        if int(f1[2]) == code_region and f1[1] == 'PRE' and int(f1[5]) == 0 and fn.endswith('.nc'):
            year = int(f1[3][:4])
            if year == par.last_year:
                par.path_data[region].sentinel2.post = dir_data + fn
            elif year == par.last_year - 1:
                par.path_data[region].sentinel2.now = dir_data + fn
            elif year == par.last_year - 2:
                par.path_data[region].sentinel2.pre = dir_data + fn
            else:
                raise NotImplementedError("no matching file in input")

    # OUTPUT METADATA FOR N2000 PRODUCT
    par.n2000 = DD()
    par.n2000[code_region] = DD()
    meta3 = dict() #                                  # metadata dictionary
    last_year = par.last_year
    meta3['change_map_filtered'] = {
            'short_name' : 'change map filtered',
            'long_name'  : 'filtered change map of land use change occurred between year {a} and year {b} according to the methodology developed by Francini et al. (2021)'.format(a=last_year-2, b=last_year-1),
            'ISTAT region code'     : code_region,
            'year'       : par.last_year - 1,
            'grid_mapping': 'spatial_ref',
            }
    meta3['magnitude'] = {
            'short_name' : 'magnitude',
            'long_name'  : 'magnitude of land use change occurred between year {a} and year {b} according to the methodology developed by Francini et al. (2021)'.format(a=last_year-2, b=last_year-1),
            'ISTAT region code'     : code_region,
            'year'       : par.last_year - 1,
            'grid_mapping': 'spatial_ref',
            }
    meta3['change_map'] = {
            'short_name' : 'change map',
            'long_name'  : 'change map of land use change occurred between year {a} and year {b} according to the methodology developed by Francini et al. (2021)'.format(a=last_year-2, b=last_year-1),
            'ISTAT region code'     : code_region,
            'year'       : par.last_year - 1,
            'grid_mapping': 'spatial_ref',
            }
    meta3['x'] = {
             'units'         : 'degrees_east'         ,
             'axis'          : 'X'                    ,
             'standard_name' : 'longitude'            ,
             'long_name'     : 'longitude coordinate' ,
            }
    meta3['y'] = {
             'units'         : 'degrees_north'        ,
             'axis'          : 'Y'                    ,
             'standard_name' : 'latitude'             ,
             'long_name'     : 'latitude coordinate'  ,
            }
    par.n2000[code_region].meta3 = meta3
    return par

class fake_logger():
    def info(self, x):
        print(x)


# -- MAIN FUNCTION -----------------------------------------------------------
def main(mon_input, my_logger):
        if TESTING == 1:
            pickle.dump(mon_input, open('mon_input.pkl', 'wb'))

        #global logger
        global logger
        logger = my_logger
        logger.info("reading parameters")

        par = f_get_parameters(mon_input)

        # -- LOGGING ---------------------------
        #logging.basicConfig(filename = par.log_path,
        #                    filemode = "w",
        #                    format = par.log_format,
        #                    level = logging.INFO)



        # -- N2000 -----------------------------
        # forest anomalies detection
        mon_start = datetime.now()
        mon_start_str = str(mon_start)
        logger.info("=== PROCESSING N2000 REQUEST ===")
        logger.info(f"start: {mon_start_str}")
        region = int(mon_input['id_regione'])
        fmask = par.path_data[region].forest_mask
        forest_mask = f_get_mask(fmask)
        in_path3 = {
                'pre': par.path_data[region].sentinel2.pre,
                'now': par.path_data[region].sentinel2.now,
                'post': par.path_data[region].sentinel2.post,
        }
        logger.info("data reading")
        data3, reference = f_get_dataset_nc_xarray(in_path3, forest_mask)
        logger.info("applying 3i3d algorithm")
        magnitude, change_map = f_3i3d(data3, 224)
        logger.info("writing 3i3d maps")

        name2 = ['magnitude', 'change_map']
        data3 = dict(zip(name2, [magnitude.astype(np.float32), change_map.astype(np.uint8)])) # data dictionary
        out_path = par.path_out[region].n2000
        meta3 = par.n2000[region].meta3
        if TESTING == 1:
            pickle.dump(reference, open('reference.pkl', 'wb'))
            pickle.dump(data3, open('data3.pkl', 'wb'))
            pickle.dump(meta3, open('meta3.pkl', 'wb'))
        f_write_nc(
                reference=reference,
                out_path=out_path,
                group='/3i3d',
                data_dict=data3,
                metadata_dict=meta3
                )
        logger.info("writing 3i3d maps complete")

        logger.info("post-processing: raster cleanup")
        # postprocessing: raster cleaning
        f_apply_raster_filter(par, region)

        logger.info("post-processing: polygonize")
        # polygonize
        polygonize(
                raster_path=par.path_out[region].n2000,
                band_name='change_map_filtered',
                out_path=par.path_tmp[region].n2000_geojson_epsg4326
                )

        # convert to epsg:3035 and compute area (m2)
        gdf = gpd.read_file(par.path_tmp[region].n2000_geojson_epsg4326)
        gdf.to_crs(epsg=3035, inplace=True)
        gdf['area_m2'] = gdf['geometry'].area
        gdf.to_json()
        gdf.to_file(
            par.path_tmp[region].n2000_geojson,
            driver='GeoJSON',
        )
        os.remove(par.path_tmp[region].n2000_geojson_epsg4326)  # cleanup temporary files
        logger.info("complete: monitoring of forest disturbances")

        # alert for forest disturbancies
        logger.info("start: forest cut alert")
        alert.add_alert_info(
            par.path_data[region].fmp,
            par.path_tmp[region].n2000_geojson,
            par.path_out[region].alert
        )
        logger.info("complete: forest cut alert")

        # biodiversity indicator (Nat2)
        logger.info("start: compute biodiversity indicator (Nat2)")
        rao_q_lin.main(
            raster_input      = par.path_data[region].sentinel2.now,
            n2000_input       = par.path_data[region].n2000_sites,
            forest_mask       = par.path_data[region].forest_mask,
            disturbances_mask = par.path_out[region].n2000,
            path_paf_export   = par.path_data[region].fmp,
            output_dir        = par.dir_tmp,
            path_nat2         = par.path_out[region].biodiv,
        )
        mon_end = datetime.now()
        mon_end_str = str(mon_end)
        duration = (mon_end - mon_start).total_seconds()
        logger.info(f"end: {mon_end_str}")
        logger.info(f"monitor process duration: {duration} seconds")
        logger.info("! All processes are complete")
        return (0)







