package l08.example2;

import java.util.Date;

public class Circle {
	/** The radius of the circle */
	private double radius = 1;

	/** The number of the objects created */
	private static int numberOfObjects = 0;

	private String circleName = "default";
	
	private Date dateCreated;

	/** Construct a circle with radius 1 */
	public Circle() {
		numberOfObjects++;
		dateCreated = new Date();
	}

	/** Construct a circle with a specified radius */
	public Circle(double newRadius) {
		radius = newRadius;
		numberOfObjects++;
		dateCreated = new Date();
	}

	public Circle(double newRadius, String name) {
		radius = newRadius;
		numberOfObjects++;
		circleName = name;
		dateCreated = new Date();
	}

	/** Return radius */
	public double getRadius() {
		return radius;
	}

	/** Return numberOfObjects */
	public static int getNumberOfObjects() {
		return numberOfObjects;
	}

	/** Return the area of this circle */
	public double getArea() {
		return radius * radius * Math.PI;
	}
	
	public String getCircleName(){
		return circleName;		
	}
	
	public Date getDateCreated(){
		return dateCreated;
	}
	
//	public Date getDateCreated(){
//		return (Date) dateCreated.clone();
//	}
//	
//	public String getDateCreatedString(){
//		return dateCreated.toString();
//	}
}
