package l10.example4;
import java.util.Calendar;
import java.util.GregorianCalendar;

public class CalenderExample {
    public static void main(String[] args){
        //initial
        Calendar myCalendar = new GregorianCalendar(2024,10,1); //year,month(0-11),day
    	
    	System.out.println("year = " + myCalendar.get(Calendar.YEAR));
        System.out.println("month = " + myCalendar.get(Calendar.MONTH));
        System.out.println("day of month = " + myCalendar.get(Calendar.DAY_OF_MONTH));
        System.out.println("maximum value for day of month = " + myCalendar.getMaximum(Calendar.DAY_OF_MONTH)+"\n"); //Calender abstract method
        
        //set day of month
        System.out.println("> myCalendar.set(Calendar.DAY_OF_MONTH,2)");
        myCalendar.set(Calendar.DAY_OF_MONTH,2);
        System.out.println("day of month = " + myCalendar.get(Calendar.DAY_OF_MONTH)+"\n");
        
        //add 30 days
        System.out.println("> myCalendar.add(Calendar.DAY_OF_MONTH,30)");
        myCalendar.add(Calendar.DAY_OF_MONTH,30);    //Calender abstract method
        System.out.println("day of month = " + myCalendar.get(Calendar.DAY_OF_MONTH));

    }

}
