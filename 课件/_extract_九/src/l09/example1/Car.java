package l09.example1;

public class Car {
	/** The brand of the car */
	private String brand;

	/** The engine of the car */
	private L4Engine l4Engine;

	/** The number of the car */
	private String number;

	/** Construct a car with a specified brand, number and engine */
	public Car(String brand, String number, String engineType) {
		this.brand = brand;
		this.number = number;
		this.l4Engine = new L4Engine(engineType);
	}

	/** Return brand */
	public String getBrand() {
		return brand;
	}

	/** Return number */
	public String getNumber() {
		return number;
	}

	/** Set a new number */
	public void setNumber(String number) {
		this.number = number;
	}

	/** Return engine */
	public L4Engine getL4Engine() {
		return l4Engine;
	}

	/** Set a new engine */
	public void setL4Engine(L4Engine l4Engine) {
		this.l4Engine = l4Engine;
	}

	/** Start this car */
	public void start() {
		System.out.println(">>>>>>> " + this.brand + " " + this.number);
		this.l4Engine.start();
	}

	/** Stop this car */
	public void shutOff() {
		System.out.println(">>>>>>> " + this.brand + " " + this.number);
		this.l4Engine.stop();
	}
}
