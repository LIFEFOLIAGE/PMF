# LifeFoliage - PMF

## <a id="premessa"> Premessa </a>

L'applicazione **PMF** è un componente aggiuntivo del [progetto PAF](https://github.com/LIFEFOLIAGE/PAF/) e, per permettere il suo corretto funzionamento, occorre accertarsi che il componente di backend del progetto PAF sia raggiungibile dall'applicazione PMF.

# Installazione ed Avvio

## <a id="requisiti"> Requisiti </a>

Qui di seguito sono riportati i software necessari per procedere con l’installazione.

*	Wget: client per download da rete
*	Unzip: gestore di archivi
*	Java openJdk21: piattaforma di sviluppo per il linguaggio java
*	Maven: gestore di pacchetti per il linguaggio java
*	Docker: software di containerizzazione


## <a id="installazione"> Installazione dei requisiti

```bash
sudo apt install wget
sudo apt install unzip
sudo apt install openjdk-21-jdk
sudo apt install maven
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

```

## <a id="downloadPafProject">Download dei file del progetto

I file del progetto per il sistema di monitoraggio EOP possono essere scaricati dal repository ufficiale della piattaforma presente su GITHUB ed estratti nella directory `/EOPSoftware`.

```bash
mkdir /EOPSoftware
cd /EOPSoftware
wget https://github.com/LIFEFOLIAGE/PFM/archive/refs/heads/main.zip
unzip main.zip

```


## <a id="createDockerImages">Generazione delle immagini docker

Una volta scaricato il progetto si può procedere alla generazione delle immagini per i container docker che si occuperanno di gestire le fasi di preprocessing e monitoring.

```bash
cd /EOPSoftware/EOP-main/containers/preprocessing/image
sudo docker build --no-cache -t feop-a-preprocessing .
cd /EOPSoftware/EOP-main/containers/monitoring/image
sudo docker build --no-cache -t feop-c-monitoring .
```

## <a id="sharedDirectoriesSetup">Predisposizione le directory condivise con i container

La directory /EOPStorage viene utilizzata per condividere i file tra MVM ed i 2 container docker (preprocessing e monitoring). La directory dovrebbe avere almeno 5Gb di spazio disponibile per ogni elaborazione da effettuare e deve contenere le 2 sottodirectory seguenti:
*	data/: dove vengono scritti/letti i file prodotti dalle elaborazioni avviate
*	monitoring-tmp/: che viene destinata all’allocazione di file temporanei necessari alle elaborazioni avviate dal container di monitoring.


```bash
mkdir /EOPStorage
mkdir /EOPStorage/data
mkdir /EOPStorage/monitoring-tmp
```

## <a id="batchSetup">Configurazione del batch di coordinamento

Prima procedere con la compilazione occorre effettuarne la configurazione del file  `/EOPSoftware/EOP-main/java/foliageEopBatch/src/main/resources\application.properties`.


```
spring.profiles.active=@activatedProperties@
spring.main.web-application-type=none

server.error.include-stacktrace=never
server.error.include-message=always
server.error.include-binding-errors= always
server.error.include-exception=true

foliage.is_development=true

logging.level.it.almaviva.foliageMonitoraggio = DEBUG

logging.config=classpath:log4j2.xml

foliage.backend.baseurl = <PAF-monitoring-api-url>
foliage.eop.preprocessing-url = http://127.0.0.1:8000
foliage.eop.monitoraggio-url = http://127.0.0.1:8001
foliage.cod-regione = <cod-regione>

foliage.monitoraggio.shared-directory-local-path=/EOPStorage/data
foliage.monitoraggio.shared-directory-container-path=/foliage/data
foliage.monitoraggio.path-dati-preelaborazione = preelaborazioneEOP.geojson

foliage.monitoraggio.client-id = <PAF-monitoring-api-client-id>
foliage.monitoraggio.backend-username = <PAF-monitoring-api-user>
foliage.monitoraggio.backend-password = <PAF-monitoring-api-password>

foliage.monitoraggio.skip-preprocessing=false
foliage.monitoraggio.skip-monitoring=false

logging.level:debug

```

andando ad impostare le seguenti voci:
*	PAF-monitoring-api-url: url delle api del backend PAF dedicate al monitoraggio
*	cod-regione: il codice istat della regione gestita dall'applicazione
*	PAF-monitoring-api-client-id: identificativo dell’istanza corrente del batch di monitoraggio
*	PAF-monitoring-api-user: username per accedere alle api del backend PAF dedicate al monitoraggio
*	PAF-monitoring-api-password: password per accedere alle api del backend PAF dedicate al monitoraggio





## <a id="batchBuild">Compilazione del batch di coordinamento

La compilazione del pacchetto Java per il batch di coordinamento viene effettuata attraverso maven. Il file jar ottenuto dalla compilazione viene poi spostato nella directory /EOPSoftware.


```bash
cd /EOPSoftware/EOP-main/java/foliagePmfBatch
mvn clean install
cp target/foliagePmfBatch.jar /EOPSoftware

```


# Esecuzione delle elaborazioni

Presentiamo qui di seguito i passi necessari per far partire le elaborazioni del sistema di monitoraggio EOP.


## <a id="containerStartup">Predisposizione dei container

La configurazione dei container da creare viene definita nel file containers/AFEOP-Compose.yaml ed i container vanno attivato attraverso il comando docker compose.

```bash
cd /EOPSoftware/EOP-main/containers
sudo docker compose -f AFEOP-Compose.yaml up -d
```

A fine elaborazione per spegnere

```bash
cd /EOPSoftware/EOP-main/containers
sudo docker compose -f AFEOP-Compose.yaml down -d
```




## <a id="batchRun">Avvio del batch di coordinamento

Il batch di coordinamento viene quindi avviato dalla directory /EOPSotfware.
```bash
cd /EOPSoftware
java -jar foliageEopBatch.jar

```