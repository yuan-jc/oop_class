package l08.example2;

import java.util.Date;

public class TestCircle {
	/** Main method */
	public static void main(String[] args) {

		Circle myCircle = new Circle(5.0, "my circle");
		System.out.println("名称：" + myCircle.getCircleName());
		System.out.println("半径：" + myCircle.getRadius());
		System.out.println("面积：" + myCircle.getArea());
		System.out.println("对象创建时间：" + myCircle.getDateCreated());
		
		String newName = myCircle.getCircleName();
		newName = "your circle";
		myCircle.getDateCreated().setYear(100);
		
		System.out.println("------------------------------------");	
		System.out.println("名称：" + myCircle.getCircleName());
		System.out.println("半径：" + myCircle.getRadius());
		System.out.println("面积：" + myCircle.getArea());
		System.out.println("对象创建时间：" + myCircle.getDateCreated());
	}
}
