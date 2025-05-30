package it.almaviva.foliage.service;


import java.io.IOException;
import java.net.Authenticator;
import java.net.PasswordAuthentication;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpResponse.BodyHandlers;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.io.StringWriter;
import java.io.PrintWriter;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import it.almaviva.foliage.FoliageException;
import it.almaviva.foliage.bean.AttivitaMonitoraggioBean;
import it.almaviva.foliage.bean.ContainersApiResultBean;
import it.almaviva.foliage.bean.RisultatiMonitoraggioBean;
import lombok.extern.slf4j.Slf4j;



@Slf4j
@Component
public class MonitoraggioService {
	private String urlRichiestaAttivita = null;
	private URI uriRichiestaAttivita = null;
	//private HttpClient client = null;
	private Gson gson = new Gson();

	private String foliageBeBaseUrl;
	private String idClient;

	@Value("${foliage.eop.preprocessing-url}")
	private String urlEopProprocessingApi;

	@Value("${foliage.eop.monitoraggio-url}")
	private String urlEopMonitoraggioApi;

	@Value("${foliage.cod-regione}")
	private String codRegione;

	@Value("${foliage.monitoraggio.shared-directory-local-path}")
	private String awsMountpoint;

	@Value("${foliage.monitoraggio.shared-directory-container-path}")
	private String dockerMountpoint;

	@Value("${foliage.monitoraggio.path-dati-preelaborazione}")
	private String pathDatiPreelaborazione;

	@Value("${foliage.monitoraggio.backend-username}")
	private String backendUsername;

	@Value("${foliage.monitoraggio.backend-password}")
	private String backendPassword;

	@Value("${foliage.monitoraggio.skip-preprocessing}")
	private boolean skipPreprocessing;
	
	@Value("${foliage.monitoraggio.skip-monitoring}")
	private boolean skipMonitoring;


	private HttpClient backendClient = HttpClient.newBuilder().authenticator(
		new Authenticator() {
			@Override
			protected PasswordAuthentication getPasswordAuthentication() {
				return new PasswordAuthentication(backendUsername, backendPassword.toCharArray());
			}
		}
	).build();
	private HttpClient containersApiClient = HttpClient.newBuilder().build();

	public MonitoraggioService(
		@Value("${foliage.monitoraggio.client-id}") String idClient,
		@Value("${foliage.backend.baseurl}") String foliageBeBaseUrl
	) {
		this.idClient = idClient;
		this.foliageBeBaseUrl = foliageBeBaseUrl;

		urlRichiestaAttivita = String.format(
			"%sattivita/%s",
			this.foliageBeBaseUrl,
			this.idClient
		);
		
		gson = new GsonBuilder()
			.registerTypeAdapter(LocalDateTime.class, new LocalDateTimeTypeAdapter())
			.registerTypeAdapter(LocalDate.class, new LocalDateTypeAdapter())
			.create();

		try {
			uriRichiestaAttivita = new URI(urlRichiestaAttivita);
		}
		catch(Exception e) {
			StringWriter sw = new StringWriter();
			PrintWriter pw = new PrintWriter(sw);
			e.printStackTrace(pw);
			String sStackTrace = sw.toString(); 
			log.error(sStackTrace);
			System.exit(1);
		}
	}

	public AttivitaMonitoraggioBean recuperaAttivita() throws IOException, InterruptedException {
		log.debug(String.format("Connessione POST a %s", urlRichiestaAttivita));
		HttpRequest request = HttpRequest.newBuilder()
			.uri(uriRichiestaAttivita)
			.POST(HttpRequest.BodyPublishers.noBody())
			.build();

		//client = HttpClient.newBuilder().build();
		HttpResponse<String> response = backendClient.send(request, BodyHandlers.ofString());
		int statusCode = response.statusCode();
		if (statusCode >= 200 && statusCode < 300 ) {
			String result = response.body();
			log.debug(String.format("Ottenuto: %s", result));
			AttivitaMonitoraggioBean outVal = gson.fromJson(JsonParser.parseString(result), AttivitaMonitoraggioBean.class);
			return outVal;
		}
		else {
			String result = response.body();
			log.error(String.format("Ottenuto errore: %s", result));
			throw new FoliageException("errore");
		}
	}

