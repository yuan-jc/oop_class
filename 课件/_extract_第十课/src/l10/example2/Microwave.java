package l10.example2;

import javax.swing.*;
import java.awt.BorderLayout;
import java.awt.event.ActionListener;
import java.awt.event.ActionEvent;


public class Microwave extends JFrame {
	public Microwave() {
		
		JButton btnNewButton = new JButton("New button");
		btnNewButton.addActionListener(new ActionListener() {
			public void actionPerformed(ActionEvent e) {
				System.out.print("Hello, programmer, happy 1024");
			}
		});
		getContentPane().add(btnNewButton, BorderLayout.CENTER);
	
	}

	/** Main method */
	public static void main(String[] args) {
		Microwave frame = new Microwave();
		frame.setTitle("The Front View of a Microwave Oven");
		frame.setSize(400, 250);
		frame.setLocationRelativeTo(null); // Center the frame
		frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
		frame.setVisible(true);
	}
}
