package l09.example4;

public class L4Engine extends Engine{
	private static int numberOfEngines = 0;

	public L4Engine(double displacement, double power) {
		super(L4TYPE, displacement, power);
		numberOfEngines++;
		this.setId(this.getType() + String.format("%06d", numberOfEngines));
	}


	public static int getNumberOfEngines() {
		return numberOfEngines;
	}
	
	public void start() {
		System.out.println(">>>>>>> L4.start()...");
		//do something to start L4...
		this.setStarted(true);		
	}

	public void stop() {
		System.out.println(">>>>>>> L4.stop()...");
		//do something to stop L4...
		this.setStarted(false);
	}
}
