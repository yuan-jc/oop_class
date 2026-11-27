package l09.example5;

import l09.example4.Engine;

public class Car2 {
	private Engine engine;
	
	public Engine getEngine() {
		return engine;
	}

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
