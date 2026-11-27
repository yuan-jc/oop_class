package l09.example8;

public class Super {
	Super(){
		System.out.println("in Super()");
		
		greeting();
		
		System.out.println("out Super()");
	}
	
	void greeting() {
		System.out.println("super greeting");
	}
}
