package l10.example6;
import java.util.Arrays;

public class ComparableExample {

    public static void compareTwoString(String a,String b){
        int result = a.compareTo(b); //String implement compareTo method
        if (result>0)
            System.out.println(a + " > "+ b);
        else if (result == 0)
            System.out.println(a + " = "+ b);
        else
            System.out.println(a + " < "+ b);
    }

    public static void main(String[] args){

        String[] strs = {"Derick","Alice","Derick","Eric","Bob"};

        //compare
        compareTwoString(strs[0],strs[1]);
        compareTwoString(strs[0],strs[2]);
        compareTwoString(strs[0],strs[3]);
        
        System.out.println("=======================");
        
        //sort
        Arrays.sort(strs);
        for(String str : strs) {
            System.out.println(str);
        }
    }
}
