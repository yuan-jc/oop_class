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
import io.netty.handler.codec.MessageToByteEncoder;
import io.netty.handler.codec.EncoderException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * @author Zhen Tang
 */
public class MessageEncoder extends MessageToByteEncoder<Message> {
    private static final Logger LOGGER = LoggerFactory.getLogger(MessageEncoder.class);

    private final boolean packedFrame;
    private final boolean allowCompression;

    private Map<MessageType, Encoder> encoders;

    private Map<MessageType, Encoder> getEncoders() {
        return encoders;
    }

    private void setEncoders(Map<MessageType, Encoder> encoders) {
        this.encoders = encoders;
    }

    public MessageEncoder() {
        this(false);
    }

    public MessageEncoder(boolean packedFrame) {
        this.packedFrame = packedFrame;
        this.allowCompression = packedFrame && PackedFrame.compressionEnabled();
        this.setEncoders(new ConcurrentHashMap<>());
    }

    public void registerEncoder(MessageType type, Encoder encoder) {
        this.getEncoders().put(type, encoder);
    }

    @Override
    protected void encode(ChannelHandlerContext ctx, Message message, ByteBuf out) {
        Encoder encoder = this.getEncoders().get(message.getType());
        if (encoder != null) {
            if (!packedFrame) {
                encoder.encode(message, out);
                return;
            }
            int start = out.writerIndex();
            // The existing encoder writes the type at offset 3; overwrite it with the packed header.
            out.writeZero(PackedFrame.HEADER_BYTES - 1);
            boolean compressed = encoder.encodePacked(message, out, allowCompression);
            int frameBytes = out.writerIndex() - start;
            int length = frameBytes - PackedFrame.HEADER_BYTES;
            int type = message.getType().getValue() & 0xff;
            if (length <= 0 || frameBytes > PackedFrame.MAX_FRAME_BYTES || type > PackedFrame.TYPE_MASK) {
                throw new EncoderException("Message does not fit the Ripple packed frame header");
            }
            out.setInt(start, (type << PackedFrame.LENGTH_BITS) | length
                    | (compressed ? PackedFrame.COMPRESSED_MASK : 0));
        } else {
            LOGGER.info("[MessageEncoder] encode(): Cannot find the encoder for the message type: {}.", message.getType());
        }
    }
}
