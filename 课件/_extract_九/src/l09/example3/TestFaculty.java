package l09.example3;

public class TestFaculty {
	public static void main(String[] args) {
		testCreat();
		testClose();
	}
	
	static void testCreat(){
		new Faculty();
		System.out.println("-----------------------");
		System.out.println("-----------------------");
		new Faculty();
	}
	
	static void testClose(){
		Person p = new Faculty();
		System.out.println("----------Bye-------------");
		System.out.println("----------Bye-------------");
		p.close();
	}
	
}
