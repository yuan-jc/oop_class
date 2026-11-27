package l08.example2;

import java.lang.reflect.Field;
import java.util.Date;

public class TestCircleUsingReflection {
	/** Main method */
	public static void main(String[] args) {

		Circle myCircle = new Circle(5.0, "my circle");
		System.out.println("名称：" + myCircle.getCircleName());
		System.out.println("半径：" + myCircle.getRadius());
		System.out.println("面积：" + myCircle.getArea());
		System.out.println("对象创建时间：" + myCircle.getDateCreated());

		Class cls = Circle.class;
		
		//access the private field
		Field field;
		try {
			field = cls.getDeclaredField("circleName");
	        field.setAccessible(true);  
	        field.set(myCircle, "your circle");
		} catch (NoSuchFieldException e) {
			// TODO Auto-generated catch block
			e.printStackTrace();
		} catch (SecurityException e) {
			// TODO Auto-generated catch block
			e.printStackTrace();
		} catch (IllegalArgumentException e) {
			// TODO Auto-generated catch block
			e.printStackTrace();
		} catch (IllegalAccessException e) {
			// TODO Auto-generated catch block
			e.printStackTrace();
		}  
		
		System.out.println("------------------------------------");	
		System.out.println("名称：" + myCircle.getCircleName());
		System.out.println("半径：" + myCircle.getRadius());
		System.out.println("面积：" + myCircle.getArea());
		System.out.println("对象创建时间：" + myCircle.getDateCreated());
	}
}