	private ContainersApiResultBean getContainersApiResult(String responseBody, String apiUrl) {
		ContainersApiResultBean res = null;
		//try {}catch(){}
		res = gson.fromJson(responseBody, ContainersApiResultBean.class);
		
		if ( (res.isOk != null && res.isOk.booleanValue())  || (res.isOK != null && res.isOK.booleanValue()) ) {
			return res;
		}
		else {
			throw new FoliageException(String.format(
					"Elaborazione in errore per la richiesta verso %s ",
					apiUrl
				)
			);
		}
	}
	private ContainersApiResultBean getContainersApiResult(HttpRequest request) throws IOException, InterruptedException {
		HttpResponse<String> response = containersApiClient.send(
			request,
			HttpResponse.BodyHandlers.ofString()
		);
		int statusCode = response.statusCode();
		if (statusCode >= 200 && statusCode < 300 ) {
			log.info("Ok");
			String responseBody = response.body();
			log.debug(String.format("Ottenuto:\n %s", responseBody));

			
			ContainersApiResultBean res = getContainersApiResult(responseBody, request.uri().toURL().toString());
			return res;
		}
		else {
			log.error("Errore");
			String result = response.body();
			log.debug(String.format("Ottenuto:\n %s", result));
			throw new FoliageException(
				String.format(
					"Richiesta fallita(%d) verso %s ",
					statusCode,
					request.uri().toURL().toString()
				)
			);
		}
	}


	
	private ContainersApiResultBean getContainersApiResultAsync(HttpRequest request) throws IOException, InterruptedException {
		String url = request.uri().toURL().toString();
		CompletableFuture<HttpResponse<String>> responsePromise = containersApiClient.sendAsync(
			request,
			HttpResponse.BodyHandlers.ofString()
		);

		boolean completed = false;
		HttpResponse<String> response = null;
		do {
			try {
				response = responsePromise.get(30, TimeUnit.MINUTES);
				log.debug(String.format("...completata GET a %s", url));
				completed = true;
			}
			catch(TimeoutException e) {
				log.debug(String.format("...in attesa della risposta da GET a %s", url));
			}
			catch(ExecutionException e) {
				log.debug(String.format("...rilevato errore da GET a %s", url));
				completed = true;
			}
		} while(completed == false);

		int statusCode = response.statusCode();
		if (statusCode >= 200 && statusCode < 300 ) {
			//log.info("Ok");
			String responseBody = response.body();
			log.debug(String.format("Ottenuto:\n %s", responseBody));

			
			ContainersApiResultBean res = getContainersApiResult(responseBody, url);
			return res;
		}
		else {
			log.error("Errore");
			String result = response.body();
			log.debug(String.format("Ottenuto:\n %s", result));
			throw new FoliageException(
				String.format(
					"Richiesta fallita(%d) verso %s ",
					statusCode,
					request.uri().toURL().toString()
				)
			);
		}
	}

	public void pingApi(String api) throws URISyntaxException, IOException, InterruptedException {
		String urlPreprocessing = String.format("%s/ping", api );
		log.info(String.format("Verifica connessione alle API di %s ...", urlPreprocessing));
		URI uriPreprocessing = new URI(urlPreprocessing);
		HttpRequest request = HttpRequest.newBuilder()
			.uri(uriPreprocessing)
			.GET()
			.build();

		ContainersApiResultBean res = getContainersApiResult(request);
	}

	public void checkRequisiti() throws URISyntaxException, IOException, InterruptedException {
		log.info("Inizio verifica dei requisiti");

		log.info("Test preprocessing");
		pingApi(urlEopProprocessingApi);
		
		log.info("Test monitoraggio");
		pingApi(urlEopMonitoraggioApi);
		
		log.info("Verifica dei requisiti completata con successo");
	}

	public void eseguiMonitoraggio() throws Exception {
		log.debug("Inizio elaborazioni per il monitoraggio");

		AttivitaMonitoraggioBean attMonitoraggio = recuperaAttivita();
		if (attMonitoraggio != null) {
			/// TODO: ripristinare
			//checkRequisiti();
	
			int i = 0;
			do {
				RisultatiMonitoraggioBean risultati = esecuzioneAttivitaMonitoraggio(attMonitoraggio);
	
				registraFineMonitoraggio(risultati);
				attMonitoraggio = recuperaAttivita();
	
				//TODO: togliere attMonitoraggio = null; dopo i test
				//attMonitoraggio = null;
				i++;
			} while (attMonitoraggio != null);
			log.debug(String.format("Eseguite %d elaborazioni", i));
		}
		else {
			log.debug("Non ci sono elaborazioni da avviare");
		}
		log.debug("Fine elaborazioni per il monitoraggio");
		System.exit(0);
	}

