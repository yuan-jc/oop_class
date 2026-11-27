package l10.example1;

public class Test {
	public static void main(String[] args) {
		test(new Super());
		
		System.out.println("==========================================");
		
		test(new Sub());
	}

	static void test(Object obj) {
		System.out.println("类型为" + obj.getClass() + "的对象obj");
		
		System.out.println("ojb instanceof Super：" + (obj instanceof Super));
		System.out.println("ojb instanceof Sub：" + (obj instanceof Sub));
		
		System.out.println("Super.class.isInstance(obj)：" + Super.class.isInstance(obj));
		System.out.println("Sub.class.isInstance(obj)：" + Sub.class.isInstance(obj));
		
		System.out.println("obj.getClass() == Super.class：" + (obj.getClass() == Super.class));
		System.out.println("obj.getClass() == Sub.class：" + (obj.getClass() == Sub.class));
		
		System.out.println("obj.getClass().equals(Super.class)：" + (obj.getClass().equals(Super.class)));
		System.out.println("obj.getClass().equals(Sub.class)：" + (obj.getClass().equals(Sub.class)));		
	}
	
	
}