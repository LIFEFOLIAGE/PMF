# ref: https://github.com/AndreaTassi23/spectralrao-monitoring.git
# licence: none
# from rasterstats import zonal_stats



import numpy as np
import pandas as pd
import math
from itertools import combinations
import rasterio
from rasterio.merge import merge
#import xarray as xr
import rioxarray
import os
import copy
from rasterio.mask import mask as rio_mask
import geopandas as gpd
import ray
from rasterstats import zonal_stats
from tqdm import tqdm
from rasterio.warp import calculate_default_transform, reproject, Resampling
import multiprocessing
import psutil


TEST = False


# --- RAO Q ---
# From https://github.com/mmadrz/PaRaVis.git

# Write the computation output to a GeoTIFF file
def export_geotiff(naip_meta, output_rao, output_path):
    naip_meta["count"] = 1
    naip_meta["dtype"] = "float64"
    with rasterio.open(output_path, "w", **naip_meta) as dst:
        dst.write(output_rao, 1)


# Compute Euclidean distance between two vectors
def euclidean_dist(pair_list):
    #return math.sqrt((x[0] - x[1]) ** 2)
    return math.sqrt(sum([(x[0] - x[1]) ** 2 for x in pair_list]))


# Compute Manhattan distance between two vectors
def manhattan_dist(pair_list):
    return sum([abs(x[0] - x[1]) for x in pair_list])

# Compute Chebyshev distance between two vectors
def chebyshev_dist(pair_list):
    return max([abs(x[0] - x[1]) for x in pair_list])

# Compute Jaccard distance between two vectors
def jaccard_dist(pair_list):
    dists = []
    for x in pair_list:
        numerator = min(x[0], x[1])
        denominator = max(x[0], x[1])
        dists.append(1 - (numerator / denominator))
    return sum(dists)

# Compute canberra distance between two vectors
def canberra_dist(pair_list):
    dists = []
    for x in pair_list:
        numerator = abs(x[0] - x[1])
        denominator = abs(x[0]) + abs(x[1])
        dists.append(numerator / denominator)
    return sum(dists)

# Compute Minkowski distance between two vectors with parameter p
def minkowski_dist(pair_list, p_minkowski):
    return sum(
        [(abs(x[0] - x[1]) ** p_minkowski) ** (1 / p_minkowski) for x in pair_list]
    )



# Convert TIFF input(s) to NumPy array
def tiff_to_np(tiff_input):
    matrix1 = tiff_input.read()
    matrix1 = matrix1.reshape((matrix1.shape[1]), matrix1.shape[2])
    minNum = -999
    matrix1[matrix1 == minNum] = np.nan
    return matrix1


def extract_win_1d(data1d, row, col, shape1, window, width):
    data = []
    for i in range(window):
        row1d_index = (row + i - width) * shape1
        start = row1d_index + col - width
        end =  row1d_index + col + width + 1
        data.append(data1d[start:end])
    return np.concatenate(data)


@ray.remote
def compute_raoq_range(
    row_start,
    row_end,
    col_start,
    col_end,
    data1d,
    shape1,
    window,
    distance_m,
    na_tolerance,
):
    width = int(
        (window - 1) / 2
    )  # Number of neighbors from the central pixel to the edge of the window
    raoq_values = []  # Initialize a list to store computed Rao's Q values


    # iterate through rows and columns
    for rw in range(row_start, row_end):
        for cl in range(col_start, col_end):

            # Create a list of border condition results for all input arrays
            #data1d = trastersm_list.flatten()
            data = [extract_win_1d(data1d, rw, cl, shape1, window, width)]

            borderCondition = (
                np.sum(np.invert(np.isnan(data)))
                < np.power(window, 2) - ((np.power(window, 2)) * na_tolerance)
            )

            # Check if any array satisfies the border condition
            if borderCondition:
                raoq_values.append(np.nan)
            else:
                # Extract sub-windows for all input arrays

                # Generate combinations of sub-window pairs
                vcomb = list(
                    combinations(range(data[0].shape[0]), 2)
                )
                lpair2 = np.take(data, vcomb).tolist()
                vout = [euclidean_dist([x]) for x in lpair2]



                # Calculate  selected distances for all sub-window pairs
                #vout = []
                #check = []
                #for comb in vcomb:
                #    lpair = [[x[comb[0]], x[comb[1]]] for x in lv]
                #    check.append(lpair)
                #    if distance_m == "euclidean":
                #        out = euclidean_dist(lpair)
                #    elif distance_m == "manhattan":
                #        out = manhattan_dist(lpair)
                #    elif distance_m == "chebyshev":
                #        out = chebyshev_dist(lpair)
                #    elif distance_m == "canberra":
                #        out = canberra_dist(lpair)
                #    elif distance_m == "Jaccard":
                #        out = jaccard_dist(lpair)
                #    vout.append(out)

                # Rescale the computed distances and calculate Rao's Q value
                vout_rescaled = [x * 2 for x in vout]
                vout_rescaled[:] = [x / window**4 for x in vout_rescaled]
                raoq_value = np.nansum(vout_rescaled)
                raoq_values.append(raoq_value)

    # Return the results for the specified row and column range
    return row_start, row_end, col_start, col_end, raoq_values

