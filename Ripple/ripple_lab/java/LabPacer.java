/** 单调时间定速器，执行落后时舍弃错过的时隙，不追赶发送。 */
public final class LabPacer {
    private final long period;
    private long next;
    public LabPacer(double rate, long origin) {
        if (!Double.isFinite(rate) || rate <= 0) throw new IllegalArgumentException("速率必须是正数");
        period = Math.max(1, Math.round(1000000000.0 / rate));
        next = origin;
    }
    public boolean isDue(long current) { return current - next >= 0; }
    public long remaining(long current) { return Math.max(0,next-current); }
    public void advance(long current) { next = Math.max(next + period,current + period); }
}
