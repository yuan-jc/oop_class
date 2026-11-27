package l09.example8;

class Sub extends Super {
	String greetingStr = null;
	
	Sub(String greetingStr){
		System.out.println("in Sub()");
		
		this.greetingStr = greetingStr;
		
		System.out.println("out Sub()");
	}
	
	void greeting() {
		System.out.println("sub " + this.greetingStr.toUpperCase());
	}
}
