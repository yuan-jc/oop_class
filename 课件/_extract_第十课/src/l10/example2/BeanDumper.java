//: gui/BeanDumper.java
// Introspecting a Bean.

package l10.example2;

import javax.swing.*;

import java.awt.*;
import java.awt.event.*;
import java.beans.*;
import java.lang.reflect.*;

public class BeanDumper extends JFrame {
	private JTextField query = new JTextField(20);
	private JTextArea results = new JTextArea();

	public void print(String s) {
		results.append(s + "\n");
	}

	public void dump(Class<?> bean) {
		results.setText("");
		BeanInfo bi = null;
		
		try {
			bi = Introspector.getBeanInfo(bean, Object.class);
		} catch (IntrospectionException e) {
			print("无法获取" + bean.getName() + "的类信息");
			return;
		}
		
		/*
		 * 获取属性信息
		 */
		for (PropertyDescriptor d : bi.getPropertyDescriptors()) {
			Class<?> p = d.getPropertyType();
			
			if (p == null)
				continue;
			
			print("属性类型:\n  " + p.getName());
			
			print("属性名称:\n  " + d.getName());
			
			Method readMethod = d.getReadMethod();
			if (readMethod != null)
				print("get方法:\n  " + readMethod);
			
			Method writeMethod = d.getWriteMethod();
			if (writeMethod != null)
				print("set方法:\n  " + writeMethod);
			
			print("====================");
		}
		
		/*
		 * 获取公有方法信息
		 */
		print("Public方法:");

		for (MethodDescriptor m : bi.getMethodDescriptors())
			print(m.getMethod().toString());
		
		print("======================");
		
		/*
		 * 获取支持的事件信息
		 */
		print("支持的事件:");
		
		for (EventSetDescriptor e : bi.getEventSetDescriptors()) {
			print("事件处理器类型:\n  " + e.getListenerType().getName());
			
			for (Method lm : e.getListenerMethods())
				print("事件处理器方法:\n  " + lm.getName());
			
			for (MethodDescriptor lmd : e.getListenerMethodDescriptors())
				print("方法描述符:\n  " + lmd.getMethod());
			
			Method addListener = e.getAddListenerMethod();
			print("添加事件处理器方法:\n  " + addListener);
			
			Method removeListener = e.getRemoveListenerMethod();
			print("移除事件处理器方法:\n  " + removeListener);
			
			print("====================");
		}
	}

	public BeanDumper() {
		JPanel p = new JPanel();
		p.setLayout(new FlowLayout());
		p.add(new JLabel("请输入Bean Class名称（包含包名）:"));
		p.add(query);
		
		add(BorderLayout.NORTH, p);
		add(new JScrollPane(results));
		
		Dumper dmpr = new Dumper();
		query.addActionListener(dmpr);
	}
	
	class Dumper implements ActionListener {
		public void actionPerformed(ActionEvent e) {
			String name = query.getText();
			Class<?> c = null;
			try {
				c = Class.forName(name);
			} catch (ClassNotFoundException ex) {
				results.setText("没有找到" + name);
				return;
			}
			dump(c);
		}
	}

	public static void main(String[] args) {
		BeanDumper beanDumper = new BeanDumper();
		beanDumper.setTitle("BeanDumper");
		beanDumper.setSize(600, 500);
		beanDumper.setLocationRelativeTo(null); // Center the frame
		beanDumper.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
		beanDumper.setVisible(true);
	}
} // /:~
