// Copyright (c) 2023 Institute of Software, Chinese Academy of Sciences
// Ripple is licensed under Mulan PSL v2.
// You can use this software according to the terms and conditions of the Mulan PSL v2.
// You may obtain a copy of Mulan PSL v2 at:
//          http://license.coscl.org.cn/MulanPSL2
// THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
// EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
// MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
// See the Mulan PSL v2 for more details.

package ripple.common.tcp;

import io.netty.buffer.ByteBuf;
import io.netty.channel.ChannelPipeline;
import io.netty.handler.codec.LengthFieldBasedFrameDecoder;
import io.netty.handler.codec.LengthFieldPrepender;

/** Four-byte header: [6 reserved bits | 1 compression bit | 5 type bits | 20 body-length bits]. */
public final class PackedFrame {
    static final int HEADER_BYTES = 4;
    static final int MAX_FRAME_BYTES = 1024 * 1024;
    static final int LENGTH_BITS = 20;
    static final int LENGTH_MASK = (1 << LENGTH_BITS) - 1;
    static final int TYPE_MASK = 0x1f;
    static final int COMPRESSED_MASK = 1 << 25;
    static final int RESERVED_MASK = 0xfc000000;

    static boolean compressionEnabled() {
        return Boolean.getBoolean("ripple.wire.frameCompression");
    }

    private PackedFrame() {
    }

    /** Install framing and return the mode to use for both message codecs. */
    public static boolean configure(ChannelPipeline pipeline) {
        boolean packed = Boolean.getBoolean("ripple.wire.packedFrame");
        if (packed) {
            pipeline.addLast(new PackedFrameDecoder());
        } else {
            pipeline.addLast(new LengthFieldBasedFrameDecoder(MAX_FRAME_BYTES, 0, HEADER_BYTES, 0, HEADER_BYTES));
            pipeline.addLast(new LengthFieldPrepender(HEADER_BYTES));
        }
        return packed;
    }
}
