package l09.example2;

public class TestEngine {
	public static void main(String[] args) {
		L4Engine myL4 = new L4Engine(1.8, 150);
		L4Engine yourL4 = new L4Engine(2.0, 160);

		System.out.println(">>>>>>> " + myL4.getEngineInfo());
		myL4.start();
		myL4.stop();

		System.out.println(">>>>>>> " + yourL4.getEngineInfo());
		yourL4.start();
		yourL4.stop();
		
		System.out.println(">>>>>>> ÒýÇæÉý¼¶...");

		myL4.setPower(180);

		System.out.println(">>>>>>> " + myL4.getEngineInfo());
		myL4.start();
		myL4.stop();
	}
}