	private void salvaDatiPreElaborazione(AttivitaMonitoraggioBean attMonitoraggio) throws URISyntaxException, IOException, InterruptedException {
		log.info(String.format("Recupero dati pre-elaborazione per attività a %s", attMonitoraggio.idRichiesta));

		String urlDatiPreelaborazione  = String.format(
			"%sdati-preelaborazione/%s",
			this.foliageBeBaseUrl,
			attMonitoraggio.idRichiesta
		);

		log.debug(String.format("Connessione GET a %s", urlDatiPreelaborazione));


		URI uriDatiPreelaborazione = new URI(urlDatiPreelaborazione);
		HttpRequest request = HttpRequest.newBuilder()
			.uri(uriDatiPreelaborazione)
			.GET().build();

		Path path = Path.of(awsMountpoint, pathDatiPreelaborazione);
		log.debug(String.format("Salvataggio del file %s", path.toAbsolutePath().toString()));
		Files.createDirectories(path.getParent());
		
		HttpResponse<Path> response = backendClient.send(
			request,
			HttpResponse.BodyHandlers.ofFile(path, StandardOpenOption.WRITE, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING)
		);
		int statusCode = response.statusCode();
		if (statusCode >= 200 && statusCode < 300 ) {
			Path result = response.body();
			log.debug(String.format("Salvato file in : %s", result.toAbsolutePath()));
		}
		else {
			log.error(String.format("Errore: %d", statusCode));
			throw new FoliageException("errore");
		}
	}

	public static final DateTimeFormatter dateFormatter = DateTimeFormatter.ofPattern("yyyyMMdd");
	public static final DateTimeFormatter minutesFormatter = DateTimeFormatter.ofPattern("yyyyMMddHHmm");
	public static final DateTimeFormatter timeFormatter = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");

	public RisultatiMonitoraggioBean esecuzioneAttivitaMonitoraggio(AttivitaMonitoraggioBean attMonitoraggio) throws Exception {
		LocalDateTime dataAvvioPianificata = attMonitoraggio.dataAvvioPianificata;
		LocalDateTime dataAvvio = LocalDateTime.now();

		LocalDate dataRiferimento = attMonitoraggio.dataRiferimento;
		int annoElaborazione = dataRiferimento.getYear() - 1;

		LocalDate dInizio = LocalDate.of(annoElaborazione, 6, 1);
		LocalDate dFine = LocalDate.of(annoElaborazione, 8, 31);


		String strDataAvvioSec = dataAvvioPianificata.format(timeFormatter);
		String strDataAvvioMin = dataAvvioPianificata.format(minutesFormatter);

		RisultatiMonitoraggioBean outVal = new RisultatiMonitoraggioBean();
		outVal.dataInizioElaborazione = dataAvvio.format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
		outVal.idRichiesta = attMonitoraggio.idRichiesta;

		if (skipPreprocessing) {
			log.info("Salto fase di preprocessing");
		}
		else {
			log.info("Fase di preprocessing - INIZIO");
			String strDataInizio = dInizio.format(dateFormatter);
			String strDataFine = dFine.format(dateFormatter);
			
			String urlPreprocessing = String.format(
				"%s/preprocess/%s/%s/%s/%s",
				urlEopProprocessingApi,
				strDataAvvioMin,
				codRegione,
				strDataInizio,
				strDataFine
			);
			log.debug(String.format("Connessione GET a %s ...", urlPreprocessing));
			URI uriPreprocessing = new URI(urlPreprocessing);
			HttpRequest request = HttpRequest.newBuilder()
				.uri(uriPreprocessing)
				.GET()
				.build();
	
			ContainersApiResultBean res = getContainersApiResultAsync(request);
			log.info("Fase di preprocessing - COMPLETATA");
		}
		
		if (skipMonitoring) {
			log.info("Salto fase di monitoring");
		}
		else {
			salvaDatiPreElaborazione(attMonitoraggio);

			log.info("Fase di monitoring - INIZIO");
			String strDataInizio = dInizio.format(dateFormatter);
			String strDataFine = dFine.format(dateFormatter);

			JsonObject jsonParObj = new JsonObject();
			jsonParObj.addProperty("data_rif", strDataAvvioSec); //yyyymmddhh24miss
			jsonParObj.addProperty("id_regione", codRegione);

			jsonParObj.addProperty("data_ini_mon", strDataInizio); //yyyymmdd
			jsonParObj.addProperty("data_fin_mon", strDataFine); //yyyymmdd

			JsonArray arrFilePrep = new JsonArray();
			String s1 = String.format(
				"%s_PRE_%s",
				strDataAvvioMin,
				codRegione
			);

			Integer[] arr = {-1, 0, 1};
			Arrays.stream(arr).forEach(
				(Integer i) -> {
					LocalDate cdInizio = dInizio.plusYears(i.intValue());
					LocalDate cdFine = dFine.plusYears(i.intValue());
					String sInizio = cdInizio.format(dateFormatter);
					String sFine = cdFine.format(dateFormatter);

					String fName = String.format(
						"%s_%s_%s_0_1_R.nc",
						s1,
						sInizio,
						sFine
					);
					arrFilePrep.add(fName);
				}
			);
			
			jsonParObj.add("path_file_preprocessing", arrFilePrep);
			String[] pathNames = { dockerMountpoint, pathDatiPreelaborazione };
			jsonParObj.addProperty("path_file_fmp", String.join("/", pathNames));

			String jsonInpMonitoraggio = gson.toJson(jsonParObj);
			String urlMonitoraggio = String.format("%s/monitor", urlEopMonitoraggioApi);
			log.debug(String.format("Connessione POST a %s ...", urlMonitoraggio));
			log.debug("Request body:");
			log.debug(jsonInpMonitoraggio);

			URI uriMonitoraggio = new URI(urlMonitoraggio);
			HttpRequest request = HttpRequest.newBuilder()
				.uri(uriMonitoraggio)
				.header("Content-Type", "application/json")
				.POST(
					HttpRequest.BodyPublishers.ofString(jsonInpMonitoraggio)
				).build();
			
			ContainersApiResultBean res = getContainersApiResultAsync(request);
			log.info("Fase di monitoring - COMPLETATA");
		}

		
		log.info("Recupero dei risultati - INIZIO");
		{
			salvataggioRisultati(attMonitoraggio, strDataAvvioSec, "alert");
			salvataggioRisultati(attMonitoraggio, strDataAvvioSec, "nat2000");
		}
		log.info("Recupero dei risultati - INIZIO");

		return outVal;
	}
	
