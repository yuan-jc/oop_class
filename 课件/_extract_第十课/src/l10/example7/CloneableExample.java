package l10.example7;

import java.util.Date;

public class CloneableExample {
	public static void main(String[] args) {
		Date myDate = new Date();
		Date myDateClone = (Date) myDate.clone();

		System.out.println("myDate != myDateClone                        => "
				+ (myDate != myDateClone));
		System.out.println("myDate.getClass() == myDateClone.getClass()  => "
				+ (myDate.getClass() == myDateClone.getClass()));
		System.out.println("myDate.equals(myDateClone)                   => "
				+ myDate.equals(myDateClone));

		System.out.println("\nmyDate timestamp = " + myDate.getTime());
		System.out.println("myDateClone timestamp = " + myDateClone.getTime());

		myDate.setTime(1);
		System.out.println("\nmyDate.setTime(1)");
		System.out.println("myDate timestamp = " + myDate.getTime());
		System.out.println("myDateClone timestamp = " + myDateClone.getTime());
	}
}
