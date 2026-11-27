package l09.example5;

import l09.example4.*;

public class TestCar1 {
  public static void main(String[] args) {
	  
    Car1 myCar = new Car1();
    
    myCar.setL4Engine(new L4Engine(1.8, 150));
    myCar.start();
    myCar.shutOff();
    
    System.out.println(">>>>>>> ÒıÇæÉı¼¶");
    myCar.setV6Engine(new V6Engine(3.0, 300));
    myCar.start();
    myCar.shutOff();
  }
}