	private void salvataggioRisultati(AttivitaMonitoraggioBean attMonitoraggio, String strDataAvvioSec, String nomeFile) throws Exception {
		
		String urlSalvataggioRisultati  = String.format(
			"%srisultati-monitoraggio/%d/%s",
			this.foliageBeBaseUrl,
			attMonitoraggio.idRichiesta,
			nomeFile
		);
		
		String s1 = String.format(
			"%s_MON_%s",
			strDataAvvioSec,
			codRegione
		);

		LocalDate dataRiferimento = attMonitoraggio.dataRiferimento;
		int annoElaborazione = dataRiferimento.getYear() - 1;


		//LocalDate dInizio = attMonitoraggio.parametri.dataInizio;
		//LocalDate dFine = attMonitoraggio.parametri.dataFine;
		LocalDate dInizio = LocalDate.of(annoElaborazione, 6, 1);
		LocalDate dFine = LocalDate.of(annoElaborazione, 8, 31);

		String sInizio = dInizio.format(dateFormatter);
		String sFine = dFine.format(dateFormatter);

		String nomeFileCompleto = String.format(
			"%s_%s_%s_0_1_%s.geojson",
			s1,
			sInizio,
			sFine,
			nomeFile
		);

		log.debug(String.format("Trasmissione del file %s", nomeFileCompleto));
		log.debug(String.format("Connessione PUT a %s", urlSalvataggioRisultati));
		
		URI uriSalvataggioRisultati = new URI(urlSalvataggioRisultati);
		Path path = Path.of(awsMountpoint, "output", nomeFileCompleto);
		
		HttpRequest request = HttpRequest.newBuilder()
			.uri(uriSalvataggioRisultati)
			.header("Content-Type", "application/json")
			.PUT(
				HttpRequest.BodyPublishers.ofFile(path)
			).build();

		HttpResponse<String> response = backendClient.send(
			request,
			HttpResponse.BodyHandlers.ofString()
		);
		int statusCode = response.statusCode();
		if (statusCode >= 200 && statusCode < 300 ) {
			String result = response.body();
			log.debug(String.format("Ottenuto: %s", result));
		}
		else {
			String result = response.body();
			log.error(String.format("Ottenuto errore: %s", result));
			throw new FoliageException("errore");
		}
	}

	public void registraFineMonitoraggio(RisultatiMonitoraggioBean risultati) throws IOException, InterruptedException {
		log.info(String.format("Conclusione attività a %s", risultati.idRichiesta));
		log.debug(String.format("Connessione PUT a %s", urlRichiestaAttivita));

		String jsonRisultati = gson.toJson(risultati);
		log.debug(String.format("%s", jsonRisultati));
		
		HttpRequest request = HttpRequest.newBuilder()
			.uri(uriRichiestaAttivita)
			.header("Content-Type", "application/json")
			.PUT(
				HttpRequest.BodyPublishers.ofString(jsonRisultati)
			).build();

		HttpResponse<String> response = backendClient.send(
			request,
			HttpResponse.BodyHandlers.ofString()
		);
		int statusCode = response.statusCode();
		if (statusCode >= 200 && statusCode < 300 ) {
			String result = response.body();
			log.debug(String.format("Ottenuto: %s", result));
		}
		else {
			String result = response.body();
			log.debug(String.format("Ottenuto errore: %s", result));
			throw new FoliageException("errore");
		}
	}
}
