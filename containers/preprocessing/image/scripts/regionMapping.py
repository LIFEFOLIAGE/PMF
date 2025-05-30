def regionMapping(idRegion=None):
    regions = {"01": "piemonte",
            "02": "valle d'aosta",
            "03": "lombardia",
            "04": "trentino-alto adige",
            "05": "veneto",
            "06": "friuli venezia giulia",
            "07": "liguria",
            "08": "emilia-romagna",
            "09": "toscana",
            "10": "umbria",
            "11": "marche",
            "12": "lazio",
            "13": "abruzzo",
            "14": "molise",
            "15": "campania",
            "16": "puglia",
            "17": "basilicata",
            "18": "calabria",
            "19": "sicilia",
            "20": "sardegna"}
    if idRegion != None: 
        return regions[idRegion] 
    return regions
    