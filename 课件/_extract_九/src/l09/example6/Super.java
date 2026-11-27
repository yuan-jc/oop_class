package l09.example6;

public class Super {	
	private void pm(){
		System.out.println("call super.pm()");
	}
	
	public static void main(String[] args) {
		Super s = new Sub();
		s.pm();
		((Sub)s).pm();
	}
}
