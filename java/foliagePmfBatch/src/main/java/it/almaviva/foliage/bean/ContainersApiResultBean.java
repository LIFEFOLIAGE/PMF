package it.almaviva.foliage.bean;

import com.fasterxml.jackson.annotation.JsonProperty;

public class ContainersApiResultBean {
	@JsonProperty("api_version")
	public String ApiVersion;

	public Boolean isOk;
	public Boolean isOK;
	public ContainersApiErrorBean error;
	public Object data;
}
