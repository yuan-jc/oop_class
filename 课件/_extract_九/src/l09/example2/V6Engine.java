package l09.example2;

import java.util.Date;

public class V6Engine {
	public static final String TYPE = "V6";
	private String id;
	private Date dateCreated;
	private boolean isStarted;
	private double displacement;
	private double power;
	
	private static int numberOfEngines = 0;

	public V6Engine(){
		this.dateCreated = new Date();
		numberOfEngines++;
		this.id = TYPE + String.format("%06d", numberOfEngines);
	}

	public V6Engine(double displacement, double power) {
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
		System.out.println(">>>>>>> V6.start()...");
		//do something to start V6...
		this.isStarted = true;
	}

	public void stop() {
		System.out.println(">>>>>>> V6.stop()...");
		//do something to stop V6...
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
