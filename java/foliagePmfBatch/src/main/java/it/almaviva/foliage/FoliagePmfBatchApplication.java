package it.almaviva.foliage;


import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.event.EventListener;

import it.almaviva.foliage.service.MonitoraggioService;

@SpringBootApplication()
@Configuration
public class FoliagePmfBatchApplication {

	@Autowired
	public MonitoraggioService servizio;
	
	public static void main(String[] args) throws Exception {
		SpringApplication.run(FoliagePmfBatchApplication.class, args);
	}

	@EventListener(ApplicationReadyEvent.class)
	public void doSomethingAfterStartup(
	) throws Exception {
		servizio.eseguiMonitoraggio();
	}
}
