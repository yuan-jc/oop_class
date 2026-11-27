package l09.example5;

import l09.example4.*;

public class TestCar2 {
	public static void main(String[] args) {

		Car2 myCar = new Car2();

		myCar.setEngine(new L4Engine(1.8, 150));
		myCar.start();
		myCar.shutOff();

		System.out.println(">>>>>>> ÒıÇæÉı¼¶");

		myCar.setEngine(new V6Engine(3.0, 300));
		myCar.start();
		myCar.shutOff();
	}
}
