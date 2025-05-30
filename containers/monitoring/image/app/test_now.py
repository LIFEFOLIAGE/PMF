# TESTING EOP PROCESSING
# ABILITARE VPN
import requests
r = requests.post('http://127.0.0.1:8000/monitor',
        json={
            'data_rif': '20220714160912',
            'id_regione': 10,
            'data_ini_mon': '20210601',
            'data_fin_mon': '20210831',
            'path_file_preprocessing': [
                '20241001101438_PRE_10_20220601_20220930_0_1_R.nc',
                '20241001101438_PRE_10_20230601_20230930_0_1_R.nc',
                '20241001101438_PRE_10_20240601_20240930_0_1_R.nc',
            ],
            'path_file_fmp': 'fmp_export_test.geojson',
            'tipo_algoritmo': 0,
            'monitor_tagli_boschivi': True,
            'monitor_alert_tagli_boschivi': True,
            'monitor_natura_2000': True
            }
        )
print(r.json())
