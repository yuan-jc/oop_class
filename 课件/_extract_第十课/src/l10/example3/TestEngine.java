package l12.example1;

import java.util.Random;

public class TestEngine {
	public static void main(String[] args) {
		int numOfEngineUnderTest = 100;

		Engine[] engines = genRandomEngines(numOfEngineUnderTest);

		System.out.println(">>>>>>> 引擎测试开始...");

		certificateTest(engines);

		System.out.println(">>>>>>> 引擎测试结束...");
	}

	public static void certificateTest(Engine[] enginesUnderTest) {
		
		Car testBed = new Car();

		for (int i = 0; i < enginesUnderTest.length; i++) {
			System.out.println(">>>>>>> 第" + (i + 1) + "台引擎测试开始，引擎ID："
					+ enginesUnderTest[i].getId());

			enginesUnderTest[i].setCertificated(true);

			testBed.setEngine(enginesUnderTest[i]);

			try {

				testBed.start();

				if (enginesUnderTest[i].isStarted() != true) {
					throw new Exception();
				}

				testBed.shutOff();
				if (enginesUnderTest[i].isStarted() != false) {
					throw new Exception();
				}

			} catch (Exception e) {
				enginesUnderTest[i].setCertificated(false);
			}

			System.out.println(">>>>>>> 测试是否通过："
					+ enginesUnderTest[i].isCertificated());
			System.out.println();
		}
	}

	public static Engine[] genRandomEngines(int numOfEngines) {

		Engine[] engines = new Engine[numOfEngines];
		Random rand = new Random();

		for (int i = 0; i < numOfEngines; i++) {
			switch (rand.nextInt(4)) {
			default:
			case 0:
				engines[i] = new L4Engine(1.8, 150);
				continue;
			case 1:
				engines[i] = new V6Engine(3.0, 300);
				continue;
			case 2:
				engines[i] = new V8Engine(4.0, 360);
				continue;
			case 3:
				engines[i] = new W12Engine(6.0, 530);
				continue;
			}
		}

		return engines;
	}
}