def parallel_raoq(
    data_input,
    output_path,
    distance_m="euclidean",
    window=9,
    na_tolerance=0.0,
    batch_size=100,
):
    if window % 2 == 1:
        w = int((window - 1) / 2)
    else:
        raise Exception(
            "The size of the moving window must be an odd number. Exiting..."
        )

    # Convert input data to NumPy arrays
    numpy_data = [tiff_to_np(data) for data in data_input]

    # Initialize raoq array with NaN values
    raoq = np.zeros(shape=numpy_data[0].shape)
    raoq[:] = np.nan

    # Create a list of transformed arrays for each input
    trastersm_list = []
    for mat in numpy_data:
        trasterm = np.zeros(shape=(mat.shape[0] + 2 * w, mat.shape[1] + 2 * w))
        trasterm[:] = np.nan
        trasterm[w : w + mat.shape[0], w : w + mat.shape[1]] = mat
        trastersm_list.append(trasterm)

    # Adjust batch size to fit all pixels
    max_rows = numpy_data[0].shape[0] - 2 * w + 1
    max_cols = numpy_data[0].shape[1] - 2 * w + 1
    batch_size = min(batch_size, max_rows, max_cols)

    # Adjust row and column batches
    rows = numpy_data[0].shape[0]
    cols = numpy_data[0].shape[1]
    row_batches = range(w, rows + w, batch_size)
    col_batches = range(w, cols + w, batch_size)

    # Adjust the last batch
    row_batches = list(row_batches)
    col_batches = list(col_batches)
    if row_batches[-1] != rows + w:
        row_batches.append(rows + w)
    if col_batches[-1] != cols + w:
        col_batches.append(cols + w)

    data1d = trastersm_list[0].flatten()
    shape1 = trastersm_list[0].shape[1]
    # Use Ray to parallelize the computation
    ray_results = []
    for row_start, row_end in zip(row_batches[:-1], row_batches[1:]):
        for col_start, col_end in zip(col_batches[:-1], col_batches[1:]):
            pixel_data = (
                row_start,
                row_end,
                col_start,
                col_end,
                data1d,
                shape1,
                window,
                distance_m,
                na_tolerance,
            )
            # ray_results.append(compute_raoq_range(*pixel_data))
            ray_results.append(compute_raoq_range.remote(*pixel_data))


    # Update raoq array with the computed values
    with tqdm(total=len(ray_results)) as pbar:
        for result in ray_results:
            row_start, row_end, col_start, col_end, raoq_values = ray.get(result)
            raoq[
                row_start - w : row_end - w, col_start - w : col_end - w
            ] = np.array(raoq_values).reshape(
                row_end - row_start, col_end - col_start
            )
            pbar.update(1)

    # Export the computed Rao's Q index as a TIFF file
    info = data_input[0].profile
    print(f'exporting: {output_path}')
    export_geotiff(info, raoq, output_path)


def apply_raoq(
    data_input,
    output_path  = "test_raoq.tif",
    distance_m   = "euclidean",
    window       = 3,
    na_tolerance = 0,
    batch_size   = 100,
):
    # Initialize Ray
    # options=["euclidean", "manhattan", "chebyshev", "Jaccard", "canberra", "minkowski"],
    #     description="Batch size:", min=10, max=10000, step=10, value=100
    #     description="NA Tolerance:", min=0, max=1, step=0.1, value=0.0
    # window = widgets.BoundedIntText(description="Window:", min=1, max=333, step=2, value=3)

    parallel_raoq(
        data_input   = data_input,
        output_path  = output_path,
        distance_m   = distance_m,
        window       = window,
        na_tolerance = na_tolerance,
        batch_size   = batch_size,
    )

