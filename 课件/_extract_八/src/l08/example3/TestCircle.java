package l08.example3;

public class TestCircle {
  /** Main method */
  public static void main(String[] args) {

	  Circle c1 = new Circle();
	
	  System.out.println("c1面积为：" + c1.getArea());
	  System.out.println("c1颜色为：" + c1.color);
	  
	  System.out.println("------------------------------");
	  
	  c1.getPainted(Color.BLUE).increment(1.0).increment(1.0).increment(1.0);
	  //PaintBrush.paint(c1, Color.BLUE).increment(1.0).increment(1.0).increment(1.0);
	  System.out.println("c1面积为：" + c1.getArea());
	  System.out.println("c1颜色为：" + c1.color);
  }
}
