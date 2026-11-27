package l10.example3;

public class Car {
	private Engine engine;
	
	public void setEngine(Engine engine) {
		this.engine = engine;
	}

	public void start() {
		this.engine.start();
	}
	
	public void shutOff() {
		this.engine.stop();
	}
}