def reproject_geotiff(path_input, path_output, dst_crs):
    #dst_crs = 'EPSG:4326'
    with rasterio.open(path_input) as src:
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds)
        kwargs = src.meta.copy()
        kwargs.update({
            'crs': dst_crs,
            'transform': transform,
            'width': width,
            'height': height
        })

        with rasterio.open(path_output, 'w', **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.nearest)
    return


def batch_clip_raster(src_vector, path_raster, id_field, prefix, output_dir):
    output_dict = dict()
    #src_vector = gpd.read_file(path_vector)
    n2000_len = len(src_vector)
    with rasterio.open(path_raster) as src_raster:
        for ix in range(n2000_len):
            coords = [src_vector.iloc[ix]['geometry']]
            code = src_vector.iloc[ix][id_field]
            clipped_array, clipped_transform = rio_mask(
                dataset=src_raster,
                shapes=coords,
                crop=True
            )
            out_meta = src_raster.meta.copy()
            out_meta.update({"driver": "GTiff",
                             "height": clipped_array.shape[1],
                             "width": clipped_array.shape[2],
                             "transform": clipped_transform})
            out_path = f"{output_dir}/{prefix}_{code}.tif"
            with rasterio.open(out_path, "w", **out_meta) as dest:
                dest.write(clipped_array)
            output_dict[code] = out_path
    return output_dict


def extract_stats_dict(
    stats,    # stats from zonal_stats
    keys,     # filed names in zonal_stats
    keys_new  # new field names
):
    stats1 = [x['properties'] for x in stats]
    stat_filt2 = []
    for stat11 in stats1:
        s_filt = dict(zip(keys_new, [stat11[k] for k in keys]))
        stat_filt2.append(s_filt)
    return stat_filt2


