package l09.example3;

public class Faculty extends Employee {
	static MemberVar staticVarInFaculty = new MemberVar("staticVarInFaculty");

	static {
		System.out.println("static block in Faculty Class");
	}

	MemberVar varInFaculty = new MemberVar("varInFaculty");

	public Faculty() {
		System.out.println("in Faculty()");

		System.out.println("out Faculty()");
	}
	
	public void close() {
		System.out.println("release sth in faculty");
		super.close();
	}
}
