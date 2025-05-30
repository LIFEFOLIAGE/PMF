package it.almaviva.foliage;

public class FoliageException extends RuntimeException {
	public FoliageException(String message) {
		super(message);
	}
	public FoliageException(String message, Throwable cause) {
		super(message, cause);
	}
}
