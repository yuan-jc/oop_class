package l10.example5;

import java.util.ArrayList;
import java.util.Random;

public class TestEngine {
	public static void main(String[] args) {
		int numOfEngineUnderTest = 20;
		
		ArrayList<Engine> engines = genRandomEngines(numOfEngineUnderTest);

		System.out.println(">>>>>>> 引擎测试开始...");
		
		certificateTest(engines);
		
		System.out.println(">>>>>>> 引擎测试结束...");
	}

	public static void certificateTest(ArrayList<Engine> enginesUnderTest) {
		
		Car testBed = new Car();

		for (Engine engine : enginesUnderTest) {
			System.out.println(">>>>>>> 第" + (enginesUnderTest.indexOf(engine)+1) +"台引擎测试开始，引擎ID：" + engine.getId());

			testBed.setEngine(engine);
			
			try {
				
				testBed.start();
				if(engine.isStarted() != true){
					throw new Exception();
				}
				
				if(engine instanceof CanAlarm)
					alarm((CanAlarm)engine);
				
				if(engine instanceof CanLocate)
					locating((CanLocate)engine);
				
				testBed.shutOff();
				
				if(engine.isStarted() != false){
					throw new Exception();
				}
				
			} catch (Exception e) {
				engine.setCertificated(false);
				return;
			}
			
			engine.setCertificated(true);			
			System.out.println(">>>>>>> 测试是否通过：" + engine.isCertificated());
			System.out.println();
			
			try {
				Thread.sleep(500);
			} catch (InterruptedException e) {
				e.printStackTrace();
			}
		}
	}
	
	public static ArrayList<Engine> genRandomEngines(int numOfEngines) {
		
		ArrayList<Engine> engines = new ArrayList<>();
		
		Random rand = new Random(System.currentTimeMillis());

		for (int i = 0; i < numOfEngines; i++) {
			switch (rand.nextInt(4)) {
			default:
			case 0:
				engines.add(new L4Engine(1.8, 150));
				continue;
			case 1:
				engines.add(new V6Engine(3.0, 300));
				continue;
			case 2:
				engines.add(new V8Engine(4.0, 360));
				continue;
			case 3:
				engines.add(new W12Engine(6.0, 530));
				continue;
			}
		}
		return engines;
	}
	
	public static void alarm(CanAlarm alarm) {
		System.out.println(">>>>>>> " + alarm.getAlarmInfo());
	}

	public static void locating(CanLocate locator) {
		System.out.println(">>>>>>> " + locator.getLocation());		
	}	
}
