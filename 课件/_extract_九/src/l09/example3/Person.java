package l09.example3;

class Person {
	static {
		System.out.println("static block in Person Class");
	}
	
	static MemberVar staticVarInPerson = new MemberVar("staticVarInPerson");

	MemberVar varInPerson = new MemberVar("varInPerson");

	public Person() {
		System.out.println("in Person()");

		System.out.println("out Person()");
	}

	public void close() {
		System.out.println("release sth in person");
	}
}
