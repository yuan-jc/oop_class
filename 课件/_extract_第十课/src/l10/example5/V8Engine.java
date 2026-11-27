package l10.example5;

public class V8Engine extends Engine implements CanAlarm, CanLocate{
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
	
	public String getAlarmInfo() {
		return "Alarm info...";
	}

	public String getLocation() {
		return "Location info...";
	}
}
