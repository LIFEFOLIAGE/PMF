package it.almaviva.foliage.bean;

import com.fasterxml.jackson.annotation.JsonProperty;

public class ContainersApiErrorBean {
	@JsonProperty("coderr")
	public Integer codError;
	
	@JsonProperty("deserr")
	public String descError;
}
