
import os
import time
from typing import Union
import json
import logging
import requests
import hashlib
from osgeo import gdal
import fiona
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape
import concurrent.futures
import threading

from .regionMapping import regionMapping

thread_local = threading.local()

def executeDownload(region: str, config, startDateRef:str, startDate:str, endDate:str) -> tuple[int,int]:
	"""download S2 files from ESA copernicus hub

	Args:
		region (str): id of region to process
		config (configparser.ConfigParser): config file with query info and folder to save files
		startDateRef (str): pipline start time
		startDate (str): download images starting at startDate, format: yyyymmdd
		endDate (str): download images until endDate, format: yyyymmdd

	Raises:
		ValueError: no products to download if api returns an empty list

	Returns:
		int: number of products downloaded (present in output directory)
		int: total number of products to download
	"""
	# create logger
	global logger 
	logger = logging.getLogger('{}'.format(startDateRef))

	# copernicus download parameters
	cloudmin = config['download']['CLOUDMIN']
	cloudmax = config['download']['CLOUDMAX']
	geojsonDir = config['project']['GEOJSONDIR']
	outputDir = config['project']['OUTPUTDIR']
	inputDir = os.path.join(config['project']['OUTPUTDIR'], 'input')
	tiles = config[region]['TILES'].split(',')
	year = startDate[:4]
	VP = 1 # algorithm version, hardcoded at the moment

	assert os.path.exists(os.path.join(geojsonDir, '{}_convexhull_epsg_4326.geojson'.format(region))), \
		'convexhull for region {} does not exist in {}. \nPlease create with getRegionGeojsons.py'.format(
			region.capitalize(), geojsonDir)
	convexhullFile = os.path.join(
		geojsonDir, '{}_convexhull_epsg_4326.geojson'.format(region))

	# logging
	logger.info(
		'####Life Foliage: Sentinel-2 data download started for region {} ({}) {} ####'.format(region, regionMapping(region).capitalize(), year))

	# footprint for download
	with fiona.open(convexhullFile) as f:
		if len(list(f)) == 1:
			pol = next(iter(f))
			footprint = str(shape(pol["geometry"])) 

	logger.info("footprint is...\n{}".format(footprint))

	# build query
	url = "https://catalogue.dataspace.copernicus.eu/odata/v1"
	qArea = f"OData.CSC.Intersects(area=geography'SRID=4326;{footprint}')"
	qTimerange = f"ContentDate/Start gt {year}-{startDate[4:6]}-{startDate[6:8]}T00:00:00.000Z and ContentDate/End lt {endDate[:4]}-{endDate[4:6]}-{endDate[6:8]}T23:59:59.999Z"
	qCollection = f"Collection/Name eq 'SENTINEL-2'"
	qProductType = f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A')"
	qCloudCover = f"Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value ge {cloudmin}) and Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value le {cloudmax})"
	qAttributes = "&$expand=Attributes"
	qOrderby = "&$orderby=ContentDate/Start asc"
	query = url + "/Products?$filter=" \
		+ qArea + " and " + qTimerange + " and " + qCollection \
		+ " and " + qProductType + " and " + qCloudCover + qOrderby  + qAttributes
	
	# run query
	jsonOut = runQuery(query)
	gdf = pd.DataFrame.from_dict(jsonOut['value'])

	# NOTE: results are paginated, repeat query until we have all data
	while '@odata.nextLink' in jsonOut:
		jsonOut = runQuery(jsonOut['@odata.nextLink'])
		dfNew = pd.DataFrame.from_dict(jsonOut['value'])
		gdf = pd.concat([gdf, dfNew], ignore_index=True)
	

	if len(gdf) == 0:
		logger.error("No products covers the region in the range {}-{}.".format(startDate, endDate))
		raise ValueError('No products to download')

	# IMAGES SELECTION
	# subset products on main tiles
	gdf['Tile'] = gdf["Name"].apply(lambda x: x.split("_")[5])

	gdfSubTiles =gdf[gdf['Tile'].isin(tiles)].reset_index()
	
	# create gdf as output file
	gdfSubTiles['Date'] = gdfSubTiles['ContentDate'].apply(lambda x: x['Start'])
	gdfSubTiles['URI'] = gdfSubTiles['Id'].apply(lambda x: f"https://download.dataspace.copernicus.eu/odata/v1/Products({x})/$value")
	gdfSubTiles['CloudCover'] = gdfSubTiles['Attributes'].apply(lambda att: [att["Value"] for att in att if att["Name"]=="cloudCover"][0])
	gdfSubTiles['Baseline'] = gdfSubTiles["Attributes"].apply(lambda att: [att["Value"] for att in att if att["Name"]=="processorVersion"][0])
	# create column with output name for zip file
	gdfSubTiles["Name"] = gdfSubTiles["Name"].apply(lambda n: n+".SAFE" if not n.endswith(".SAFE") else n) # sometimes the file extention (.SAFE) is not mentioned in Name
	gdfSubTiles["ZipName"] = gdfSubTiles[["Tile","Name"]].agg(lambda x: os.path.join(inputDir, str(year), f'{x["Tile"]}', f'{x["Name"].replace(".SAFE", ".zip")}'), axis=1)    
	
	# remove duplicate tiles with different baseline, keep newest baseline
	gdfSubTiles["Baseline_float"] = gdfSubTiles["Baseline"].apply(lambda b: float(b.strip('0'))) 
	
	logger.info("gdfSubTiles is:\n{}".format(str(gdfSubTiles)))

	idx_keep = gdfSubTiles.groupby(['Date', 'Tile'], group_keys=False)["Baseline_float"].transform('max') == gdfSubTiles['Baseline_float'] 
	
	gdfSubTiles = gdfSubTiles[idx_keep]

	logger.info("Number of products to download: {}".format(
		len(gdfSubTiles)))
	
	logger.info("Products to download:\n{}".format(str(gdfSubTiles)))

	# run download in parallel (4 workers = max for copernicus data space)
	with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
		gdfSubTiles["Downloaded"] = list(executor.map(downloadAll, gdfSubTiles["URI"], gdfSubTiles["ZipName"], gdfSubTiles["Checksum"],gdfSubTiles["index"]))

