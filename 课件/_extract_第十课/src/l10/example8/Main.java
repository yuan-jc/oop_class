package l10.example8;

import java.awt.event.ActionEvent;
import java.awt.event.ActionListener;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import javax.swing.JButton;

public class Main {

	public static void main(String[] args) {
		/**
		 * 列表迭代
		 */
		List<Integer> list = new ArrayList<>();
		for (int j = 0; j <= 10; j++) {
			list.add(j);
		}
		
		// Java 8之前
		for(int item: list){
			  System.out.println(item);
		}

		// Java 8方式
		list.forEach(a -> System.out.println(a));
		
		list.forEach(System.err::println);
		
		/**
		 * 多线程
		 */
		// Java 8之前：
		new Thread(new Runnable() {
		    @Override
		    public void run() {
		    	System.out.println("Before Java8, too much code for too little to do");
		    }
		}).start();
		
		//Java 8方式
		new Thread(() -> System.out.println("In Java8, Lambda expression rocks !!")).start();
		
		/**
		 * 事件处理
		 */
		// Java 8之前
		JButton show =  new JButton("Show");
		show.addActionListener(new ActionListener() {
		    @Override
		    public void actionPerformed(ActionEvent e) {
		    	System.out.println("Event handling without lambda expression is boring");
		    }
		});
		
		// Java 8方式：
		show.addActionListener(e -> {
		    System.out.println("Light, Camera, Action !! Lambda expressions Rocks");
		});
	}
}
