package l12.example1;

public class V6Engine extends Engine{
	private static int numberOfEngines = 0;

	public V6Engine(double displacement, double power) {
		super(V6TYPE, displacement, power);
		numberOfEngines++;
		this.setId(this.getType() + String.format("%06d", numberOfEngines));
	}


	public static int getNumberOfEngines() {
		return numberOfEngines;
	}
	
	public void start() {
		System.out.println(">>>>>>> V6.start()...");
		//do something to start V6...
		this.setStarted(true);
	}

	public void stop() {
		System.out.println(">>>>>>> V6.stop()...");
		//do something to stop V6...
		this.setStarted(false);
	}
}