#	class MyRequest(object):
#		url = ""
#		zipName = ""
#		checkSum = ""
#		name = ""
#	def makeMyRequest(url, zipName, checkSum, name):
#		myRequest = MyRequest()
#		myRequest.url = url
#		myRequest.zipName = zipName
#		myRequest.checkSum = checkSum
#		myRequest.name = name
#		return myRequest
#
#	myList = list(
#			map(
#				makeMyRequest,
#				gdfSubTiles["URI"],
#				gdfSubTiles["ZipName"],
#				gdfSubTiles["Checksum"],
#				gdfSubTiles["index"]
#			)
#		)
#	resList = []
#	for item in myList:
#		res = downloadAll(item.url, item.zipName, item.checkSum, item.name)
#		resList.append(res)
#
#	gdfSubTiles["Downloaded"] = list(map(downloadAll, gdfSubTiles["URI"], gdfSubTiles["ZipName"], gdfSubTiles["Checksum"],gdfSubTiles["index"]))

	# select columns and generate output file
	gdfSubTiles_meta_out = gdfSubTiles[["Id","URI","Date","CloudCover","Downloaded"]]
	gdfSubTiles_meta_out.to_json(os.path.join(outputDir, f"{startDateRef}_PRE_{region}_{startDate}_{endDate}_x_{VP}_R_meta.json"),orient="records")

	return int(sum(gdfSubTiles_meta_out["Downloaded"] == True)), int(len(gdfSubTiles_meta_out.index))
	
def runQuery(query:str) -> dict:
	""" Run search query

	Args:
		query (str): search query

	Raises:
	NOTE: at 07/09/2024 no specific errors where available for the API used
		ConnectionError: when response on request is other then 200
		ConnectionError: when request is not succesfull

	Returns:
		dict: response
	"""

	logger.info("Getting... {}\n".format(query))

	for attempt in range(1):
		try:
			# fetch product metadata for search criteria
			response = requests.get(query)
			if not response.status_code == 200:
				logger.info(f'query status code: {response.status_code}')
				try:
					logger.info(f'query response:\n {response.json()}')
				except:
					raise ConnectionError
				raise ConnectionError
			jsonOut = response.json()
		# TODO add specific exceptions for serverside errors
		except ConnectionError as e:
			logger.error('connection error', e)
			time.sleep(1) # retry after 1 minute
		else: 
			# break out of for loop if try was succesfull
			break
	else:
		# we got 10 times a server error
		raise ConnectionError
	
	logger.info("Obtained...\n{}\n".format(str(jsonOut)))

	return jsonOut
   
def get_session(name) -> requests.sessions.Session:
	"""create or return local thread session for download

	Returns:
		requests.sessions.Session: thread save request session
	"""
	if not hasattr(thread_local, "session"):
		thread_local.session = requests.Session()
		thread_local.session.headers.update({'name_x': f'name_{name}'})
		# request new token
		tokenReq = getKeycloak()
		logger.info(f"token = {tokenReq["access_token"]}")
		thread_local.session.headers.update({'Authorization': f'Bearer {tokenReq["access_token"]}'})

	return thread_local.session

