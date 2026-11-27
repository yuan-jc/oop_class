package l12.example1;

import java.util.Date;

public abstract class Engine {

	protected static final String L4TYPE = "L4";
	protected static final String V6TYPE = "V6";
	protected static final String V8TYPE = "V8";
	protected static final String W12TYPE = "W12";

	private String type;
	private String id;
	private Date dateCreated;
	private boolean isStarted;
	private double displacement;
	private double power;
	private boolean isCertificated;
	
	public Engine(){
		this.dateCreated = new Date();
	}
	
	public Engine(String type, double displacement, double power) {
		this();
		this.type = type;
		this.displacement = displacement;
		this.power = power;
	}

	public abstract void start();

	public abstract void stop();

	public String getId() {
		return id;
	}

	protected void setId(String id) {
		this.id = id;
	}

	public boolean isCertificated() {
		return isCertificated;
	}

	public void setCertificated(boolean isCertificated) {
		this.isCertificated = isCertificated;
	}

	public String getDateCreated() {
		return dateCreated.toString();
	}

	public boolean isStarted() {
		return isStarted;
	}

	protected void setStarted(boolean isStarted) {
		this.isStarted = isStarted;
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
		return "ID: " + this.id + "; 发动机型号: " + this.type + "; 排量: "
				+ this.displacement + "; 功率: " + this.power + "; 出厂日期: "
				+ this.dateCreated;
	}

	public String getType() {
		return type;
	}

	public String toString() {
		return this.getEngineInfo();
	}
}
