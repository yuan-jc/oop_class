package l09.example7;

public class Test {
	public static void main(String[] args) {
		Super s = new Sub();
		System.out.println(s.greeting() + ", " + s.id + ", " + s.name());
		
		System.out.println("=======one more========");
		System.out.println(Sub.greeting() + ", " + s.id + ", " + s.name());
		
		System.out.println("=======one more========");
		System.out.println(Super.greeting() + ", " + s.id + ", " + s.name());
	}
}