def close_session():
	if hasattr(thread_local, "session"):
		name = thread_local.session.headers["name_x"]
		thread_local.session.close()
		del thread_local.session

def getKeycloak() -> dict:
	"""Generate autorization token for Copernicus Dataspace Ecosystem

	Raises:
		Exception: if token creation fails.

	Returns:
		dict: local thread response with autorization token and refresh token + metadata
	"""
	# get account configuration
	# username = os.getenv('COPERNICUS_DATASPACE_USERNAME')
	# password = os.getenv('COPERNICUS_DATASPACE_PASSWORD')
	username = "lifefoliage20@gmail.com"
	password = "life20.MONITORAGGIO"

	data = {
		"client_id": "cdse-public",
		"username": username,
		"password": password,
		"grant_type": "password",
		}
	logger.info("Requesting token...")
	logger.info("POST https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token")
	logger.info(data)
	try:
		r = requests.post("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
			data=data
		)
		logger.info(f"Status Code: {r.status_code}")
		logger.info(f"Content:\n{r.content}")
		
		r.raise_for_status()
	except Exception as e:
		if r.status_code == 401:
			logger.warning(f"Keycloak token creation failed. Reponse from the server was: {r.status_code}:{r.json()}. Wait for 15 minutes and retry")
			time.sleep(60*15) #sleep for 15 minutes 
			return getKeycloak()
		else:
			raise Exception(
				f"Keycloak token creation failed. Reponse from the server was: {r.status_code}:{r.json()}"
				)
	
	thread_local.tokenReq = r.json()
	return thread_local.tokenReq

def refreshKeycload() -> dict:
	""" Refresh autorization token

	Raises:
		Exception: if token creation fails.

	Returns:
		dict: local thread response with autorization token and refresh token + metadata
	"""

	if not hasattr(thread_local, "tokenReq"):
		return getKeycloak()
	
	data = {
		"client_id": "cdse-public",
		"grant_type": "refresh_token", 
		"refresh_token": thread_local.tokenReq["refresh_token"]
	}
	try:
		r = requests.post("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
		data=data,
		)
		r.raise_for_status()
	except Exception as e:
		if r.status_code == 401:
			logger.warning(f"Keycloak token creation failed. Reponse from the server was: {r.status_code}:{r.json()}. Wait for 15 minutes and retry")
			time.sleep(60*10) #sleep for 15 minutes 
			return getKeycloak()
		else:
			raise Exception(
				f"Keycloak token creation failed. Reponse from the server was: {r.status_code}:{r.json()}"
				)
	
	thread_local.tokenReq = r.json()
	return thread_local.tokenReq


def verifyFileIntegrity(fname:str, checksum:str):
	""" verify file integrety using file checksum

	Args:
		fname (str): filename
		checksum (str): reported checksum of input file

	Returns:
		bool: True if checksums match, otherwise False
	"""
	hashMd5 = hashlib.md5()
	with open(fname, "rb") as f:
		for chunk in iter(lambda: f.read(4096), b""):
			hashMd5.update(chunk)
	checksumFile = hashMd5.hexdigest()
	return checksum == checksumFile

def downloadAll(url:str, zipName:str, checkSum, name:Union[str, int]) -> bool:
		""" Create separate download session and trigger parallel download

		Args:
			url (str): download url
			zipName (str): full path to target location of file
			checkSum: Md5 checksum for product validation
		
		Returns:
			bool: True is download was succesfull, otherwise False
		"""

		if os.path.exists(zipName):
			logger.info(f"Product {os.path.basename(zipName)} is already present in the output directory.")
			return True
		else:
			logger.info(f"Downloading product {os.path.basename(zipName)}")
		
		os.makedirs(os.path.dirname(zipName), exist_ok=True)
		
		session = get_session(name)

		startTime = time.time()
		if downloadFile(
			session = session, 
			url = url,
			zipName = zipName, 
			productChecksum = checkSum, 
			downloadAttempt=0):
			timeDelta = time.time() - startTime

			logger.info(f"Download of product {os.path.basename(zipName)} finished in {timeDelta}")
			# close_session()
			return True
		else:
			logger.info(f"Download of product {os.path.basename(zipName)} failed after maximum allowed number of attempts. Checksums do not match")
			# close_session()
			return False
		
		

