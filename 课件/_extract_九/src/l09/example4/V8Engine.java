package l09.example4;

public class V8Engine extends Engine{
	private static int numberOfEngines = 0;

	public V8Engine(double displacement, double power) {
		super(V8TYPE, displacement, power);
		numberOfEngines++;
		this.setId(this.getType() + String.format("%06d", numberOfEngines));
	}


	public static int getNumberOfEngines() {
		return numberOfEngines;
	}
	
	public void start() {
		System.out.println(">>>>>>> V8.start()...");
		//do something to start V8...
		this.setStarted(true);
	}

	public void stop() {
		System.out.println(">>>>>>> V8.stop()...");
		//do something to stop V8...
		this.setStarted(false);
	}
}
