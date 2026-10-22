import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/** 适配器的独立载荷契约测试。 */
public final class LabSelfTest {
    public static void run() {
        for (int size : new int[]{32, 33, 1024, 500000}) {
            String value = LabPayload.create("p1", 17, size, 42);
            check(value.getBytes(StandardCharsets.UTF_8).length == size, "载荷字节数");
            check(value.equals(LabPayload.create("p1", 17, size, 42)), "固定种子可复现");
            check(!value.equals(LabPayload.create("p1", 18, size, 42)), "不同序号不同载荷");
            check(LabPayload.parse(value).seq == 17, "序号解析");
        }
        check(LabPayload.parse(LabPayload.create("p1", -1, 32, 42)).seq == -1, "暖机序号");
        LabPacer pacing = new LabPacer(10, 0);
        check(pacing.isDue(0), "首条立即提交");
        pacing.advance(0);
        check(!pacing.isDue(99999999), "周期之前不能提交");
        check(pacing.isDue(100000000), "周期截止允许提交");
        pacing.advance(900000000);
        check(!pacing.isDue(900000000), "执行落后后不能追赶突发");
        check(!pacing.isDue(999999999), "落后后保留完整发送间隔");
        check(pacing.isDue(1000000000), "落后后下一截止时间");
        checkDispatcher();
        String original = LabPayload.create("p1", 0, 1024, 42);
        String changed = original.substring(0,1023) + (original.charAt(1023) == 'a' ? 'b' : 'a');
        check(LabContent.matches(original,"p1",0,1024,42),"完整载荷验证通过");
        check(!LabContent.matches(changed,"p1",0,1024,42),"末尾单字节变化必须检出");
        check(!LabContent.sha256(original).equals(LabContent.sha256(changed)),"单字节变化的摘要不同");
        check(LabContent.bytes("汉") == 3,"实际 UTF-8 字节计数");
        try { LabObserverSelfTest.run(); }
        catch (Exception e) { throw new AssertionError("处理器包装和完整内容验证",e); }
        System.out.println("适配器自测通过：精确大小、固定种子、序号、暖机标识及落后不追赶的定速截止时间");
    }
    private static void check(boolean ok, String label) {
        if (!ok) throw new AssertionError(label);
    }
    private static void checkDispatcher() {
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        AtomicLong clock = new AtomicLong(0);
        LabLoadDispatcher dispatcher = new LabLoadDispatcher(100,clock::get,() -> false,seq -> {
            entered.countDown();
            try { release.await(); } catch (InterruptedException e) { throw new AssertionError(e); }
        });
        try {
            dispatcher.offer();
            check(entered.await(2,TimeUnit.SECONDS),"业务提交进入独立线程");
            dispatcher.offer();
            check(dispatcher.blockedSlots() == 1,"阻塞期间不排队追赶");
            dispatcher.finish();
            check(dispatcher.submitted() == 1 && dispatcher.inFlight(),"截止保留调用开始计数和阻塞状态");
            check(!dispatcher.await(1),"调度截止不伪称阻塞调用完成");
            release.countDown();
            check(dispatcher.await(2000),"释放原库调用后线程退出");
            LabLoadDispatcher expired = new LabLoadDispatcher(0,clock::get,() -> false,seq -> {
                throw new AssertionError("截止后不能调用业务");
            });
            expired.offer(); expired.finish();
            check(expired.await(2000) && expired.submitted() == 0,"截止后任务不提交");
        } catch (InterruptedException e) { throw new AssertionError(e); }
        finally { release.countDown(); dispatcher.finish(); }
    }
}
