package l09.example4;

public class TestEngine {
	public static void main(String[] args) {
		
		L4Engine myL4 = new L4Engine(1.8, 150);
		L4Engine yourL4 = new L4Engine(2.0, 160);
		
		V6Engine myV6 = new V6Engine(3.0, 260);
		V6Engine yourV6 = new V6Engine(3.0, 300);

		System.out.println(">>>>>>> " + myL4.toString());
		myL4.start();
		myL4.stop();

		System.out.println(">>>>>>> " + yourL4.toString());
		yourL4.start();
		yourL4.stop();
		
		System.out.println(">>>>>>> " + myV6.toString());
		myV6.start();
		myV6.stop();
		
		System.out.println(">>>>>>> " + yourV6.toString());
		yourV6.start();
		yourV6.stop();
	}
}
