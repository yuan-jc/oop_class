package l10.example6;

import java.util.Arrays;

public class WrapperExample {
	public static void compareTwoLong(Long a, Long b) {
		int result = a.compareTo(b); // Wrapper class Long implement compareTo
										// method
		if (result > 0)
			System.out.println("Long(" + a + "L)" + " > " + "Long(" + b + "L)");
		else if (a.compareTo(b) == 0)
			System.out.println("Long(" + a + "L)" + " = " + "Long(" + b + "L)");
		else
			System.out.println("Long(" + a + "L)" + " < " + "Long(" + b + "L)");
	}

	public static void main(String[] args) {
		Long a = new Long(2L);
		Long b = new Long(1L);
		Long c = new Long(2L);
		Long d = new Long(3L);
		compareTwoLong(a, b);
		compareTwoLong(a, c);
		compareTwoLong(a, d);

		Integer[] arr = { 5, 3, 2, 4, 1 };
		System.out.println("sort Integer[]={5,3,2,4,1}");
		Arrays.sort(arr);
		for (Integer integer : arr) {
			System.out.println(integer);
		}

	}
}
