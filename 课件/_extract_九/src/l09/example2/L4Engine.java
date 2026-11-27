package l09.example2;

import java.util.Date;

public class L4Engine {
	public static final String TYPE = "L4";
	private String id;
	private Date dateCreated;
	private boolean isStarted;
	private double displacement;
	private double power;

	private static int numberOfEngines = 0;
	
	public L4Engine(){
		this.dateCreated = new Date();
		numberOfEngines++;
		this.id = TYPE + String.format("%06d", numberOfEngines);
	}

	public L4Engine(double displacement, double power) {
		this();
		this.displacement = displacement;
		this.power = power;
	}

	public String getId() {
		return id;
	}

	public static int getNumberOfEngines() {
		return numberOfEngines;
	}

	public void start() {
		System.out.println(">>>>>>> L4.start()...");
		// do something to start L4...
		this.isStarted = true;
	}

	public void stop() {
		System.out.println(">>>>>>> L4.stop()...");
		// do something to stop L4...
		this.isStarted = false;
	}

	public String getDateCreated() {
		return dateCreated.toString();
	}

	public boolean isStarted() {
		return isStarted;
	}

	public double getDisplacement() {
		return displacement;
	}

	public double getPower() {
		return power;
	}

	public void setPower(double power) {
		this.power = power;
	}

	public String getEngineInfo() {
		return "ID: " + this.id + "; 发动机型号: " + TYPE + "; 排量: "
				+ this.displacement + "; 功率: " + this.power + "; 出厂日期: "
				+ this.dateCreated;
	}
}
