# add information from the FMP to the EOP result
import geopandas as gpd
import copy

'''
casistiche incluse:
- più pratiche amministrative, sopra o sotto soglia possono possono essere incluse in un unico poligono
- superficie del progetto gis può scostarsi da quella dichiarata
'''


# fieldnames FMP point

def add_alert_info(path_fmp, path_eop_result, path_out_alert):
    '''
    input and output geojson are in epsg 3035
    '''
    dict_fmp_intersect = {}
    record_intersection = {
        'ID_FMP': '',
        'AREA_TOT_DECLARED': 0.0,
        'AREA_TOT_INTERSECT': 0.0,
        'AREA_TOT_REQUESTED': 0.0,
        'AMM_TYPE': 0,  # 0: no amm, 1: pratiche sotto soglia, 2: altre pratiche, 3: mix pratiche (tipo 1 e 2)
    }

    # LOAD FMP DATA
    fmp_data = gpd.read_file(path_fmp)

    # check if fmp_data is is empty
    if len(fmp_data) == 0:
        eop_in = gpd.read_file(path_eop_result)
        eop_in['ID_EOP'] = eop_in.index.astype(str)
        eop_in['AREA_EOP'] = eop_in.area
        eop_in = eop_in[['ID_EOP', 'AREA_EOP', 'geometry']]
        eop_in['ID_FMP'] = ''
        eop_in['AREA_TOT_DECLARED'] = 0.0
        eop_in['AREA_TOT_INTERSECT'] = 0.0
        eop_in['AREA_TOT_REQUESTED'] =  0.0
        eop_in['AMM_TYPE'] = 0  # 0: no amm, 1: pratiche sotto soglia, 2: altre pratiche, 3: mix pratiche (tipo 1 e 2)
        eop_in['ALERT'] = -1  # No FMP data
        eop_in.to_file(
            path_out_alert,
            driver='GeoJSON',
        )
        return




    fmp_data = fmp_data.set_crs('EPSG:3035',  allow_override=True)
    fmp_data.rename(columns={
        'superficie_utile': 'AREA_DECLARED',
        'codi_ista': 'ID_FMP',
    }, inplace=True)
    fmp_data['AREA_DECLARED'] = fmp_data['AREA_DECLARED'].astype(float)

    fmp_polygon = fmp_data[fmp_data['geometry'].geom_type == 'Polygon']
    fmp_point = fmp_data[fmp_data.geometry.type=="Point"]
    fmp_polygon = fmp_polygon.assign(AREA_PROJECT_MAP=fmp_polygon.area)

    # LOAD EOP RESULTS
    eop_in = gpd.read_file(path_eop_result)
    eop_in['ID_EOP'] = eop_in.index.astype(str)
    eop_in['AREA_EOP'] = eop_in.area
    eop_in = eop_in[['ID_EOP', 'AREA_EOP', 'geometry']]


    # FILTER: only the FMP points that intersect with the EOP
    fmp_point = gpd.sjoin(fmp_point, eop_in, how='inner', predicate='intersects')

    # INTERSECTION: only the FMP polygons that intersect with the EOP
    fmp_polygon = gpd.overlay(fmp_polygon,eop_in)
    fmp_polygon['AREA_PROJECT_INTERSECT'] = fmp_polygon.area

    # CONVERT TO DICT
    fmp_point3 = fmp_point.to_dict(orient='records')
    fmp_polygon3 = fmp_polygon.to_dict(orient='records')

    # CREATE EMPTY COLUMNS IN EOP
    eop_in['ID_FMP'] = ''
    eop_in['AREA_TOT_DECLARED'] = 0.0
    eop_in['AREA_TOT_INTERSECT'] = 0.0
    eop_in['AREA_TOT_REQUESTED'] =  0.0
    eop_in['AMM_TYPE'] = 0  # 0: no amm, 1: pratiche sotto soglia, 2: altre pratiche, 3: mix pratiche (tipo 1 e 2)
    eop_in['ALERT'] = 0  # 0: no amm, 1: pratiche sotto soglia, 2: altre pratiche, 3: mix pratiche (tipo 1 e 2)


    # UNION OF FMP POLYGONS AND POINTS
    # get intersect info from fmp points
    for pt1 in fmp_point3:
        id_eop = pt1['ID_EOP']
        id_fmp = pt1['ID_FMP']
        if not id_eop in dict_fmp_intersect:
            dict_fmp_intersect[id_eop] = copy.deepcopy(record_intersection)
        dict_fmp_intersect[id_eop]['ID_FMP'] += id_fmp + ','
        dict_fmp_intersect[id_eop]['AREA_TOT_DECLARED'] += pt1['AREA_DECLARED']
        match(dict_fmp_intersect[id_eop]['AMM_TYPE']):
            case 0:
                dict_fmp_intersect[id_eop]['AMM_TYPE'] = 1
            case 2:
                dict_fmp_intersect[id_eop]['AMM_TYPE'] = 3
            case _:
                pass
    for pol1 in fmp_polygon3:
        id_eop = pol1['ID_EOP']
        id_fmp = pol1['ID_FMP']
        if not id_eop in dict_fmp_intersect:
            dict_fmp_intersect[id_eop] = copy.deepcopy(record_intersection)
        dict_fmp_intersect[id_eop]['ID_FMP'] += id_fmp + ','
        dict_fmp_intersect[id_eop]['AREA_TOT_INTERSECT'] += pol1['AREA_PROJECT_INTERSECT']
        match(dict_fmp_intersect[id_eop]['AMM_TYPE']):
            case 0:
                dict_fmp_intersect[id_eop]['AMM_TYPE'] = 2
            case 1:
                dict_fmp_intersect[id_eop]['AMM_TYPE'] = 3
            case _:
                pass

    # CLEAN UP AND COMPUTE TOTAL REQUESTED AREA
        dict_fmp_intersect[key]['AREA_TOT_REQUESTED'] = dict_fmp_intersect[key]['AREA_TOT_INTERSECT'] + dict_fmp_intersect[key]['AREA_TOT_DECLARED']

    # ADD INFO TO EOP
    for key in dict_fmp_intersect:
        eop_in.loc[eop_in['ID_EOP'] == key, 'ID_FMP'] = dict_fmp_intersect[key]['ID_FMP']
        eop_in.loc[eop_in['ID_EOP'] == key, 'AREA_TOT_DECLARED'] = dict_fmp_intersect[key]['AREA_TOT_DECLARED']
        eop_in.loc[eop_in['ID_EOP'] == key, 'AREA_TOT_INTERSECT'] = dict_fmp_intersect[key]['AREA_TOT_INTERSECT']
        eop_in.loc[eop_in['ID_EOP'] == key, 'AREA_TOT_REQUESTED'] = dict_fmp_intersect[key]['AREA_TOT_REQUESTED']
        eop_in.loc[eop_in['ID_EOP'] == key, 'AMM_TYPE'] = dict_fmp_intersect[key]['AMM_TYPE']

        area_eop = eop_in.loc[eop_in['ID_EOP'] == key, 'AREA_EOP'].iloc[0]
        area_diff = area_eop - dict_fmp_intersect[key]['AREA_TOT_REQUESTED']
        # ADD ALERT INFO TO EOP
        # 0: difference between EOP and authorized cut area is less than 1000 m2 or 5% of the authorized cut area
        # 1: difference between EOP and authorized cut area is more than 1000 m2 and 5% of the authorized cut area
        # 2: no authorization for the cut
        #if dict_fmp_intersect[key]['AMM_TYPE'] > 0:

        # in this loop every record has an authorization
        # code 0: no alert
        if area_diff < 1000 or area_diff < (0.05 * area_eop):
            eop_in.loc[eop_in['ID_EOP'] == key, 'ALERT'] = 0
        # code 1: low alert
        elif (area_diff >= 1000 or area_diff >= (0.05 * area_eop)) and (area_diff < 10000 or area_diff < (0.20 * area_eop)):
            eop_in.loc[eop_in['ID_EOP'] == key, 'ALERT'] = 1
        # code 2: intermediate alert
        else:
            eop_in.loc[eop_in['ID_EOP'] == key, 'ALERT'] = 2

    # code 2: intermediate alert; there is no authorization
    eop_in.loc[eop_in['AMM_TYPE'] == 0, 'ALERT'] = 3

    # SAVE EOP ALERT
    eop_in.to_file(
        path_out_alert,
        driver='GeoJSON',
    )



if __name__ == '__main__':
    path_fmp = '/home/alessandro/aa/01/tmp/preelaborazione.geojson'
    path_eop_result = '/home/alessandro/aa/research/2024/prj_life-foliage/code/alert/docker/data/20240809101100_MON_10_20210601_20230930_0_1_N2000_epsg3035_alert_umbria.geojson'
    path_out_alert = '/home/alessandro/aa/00/20240809101100_MON_10_20210601_20230930_0_1_N2000_epsg3035_alert.geojson'
    add_alert_info(
        path_fmp,
        path_eop_result,
        path_out_alert
    )