def main(
    raster_input,
    n2000_input,
    forest_mask,
    disturbances_mask,
    path_paf_export,
    output_dir,
    path_nat2,
):
    # get n2000 bounding box (1 for each n2000)
    n2000_gpd = gpd.read_file(n2000_input)
    n2000_bbox = copy.deepcopy(n2000_gpd)
    n2000_bbox.geometry = (
        n2000_gpd
        .buffer(20, cap_style='square')  # add 10 meters to each side of the bounding box
        .envelope  # each row is the bounding box of the n2000 shapefile
    )


    # BUILD NDVI IMAGE
    # required workaround to fix metadata
    p_tmp = f"{output_dir}tmp.tif"
    with rioxarray.open_rasterio(raster_input) as src:
        b4 = src['B4']
        b4.rio.to_raster(p_tmp)
    with rasterio.open(p_tmp) as src:
        meta = src.meta
        os.remove(p_tmp)
    with rioxarray.open_rasterio(raster_input) as f:
        red = np.squeeze(f['B4'].data.astype(np.float32))
        ired = np.squeeze(f['B8'].data.astype(np.float32))
    ndvi_arr = (ired - red) / (ired + red)
    meta.update(
        dtype=rasterio.float32,
        driver='GTiff',
    )
    # apply forest mask to ndvi
    with rasterio.open(forest_mask) as src:
        mask = src.read(1)
    ndvi_arr[mask == 0] = np.nan
    ndvi_arr = np.expand_dims(ndvi_arr, axis=0)
    output_path_ndvi = f'{output_dir}tmp_ndvi.tif'
    with rasterio.open(output_path_ndvi, 'w', **meta) as dst:
        dst.write(
            ndvi_arr,
        )

    # REPROJECT NDVI IMAGE TO EPSG:3035
    rds = rioxarray.open_rasterio(output_path_ndvi)
    rds_3035 = rds.rio.reproject("EPSG:3035")
    rds.close()
    rds_3035.rio.to_raster(output_path_ndvi)
    rds_3035.close()

    # CLIP NDVI IMAGE FOR EACH N2000 SITE
    ndvi3 = dict()
    n2000_len = len(n2000_bbox)
    with rasterio.open(output_path_ndvi) as ndvi_rio:
        for ix in range(n2000_len):
            coords = [n2000_bbox.iloc[ix]['geometry']]
            code = n2000_bbox.iloc[ix]['codice']
            clipped_array, clipped_transform = rio_mask(
                dataset=ndvi_rio,
                shapes=coords,
                crop=True
            )
            out_meta = ndvi_rio.meta.copy()
            out_meta.update({"driver": "GTiff",
                             "height": clipped_array.shape[1],
                             "width": clipped_array.shape[2],
                             "transform": clipped_transform})
            out_path = f"{output_dir}tmp_ndvi_{code}.tif"
            with rasterio.open(out_path, "w", **out_meta) as dest:
                dest.write(clipped_array)
            ndvi3[code] = out_path
    os.remove(output_path_ndvi)

    # COMPUTE RAOQ FOR EACH N2000 SITE
    # parallel processing
    num_cpus = multiprocessing.cpu_count() - 2  # leave 2 cpus for other processes
    num_cpus = min(num_cpus, 1)

    ram_avail = psutil.virtual_memory().available - 4 * 10**9  # leave 2 GB for other processes
    ram_avail = min(ram_avail, 2 * 10**9)

    ray.init(
        num_cpus=num_cpus, object_store_memory= ram_avail
    )
    raoq3 = dict()

    cnt = 0
    for key in sorted(ndvi3.keys()):
        cnt += 1
        if TEST and cnt > 4:
            break
        ndvi_path = ndvi3[key]
        output_path_rao = f"{output_dir}tmp_raoq_{key}.tif"
        with rasterio.open(ndvi_path) as src:
            apply_raoq(
                data_input   = [src],
                output_path  = output_path_rao,
                distance_m   = "euclidean",
                window       = 3,
                na_tolerance = 0,
                batch_size   = 100,
            )
        raoq3[key] = output_path_rao
    # Shutdown Ray
    ray.shutdown()

    # MERGE BIODIV
    biodiv2 = []
    init = True
    for x in raoq3:
        path_raoq = raoq3[x]
        src = rasterio.open(path_raoq)
        biodiv2.append(src)
        if init:
            init = False
            out_meta = src.meta
    mosaic, out_trans = merge(biodiv2, method="max")
    out_meta.update({"driver": "GTiff",
                     "height": mosaic.shape[1],
                     "width": mosaic.shape[2],
                     "transform": out_trans,
                     #           "crs": "+proj=utm +zone=35 +ellps=GRS80 +units=m +no_defs "
                     }
    )
    path_raoq_mosaic = f"{output_dir}tmp_raoq_mosaic.tif"
    with rasterio.open(path_raoq_mosaic, "w", **out_meta) as dest:
        dest.write(mosaic)

    # GET RASTER STATISTICS
    '''
    id_sito
    nome_sito
    sup_sito
    sup_boschiva
    perc_dist
    perc_tagli
    indice_biodiv
    '''
    # --- RAO Q ---
    stats = zonal_stats(
        n2000_input,
        path_raoq_mosaic,
        affine=src.transform,
        stats=['mean'],
        geojson_out=True,
    )
    keys = ['codice', 'denominazi', 'mean']
    keys_new = ['id_sito', 'nome_sito', 'indice_biodiv']
    raoq_stat2 = extract_stats_dict(stats, keys, keys_new)
    del stats

    # --- FOREST AREA ---
    path_fmask_3035 = f"{output_dir}tmp_fmask_3035.tif"
    reproject_geotiff(forest_mask, path_fmask_3035, 'EPSG:3035')
    with rasterio.open(path_fmask_3035) as src:
        pixel_m2 = src.res[0] * src.res[1]
    stats = zonal_stats(
        n2000_input,
        path_fmask_3035,
        affine=src.transform,
        stats=['sum'],
        geojson_out=True,
    )
    keys = ['codice', 'sum']
    keys_new = ['id_sito', 'sup_boschiva']
    tmp_fmask_stat2 = extract_stats_dict(stats, keys, keys_new)
    fmask_stat2 = []
    for x in tmp_fmask_stat2:
        x['sup_boschiva'] = x['sup_boschiva'] * pixel_m2
        fmask_stat2.append(x)

    # --- TOTAL AREA ---
    n2000_gpd = gpd.read_file(n2000_input)
    n2000_gpd['sup_sito'] = n2000_gpd.area
    df_base = n2000_gpd[['codice', 'sup_sito']]

    # --- MERGE STATISTICS (init) ---
    df_forest_area = pd.DataFrame(fmask_stat2)
    df_raoq = pd.DataFrame(raoq_stat2)

    df = df_base.merge(df_forest_area, right_on='id_sito', left_on='codice', how='outer')
    df = df.merge(df_raoq, on='id_sito', how='outer')
    df = df[['id_sito', 'nome_sito', 'sup_sito', 'sup_boschiva', 'indice_biodiv']]

    # --- DISTURBANCES STATISTICS ---
    p_tmp = "{output_dir}tmp.tif"
    path_dist_3035 = f"{output_dir}tmp_dist_3035.tif"
    with rioxarray.open_rasterio(disturbances_mask) as src:
        change_map = src['change_map_filtered']
        change_map.rio.to_raster(p_tmp)
        affine = src.rio.transform()
    reproject_geotiff(p_tmp, path_dist_3035, 'EPSG:3035')
    stats = zonal_stats(
        n2000_input,
        path_dist_3035,
        affine=affine,
        stats=['sum'],
        geojson_out=True,
    )
    tmp_stats2 = extract_stats_dict(stats, ['codice', 'sum'], ['id_sito', 'dist_area'])
    stats_dist2 = []
    with rasterio.open(path_dist_3035) as src:
        pixel_m2 = src.res[0] * src.res[1]
        for x in tmp_stats2:
            x['dist_area'] = x['dist_area'] * pixel_m2
            stats_dist2.append(x)
    df_dist = pd.DataFrame(stats_dist2)

    # --- PAF STATISTICS ---
    # based on declared area
    fmp_data = gpd.read_file(path_paf_export)
    fmp_data = fmp_data.set_crs('EPSG:3035',  allow_override=True)

    if 'AREA_TOT_DECLARED' not in fmp_data.columns:
        fmp_data['AREA_TOT_DECLARED'] = 0

    if len(fmp_data) == 0:
        df['perc_tagli'] = 0
    else:
        gdf_n2000 = gpd.read_file(n2000_input)
        fmp_data_intersect = gpd.sjoin(fmp_data, gdf_n2000, how='inner', predicate='intersects')
        df_paf = fmp_data_intersect.pivot_table(index='codice', values='AREA_TOT_DECLARED', aggfunc='sum')
        df = df.merge(df_paf, left_on='id_sito', right_index=True, how='outer')
        df['perc_tagli'] = (df['AREA_TOT_DECLARED'] / df['sup_boschiva']) * 100

    # --- MERGE STATISTICS (final) ---
    df = df.merge(df_dist, on='id_sito', how='outer')
    df['perc_dist'] = (df['dist_area'] / df['sup_boschiva']) * 100
    df['sup_sito'] = df['sup_sito'] / 10**6
    df['sup_boschiva'] = df['sup_boschiva'] / 10**6


    field2 = ['id_sito', 'nome_sito', 'sup_sito', 'sup_boschiva', 'perc_dist', 'perc_tagli', 'indice_biodiv']
    df = df[field2]

    # --- BUILD and EXPORT GEOJSON ---
    gdf_n2000 = gpd.read_file(n2000_input, columns=['codice', 'geometry'])
    gdf_n2000_indices = gdf_n2000.merge(df, left_on='codice', right_on='id_sito', how='outer')
    gdf_n2000_indices = gdf_n2000_indices.drop(columns='codice')
    gdf_n2000_indices.to_file(path_nat2, driver='GeoJSON')


if __name__ == "__main__":
    output_dir   = "/home/alessandro/aa/00",
    path_nat2  = f"{output_dir}/nat2.geojson",
    main(
        raster_input = "/home/alessandro/aa/research/2024/prj_life-foliage/actions/B1/eop_dataset/20241001101438_PRE_10_20220601_20220930_1_1_R.nc",
        n2000_input  = "/home/alessandro/aa/research/2024/prj_life-foliage/actions/B1/eop_dataset/other_data/n2000/N2000_umbria.shp",
        forest_mask  = "/home/alessandro/aa/research/2024/prj_life-foliage/actions/B1/eop_v4/docker/dati_aggiuntivi/STC_forest_mask_10.tif",
        disturbances_mask = '/home/alessandro/aa/research/2024/prj_life-foliage/code/alert/docker/data/20240809101100_MON_10_20210601_20230930_0_1_N2000.nc',
        path_paf_export = "/home/alessandro/aa/research/2024/prj_life-foliage/code/alert/docker/data/20240809101100_MON_10_20210601_20230930_0_1_N2000_epsg3035_alert.geojson",
        output_dir   = "/home/alessandro/aa/00/",
        path_nat2 = path_nat2,
    )
