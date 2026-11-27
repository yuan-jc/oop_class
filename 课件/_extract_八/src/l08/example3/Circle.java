package l08.example3;

public class Circle {
	/** The radius of the circle */
	private double radius;
	
	/** The color of the circle */
	Color color;

	/** Construct a circle with radius 1 and WHITE color*/
	public Circle() {
		this(1.0, Color.WHITE);
	}

	/** Construct a circle with a specified radius */
	public Circle(double newRadius) {
		this.radius = newRadius;
	}
	
	/** Construct a circle with a specified color */
	public Circle(Color newColor) {
		this.color = newColor;
	}
	
	/** Construct a circle with a specified radius and the specified color */
	public Circle(double newRadius, Color newColor) {
		this(newRadius);
		//this(newColor);
		this.color = newColor;
	}

	/** Return the area of this circle */
	public double getArea() {
		return this.radius * this.radius * Math.PI;
	}
	
	/** Increase the radius of this circle */
	public Circle increment(double increment) {
		this.radius = this.radius + ((increment >= 0) ? increment : 0);
		return this;
	}
	
	public Circle getPainted(Color color){
		return PaintBrush.paint(this, color);
	}
}
