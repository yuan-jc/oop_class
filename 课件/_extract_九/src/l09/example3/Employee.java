package l09.example3;

class Employee extends Person {
	static MemberVar staticVarInEmployee = new MemberVar("staticVarInEmployee");

	static {
		System.out.println("static block in Employee Class");
	}

	MemberVar varInEmployee = new MemberVar("varInEmployee");

	public Employee() {
		this("test");

		System.out.println("in Employee()");

		System.out.println("out Employee()");
	}

	public Employee(String s) {
		System.out.println("in Employee(String s)");

		System.out.println("out Employee(String s)");
	}
	
	public void close() {
		System.out.println("release sth in employee");
		super.close();
	}
}
