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
import io.netty.channel.ChannelHandlerContext;
import io.netty.handler.codec.ByteToMessageDecoder;
import io.netty.handler.codec.CorruptedFrameException;

import java.util.List;

/** Split the TCP stream into complete frames, retaining the header for type dispatch. */
final class PackedFrameDecoder extends ByteToMessageDecoder {
    @Override
    protected void decode(ChannelHandlerContext ctx, ByteBuf in, List<Object> out) {
        if (in.readableBytes() < PackedFrame.HEADER_BYTES) {
            return;
        }
        int header = in.getInt(in.readerIndex());
        int length = header & PackedFrame.LENGTH_MASK;
        int frameBytes = PackedFrame.HEADER_BYTES + length;
        if ((header & PackedFrame.RESERVED_MASK) != 0 || length == 0
                || frameBytes > PackedFrame.MAX_FRAME_BYTES) {
            in.skipBytes(in.readableBytes());
            ctx.close();
            throw new CorruptedFrameException("Invalid Ripple packed frame header");
        }
        if (in.readableBytes() >= frameBytes) {
            out.add(in.readRetainedSlice(frameBytes));
        }
    }
}