def downloadFile(session:requests.sessions.Session, url:str, zipName:str, productChecksum:list, downloadAttempt=0) -> bool:
	"""Downloading the requested file from the Copernicus Dataspace Ecosystem

	Args:
		session (requests.sessions.Session): thread save download session
		url (str): download url
		zipName (str): full path to outputfile
		productChecksum (list): list of dict with product checksums
		downloadAttempt (int, optional): number of attempt used for downloading. Defaults to 0.

	Returns:
		bool: True if download was succesfull, otherwise False
	"""
	maxDownloadAttempts = 3
	downloadAttempt +=1
	logger.info("Downloading({})... GET {}".format(downloadAttempt, url))
	try:
		with session.get(url, allow_redirects=False, stream=True, verify= None) as response:
			
			if response.status_code == 200:
				if response.content == b'{detail: "Expired signature!"}':
					# refresh token (after 10 minutes) or request new token (after 1h)
					try:
						tokenReq = refreshKeycload()
					except:
						tokenReq = getKeycloak()
					session.headers.update({'Authorization': 'Bearer ' + tokenReq["access_token"]})
					# don't count attempt
					return downloadFile(session=session, 
										url=url, 
										zipName=zipName,
										productChecksum=productChecksum, 
										downloadAttempt=downloadAttempt-1)
				with open(zipName, "wb") as file:
					for chunk in response.iter_content(chunk_size=8192):
						if chunk:  # filter out keep-alive new chunks
							file.write(chunk)

				if len(productChecksum) > 0 and len(productChecksum[0]) > 0: 
					md5Idx = next((index for (index, d) in enumerate(productChecksum) if d["Algorithm"] == "MD5"), None)
					originalChecksum = productChecksum[md5Idx]["Value"]
					if verifyFileIntegrity(zipName, originalChecksum):
						return True
					else:
						# retry download
						if downloadAttempt < maxDownloadAttempts:
							return downloadFile(session=session, 
												url=url, 
												zipName=zipName,
												productChecksum=productChecksum, 
												downloadAttempt=downloadAttempt)
						else:
							os.remove(zipName)
							return False
				else: 
					# Checksum cannot be checked. Checking if filesize > 1MB
					if os.stat(zipName).st_size > 1000000: #1MB
						return True
					else:
						# retry download
						if downloadAttempt < maxDownloadAttempts:
							return downloadFile(session=session, 
												url=url, 
												zipName=zipName,
												productChecksum=productChecksum, 
												downloadAttempt=downloadAttempt)
						else:
							os.remove(zipName)
							return False
			else:
				logger.info("Error occurred in download: {}".format(response.status_code))
				logger.info(str(response.content))
				
				request = response.request
				logger.info(f"METHOD: {request.method}")
				logger.info(f"URL: {request.url}")
				logger.info(f"HEADERS: {request.headers}")
				logger.info(f"BODY: {request.body}")
				if response.status_code in (301, 302, 303, 307, 308):
					url = response.headers['Location']
					# don't count as attempt
					return downloadFile(session=session, 
										url=url, 
										zipName=zipName,
										productChecksum=productChecksum, 
										downloadAttempt=downloadAttempt-1)
				elif response.status_code == 401:
					# TODO after 1h request new token, check error message after 1 h
						try:
							tokenReq = refreshKeycload()
						except:
							tokenReq = getKeycloak()
						session.headers.update({'Authorization': 'Bearer ' + tokenReq["access_token"]})
						# dont't count as attempt
						return downloadFile(session=session, 
											url=url, 
											zipName=zipName,
											productChecksum=productChecksum, 
											downloadAttempt=downloadAttempt-1)
				else:
					logger.warning(f"{response.status_code}: Download of product {os.path.basename(zipName)} failed: {response.reason}")
					if downloadAttempt < maxDownloadAttempts:
						return downloadFile(session=session, 
											url=url, 
											zipName=zipName,
											productChecksum=productChecksum, 
											downloadAttempt=downloadAttempt)
	except ConnectionError:
		logger.error('')
		# close_session()
		# wait 15 minutes before retrying to download (to resolve server error)
		if downloadAttempt < maxDownloadAttempts:
			time.sleep(15*60) 
			return downloadFile(session=session, 
										url=url, 
										zipName=zipName,
										productChecksum=productChecksum, 
										downloadAttempt=downloadAttempt)
	except Exception as error:
		logger.exception('')
		# close_session()
		if downloadAttempt < maxDownloadAttempts:
			# wait 5 minutes before retrying to download
			time.sleep(5*60) 
			return downloadFile(session=session, 
										url=url, 
										zipName=zipName,
										productChecksum=productChecksum, 
										downloadAttempt=downloadAttempt)
		

