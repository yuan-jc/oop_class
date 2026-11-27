package l09.example1;

public class TestCar {
	/** Main method */
	public static void main(String[] args) {

		// Create a car
		Car myCar = new Car("VW", "¾©N09527", "L4 2.0L");

		// Get the car started
		myCar.start();

		// Shut off the car
		myCar.shutOff();
    
		// Change the engine of myCar
	    myCar.setL4Engine(new L4Engine("L4 2.0T"));
	    
		System.out.println("----------Engine upgrade complete-----------");

	    // Get the car started
	    myCar.start();
	    
	    //Shut off the car
	    myCar.shutOff();
		
	}
}
