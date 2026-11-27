package l09.example5;

import l09.example4.*;

public class Car1 {
	private L4Engine l4Engine;
		
	public void setL4Engine(L4Engine l4Engine) {
		this.l4Engine = l4Engine;
	}

	public void start() {
		this.l4Engine.start();
	}
	
	public void shutOff() {
		this.l4Engine.stop();
	}
	
	
	private V6Engine v6Engine;
	private V8Engine v8Engine;
	private W12Engine w12Engine;

	public void setV6Engine(V6Engine v6Engine) {
		this.v6Engine = v6Engine;
	}
	
	public void setV8Engine(V8Engine v8Engine) {
		this.v8Engine = v8Engine;
	}
	
	public void setW12Engine(W12Engine w12Engine) {
		this.w12Engine = w12Engine;
	}
}
