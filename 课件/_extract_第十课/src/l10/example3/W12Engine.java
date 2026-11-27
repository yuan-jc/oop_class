package l10.example3;

public class W12Engine extends Engine{
	private static int numberOfEngines = 0;

	public W12Engine(double displacement, double power) {
		super(W12TYPE, displacement, power);
		numberOfEngines++;
		this.setId(this.getType() + String.format("%06d", numberOfEngines));
	}


	public static int getNumberOfEngines() {
		return numberOfEngines;
	}
	
	public void start() {
		System.out.println(">>>>>>> W12.start()...");
		//do something to start W12...
		this.setStarted(true);
	}

	public void stop() {
		System.out.println(">>>>>>> W12.stop()...");
		//do something to stop W12...
		this.setStarted(false);
	}
}
