package l09.example1;

public class L4Engine {
	/** The engine type */
	private String engineType = null;

	/** Construct a L4Engine with default type */
	public L4Engine() {
		engineType = "L4";
	}

	/** Construct a L4Engine with a specified type */
	public L4Engine(String engineType) {
		this.engineType = engineType;
	}

	/** Return EngineType */
	public String getEngineType() {
		return engineType;
	}

	/** Start this engine */
	public void start() {
		System.out.println(">>>>>>> " + this.engineType + " engine started");
	}
	
	/** Stop this engine */
	public void stop() {
		System.out.println(">>>>>>> " + this.engineType + " engine stopped");
	}
}
